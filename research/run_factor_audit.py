"""
RESEARCH ONLY. Produces the factor-level audit report. Does not modify any
production file -- reads/reuses analyzer.py, backtest.py, market_regime.py,
sector.py functions unchanged (see factor_data.py's docstring).

Run:
    .venv\\Scripts\\python.exe -m research.run_factor_audit --history 3y
    .venv\\Scripts\\python.exe -m research.run_factor_audit --universe-limit 8 --history 2y   (quick check)
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM
from backtest import compute_performance_metrics
import config as cfg
import symbols as sym
from research.factor_data import FORWARD_HORIZONS, load_universe, build_master_dataset, run_ablation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("nifty_agent.research")

RESULTS_DIR = Path(__file__).resolve().parent / "results"
RESULTS_DIR.mkdir(exist_ok=True)

CATEGORY_FACTORS = {
    CATEGORY_SHORT_TERM: list(cfg.WEIGHTS_SHORT_TERM.keys()),
    CATEGORY_LONG_TERM: list(cfg.WEIGHTS_LONG_TERM.keys()),
}
FWD_COLS = [f"fwd_ret_{h}d" for h in FORWARD_HORIZONS]


# ---------------------------------------------------------------------------
# Section 1/2: per-factor correlation + quantile/bucket analysis
# ---------------------------------------------------------------------------

def factor_correlation_table(df: pd.DataFrame, category: str) -> pd.DataFrame:
    sub = df[df["category"] == category]
    rows = []
    for factor in CATEGORY_FACTORS[category]:
        col = f"factor__{factor}"
        if col not in sub.columns:
            continue
        valid = sub[[col] + FWD_COLS].dropna(subset=[col])
        n = len(valid)
        row = {"factor": factor, "n": n}
        for h, fc in zip(FORWARD_HORIZONS, FWD_COLS):
            v = valid.dropna(subset=[fc])
            row[f"corr_{h}d"] = v[col].corr(v[fc]) if len(v) > 30 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def factor_bucket_table(df: pd.DataFrame, category: str, factor: str, horizon_col: str = "fwd_ret_20d") -> pd.DataFrame:
    sub = df[df["category"] == category]
    col = f"factor__{factor}"
    if col not in sub.columns:
        return pd.DataFrame()
    valid = sub[[col, horizon_col]].dropna()
    if len(valid) < 50:
        return pd.DataFrame()
    try:
        valid = valid.copy()
        valid["bucket"] = pd.qcut(valid[col], q=5, duplicates="drop")
    except ValueError:
        return pd.DataFrame()
    agg = valid.groupby("bucket", observed=True)[horizon_col].agg(["count", "mean", "median"])
    win_rate = valid.groupby("bucket", observed=True)[horizon_col].apply(lambda s: (s > 0).mean() * 100)
    agg["win_rate_pct"] = win_rate
    return agg


def check_monotonic(series: pd.Series) -> str:
    vals = series.dropna().values
    if len(vals) < 3:
        return "insufficient buckets"
    diffs = np.diff(vals)
    if np.all(diffs >= -1e-9):
        return "monotonic increasing"
    if np.all(diffs <= 1e-9):
        return "monotonic decreasing (inverted)"
    return "NOT monotonic"


# ---------------------------------------------------------------------------
# Section 6: factor redundancy
# ---------------------------------------------------------------------------

def redundancy_matrix(df: pd.DataFrame, category: str) -> pd.DataFrame:
    sub = df[df["category"] == category]
    cols = [f"factor__{f}" for f in CATEGORY_FACTORS[category] if f"factor__{f}" in sub.columns]
    return sub[cols].corr()


# ---------------------------------------------------------------------------
# Section 7: cross-sectional vs absolute
# ---------------------------------------------------------------------------

def cross_sectional_table(df: pd.DataFrame, category: str, horizon_col: str = "fwd_ret_20d") -> pd.DataFrame:
    sub = df[df["category"] == category].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    # Rank within each date across stocks -- needs >=5 stocks scored on the same day to be meaningful
    counts = sub.groupby("date")["symbol"].transform("count")
    sub = sub[counts >= 5]
    sub["xs_pct_rank"] = sub.groupby("date")["score"].rank(pct=True)
    valid = sub[["xs_pct_rank", horizon_col]].dropna()
    if len(valid) < 50:
        return pd.DataFrame()
    valid = valid.copy()
    valid["xs_bucket"] = pd.qcut(valid["xs_pct_rank"], q=5, duplicates="drop")
    agg = valid.groupby("xs_bucket", observed=True)[horizon_col].agg(["count", "mean", "median"])
    return agg


# ---------------------------------------------------------------------------
# Section 8: time-period robustness
# ---------------------------------------------------------------------------

def time_split_correlation(df: pd.DataFrame, category: str, factor: str, horizon_col: str = "fwd_ret_20d") -> pd.DataFrame:
    sub = df[df["category"] == category].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    col = f"factor__{factor}"
    if col not in sub.columns:
        return pd.DataFrame()
    n = len(sub)
    third = n // 3
    thirds = [sub.iloc[:third], sub.iloc[third:2 * third], sub.iloc[2 * third:]]
    rows = []
    for label, part in zip(["Early", "Middle", "Recent"], thirds):
        valid = part[[col, horizon_col]].dropna()
        rows.append({
            "period": label,
            "date_range": f"{part['date'].min().date()} to {part['date'].max().date()}" if len(part) else "n/a",
            "n": len(valid),
            "corr": valid[col].corr(valid[horizon_col]) if len(valid) > 30 else np.nan,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Section 5: regime anomaly robustness
# ---------------------------------------------------------------------------

def regime_robustness(ablation_full: pd.DataFrame) -> dict:
    out = {}
    base = ablation_full[ablation_full["regime"].isin(["BULLISH", "STRONG_BEARISH"])]
    out["baseline"] = {
        r: compute_performance_metrics(base[base["regime"] == r]["strategy_return_pct"])
        for r in ["BULLISH", "STRONG_BEARISH"]
    }

    # (a) symbol concentration -- top-3 symbols by trade count in each regime
    top_symbols = {}
    for r in ["BULLISH", "STRONG_BEARISH"]:
        vc = ablation_full[ablation_full["regime"] == r]["symbol"].value_counts()
        top_symbols[r] = list(vc.head(3).index)
    out["top_symbols"] = top_symbols

    excl_symbols = set(top_symbols["BULLISH"]) | set(top_symbols["STRONG_BEARISH"])
    excl = base[~base["symbol"].isin(excl_symbols)]
    out["excl_top_symbols"] = {
        r: compute_performance_metrics(excl[excl["regime"] == r]["strategy_return_pct"])
        for r in ["BULLISH", "STRONG_BEARISH"]
    }

    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", default="3y")
    parser.add_argument("--universe-limit", type=int, default=None)
    parser.add_argument("--min-score", type=float, default=40.0)
    args = parser.parse_args()

    universe = sym.get_universe()
    if args.universe_limit:
        universe = universe[: args.universe_limit]

    logger.info("=== FACTOR AUDIT (research only, no production changes) ===")
    u = load_universe(universe, history_period=args.history)
    universe = list(u.daily.keys())  # only symbols that actually loaded

    logger.info("Building master observational dataset (%d symbols x 2 categories)...", len(universe))
    master = build_master_dataset(u, universe)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    master_path = RESULTS_DIR / f"master_dataset_{ts}.csv"
    master.to_csv(master_path, index=False)
    logger.info("Master dataset saved: %s (%d rows)", master_path, len(master))

    report = []
    report.append(f"FACTOR AUDIT -- {len(universe)} symbols, history={args.history}, generated {ts}")
    report.append(f"Master dataset: {len(master)} rows ({master_path.name})")
    report.append("CAVEAT: forward-return observations for the same stock overlap in time (adjacent signal-days "
                   "share most of their forward window) -- NOT independent draws. Correlations/bucket patterns "
                   "below are descriptive evidence, not p-value-backed hypothesis tests.\n")

    # ---- Section 1/2: correlation + bucket + monotonicity per factor ----
    for category in (CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM):
        report.append(f"\n{'='*70}\nCATEGORY: {category}\n{'='*70}")
        corr_table = factor_correlation_table(master, category)
        report.append("\n--- Factor correlation with forward returns (Pearson r) ---")
        report.append(corr_table.to_string(index=False, float_format=lambda x: f"{x:.3f}"))

        report.append("\n--- Quantile bucket analysis (fwd_ret_20d) + monotonicity ---")
        for factor in CATEGORY_FACTORS[category]:
            bt = factor_bucket_table(master, category, factor, "fwd_ret_20d")
            if bt.empty:
                report.append(f"  {factor}: insufficient data for bucketing.")
                continue
            mono = check_monotonic(bt["mean"])
            report.append(f"  {factor} -- monotonicity: {mono}")
            report.append("    " + bt.to_string().replace("\n", "\n    "))

        report.append("\n--- Cross-sectional rank vs absolute score (fwd_ret_20d) ---")
        xs = cross_sectional_table(master, category, "fwd_ret_20d")
        if not xs.empty:
            report.append(xs.to_string())
            report.append(f"  Cross-sectional monotonicity: {check_monotonic(xs['mean'])}")
        else:
            report.append("  Insufficient same-date coverage for cross-sectional ranking.")

        report.append("\n--- Time-period robustness (score factor -> fwd_ret_20d correlation) ---")
        for factor in CATEGORY_FACTORS[category]:
            tt = time_split_correlation(master, category, factor, "fwd_ret_20d")
            if not tt.empty:
                report.append(f"  {factor}:")
                report.append("    " + tt.to_string(index=False, float_format=lambda x: f"{x:.3f}").replace("\n", "\n    "))

        report.append("\n--- Factor redundancy (correlation matrix among factor fractions) ---")
        rmat = redundancy_matrix(master, category)
        report.append(rmat.to_string(float_format=lambda x: f"{x:.2f}"))
        high_corr_pairs = []
        for i, a in enumerate(rmat.columns):
            for b in rmat.columns[i + 1:]:
                v = rmat.loc[a, b]
                if pd.notna(v) and abs(v) >= 0.4:
                    high_corr_pairs.append((a, b, round(v, 2)))
        report.append(f"  Pairs with |r|>=0.4 (possible redundancy): {high_corr_pairs or 'none'}")

    # ---- Section 3: ablation study ----
    report.append(f"\n{'='*70}\nABLATION STUDY (threshold={args.min_score})\n{'='*70}")
    for category in (CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM):
        report.append(f"\n--- {category} ---")
        variants = [("FULL SCORE", None)] + [(f"minus {f}", f) for f in CATEGORY_FACTORS[category]]
        ablation_frames = {}
        for label, factor in variants:
            trades = run_ablation(u, universe, category, ablate_factor=factor, min_score=args.min_score)
            ablation_frames[label] = trades
            m = compute_performance_metrics(trades["strategy_return_pct"]) if len(trades) else {"n": 0}
            if m.get("n", 0) == 0:
                report.append(f"  {label}: no trades.")
                continue
            report.append(f"  {label}: n={m['n']}  win_rate={m['win_rate_pct']}%  expectancy={m['expectancy_pct']}%/trade  "
                           f"profit_factor={m['profit_factor']}  max_drawdown={m['max_drawdown_pct']}%  "
                           f"sharpe-like={m['sharpe_like']}  sortino-like={m['sortino_like']}")

        if category == CATEGORY_SHORT_TERM:
            full_trades = ablation_frames["FULL SCORE"]

    # ---- Section 5: regime anomaly robustness (Short-Term full-score trades) ----
    report.append(f"\n{'='*70}\nREGIME ANOMALY ROBUSTNESS (Short-Term, full score, threshold={args.min_score})\n{'='*70}")
    st_full = run_ablation(u, universe, CATEGORY_SHORT_TERM, ablate_factor=None, min_score=args.min_score)
    lt_full = run_ablation(u, universe, CATEGORY_LONG_TERM, ablate_factor=None, min_score=args.min_score)
    combined_full = pd.concat([st_full, lt_full], ignore_index=True)
    rr = regime_robustness(combined_full)
    report.append(f"Baseline: BULLISH n={rr['baseline']['BULLISH'].get('n',0)} "
                   f"expectancy={rr['baseline']['BULLISH'].get('expectancy_pct','n/a')}%  |  "
                   f"STRONG_BEARISH n={rr['baseline']['STRONG_BEARISH'].get('n',0)} "
                   f"expectancy={rr['baseline']['STRONG_BEARISH'].get('expectancy_pct','n/a')}%")
    report.append(f"Top symbols driving each regime bucket: {rr['top_symbols']}")
    report.append(f"After excluding those top symbols: BULLISH "
                   f"n={rr['excl_top_symbols']['BULLISH'].get('n',0)} expectancy={rr['excl_top_symbols']['BULLISH'].get('expectancy_pct','n/a')}%  |  "
                   f"STRONG_BEARISH n={rr['excl_top_symbols']['STRONG_BEARISH'].get('n',0)} "
                   f"expectancy={rr['excl_top_symbols']['STRONG_BEARISH'].get('expectancy_pct','n/a')}%")

    # sector composition per regime
    report.append("\nSector composition of BULLISH vs STRONG_BEARISH signals (Short-Term+Long-Term combined):")
    sector_map_reverse = master[["symbol", "sector_ticker"]].drop_duplicates().set_index("symbol")["sector_ticker"].to_dict()
    for r in ["BULLISH", "STRONG_BEARISH"]:
        syms = combined_full[combined_full["regime"] == r]["symbol"]
        sectors = syms.map(sector_map_reverse).fillna("UNMAPPED").value_counts()
        report.append(f"  {r}: {sectors.to_dict()}")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"factor_audit_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nFull report saved to: {report_path}")
    print(f"Master dataset saved to: {master_path}")


if __name__ == "__main__":
    main()
