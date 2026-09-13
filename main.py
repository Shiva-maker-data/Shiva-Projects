"""
Entry point for the daily NIFTY 50 / SENSEX tipper agent.

Pipeline:
  1. Load the stock universe (symbols.py)
  2. For each symbol, fetch daily history (+ intraday history) from Yahoo
     Finance, and a latest quote from NSE India for cross-checking
     (data_sources.py)
  3. Score each symbol for Intraday / Short-Term / Long-Term setups and
     derive entry/target/stop-loss levels (analyzer.py)
  4. Reconcile yesterday's still-open Short-Term/Long-Term picks against
     today's data -- close out any that hit target/stop/expired, and drop
     any still-open ones from today's candidate pool so the same idea
     isn't re-suggested every day while it's still active (positions.py)
  5. Pick the top N per category from what's left, write a short rationale
     for each (narrative.py -- Claude if configured, else a template)
  6. Build the HTML report and email it (report.py, emailer.py)

Run manually with:  python main.py
Scheduled daily via Windows Task Scheduler -- see README.md.
"""
from __future__ import annotations

import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import config as cfg
import data_sources as ds
import market_regime as regime_mod
import sector as sector_mod
import symbols as sym
from analyzer import (
    CATEGORY_INTRADAY, CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM,
    check_data_quality, compute_bundle, rank_and_select, score_intraday, score_long_term, score_short_term,
)
from emailer import send_report_email
from narrative import write_rationale
from positions import (
    already_open_keys, idea_to_open_position, load_open_positions, reconcile, save_open_positions,
)
from local_tracking import export_daily_results_local
from report import build_html_report
from sheets_export import export_daily_results

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
ARCHIVE_DIR = BASE_DIR / "reports_archive"
ARCHIVE_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / f"run_{datetime.now():%Y%m%d}.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("nifty_agent.main")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
PICKS_PER_CATEGORY = int(os.getenv("PICKS_PER_CATEGORY", "3"))
MIN_SCORE = float(os.getenv("MIN_SCORE", "40"))


def analyze_symbol(raw_symbol: str, regime_label: str | None, nifty_close) -> dict | None:
    """Fetch data and score one symbol across all three categories."""
    yf_ticker = sym.to_yf_ticker(raw_symbol)
    daily_df = ds.fetch_daily_history(yf_ticker, period="1y")
    if daily_df is None:
        return None

    # Data-quality gate (analyzer.check_data_quality) -- previously
    # implemented and unit-tested but never actually called from the live
    # pipeline. Stale bars, abnormal single-day moves (possible corporate
    # action/bad print), or missing OHLC now skip the symbol here instead
    # of silently flowing into scoring.
    quality_ok, quality_note = check_data_quality(daily_df, idx=len(daily_df) - 1, now=pd.Timestamp.now())
    if not quality_ok:
        logger.warning("Data quality check failed for %s: %s", raw_symbol, quality_note)
        return None

    intraday_df = ds.fetch_intraday_history(yf_ticker, period="5d", interval="15m")
    nse_quote = ds.get_nse_quote(raw_symbol)
    price_check = ds.cross_check_price(float(daily_df["Close"].iloc[-1]), nse_quote)

    bundle = compute_bundle(daily_df)

    # Sector confirmation needs a preliminary "is this stock's own signal
    # bullish" reading to judge alignment -- price above its 50-day SMA is
    # a reasonable, cheap proxy shared by both categories. Relative
    # strength uses a DIFFERENT lookback per category (20d Short-Term, 60d
    # Long-Term, per config.py's RS_LOOKBACK_DAYS / RS_LOOKBACK_DAYS_LONG)
    # -- previously both categories silently used the 20-day default.
    stock_bullish = bool(pd.notna(bundle.sma50.iloc[-1]) and bundle.close.iloc[-1] > bundle.sma50.iloc[-1])
    sector_confirmation_st = sector_mod.get_sector_confirmation(
        raw_symbol, stock_bullish, nifty_close=nifty_close, stock_close=bundle.close,
        lookback_days=cfg.RS_LOOKBACK_DAYS)
    sector_confirmation_lt = sector_mod.get_sector_confirmation(
        raw_symbol, stock_bullish, nifty_close=nifty_close, stock_close=bundle.close,
        lookback_days=cfg.RS_LOOKBACK_DAYS_LONG)

    lt_idea = score_long_term(raw_symbol, bundle, regime_label=regime_label,
                               sector_confirmation=sector_confirmation_lt, data_note=price_check.note)
    st_idea = score_short_term(raw_symbol, bundle, regime_label=regime_label,
                                sector_confirmation=sector_confirmation_st, data_note=price_check.note)
    id_idea = score_intraday(raw_symbol, bundle, intraday_df, regime_label=regime_label, data_note=price_check.note)

    return {"symbol": raw_symbol, "ideas": [lt_idea, st_idea, id_idea], "daily_df": daily_df}


def run() -> None:
    started = datetime.now()
    logger.info("=== NIFTY/SENSEX daily agent run started ===")

    universe = sym.get_universe()
    logger.info("Scanning %d symbols...", len(universe))

    # Market regime is computed ONCE (NIFTY 50 is the same for every stock
    # this run) and applied as a real, weighted factor in every score --
    # see market_regime.py / analyzer.py's "Market Regime" breakdown line.
    regime = regime_mod.get_market_regime()
    if regime:
        logger.info("Market regime: %s (NIFTY %.2f, %.1f%% vs 20-SMA, %.1f%% vs 50-SMA, ATR %.1f%% at %.0fth pctile)",
                     regime.label, regime.index_price, regime.pct_from_sma_fast, regime.pct_from_sma_slow,
                     regime.atr_pct, regime.atr_percentile)
    else:
        logger.warning("Could not determine market regime -- scoring will default to neutral for this factor.")
    regime_label = regime.label if regime else None

    nifty_df = ds.fetch_daily_history(cfg.REGIME_INDEX_TICKER, period="1y")
    nifty_close = nifty_df["Close"] if nifty_df is not None else None

    # Pre-fetch every unique sector index ONCE, sequentially, before the
    # concurrent per-stock loop below -- see sector.py's prefetch docstring
    # for why (avoids a cache race + redundant fetches across the several
    # stocks that share each sector index).
    sector_mod.prefetch_sector_trends()

    all_ideas_by_category: dict[str, list] = {
        CATEGORY_INTRADAY: [], CATEGORY_SHORT_TERM: [], CATEGORY_LONG_TERM: []
    }
    skipped: list[str] = []
    daily_data: dict[str, pd.DataFrame] = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_symbol, s, regime_label, nifty_close): s for s in universe}
        for future in as_completed(futures):
            raw_symbol = futures[future]
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Unexpected error analyzing %s: %s", raw_symbol, exc)
                result = None
            if result is None:
                skipped.append(raw_symbol)
                continue
            daily_data[result["symbol"]] = result["daily_df"]
            for idea in result["ideas"]:
                all_ideas_by_category[idea.category].append(idea)

    if skipped:
        logger.warning("Skipped %d symbols due to data issues: %s", len(skipped), ", ".join(skipped))

    # Reconcile Short-Term/Long-Term positions already open from prior runs:
    # close out anything that hit target/stop/expired, and don't re-suggest
    # anything still open (Intraday is never tracked -- it squares off same day).
    today = pd.Timestamp(started.date())
    prior_open = load_open_positions()
    still_open, closed_positions = reconcile(prior_open, daily_data, today)
    if closed_positions:
        logger.info("Closed %d position(s): %s", len(closed_positions),
                     ", ".join(f"{p.symbol}/{p.exit_reason}/{p.return_pct}%" for p in closed_positions))
    open_keys = already_open_keys(still_open)
    for category in (CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM):
        before = len(all_ideas_by_category[category])
        all_ideas_by_category[category] = [
            i for i in all_ideas_by_category[category] if (i.symbol, i.category) not in open_keys
        ]
        logger.info("%s: filtered out %d already-open candidate(s)", category,
                    before - len(all_ideas_by_category[category]))

    picks_by_category = {
        category: rank_and_select(ideas, top_n=PICKS_PER_CATEGORY, min_score=MIN_SCORE)
        for category, ideas in all_ideas_by_category.items()
    }

    # Track newly suggested Short-Term/Long-Term picks as open positions so
    # tomorrow's run knows not to repeat them until they resolve.
    for category in (CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM):
        for idea in picks_by_category[category]:
            still_open.append(idea_to_open_position(idea, today))
    save_open_positions(still_open)

    # Best-effort: log today's suggestions + any resolved outcomes to Google
    # Sheets for later accuracy analysis. No-ops cleanly if not configured,
    # and never affects the email pipeline if it fails.
    export_daily_results(picks_by_category, closed_positions, started)

    # Always log the same data to local CSVs under tracking/ too, so
    # suggestion/outcome history accumulates even without Google Sheets
    # configured. Also best-effort -- never affects the email pipeline.
    export_daily_results_local(picks_by_category, closed_positions, started)

    total_picks = sum(len(v) for v in picks_by_category.values())
    logger.info("Selected %d total picks across categories. Writing rationales...", total_picks)

    rationales: dict[str, str] = {}
    for ideas in picks_by_category.values():
        for idea in ideas:
            rationales[idea.symbol + idea.category] = write_rationale(idea)

    html = build_html_report(picks_by_category, rationales, run_date=started, skipped_symbols=skipped,
                              closed_positions=closed_positions)

    archive_path = ARCHIVE_DIR / f"report_{started:%Y-%m-%d}.html"
    archive_path.write_text(html, encoding="utf-8")
    logger.info("Report archived to %s", archive_path)

    subject = f"NIFTY/SENSEX Daily Watchlist -- {started:%d %b %Y} ({total_picks} picks)"
    sent = send_report_email(html, subject)
    if not sent:
        logger.error("Email send FAILED. Report is still saved locally at %s", archive_path)
        sys.exit(1)

    elapsed = (datetime.now() - started).total_seconds()
    logger.info("=== Run complete in %.1fs ===", elapsed)


if __name__ == "__main__":
    run()
