"""
RESEARCH ONLY -- Experiment: does volatility/ATR explain the
STRONG_BEARISH > BULLISH regime anomaly, given the fixed-ATR-multiple
target/stop construction?

Uses the SAME population that produced the original anomaly: threshold=40,
non-overlapping, target1/stop-loss-simulated trades via
research.factor_data.run_ablation (which itself calls the UNCHANGED
production scoring functions and backtest._simulate_trade). Not the raw
unfiltered master dataset from the earlier factor audit -- that's a
different population (every candidate day, no threshold/exit simulation)
and would not be answering "does volatility explain THIS anomaly."

ATR bucketing uses the exact same fixed thresholds analyzer._volatility_profile
already uses in production (<=3% orderly, 3-5% moderate, >5% excessive) --
not a data-dependent quantile chosen after seeing outcomes, so the boundary
is identical and fair across both regimes by construction.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM
from research.factor_data import load_universe, run_ablation
from research.rr_quality_experiment import factor_stats, fmt, RESULTS_DIR

TOP_SYMBOLS = {  # reused verbatim from the prior factor audit -- not re-derived here
    "BULLISH": ["LT", "BAJFINANCE", "JSWSTEEL"],
    "STRONG_BEARISH": ["WIPRO", "HINDALCO", "TATASTEEL"],
}


def atr_bucket(atr_pct: float) -> str:
    if pd.isna(atr_pct):
        return "UNKNOWN"
    if atr_pct <= 3.0:
        return "LOW (<=3%)"
    if atr_pct <= 5.0:
        return "MEDIUM (3-5%)"
    return "HIGH (>5%)"


def section1_basic(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 1: Basic STRONG_BEARISH vs BULLISH comparison ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        s = factor_stats(g["strategy_return_pct"])
        report.append(f"\n  {regime}: n={len(g)}")
        report.append(f"    Volatility Profile factor: mean={g['factor__Volatility Profile'].mean():.3f} "
                       f"median={g['factor__Volatility Profile'].median():.3f}" if "factor__Volatility Profile" in g.columns and len(g) else "    Volatility Profile factor: n/a")
        report.append(f"    ATR%%: mean={g['atr_pct'].mean():.2f}%  median={g['atr_pct'].median():.2f}%")
        report.append(f"    Target distance: mean={g['target_distance_pct'].mean():.2f}%")
        report.append(f"    Stop distance: mean={g['stop_distance_pct'].mean():.2f}%")
        report.append(f"    Realized performance: {fmt(s)}")


def section2_3_buckets(df: pd.DataFrame, report: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["atr_bucket"] = df["atr_pct"].apply(atr_bucket)
    report.append("\n### SECTION 2/3: Volatility-bucket comparison (common fixed ATR%% boundaries) ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        g = df[df["regime"] == regime]
        for bucket in ["LOW (<=3%)", "MEDIUM (3-5%)", "HIGH (>5%)"]:
            gb = g[g["atr_bucket"] == bucket]
            if gb.empty:
                report.append(f"    {bucket}: no trades.")
                continue
            s = factor_stats(gb["strategy_return_pct"])
            target_rate = (gb["exit_reason"] == "target1").mean() * 100
            stop_rate = (gb["exit_reason"] == "stop_loss").mean() * 100
            report.append(f"    {bucket}: {fmt(s)}  target_hit={target_rate:.0f}%  stop_hit={stop_rate:.0f}%  "
                           f"avg_days_held={gb['days_held'].mean():.1f}")

    report.append("\n  --- WITHIN-BUCKET comparison: does STRONG_BEARISH beat BULLISH at the SAME volatility level? ---")
    for bucket in ["LOW (<=3%)", "MEDIUM (3-5%)", "HIGH (>5%)"]:
        bull = factor_stats(df[(df["regime"] == "BULLISH") & (df["atr_bucket"] == bucket)]["strategy_return_pct"])
        bear = factor_stats(df[(df["regime"] == "STRONG_BEARISH") & (df["atr_bucket"] == bucket)]["strategy_return_pct"])
        report.append(f"    {bucket}:  BULLISH {fmt(bull)}  |  STRONG_BEARISH {fmt(bear)}")
    return df


def section4_mechanics(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 4: ATR target/stop exit mechanics ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        n = len(g)
        if n == 0:
            report.append(f"  {regime}: no trades.")
            continue
        target_hit = g[g["exit_reason"] == "target1"]
        stop_hit = g[g["exit_reason"] == "stop_loss"]
        timeout = g[g["exit_reason"] == "time_exit"]
        report.append(f"\n  {regime} (n={n}):")
        report.append(f"    Target distance avg={g['target_distance_pct'].mean():.2f}%  "
                       f"Stop distance avg={g['stop_distance_pct'].mean():.2f}%  ATR%% avg={g['atr_pct'].mean():.2f}%")
        report.append(f"    Target-hit: {len(target_hit)} ({len(target_hit)/n*100:.1f}%)  "
                       f"avg days-to-target={target_hit['days_held'].mean():.1f}" if len(target_hit) else "    Target-hit: 0")
        report.append(f"    Stop-hit: {len(stop_hit)} ({len(stop_hit)/n*100:.1f}%)  "
                       f"avg days-to-stop={stop_hit['days_held'].mean():.1f}" if len(stop_hit) else "    Stop-hit: 0")
        report.append(f"    Timeout (90d, neither hit): {len(timeout)} ({len(timeout)/n*100:.1f}%)  "
                       f"avg return-after-timeout={timeout['strategy_return_pct'].mean():.2f}%" if len(timeout) else "    Timeout: 0")


def _hilo(df: pd.DataFrame, col: str) -> pd.Series:
    cutoff = df[col].quantile(0.75)
    return np.where(df[col] > cutoff, "HIGH", "LOW")


def section5_6_interactions(df: pd.DataFrame, report: list[str], factor_col: str, factor_label: str) -> None:
    report.append(f"\n### Volatility x {factor_label} ###")
    d = df.copy()
    d["vol_group"] = np.where(d["atr_bucket"] == "LOW (<=3%)", "LOW", np.where(d["atr_bucket"] == "HIGH (>5%)", "HIGH", "MEDIUM_excluded"))
    d = d[d["vol_group"] != "MEDIUM_excluded"]  # clean 2x2, medium excluded per instructions (not forced into either bin)
    if factor_col not in d.columns or d[factor_col].notna().sum() < 30:
        report.append(f"  Insufficient data for {factor_label}.")
        return
    d[f"{factor_label}_group"] = _hilo(d, factor_col)

    def cell(vol, fac):
        return d[(d["vol_group"] == vol) & (d[f"{factor_label}_group"] == fac)]

    report.append("  All regimes combined:")
    for vol in ["LOW", "HIGH"]:
        for fac in ["LOW", "HIGH"]:
            s = factor_stats(cell(vol, fac)["strategy_return_pct"])
            report.append(f"    Vol {vol:4s} / {factor_label} {fac:4s}: {fmt(s)}")

    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"  Within {regime}:")
        dr = d[d["regime"] == regime]
        for vol in ["LOW", "HIGH"]:
            for fac in ["LOW", "HIGH"]:
                cc = dr[(dr["vol_group"] == vol) & (dr[f"{factor_label}_group"] == fac)]
                s = factor_stats(cc["strategy_return_pct"])
                report.append(f"    Vol {vol:4s} / {factor_label} {fac:4s}: {fmt(s)}")


def section7_robustness(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 7: Symbol/sector robustness (reusing prior audit's exact exclusion list) ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        baseline = factor_stats(g["strategy_return_pct"])
        excl = factor_stats(g[~g["symbol"].isin(TOP_SYMBOLS[regime])]["strategy_return_pct"])
        report.append(f"  {regime}: baseline {fmt(baseline)}  |  excluding {TOP_SYMBOLS[regime]}: {fmt(excl)}")
        sectors = g["sector_ticker"].fillna("UNMAPPED").value_counts()
        report.append(f"    Sector spread: {sectors.to_dict()}")


def section8_time(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 8: Time stability (same 3-way chronological split as prior audits) ###")
    d = df.copy()
    d["signal_date"] = pd.to_datetime(d["signal_date"])
    d = d.sort_values("signal_date")
    n = len(d)
    third = n // 3
    thirds = [("Early", d.iloc[:third]), ("Middle", d.iloc[third:2 * third]), ("Recent", d.iloc[2 * third:])]
    for label, part in thirds:
        if part.empty:
            continue
        date_range = f"{part['signal_date'].min().date()} to {part['signal_date'].max().date()}"
        report.append(f"\n  {label} ({date_range}):")
        for regime in ["BULLISH", "STRONG_BEARISH"]:
            g = part[part["regime"] == regime]
            s = factor_stats(g["strategy_return_pct"])
            avg_atr = g["atr_pct"].mean() if len(g) else float("nan")
            report.append(f"    {regime}: {fmt(s)}  avg_ATR%={avg_atr:.2f}%" if len(g) else f"    {regime}: no trades")


def main():
    report = []
    report.append("VOLATILITY / REGIME ANOMALY EXPERIMENT (research only, no production changes)")

    from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM
    import symbols as sym

    universe = sym.get_universe()
    u = load_universe(universe, history_period="3y")
    universe = list(u.daily.keys())

    print("Running ablation-style trade simulation (threshold=40, full score) for both categories...")
    st = run_ablation(u, universe, CATEGORY_SHORT_TERM, ablate_factor=None, min_score=40.0)
    lt = run_ablation(u, universe, CATEGORY_LONG_TERM, ablate_factor=None, min_score=40.0)
    combined = pd.concat([st, lt], ignore_index=True)

    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_path = RESULTS_DIR / f"volatility_trades_{ts}.csv"
    combined.to_csv(data_path, index=False)
    print(f"Trade-level dataset saved: {data_path} ({len(combined)} rows)")

    report.append(f"Trade dataset: {len(combined)} rows ({data_path.name})")
    report.append(f"BULLISH n={len(combined[combined['regime']=='BULLISH'])}  "
                   f"STRONG_BEARISH n={len(combined[combined['regime']=='STRONG_BEARISH'])}")

    section1_basic(combined, report)
    bucketed = section2_3_buckets(combined, report)
    section4_mechanics(bucketed, report)
    section5_6_interactions(bucketed, report, "factor__Risk/Reward Quality", "RRQuality")
    section5_6_interactions(bucketed, report, "factor__Momentum", "Momentum")
    section7_robustness(bucketed, report)
    section8_time(bucketed, report)

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"volatility_regime_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
