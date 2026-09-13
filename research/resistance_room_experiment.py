"""
RESEARCH ONLY -- Experiment: does "room to run" toward resistance/52-week
highs explain the STRONG_BEARISH > BULLISH regime anomaly?

Follows the same two-dataset pattern as research/support_proximity_experiment.py:
  - "master" (build_master_dataset, unfiltered, every candidate day): used
    for the general "does resistance-distance predict returns at all,
    independent of regime" question.
  - "trades" (run_ablation, threshold=40, non-overlapping, real
    target1/stop-loss simulation): the EXACT population that produced the
    original anomaly (n=324 BULLISH, n=48 STRONG_BEARISH) -- used for every
    section that asks "does this explain THAT anomaly."

resistance20 and high52w are used completely unmodified, straight from the
production IndicatorBundle (see Section A of the report for the verified
definitions).
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
    df["dist_resistance_pct"] = (df["resistance20"] - df["entry_price"]) / df["entry_price"] * 100
    df["dist_52w_high_pct"] = (df["high52w"] - df["entry_price"]) / df["entry_price"] * 100
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


def section2_regime(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 2: Regime-level comparison -- room to run ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        s = factor_stats(g["strategy_return_pct"])
        target_rate = (g["exit_reason"] == "target1").mean() * 100 if len(g) else float("nan")
        stop_rate = (g["exit_reason"] == "stop_loss").mean() * 100 if len(g) else float("nan")
        report.append(f"\n  {regime} (n={len(g)}):")
        report.append(f"    [A] Dist to resistance20: mean={g['dist_resistance_pct'].mean():.2f}%  "
                       f"median={g['dist_resistance_pct'].median():.2f}%  std={g['dist_resistance_pct'].std():.2f}%  "
                       f"p25={g['dist_resistance_pct'].quantile(.25):.2f}%  p75={g['dist_resistance_pct'].quantile(.75):.2f}%")
        report.append(f"    [B] Dist to 52w high:    mean={g['dist_52w_high_pct'].mean():.2f}%  "
                       f"median={g['dist_52w_high_pct'].median():.2f}%  std={g['dist_52w_high_pct'].std():.2f}%  "
                       f"p25={g['dist_52w_high_pct'].quantile(.25):.2f}%  p75={g['dist_52w_high_pct'].quantile(.75):.2f}%")
        report.append(f"    Realized performance: {fmt(s)}  target_hit={target_rate:.0f}%  stop_hit={stop_rate:.0f}%")


def _bucket_and_compare(df: pd.DataFrame, dist_col: str, bucket_col: str, report: list[str], label: str) -> pd.DataFrame:
    df = df.copy()
    try:
        df[bucket_col], edges = pd.qcut(df[dist_col], q=4, retbins=True, duplicates="drop")
    except ValueError:
        report.append(f"  Could not form quantile buckets for {label} (insufficient unique values).")
        return df
    buckets = list(df[bucket_col].cat.categories)
    report.append(f"\n### SECTION 3: {label} buckets (common pooled-quantile boundaries, {len(buckets)} bucket(s)) ###")
    report.append(f"  Boundaries (pooled {dist_col}, %): {np.round(edges, 2).tolist()}  [CLOSEST-to-level first]")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        g = df[df["regime"] == regime]
        for bucket in buckets:
            gb = g[g[bucket_col] == bucket]
            if gb.empty:
                report.append(f"    {bucket}: no trades.")
                continue
            s = factor_stats(gb["strategy_return_pct"])
            target_rate = (gb["exit_reason"] == "target1").mean() * 100
            stop_rate = (gb["exit_reason"] == "stop_loss").mean() * 100
            report.append(f"    {bucket}: n={len(gb)}  {fmt(s)}  target_hit={target_rate:.0f}%  stop_hit={stop_rate:.0f}%")

    report.append(f"\n  --- WITHIN-BUCKET: does STRONG_BEARISH beat BULLISH at the SAME {label} level? ---")
    for bucket in buckets:
        bull = df[(df["regime"] == "BULLISH") & (df[bucket_col] == bucket)]
        bear = df[(df["regime"] == "STRONG_BEARISH") & (df[bucket_col] == bucket)]
        bull_s, bear_s = factor_stats(bull["strategy_return_pct"]), factor_stats(bear["strategy_return_pct"])
        flag = "  [SMALL SAMPLE]" if min(len(bull), len(bear)) < 15 else ""
        exp_gap = (bear_s["mean"] - bull_s["mean"]) if pd.notna(bear_s["mean"]) and pd.notna(bull_s["mean"]) else float("nan")
        win_gap = (bear_s["win_rate_pct"] - bull_s["win_rate_pct"]) if pd.notna(bear_s.get("win_rate_pct")) and pd.notna(bull_s.get("win_rate_pct")) else float("nan")
        report.append(f"    {bucket}:  BULLISH n={len(bull)} {fmt(bull_s)}  |  STRONG_BEARISH n={len(bear)} {fmt(bear_s)}"
                       f"  |  exp_gap={exp_gap:+.2f}pp  win_gap={win_gap:+.1f}pp{flag}")
    return df


def section4_matrix(df: pd.DataFrame, bucket_col: str, report: list[str], label: str) -> None:
    if bucket_col not in df.columns:
        return
    report.append(f"\n### SECTION 5: {label} x Regime matrix ###")
    majority_note = df[df["regime"].isin(["BULLISH", "STRONG_BEARISH"])][bucket_col].value_counts()
    for bucket in df[bucket_col].cat.categories:
        for regime in ["STRONG_BEARISH", "BULLISH"]:
            g = df[(df[bucket_col] == bucket) & (df["regime"] == regime)]
            s = factor_stats(g["strategy_return_pct"])
            flag = "  [SMALL SAMPLE]" if len(g) < 20 else ""
            report.append(f"  {bucket} + {regime}: n={len(g)}  {fmt(s)}{flag}")
    if len(majority_note):
        top_bucket = majority_note.idxmax()
        report.append(f"  Majority of trades fall in bucket: {top_bucket} ({majority_note.max()} of {majority_note.sum()})")


def section_direct(master: pd.DataFrame, dist_col: str, report: list[str], label: str) -> None:
    report.append(f"\n### SECTION 4: {label} vs forward returns, independent of regime (master dataset, all signal-days) ###")
    m = master[master[dist_col].notna()].copy()
    try:
        m["q"] = pd.qcut(m[dist_col], q=5, duplicates="drop")
    except ValueError:
        report.append("  Could not form quintiles.")
        return
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        v = m[[col, dist_col]].dropna()
        corr = v[dist_col].corr(v[col]) if len(v) >= 30 else float("nan")
        report.append(f"\n  --- Horizon {h}d --- (corr={corr:.3f}, n={len(v)})")
        means = []
        for bucket, g in m.groupby("q", observed=True):
            s = factor_stats(g[col])
            means.append(s["mean"])
            report.append(f"    {bucket}: n={len(g)}  {fmt(s)}")
        report.append(f"    Monotonicity: {monotonic_check(means)}")


def section6_resistance_vs_52w(master: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 6: 20d-resistance distance vs 52w-high distance -- which is the stronger explanatory variable? ###")
    m = master.dropna(subset=["dist_resistance_pct", "dist_52w_high_pct"])
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        v = m[[col, "dist_resistance_pct", "dist_52w_high_pct"]].dropna()
        if len(v) < 30:
            continue
        report.append(f"  {h}d: corr(dist_resistance20)={v['dist_resistance_pct'].corr(v[col]):.3f}  "
                       f"corr(dist_52w_high)={v['dist_52w_high_pct'].corr(v[col]):.3f}")
    same_level_frac = (master["dist_resistance_pct"].sub(master["dist_52w_high_pct"]).abs() < 0.5).mean() * 100
    report.append(f"\n  Fraction of signal-days where resistance20 == 52w-high (within 0.5%): {same_level_frac:.1f}% "
                   f"(20d resistance is capped by / often coincides with the 52w high for stocks near multi-year highs)")


def section7_geometry(df: pd.DataFrame, bucket_col: str, report: list[str]) -> None:
    if bucket_col not in df.columns:
        return
    report.append("\n### SECTION 7: Target/stop geometry vs resistance-room bucket ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        g = df[df["regime"] == regime]
        for bucket in df[bucket_col].cat.categories:
            gb = g[g[bucket_col] == bucket]
            if gb.empty:
                continue
            target_rate = (gb["exit_reason"] == "target1").mean() * 100
            stop_rate = (gb["exit_reason"] == "stop_loss").mean() * 100
            timeout_rate = (gb["exit_reason"] == "time_exit").mean() * 100
            target_days = gb.loc[gb["exit_reason"] == "target1", "days_held"].mean()
            stop_days = gb.loc[gb["exit_reason"] == "stop_loss", "days_held"].mean()
            report.append(f"    {bucket} (n={len(gb)}): target_dist={gb['target_distance_pct'].mean():.2f}%  "
                           f"stop_dist={gb['stop_distance_pct'].mean():.2f}%  "
                           f"ratio={gb['target_distance_pct'].mean()/gb['stop_distance_pct'].mean():.2f}  "
                           f"target_hit={target_rate:.0f}%(avg_days={target_days:.1f})  "
                           f"stop_hit={stop_rate:.0f}%(avg_days={stop_days:.1f})  timeout={timeout_rate:.0f}%")


def _hilo(df: pd.DataFrame, col: str) -> pd.Series:
    cutoff = df[col].quantile(0.75)
    return np.where(df[col] > cutoff, "HIGH", "LOW")


def section8_9_control(df: pd.DataFrame, report: list[str], factor_col: str, label: str) -> None:
    report.append(f"\n### Controlling for {label} ###")
    d = df.copy()
    close_cutoff = d["dist_resistance_pct"].quantile(0.5)
    d["resist_group"] = np.where(d["dist_resistance_pct"] <= close_cutoff, "CLOSE(<=med)", "FAR(>med)")
    if factor_col not in d.columns or d[factor_col].notna().sum() < 30:
        report.append(f"  Insufficient data for {label}.")
        return
    d[f"{label}_group"] = _hilo(d, factor_col)

    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"  Within {regime}:")
        dr = d[d["regime"] == regime]
        for resist_g in ["CLOSE(<=med)", "FAR(>med)"]:
            for fac in ["LOW", "HIGH"]:
                cc = dr[(dr["resist_group"] == resist_g) & (dr[f"{label}_group"] == fac)]
                s = factor_stats(cc["strategy_return_pct"])
                flag = "  [SMALL SAMPLE / UNTESTABLE]" if len(cc) < 15 else ""
                report.append(f"    {label} {fac:4s} / Resistance-room {resist_g:12s}: n={len(cc)}  {fmt(s)}{flag}")


def section10_time(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 10: Time-split robustness (same 3-way chronological split as prior audits) ###")
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
            if g.empty:
                report.append(f"    {regime}: no trades")
                continue
            s = factor_stats(g["strategy_return_pct"])
            report.append(f"    {regime}: n={len(g)}  {fmt(s)}  mean_dist_resistance={g['dist_resistance_pct'].mean():.2f}%")


def section11_symbols(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 11: Symbol robustness (reusing prior audits' exact exclusion list) ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        baseline = factor_stats(g["strategy_return_pct"])
        excl = factor_stats(g[~g["symbol"].isin(TOP_SYMBOLS[regime])]["strategy_return_pct"])
        report.append(f"  {regime}: baseline n={len(g)} {fmt(baseline)}  |  excluding {TOP_SYMBOLS[regime]}: "
                       f"n={len(g[~g['symbol'].isin(TOP_SYMBOLS[regime])])} {fmt(excl)}")
        report.append(f"    Mean dist_resistance_pct (baseline vs excl): "
                       f"{g['dist_resistance_pct'].mean():.2f}%  vs  "
                       f"{g[~g['symbol'].isin(TOP_SYMBOLS[regime])]['dist_resistance_pct'].mean():.2f}%")


def section12_sectors(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### SECTION 12: Sector robustness ###")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        sectors = g["sector_ticker"].fillna("UNMAPPED").value_counts()
        report.append(f"  {regime} sector spread: {sectors.to_dict()}")


def main():
    universe = sym.get_universe()
    u = load_universe(universe, history_period="3y")
    universe = list(u.daily.keys())

    print("Building master dataset (with resistance20/high52w)...")
    master = build_master_dataset(u, universe)
    master = add_distances(master)

    print("Running ablation-style trade simulation (threshold=40, full score)...")
    st = run_ablation(u, universe, CATEGORY_SHORT_TERM, ablate_factor=None, min_score=40.0)
    lt = run_ablation(u, universe, CATEGORY_LONG_TERM, ablate_factor=None, min_score=40.0)
    trades = add_distances(pd.concat([st, lt], ignore_index=True))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    trades.to_csv(RESULTS_DIR / f"resistance_trades_{ts}.csv", index=False)
    master.to_csv(RESULTS_DIR / f"resistance_master_{ts}.csv", index=False)

    report = []
    report.append("RESISTANCE / ROOM-TO-RUN EXPERIMENT (research only, no production changes)")
    report.append(f"Trade dataset: {len(trades)} rows | Master dataset: {len(master)} rows")
    report.append(f"BULLISH n={len(trades[trades['regime']=='BULLISH'])}  "
                   f"STRONG_BEARISH n={len(trades[trades['regime']=='STRONG_BEARISH'])}")

    section2_regime(trades, report)
    bucketed = _bucket_and_compare(trades, "dist_resistance_pct", "resist_bucket", report, "Resistance-room")
    section_direct(master, "dist_resistance_pct", report, "20d-resistance distance")
    section4_matrix(bucketed, "resist_bucket", report, "Resistance-room")
    section6_resistance_vs_52w(master, report)

    # 52w-high conditioning (Section 6 of the spec) -- same bucket/matrix treatment, using dist_52w_high_pct
    report.append("\n\n========== 52-WEEK-HIGH CONDITIONING (parallel to resistance20 above) ==========")
    bucketed_52w = _bucket_and_compare(trades, "dist_52w_high_pct", "high52w_bucket", report, "52w-high-room")
    section_direct(master, "dist_52w_high_pct", report, "52-week-high distance")
    section4_matrix(bucketed_52w, "high52w_bucket", report, "52w-high-room")

    section7_geometry(bucketed, "resist_bucket", report)
    section8_9_control(bucketed, report, "factor__Risk/Reward Quality", "RRQuality")
    section8_9_control(bucketed, report, "factor__Momentum", "Momentum")
    section10_time(bucketed, report)
    section11_symbols(bucketed, report)
    section12_sectors(bucketed, report)

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"resistance_room_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
