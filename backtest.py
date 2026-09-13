"""
Backtests the EXACT live scoring/level rules from analyzer.py (v2: regime-
aware, weighted-factor scoring) across historical data.

Run it directly:
    .venv\\Scripts\\python.exe backtest.py
    .venv\\Scripts\\python.exe backtest.py --min-scores 0,40,60 --history 3y

Methodology (read this before trusting the numbers):
- Point-in-time correct for BOTH the stock's own indicators AND the market
  regime: NIFTY's regime is computed once into a RegimeBundle (same
  pattern as IndicatorBundle) and sliced at each historical idx, so a
  signal's "Market Regime" score factor reflects what the regime actually
  was on that historical day -- not today's regime applied retroactively.
- KNOWN LIMITATION: Sector confirmation and relative-strength are NOT
  point-in-time backtested here (sector_confirmation=None is passed to
  every call) -- extending the same point-in-time-bundle approach to ~9
  sector indices with correct date-alignment is a real follow-up, not yet
  done. Those two factors fall back to their documented neutral defaults
  in every backtested score, same as the live path does when sector data
  is genuinely unavailable. This means backtested scores are NOT identical
  in magnitude to what would have shown live (which does have sector data)
  -- only the Market-Regime-aware core is validated end-to-end here.
- Non-overlapping trades per stock/category/threshold: once a signal
  fires, no new signal is considered until that trade resolves (hits
  target1, hits stop-loss, or times out at 90 days).
- Entry is simulated at the NEXT day's Open after the signal.
- Each day going forward, the stop-loss is checked before the target
  (conservative assumption when both could plausibly have been hit).
- Two return numbers per trade: strategy_return_pct (following the tool's
  own target1/stop-loss exit rules) and raw_90d_return_pct (just holding
  90 calendar days regardless of stop-loss -- what the >20% filter is
  judged against).
- Performance metrics (win rate, expectancy, profit factor, drawdown,
  Sharpe/Sortino-like ratios) are computed on strategy_return_pct -- the
  tool's own defined objective -- with an explicit TRAIN/OUT-OF-SAMPLE
  split by entry date, so "does a higher score bucket actually perform
  better" is checked on data not used to look at it the first time.

Still a heuristic backtest of a heuristic screener -- no transaction costs
or slippage, today's index list projected backward (survivorship bias),
and the equity-curve/drawdown figures assume each trade consumes a fixed
~2% slice of capital compounding sequentially (roughly a 50-position
diversified book) -- a simplification (real signals overlap in time across
stocks rather than strictly queuing one after another), but a far more
honest order-of-magnitude drawdown estimate than naively compounding 100%
of capital into one trade at a time, which produces a meaningless
near-total-wipeout number over thousands of trades regardless of the real
edge. Treat this as a first, honest look at whether the rulebook has any
edge, not a finished, validated trading system. Sharpe/Sortino here are
per-trade mean/std ratios, NOT annualized in the conventional sense (trades
have variable holding periods) -- labeled as such, not dressed up as a
standard annualized figure.
"""
from __future__ import annotations

import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
import data_sources as ds
import market_regime as regime_mod
import symbols as sym
from analyzer import (
    CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM,
    IndicatorBundle, compute_bundle, score_long_term, score_short_term,
)

BASE_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BASE_DIR / "backtest_results"
RESULTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nifty_agent.backtest")

MIN_WARMUP_DAYS = 200
FORWARD_WINDOW_DAYS = 90
CENSOR_BUFFER_DAYS = 95
TARGET_RETURN_PCT = 20.0

SCORERS = {CATEGORY_SHORT_TERM: score_short_term, CATEGORY_LONG_TERM: score_long_term}


@dataclass
class TradeResult:
    symbol: str
    category: str
    threshold: float
    signal_date: str
    score: float
    grade: str | None
    signal: str
    regime_at_signal: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    exit_reason: str
    days_held: int
    strategy_return_pct: float
    raw_90d_return_pct: float | None
    hit_20pct_raw: bool | None


def _simulate_trade(df: pd.DataFrame, entry_idx: int, target1: float, stop_loss: float,
                     max_days: int = FORWARD_WINDOW_DAYS) -> tuple[int, float, str]:
    entry_date = df.index[entry_idx]
    i = entry_idx
    while i < len(df):
        if (df.index[i] - entry_date).days > max_days:
            break
        low, high = float(df["Low"].iloc[i]), float(df["High"].iloc[i])
        if low <= stop_loss:
            return i, stop_loss, "stop_loss"
        if high >= target1:
            return i, target1, "target1"
        i += 1
    exit_idx = min(i, len(df) - 1)
    return exit_idx, float(df["Close"].iloc[exit_idx]), "time_exit"


def _backtest_one(symbol: str, category: str, df: pd.DataFrame, bundle: IndicatorBundle,
                   regime_bundle: regime_mod.RegimeBundle | None, min_score: float) -> list[TradeResult]:
    scorer = SCORERS[category]
    results: list[TradeResult] = []
    censor_date = df.index[-1] - pd.Timedelta(days=CENSOR_BUFFER_DAYS)

    i = MIN_WARMUP_DAYS
    while i < len(df) - 1:
        if df.index[i] > censor_date:
            break

        regime_label = None
        if regime_bundle is not None:
            # Align by date: regime_bundle is indexed by NIFTY's own trading
            # calendar, which can differ slightly from the stock's (holidays
            # etc.) -- find the nearest regime reading at or before this date.
            regime_idx = regime_bundle.close.index.searchsorted(df.index[i], side="right") - 1
            if regime_idx >= 0:
                regime_label = regime_mod.classify_regime_at(regime_bundle, regime_idx)

        idea = scorer(symbol, bundle, i, regime_label=regime_label, sector_confirmation=None, data_note="")
        if idea.score < min_score:
            i += 1
            continue

        entry_idx = i + 1
        entry_price = float(df["Open"].iloc[entry_idx])
        exit_idx, exit_price, exit_reason = _simulate_trade(df, entry_idx, idea.target1, idea.stop_loss)
        days_held = (df.index[exit_idx] - df.index[entry_idx]).days
        strategy_return_pct = (exit_price / entry_price - 1) * 100

        target_date = df.index[entry_idx] + pd.Timedelta(days=FORWARD_WINDOW_DAYS)
        future = df[df.index >= target_date]
        if not future.empty:
            raw_90d_return_pct = (float(future["Close"].iloc[0]) / entry_price - 1) * 100
            hit_20pct_raw = raw_90d_return_pct >= TARGET_RETURN_PCT
        else:
            raw_90d_return_pct = None
            hit_20pct_raw = None

        results.append(TradeResult(
            symbol=symbol, category=category, threshold=min_score,
            signal_date=str(df.index[i].date()), score=idea.score, grade=idea.grade, signal=idea.signal,
            regime_at_signal=regime_label or "UNKNOWN",
            entry_date=str(df.index[entry_idx].date()), entry_price=round(entry_price, 2),
            exit_date=str(df.index[exit_idx].date()), exit_price=round(exit_price, 2),
            exit_reason=exit_reason, days_held=days_held,
            strategy_return_pct=round(strategy_return_pct, 2),
            raw_90d_return_pct=round(raw_90d_return_pct, 2) if raw_90d_return_pct is not None else None,
            hit_20pct_raw=hit_20pct_raw,
        ))
        i = max(exit_idx + 1, i + 1)

    return results


def backtest_symbol(raw_symbol: str, categories: list[str], thresholds: list[float],
                     history_period: str, regime_bundle: regime_mod.RegimeBundle | None) -> list[TradeResult]:
    yf_ticker = sym.to_yf_ticker(raw_symbol)
    df = ds.fetch_daily_history(yf_ticker, period=history_period)
    if df is None or len(df) < MIN_WARMUP_DAYS + 30:
        logger.warning("Not enough history for %s, skipping", raw_symbol)
        return []

    bundle = compute_bundle(df)
    results: list[TradeResult] = []
    for category in categories:
        for threshold in thresholds:
            results.extend(_backtest_one(raw_symbol, category, df, bundle, regime_bundle, threshold))
    return results


def run_backtest(categories: list[str], thresholds: list[float], history_period: str,
                  universe: list[str], max_workers: int = 8) -> pd.DataFrame:
    logger.info("Fetching NIFTY 50 once to build the point-in-time regime bundle...")
    nifty_df = ds.fetch_daily_history(cfg.REGIME_INDEX_TICKER, period=history_period)
    regime_bundle = regime_mod.compute_regime_bundle(nifty_df) if nifty_df is not None else None
    if regime_bundle is None:
        logger.warning("Could not fetch NIFTY -- backtest will run with Market Regime defaulted to neutral throughout.")

    all_results: list[TradeResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(backtest_symbol, s, categories, thresholds, history_period, regime_bundle): s
                   for s in universe}
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


# ---------------------------------------------------------------------------
# Performance metrics
# ---------------------------------------------------------------------------

PORTFOLIO_ALLOCATION_PER_TRADE = 0.02  # see drawdown note below


def compute_performance_metrics(returns_pct: pd.Series) -> dict:
    """Standard trade-performance metrics on a series of per-trade % returns
    (using strategy_return_pct -- the tool's own defined exit rules)."""
    n = len(returns_pct)
    if n == 0:
        return {"n": 0}

    wins = returns_pct[returns_pct > 0]
    losses = returns_pct[returns_pct <= 0]
    win_rate = len(wins) / n * 100
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
    gross_profit = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Equity curve for drawdown: allocating 100% of capital to each trade in
    # sequence (naive full compounding) is NOT what any real diversified
    # portfolio does, and produces a meaningless near-total-wipeout number
    # over thousands of trades regardless of the real edge. Instead, model
    # each trade as consuming a fixed, modest slice of capital
    # (PORTFOLIO_ALLOCATION_PER_TRADE = 2%, i.e. roughly a 50-position
    # diversified book) compounding sequentially -- still a simplification
    # (real signals overlap in time across stocks rather than strictly
    # queuing), but a far more honest order-of-magnitude drawdown estimate
    # than assuming one all-in account per trade.
    equity = (1 + (returns_pct / 100) * PORTFOLIO_ALLOCATION_PER_TRADE).cumprod()
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown_pct = drawdown.min() * 100

    std = returns_pct.std()
    sharpe_like = returns_pct.mean() / std if std and not np.isnan(std) else 0.0
    downside_std = losses.std() if len(losses) > 1 else 0.0
    sortino_like = returns_pct.mean() / downside_std if downside_std else 0.0

    return {
        "n": n, "win_rate_pct": round(win_rate, 1), "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(avg_loss, 2), "expectancy_pct": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2), "max_drawdown_pct": round(max_drawdown_pct, 1),
        "sharpe_like": round(sharpe_like, 2), "sortino_like": round(sortino_like, 2),
    }


def _format_metrics(m: dict, label: str) -> list[str]:
    if m.get("n", 0) == 0:
        return [f"  {label}: no trades."]
    return [
        f"  {label}: n={m['n']}  win_rate={m['win_rate_pct']}%  expectancy={m['expectancy_pct']}%/trade  "
        f"profit_factor={m['profit_factor']}  max_drawdown={m['max_drawdown_pct']}%  "
        f"sharpe-like={m['sharpe_like']}  sortino-like={m['sortino_like']}  "
        f"(avg win {m['avg_win_pct']}% / avg loss {m['avg_loss_pct']}%)"
    ]


def summarize(df: pd.DataFrame) -> str:
    if df.empty:
        return "No trades were generated at all -- check data fetching / thresholds."

    lines = []
    total = len(df)
    resolved = df[df["raw_90d_return_pct"].notna()].copy()
    lines.append(f"Total simulated trades: {total}  (excluded {total - len(resolved)} too recent for a known 90-day outcome)")
    lines.append(f"Universe: today's NIFTY 50 + SENSEX constituents (see symbols.py) | "
                 f"20%-target uses raw close-to-close return within {FORWARD_WINDOW_DAYS} calendar days\n")

    for threshold in sorted(resolved["threshold"].unique()):
        g = resolved[resolved["threshold"] == threshold]
        hit_rate = g["hit_20pct_raw"].mean() * 100
        lines.append(f"=== Minimum score >= {threshold:.0f}  ({len(g)} signals) ===")
        lines.append(f"  20%-in-90d hit rate: {hit_rate:.1f}%  |  avg raw 90d return: {g['raw_90d_return_pct'].mean():.1f}%"
                      f" (median {g['raw_90d_return_pct'].median():.1f}%, worst {g['raw_90d_return_pct'].min():.1f}%, best {g['raw_90d_return_pct'].max():.1f}%)")
        lines.extend(_format_metrics(compute_performance_metrics(g["strategy_return_pct"]), "Own-target performance"))

        for cat in sorted(g["category"].unique()):
            gc = g[g["category"] == cat]
            lines.append(f"    [{cat}] n={len(gc)}  20%-hit-rate={gc['hit_20pct_raw'].mean()*100:.1f}%  "
                          f"expectancy={compute_performance_metrics(gc['strategy_return_pct']).get('expectancy_pct', 'n/a')}%/trade")
        lines.append("")

    live_threshold = 40.0 if (resolved["threshold"] == 40.0).any() else resolved["threshold"].min()
    live = resolved[resolved["threshold"] == live_threshold]

    lines.append(f"=== Performance by market regime at signal time (threshold {live_threshold:.0f}) ===")
    for regime_label in sorted(live["regime_at_signal"].unique()):
        gr = live[live["regime_at_signal"] == regime_label]
        m = compute_performance_metrics(gr["strategy_return_pct"])
        lines.extend(_format_metrics(m, regime_label))
    lines.append("")

    lines.append(f"=== Train / Out-of-sample split (threshold {live_threshold:.0f}, split at the midpoint entry date) ===")
    live_sorted = live.copy()
    live_sorted["entry_date"] = pd.to_datetime(live_sorted["entry_date"])
    live_sorted = live_sorted.sort_values("entry_date")
    split_point = len(live_sorted) // 2
    train, oos = live_sorted.iloc[:split_point], live_sorted.iloc[split_point:]
    if split_point > 0:
        lines.append(f"  Train period: {train['entry_date'].min().date()} to {train['entry_date'].max().date()}")
        lines.extend(_format_metrics(compute_performance_metrics(train["strategy_return_pct"]), "Train"))
        lines.append(f"  Out-of-sample period: {oos['entry_date'].min().date()} to {oos['entry_date'].max().date()}")
        lines.extend(_format_metrics(compute_performance_metrics(oos["strategy_return_pct"]), "Out-of-sample"))
        lines.append("  (Rule weights were fixed before this backtest was ever run and never adjusted based on "
                      "its results, so this isn't checking for classic overfitting -- it's checking whether "
                      "performance is at least time-consistent rather than driven by one lucky stretch.)")
    else:
        lines.append("  Not enough trades to split.")
    lines.append("")

    per_symbol = (
        live.groupby("symbol")
        .agg(n=("symbol", "size"), hit_rate=("hit_20pct_raw", "mean"), avg_return=("raw_90d_return_pct", "mean"))
        .query("n >= 2")
        .sort_values(["hit_rate", "avg_return"], ascending=False)
    )
    per_symbol["hit_rate"] = per_symbol["hit_rate"] * 100
    if not per_symbol.empty:
        lines.append(f"=== Per-symbol breakdown at threshold {live_threshold:.0f} (min 2 signals) ===")
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
        thresholds=thresholds, history_period=args.history, universe=universe, max_workers=args.workers,
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
