"""
RESEARCH ONLY -- Experiment: does proximity to the existing production
support20/resistance20 fields explain the STRONG_BEARISH > BULLISH regime
anomaly?

Two datasets, for two different questions:
  - "master" (build_master_dataset, unfiltered, every candidate day): used
    for Section 5's general "does support-distance predict returns at all,
    independent of regime" question -- the broadest, most statistically
    supported population available.
  - "trades" (run_ablation, threshold=40, non-overlapping, real
    target1/stop-loss simulation): the EXACT population that produced the
    original anomaly (n=324 BULLISH, n=48 STRONG_BEARISH) -- used for every
    section that asks "does this explain THAT anomaly."

support20/resistance20 are used completely unmodified, straight from the
production IndicatorBundle (see Section A of the report for the verified
definition).
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM
import symbols as sym
from research.factor_data import load_universe, build_master_dataset, run_ablation
from research.rr_quality_experiment import factor_stats, fmt, RESULTS_DIR

TOP_SYMBOLS = {  # reused verbatim from prior audits, not re-derived
    "BULLISH": ["LT", "BAJFINANCE", "JSWSTEEL"],
    "STRONG_BEARISH": ["WIPRO", "HINDALCO", "TATASTEEL"],
}
HORIZONS = [1, 5, 10, 20, 60, 90]


def add_distances(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["dist_support_pct"] = (df["entry_price"] - df["support20"]) / df["entry_price"] * 100
    df["dist_resistance_pct"] = (df["resistance20"] - df["entry_price"]) / df["entry_price"] * 100
    df["closer_to"] = np.where(df["dist_support_pct"] < df["dist_resistance_pct"], "SUPPORT", "RESISTANCE")
    return df


def monotonic_check(values: list[float]) -> str:
    v = [x for x in values if pd.notna(x)]
    if len(v) < 3:
        return "insufficient buckets"
    d = np.diff(v)
    if np.all(d >= -1e-9):
        return "monotonic increasing"
    if np.all(d <= 1e-9):
        return "monotonic decreasing"
    return "NOT monotonic"


def section2_basic(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 2: Distance to support/resistance -- STRONG_BEARISH vs BULLISH ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        report.append(f"\n  {regime} (n={len(g)}):")
        report.append(f"    Distance to support: mean={g['dist_support_pct'].mean():.2f}%  "
                       f"median={g['dist_support_pct'].median():.2f}%  std={g['dist_support_pct'].std():.2f}%")
        report.append(f"    Distance to resistance: mean={g['dist_resistance_pct'].mean():.2f}%  "
                       f"median={g['dist_resistance_pct'].median():.2f}%  std={g['dist_resistance_pct'].std():.2f}%")
        closer = g["closer_to"].value_counts(normalize=True) * 100
        report.append(f"    Closer to: {closer.round(1).to_dict()}")


def section3_buckets(df: pd.DataFrame, report: list[str]) -> pd.DataFrame:
    """Common quantile boundaries computed on the POOLED population (both
    regimes together), then applied identically to each regime -- not
    separate boundaries per regime."""
    df = df.copy()
    df["support_bucket"], edges = pd.qcut(df["dist_support_pct"], q=3, retbins=True, duplicates="drop")
    buckets = list(df["support_bucket"].cat.categories)

    report.append("\n### SECTION 3: Support-proximity buckets (common pooled-quantile boundaries) ###")
    report.append(f"  Boundaries (pooled dist_support_pct, %): {np.round(edges, 2).tolist()}  "
                   f"[{len(buckets)} bucket(s) -- CLOSEST-to-support first]")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        g = df[df["regime"] == regime]
        for bucket in buckets:
            gb = g[g["support_bucket"] == bucket]
            if gb.empty:
                report.append(f"    {bucket}: no trades.")
                continue
            s = factor_stats(gb["strategy_return_pct"])
            target_rate = (gb["exit_reason"] == "target1").mean() * 100
            stop_rate = (gb["exit_reason"] == "stop_loss").mean() * 100
            report.append(f"    {bucket}: {fmt(s)}  target_hit={target_rate:.0f}%  stop_hit={stop_rate:.0f}%")

    report.append("\n  --- WITHIN-BUCKET: does STRONG_BEARISH beat BULLISH at the SAME support-proximity level? ---")
    for bucket in buckets:
        bull = factor_stats(df[(df["regime"] == "BULLISH") & (df["support_bucket"] == bucket)]["strategy_return_pct"])
        bear = factor_stats(df[(df["regime"] == "STRONG_BEARISH") & (df["support_bucket"] == bucket)]["strategy_return_pct"])
        report.append(f"    {bucket}:  BULLISH {fmt(bull)}  |  STRONG_BEARISH {fmt(bear)}")
    return df


def section4_matrix(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 4: Support-proximity x Regime matrix ###")
    for bucket in df["support_bucket"].cat.categories:
        for regime in ["STRONG_BEARISH", "BULLISH"]:
            g = df[(df["support_bucket"] == bucket) & (df["regime"] == regime)]
            s = factor_stats(g["strategy_return_pct"])
            flag = "  [SMALL SAMPLE]" if len(g) < 20 else ""
            report.append(f"  {bucket} + {regime}: {fmt(s)}{flag}")


def section5_direct(master: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 5: Support distance vs forward returns, independent of regime (master dataset, all signal-days) ###")
    m = add_distances(master)
    m = m[m["dist_support_pct"].notna()]
    try:
        m["support_q"] = pd.qcut(m["dist_support_pct"], q=5, duplicates="drop")
    except ValueError:
        report.append("  Could not form quintiles.")
        return
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        report.append(f"\n  --- Horizon {h}d ---")
        means = []
        for bucket, g in m.groupby("support_q", observed=True):
            s = factor_stats(g[col])
            means.append(s["mean"])
            report.append(f"    {bucket}: {fmt(s)}")
        report.append(f"    Monotonicity: {monotonic_check(means)}")


def section6_support_vs_resistance(master: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 6: Support vs Resistance distance -- which correlates more with forward returns? ###")
    m = add_distances(master)
    m["support_minus_resistance"] = m["dist_support_pct"] - m["dist_resistance_pct"]
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        v = m[[col, "dist_support_pct", "dist_resistance_pct", "support_minus_resistance"]].dropna()
        if len(v) < 30:
            continue
        report.append(f"  {h}d: corr(dist_support)={v['dist_support_pct'].corr(v[col]):.3f}  "
                       f"corr(dist_resistance)={v['dist_resistance_pct'].corr(v[col]):.3f}  "
                       f"corr(support-minus-resistance)={v['support_minus_resistance'].corr(v[col]):.3f}")

    report.append("\n  By which level is closer at signal time (fwd_ret_20d):")
    for label in ["SUPPORT", "RESISTANCE"]:
        g = m[m["closer_to"] == label]
        s = factor_stats(g["fwd_ret_20d"])
        report.append(f"    Closer to {label}: {fmt(s)}")


def section7_geometry(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 7: Target/stop geometry vs support/resistance proximity ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        g = df[df["regime"] == regime]
        for bucket in df["support_bucket"].cat.categories:
            gb = g[g["support_bucket"] == bucket]
            if gb.empty:
                continue
            target_rate = (gb["exit_reason"] == "target1").mean() * 100
            stop_rate = (gb["exit_reason"] == "stop_loss").mean() * 100
            timeout_rate = (gb["exit_reason"] == "time_exit").mean() * 100
            report.append(f"    {bucket} (n={len(gb)}): target_dist={gb['target_distance_pct'].mean():.2f}%  "
                           f"stop_dist={gb['stop_distance_pct'].mean():.2f}%  "
                           f"dist_support={gb['dist_support_pct'].mean():.2f}%  dist_resistance={gb['dist_resistance_pct'].mean():.2f}%  "
                           f"target_hit={target_rate:.0f}%  stop_hit={stop_rate:.0f}%  timeout={timeout_rate:.0f}%")


def _hilo(df: pd.DataFrame, col: str) -> pd.Series:
    cutoff = df[col].quantile(0.75)
    return np.where(df[col] > cutoff, "HIGH", "LOW")


def section8_9_control(df: pd.DataFrame, report: list[str], factor_col: str, label: str) -> None:
    report.append(f"\n### Controlling for {label} ###")
    d = df.copy()
    close_cutoff = d["dist_support_pct"].quantile(0.5)
    d["support_group"] = np.where(d["dist_support_pct"] <= close_cutoff, "CLOSE", "FAR")
    if factor_col not in d.columns or d[factor_col].notna().sum() < 30:
        report.append(f"  Insufficient data for {label}.")
        return
    d[f"{label}_group"] = _hilo(d, factor_col)

    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"  Within {regime}:")
        dr = d[d["regime"] == regime]
        for support_g in ["CLOSE", "FAR"]:
            for fac in ["LOW", "HIGH"]:
                cc = dr[(dr["support_group"] == support_g) & (dr[f"{label}_group"] == fac)]
                s = factor_stats(cc["strategy_return_pct"])
                flag = "  [SMALL SAMPLE]" if len(cc) < 15 else ""
                report.append(f"    {label} {fac:4s} / Support {support_g:8s}: {fmt(s)}{flag}")


def section10_robustness(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 10: Robustness (symbols, sectors, time) ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        baseline = factor_stats(g["strategy_return_pct"])
        excl = factor_stats(g[~g["symbol"].isin(TOP_SYMBOLS[regime])]["strategy_return_pct"])
        report.append(f"  {regime} symbols: baseline {fmt(baseline)}  |  excluding {TOP_SYMBOLS[regime]}: {fmt(excl)}")
        sectors = g["sector_ticker"].fillna("UNMAPPED").value_counts()
        report.append(f"    Sector spread: {sectors.to_dict()}")
        report.append(f"    Mean dist_support_pct: {g['dist_support_pct'].mean():.2f}%")

    d = df.copy()
    d["signal_date"] = pd.to_datetime(d["signal_date"])
    d = d.sort_values("signal_date")
    n = len(d)
    third = n // 3
    thirds = [("Early", d.iloc[:third]), ("Middle", d.iloc[third:2 * third]), ("Recent", d.iloc[2 * third:])]
    report.append("\n  Time periods:")
    for label, part in thirds:
        if part.empty:
            continue
        date_range = f"{part['signal_date'].min().date()} to {part['signal_date'].max().date()}"
        report.append(f"    {label} ({date_range}):")
        for regime in ["BULLISH", "STRONG_BEARISH"]:
            g = part[part["regime"] == regime]
            if g.empty:
                report.append(f"      {regime}: no trades")
                continue
            s = factor_stats(g["strategy_return_pct"])
            report.append(f"      {regime}: {fmt(s)}  mean_dist_support={g['dist_support_pct'].mean():.2f}%")


def main():
    universe = sym.get_universe()
    u = load_universe(universe, history_period="3y")
    universe = list(u.daily.keys())

    print("Building master dataset (with support20/resistance20)...")
    master = build_master_dataset(u, universe)

    print("Running ablation-style trade simulation (threshold=40, full score)...")
    st = run_ablation(u, universe, CATEGORY_SHORT_TERM, ablate_factor=None, min_score=40.0)
    lt = run_ablation(u, universe, CATEGORY_LONG_TERM, ablate_factor=None, min_score=40.0)
    trades = add_distances(pd.concat([st, lt], ignore_index=True))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trades.to_csv(RESULTS_DIR / f"support_trades_{ts}.csv", index=False)
    master.to_csv(RESULTS_DIR / f"support_master_{ts}.csv", index=False)

    report = []
    report.append("SUPPORT/RESISTANCE PROXIMITY EXPERIMENT (research only, no production changes)")
    report.append(f"Trade dataset: {len(trades)} rows | Master dataset: {len(master)} rows")
    report.append(f"BULLISH n={len(trades[trades['regime']=='BULLISH'])}  "
                   f"STRONG_BEARISH n={len(trades[trades['regime']=='STRONG_BEARISH'])}")

    section2_basic(trades, report)
    bucketed = section3_buckets(trades, report)
    section4_matrix(bucketed, report)
    section5_direct(master, report)
    section6_support_vs_resistance(master, report)
    section7_geometry(bucketed, report)
    section8_9_control(bucketed, report, "factor__Risk/Reward Quality", "RRQuality")
    section8_9_control(bucketed, report, "factor__Momentum", "Momentum")
    section10_robustness(bucketed, report)

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"support_proximity_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
