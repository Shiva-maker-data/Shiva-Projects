"""
Backtests the EXACT live scoring/level rules from analyzer.py across
historical data to answer a specific question: when this system generates
a Short-Term or Long-Term signal, how often -- and by how much -- has the
stock actually gone on to return more than +20% within the next 90
calendar days?

Run it directly:
    .venv\\Scripts\\python.exe backtest.py
    .venv\\Scripts\\python.exe backtest.py --min-scores 0,40,60 --history 3y

Methodology (read this before trusting the numbers):
- Point-in-time correct: at each candidate day, only data up to and
  including that day is used to compute the score (see analyzer.py's
  IndicatorBundle docstring -- the exact same scoring functions that run
  live are reused here unmodified, so this tests the real system, not a
  reimplementation of it).
- Non-overlapping trades per stock/category/threshold: once a signal
  fires, no new signal is considered until that trade resolves (hits
  target1, hits stop-loss, or times out at 90 days). Avoids inflating the
  sample with near-duplicate overlapping signals from one long uptrend.
- Entry is simulated at the NEXT day's Open after the signal (you can't
  actually buy at yesterday's close).
- Each day going forward, the stop-loss is checked before the target
  (conservative assumption for days where both could plausibly have been
  hit -- avoids overstating the win rate).
- Two return numbers are reported per trade:
    strategy_return_pct -- what you'd have made following the tool's own
      exit rules (book at target1, respect the stop-loss, or exit at
      whatever the close is after 90 days if neither was hit).
    raw_90d_return_pct  -- what you'd have made just holding from entry to
      the close ~90 calendar days later, ignoring the stop-loss entirely.
      This is the literal "return within 90 days" figure the >20% filter
      is judged against; it's shown alongside the risk-managed number
      because ignoring your own stop-loss is not something this tool
      recommends anyone actually do.
- Signals in roughly the last 95 days of available data are excluded from
  the stats (not enough time has passed yet to know the 90-day outcome).

Still a heuristic backtest of a heuristic screener -- no transaction costs
or slippage modeled, and today's NIFTY 50 / SENSEX list is used as a proxy
universe for the whole lookback window (survivorship bias: it doesn't
reconstruct who was actually in the index 3 years ago). Treat this as a
first, honest look at whether the rulebook has any edge, not a finished,
validated trading system.
"""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

import data_sources as ds
import symbols as sym
from analyzer import (
    CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM,
    IndicatorBundle, build_idea, compute_bundle, score_long_term, score_short_term,
)

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nifty_agent.backtest")

MIN_WARMUP_DAYS = 200          # need this many days of history before SMA200 etc. are valid
FORWARD_WINDOW_DAYS = 90       # the user's filter: return within 90 calendar days
CENSOR_BUFFER_DAYS = 95        # skip signals too recent to have a known 90-day outcome
TARGET_RETURN_PCT = 20.0       # the user's filter: only interested in >20% moves

SCORERS = {
    CATEGORY_SHORT_TERM: score_short_term,
    CATEGORY_LONG_TERM: score_long_term,
}


@dataclass
class TradeResult:
    symbol: str
    category: str
    threshold: float
    signal_date: str
    score: float
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str                   # "target1" | "stop_loss" | "time_exit"
    days_held: int
    strategy_return_pct: float
    raw_90d_return_pct: float | None   # None if data ran out before 90 days
    hit_20pct_raw: bool | None


def _simulate_trade(df: pd.DataFrame, entry_idx: int, target1: float, stop_loss: float,
                     max_days: int = FORWARD_WINDOW_DAYS) -> tuple[int, float, str]:
    """Walk forward day by day from entry_idx until target1, stop_loss, or
    the time horizon is hit. Returns (exit_idx, exit_price, exit_reason)."""
    entry_date = df.index[entry_idx]
    i = entry_idx
    while i < len(df):
        if (df.index[i] - entry_date).days > max_days:
            break
        low, high = float(df["Low"].iloc[i]), float(df["High"].iloc[i])
        if low <= stop_loss:            # conservative: stop-loss checked first
            return i, stop_loss, "stop_loss"
        if high >= target1:
            return i, target1, "target1"
        i += 1
    exit_idx = min(i, len(df) - 1)
    return exit_idx, float(df["Close"].iloc[exit_idx]), "time_exit"


def _backtest_one(symbol: str, category: str, df: pd.DataFrame, bundle: IndicatorBundle,
                   min_score: float) -> list[TradeResult]:
    scorer = SCORERS[category]
    results: list[TradeResult] = []
    censor_date = df.index[-1] - pd.Timedelta(days=CENSOR_BUFFER_DAYS)

    i = MIN_WARMUP_DAYS
    while i < len(df) - 1:
        if df.index[i] > censor_date:
            break

        score, reasons = scorer(bundle, i)
        if score < min_score:
            i += 1
            continue

        idea = build_idea(symbol, category, bundle, i, score, reasons, "")
        entry_idx = i + 1
        entry_price = float(df["Open"].iloc[entry_idx])

        exit_idx, exit_price, exit_reason = _simulate_trade(df, entry_idx, idea.target1, idea.stop_loss)
        days_held = (df.index[exit_idx] - df.index[entry_idx]).days
        strategy_return_pct = (exit_price / entry_price - 1) * 100

        target_date = df.index[entry_idx] + pd.Timedelta(days=FORWARD_WINDOW_DAYS)
        future = df[df.index >= target_date]
        if not future.empty:
            raw_price_90d = float(future["Close"].iloc[0])
            raw_90d_return_pct = (raw_price_90d / entry_price - 1) * 100
            hit_20pct_raw = raw_90d_return_pct >= TARGET_RETURN_PCT
        else:
            raw_90d_return_pct = None
            hit_20pct_raw = None

        results.append(TradeResult(
            symbol=symbol, category=category, threshold=min_score,
            signal_date=str(df.index[i].date()), score=score,
            entry_date=str(df.index[entry_idx].date()), entry_price=round(entry_price, 2),
            exit_date=str(df.index[exit_idx].date()), exit_price=round(exit_price, 2),
            exit_reason=exit_reason, days_held=days_held,
            strategy_return_pct=round(strategy_return_pct, 2),
            raw_90d_return_pct=round(raw_90d_return_pct, 2) if raw_90d_return_pct is not None else None,
            hit_20pct_raw=hit_20pct_raw,
        ))

        i = max(exit_idx + 1, i + 1)  # non-overlapping: skip past this trade

    return results


def backtest_symbol(raw_symbol: str, categories: list[str], thresholds: list[float],
                     history_period: str = "3y") -> list[TradeResult]:
    """Fetch once, then run every (category, threshold) combo against the
    same in-memory data -- no repeated network calls per combo."""
    yf_ticker = sym.to_yf_ticker(raw_symbol)
    df = ds.fetch_daily_history(yf_ticker, period=history_period)
    if df is None or len(df) < MIN_WARMUP_DAYS + 30:
        logger.warning("Not enough history for %s, skipping", raw_symbol)
        return []

    bundle = compute_bundle(df)
    results: list[TradeResult] = []
    for category in categories:
        for threshold in thresholds:
            results.extend(_backtest_one(raw_symbol, category, df, bundle, threshold))
    return results


def run_backtest(categories: list[str], thresholds: list[float], history_period: str,
                  universe: list[str], max_workers: int = 8) -> pd.DataFrame:
    all_results: list[TradeResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(backtest_symbol, s, categories, thresholds, history_period): s for s in universe}
        done = 0
        for fut in as_completed(futures):
            s = futures[fut]
            done += 1
            try:
                res = fut.result()
                all_results.extend(res)
                logger.info("[%d/%d] %s -> %d trades", done, len(universe), s, len(res))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[%d/%d] %s FAILED: %s", done, len(universe), s, exc)

    return pd.DataFrame([asdict(r) for r in all_results])


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "No trades were generated at all -- check data fetching / thresholds."

    lines = []
    total = len(df)
    resolved = df[df["raw_90d_return_pct"].notna()].copy()
    censored = total - len(resolved)
    lines.append(f"Total simulated trades: {total}  (excluded {censored} too recent for a known 90-day outcome)")
    lines.append(f"Universe: today's NIFTY 50 + SENSEX constituents (see symbols.py) | "
                 f"Target: raw close-to-close return >= {TARGET_RETURN_PCT:.0f}% within {FORWARD_WINDOW_DAYS} calendar days\n")

    for threshold in sorted(resolved["threshold"].unique()):
        g = resolved[resolved["threshold"] == threshold]
        hit_rate = g["hit_20pct_raw"].mean() * 100
        lines.append(f"=== Minimum score >= {threshold:.0f}  ({len(g)} signals) ===")
        lines.append(f"  Hit rate for >{TARGET_RETURN_PCT:.0f}% raw return in {FORWARD_WINDOW_DAYS}d: {hit_rate:.1f}%")
        lines.append(f"  Avg raw {FORWARD_WINDOW_DAYS}-day return: {g['raw_90d_return_pct'].mean():.1f}%"
                      f"   (median {g['raw_90d_return_pct'].median():.1f}%,"
                      f" worst {g['raw_90d_return_pct'].min():.1f}%,"
                      f" best {g['raw_90d_return_pct'].max():.1f}%)")
        strat_win_rate = (g["exit_reason"] == "target1").mean() * 100
        strat_stop_rate = (g["exit_reason"] == "stop_loss").mean() * 100
        lines.append(f"  If you'd followed the tool's own exit rules instead: avg return "
                      f"{g['strategy_return_pct'].mean():.1f}%  "
                      f"(hit target1 {strat_win_rate:.1f}% of trades, hit stop-loss {strat_stop_rate:.1f}% of trades)")
        for cat in sorted(g["category"].unique()):
            gc = g[g["category"] == cat]
            lines.append(f"    [{cat}] n={len(gc)}  hit-rate={gc['hit_20pct_raw'].mean()*100:.1f}%  "
                          f"avg raw {FORWARD_WINDOW_DAYS}d return={gc['raw_90d_return_pct'].mean():.1f}%")
        lines.append("")

    # Per-symbol breakdown at the live default threshold (40), min 2 signals to reduce noise
    live_default = resolved[resolved["threshold"] == 40.0] if (resolved["threshold"] == 40.0).any() else resolved[resolved["threshold"] == resolved["threshold"].min()]
    per_symbol = (
        live_default.groupby("symbol")
        .agg(n=("symbol", "size"), hit_rate=("hit_20pct_raw", "mean"), avg_return=("raw_90d_return_pct", "mean"))
        .query("n >= 2")
        .sort_values(["hit_rate", "avg_return"], ascending=False)
    )
    per_symbol["hit_rate"] = per_symbol["hit_rate"] * 100  # fraction -> percent, matches rest of the report
    if not per_symbol.empty:
        lines.append(f"=== Per-symbol breakdown at threshold {live_default['threshold'].iloc[0]:.0f} (min 2 signals) ===")
        lines.append(per_symbol.head(15).to_string(float_format=lambda x: f"{x:.1f}"))
        lines.append("...")
        lines.append(per_symbol.tail(10).to_string(float_format=lambda x: f"{x:.1f}"))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Backtest the daily agent's scoring rules.")
    parser.add_argument("--min-scores", default="0,40,60", help="Comma-separated score thresholds to test.")
    parser.add_argument("--history", default="3y", help="yfinance history period, e.g. 2y, 3y, 5y.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--universe-limit", type=int, default=None, help="For a quick test run on N symbols.")
    args = parser.parse_args()

    thresholds = [float(x) for x in args.min_scores.split(",")]
    universe = sym.get_universe()
    if args.universe_limit:
        universe = universe[: args.universe_limit]

    logger.info("Backtesting %d symbols x %d thresholds x 2 categories, history=%s ...",
                len(universe), len(thresholds), args.history)

    df = run_backtest(
        categories=[CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM],
        thresholds=thresholds,
        history_period=args.history,
        universe=universe,
        max_workers=args.workers,
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULTS_DIR / f"trades_{ts}.csv"
    df.to_csv(csv_path, index=False)
    logger.info("Full trade log saved to %s (%d rows)", csv_path, len(df))

    summary = summarize(df)
    summary_path = RESULTS_DIR / f"summary_{ts}.txt"
    summary_path.write_text(summary, encoding="utf-8")

    print("\n" + summary)
    print(f"\nFull trade log: {csv_path}")
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
