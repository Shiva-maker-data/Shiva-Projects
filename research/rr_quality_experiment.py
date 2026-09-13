"""
RESEARCH ONLY -- Experiment: is Risk/Reward Quality an independent
predictor, or does its apparent edge only exist conditional on other
factors being absent?

Reuses the master observational dataset already produced by
run_factor_audit.py (same point-in-time methodology, same production
scoring functions, no re-fetching, no changes to how it was built) --
this script only slices/aggregates that existing data differently.

No production file is imported for logic here except backtest.py's
compute_performance_metrics is mirrored (not imported) because it expects
a specific column name and this script needs mean/median added -- the
formulas are identical, reproduced in `factor_stats` below for that reason
only, not because the original was inadequate.

Median splits used for LOW/HIGH groups use the full-sample distribution of
each (already point-in-time-computed) factor value -- standard practice
for a research-stage interaction study. This is NOT a lookahead-bias issue
for the factor values themselves (each was computed using only data up to
its own signal day), but a live threshold would need an expanding/rolling
definition; noted here for transparency, not implemented.
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"

RR_COL = "factor__Risk/Reward Quality"
FACTOR_ALIASES = {
    "Short-Term (Swing)": {"Momentum": "factor__Momentum", "Structure/Trend": "factor__Price Structure",
                            "Relative Strength": "factor__Relative Strength", "Market Regime": "factor__Market Regime"},
    "Long-Term": {"Momentum": "factor__Momentum", "Structure/Trend": "factor__Price Trend",
                  "Relative Strength": "factor__Relative Strength", "Market Regime": "factor__Market Regime"},
}
HORIZONS = [1, 5, 10, 20, 60, 90]


def factor_stats(returns: pd.Series) -> dict:
    """Mirrors backtest.compute_performance_metrics's win_rate/expectancy/
    profit_factor formulas exactly, plus mean/median which that function
    doesn't return -- reproduced (not imported) only because this needs a
    generic return series, not one named 'strategy_return_pct'."""
    r = returns.dropna()
    n = len(r)
    if n == 0:
        return {"n": 0, "mean": np.nan, "median": np.nan, "win_rate_pct": np.nan,
                "expectancy_pct": np.nan, "profit_factor": np.nan}
    wins, losses = r[r > 0], r[r <= 0]
    win_rate = len(wins) / n * 100
    avg_win = wins.mean() if len(wins) else 0.0
    avg_loss = losses.mean() if len(losses) else 0.0
    expectancy = (win_rate / 100) * avg_win + (1 - win_rate / 100) * avg_loss
    gross_profit, gross_loss = wins.sum(), abs(losses.sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (float("inf") if gross_profit > 0 else 0.0)
    return {"n": n, "mean": round(r.mean(), 3), "median": round(r.median(), 3),
            "win_rate_pct": round(win_rate, 1), "expectancy_pct": round(expectancy, 3),
            "profit_factor": round(pf, 2) if np.isfinite(pf) else pf}


def fmt(stats: dict) -> str:
    if stats["n"] == 0:
        return "n=0"
    return (f"n={stats['n']}  mean={stats['mean']}%  median={stats['median']}%  "
            f"win_rate={stats['win_rate_pct']}%  expectancy={stats['expectancy_pct']}%  PF={stats['profit_factor']}")


def load_latest_master() -> pd.DataFrame:
    files = sorted(glob.glob(str(RESULTS_DIR / "master_dataset_*.csv")))
    if not files:
        raise FileNotFoundError("No master_dataset_*.csv found -- run research.run_factor_audit first.")
    path = files[-1]
    print(f"Loading master dataset: {path}")
    df = pd.read_csv(path, parse_dates=["date"])
    return df


def monotonic_check(values: list[float]) -> str:
    v = [x for x in values if pd.notna(x)]
    if len(v) < 3:
        return "insufficient buckets"
    d = np.diff(v)
    if np.all(d >= -1e-9):
        return "monotonic increasing"
    if np.all(d <= 1e-9):
        return "monotonic decreasing (inverted)"
    return "NOT monotonic"


def section1_standalone(df: pd.DataFrame, category: str, report: list[str]) -> None:
    sub = df[df["category"] == category]
    valid = sub[sub[RR_COL].notna()].copy()
    if len(valid) < 50:
        report.append(f"  {category}: insufficient data.")
        return
    try:
        valid["bucket"] = pd.qcut(valid[RR_COL], q=5, duplicates="drop")
    except ValueError:
        report.append(f"  {category}: could not form 5 buckets (too few unique RR-Quality values).")
        return

    n_buckets = valid["bucket"].nunique()
    report.append(f"  {category} -- {n_buckets} buckets formed (qcut q=5, duplicates dropped where RR-Quality is discretized)")
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        report.append(f"\n  --- Horizon: {h}d ---")
        agg = []
        for bucket, g in valid.groupby("bucket", observed=True):
            s = factor_stats(g[col])
            agg.append((str(bucket), s))
            report.append(f"    {bucket}: {fmt(s)}")
        mono = monotonic_check([s["mean"] for _, s in agg])
        report.append(f"    Monotonicity ({h}d): {mono}")


def median_split(df: pd.DataFrame, col: str) -> pd.Series:
    """Top-quartile vs rest, NOT a strict median split -- applied uniformly
    to every factor and both categories (not chosen per-factor after
    seeing results). A true median split degenerates for Long-Term's
    Risk/Reward Quality: its distribution is heavily compressed against a
    low ceiling (Long-Term's resistance-capped target1 vs a wide 3xATR
    stop-loss structurally keeps realized RR low, so >50% of observations
    sit AT the same value and none exceeds a strict median) -- a top-25%
    cut still separates a real, non-degenerate HIGH group in that case,
    and is applied the same way to every other factor for consistency."""
    cutoff = df[col].quantile(0.75)
    return np.where(df[col] > cutoff, "HIGH", "LOW")


def section2_3_conditional(df: pd.DataFrame, category: str, report: list[str]) -> dict:
    """Returns the built HIGH/LOW label columns for reuse in later sections."""
    sub = df[df["category"] == category].copy()
    sub["RR_group"] = median_split(sub, RR_COL)
    aliases = FACTOR_ALIASES[category]
    for label, col in aliases.items():
        sub[f"{label}_group"] = median_split(sub, col)

    report.append(f"\n--- {category}: RR-Quality conditional on each factor (fwd_ret_20d) ---")
    for label in aliases:
        report.append(f"\n  vs {label}:")
        for rr_g in ["HIGH", "LOW"]:
            for f_g in ["LOW", "HIGH"]:
                cell = sub[(sub["RR_group"] == rr_g) & (sub[f"{label}_group"] == f_g)]
                s = factor_stats(cell["fwd_ret_20d"])
                report.append(f"    RR {rr_g:4s} / {label} {f_g:4s}: {fmt(s)}")
    return sub


def section5_antitrend(sub: pd.DataFrame, report: list[str]) -> None:
    report.append("\n--- Anti-trend hypothesis: HIGH RR + LOW Momentum vs HIGH RR + HIGH Momentum ---")
    for h in HORIZONS:
        col = f"fwd_ret_{h}d"
        hi_lo = factor_stats(sub[(sub["RR_group"] == "HIGH") & (sub["Momentum_group"] == "LOW")][col])
        hi_hi = factor_stats(sub[(sub["RR_group"] == "HIGH") & (sub["Momentum_group"] == "HIGH")][col])
        lo_lo = factor_stats(sub[(sub["RR_group"] == "LOW") & (sub["Momentum_group"] == "LOW")][col])
        lo_hi = factor_stats(sub[(sub["RR_group"] == "LOW") & (sub["Momentum_group"] == "HIGH")][col])
        report.append(f"  {h}d:  HIGH_RR+LOW_Mom: {fmt(hi_lo)}")
        report.append(f"        HIGH_RR+HIGH_Mom: {fmt(hi_hi)}")
        report.append(f"        LOW_RR+LOW_Mom:  {fmt(lo_lo)}")
        report.append(f"        LOW_RR+HIGH_Mom: {fmt(lo_hi)}")


def section6_regime(sub: pd.DataFrame, report: list[str]) -> None:
    report.append("\n--- RR-Quality (HIGH vs LOW) by market regime (fwd_ret_20d) ---")
    for regime in ["STRONG_BULLISH", "BULLISH", "NEUTRAL", "BEARISH", "STRONG_BEARISH", "HIGH_VOLATILITY"]:
        g = sub[sub["regime"] == regime]
        if g.empty:
            report.append(f"  {regime}: no observations.")
            continue
        hi = factor_stats(g[g["RR_group"] == "HIGH"]["fwd_ret_20d"])
        lo = factor_stats(g[g["RR_group"] == "LOW"]["fwd_ret_20d"])
        report.append(f"  {regime}: HIGH RR {fmt(hi)}  |  LOW RR {fmt(lo)}")

    report.append("\n--- Does RR-Quality level differ by regime? (mean RR-Quality fraction) ---")
    means = sub.groupby("regime")[RR_COL].mean().sort_values(ascending=False)
    report.append(means.round(3).to_string())


def section7_time_stability(sub: pd.DataFrame, report: list[str]) -> None:
    s = sub.sort_values("date")
    n = len(s)
    third = n // 3
    thirds = [("Early", s.iloc[:third]), ("Middle", s.iloc[third:2 * third]), ("Recent", s.iloc[2 * third:])]
    report.append("\n--- Time stability: RR-Quality HIGH vs LOW (fwd_ret_20d) per period ---")
    for label, part in thirds:
        if part.empty:
            continue
        date_range = f"{part['date'].min().date()} to {part['date'].max().date()}"
        hi = factor_stats(part[part["RR_group"] == "HIGH"]["fwd_ret_20d"])
        lo = factor_stats(part[part["RR_group"] == "LOW"]["fwd_ret_20d"])
        report.append(f"  {label} ({date_range}): HIGH RR {fmt(hi)}  |  LOW RR {fmt(lo)}")


def section8_symbol_concentration(sub: pd.DataFrame, report: list[str]) -> None:
    report.append("\n--- Symbol concentration: leave-top-5-out (by count in HIGH-RR bucket) ---")
    hi = sub[sub["RR_group"] == "HIGH"]
    top5 = hi["symbol"].value_counts().head(5).index.tolist()
    report.append(f"  Top 5 symbols in HIGH-RR bucket by count: {top5}")
    baseline = factor_stats(hi["fwd_ret_20d"])
    excl = factor_stats(hi[~hi["symbol"].isin(top5)]["fwd_ret_20d"])
    report.append(f"  Baseline (all symbols):        {fmt(baseline)}")
    report.append(f"  Excluding those 5 symbols:     {fmt(excl)}")


def main():
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    df = load_latest_master()
    report = []
    report.append("RR-QUALITY INDEPENDENCE EXPERIMENT (research only, no production changes)")
    report.append(f"Master dataset: {len(df)} rows\n")

    for category in ["Short-Term (Swing)", "Long-Term"]:
        report.append(f"\n{'='*70}\nCATEGORY: {category}\n{'='*70}")

        report.append("\n### SECTION 1: RR-Quality standalone (all horizons) ###")
        section1_standalone(df, category, report)

        report.append("\n### SECTIONS 2/3: Conditional + interaction analysis ###")
        sub = section2_3_conditional(df, category, report)

        report.append("\n### SECTION 5: Anti-trend hypothesis ###")
        section5_antitrend(sub, report)

        report.append("\n### SECTION 6: Market regime conditioning ###")
        section6_regime(sub, report)

        report.append("\n### SECTION 7: Time stability ###")
        section7_time_stability(sub, report)

        report.append("\n### SECTION 8: Symbol concentration ###")
        section8_symbol_concentration(sub, report)

    full_report = "\n".join(str(x) for x in report)
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"rr_quality_experiment_{ts}.txt"
    out_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {out_path}")


if __name__ == "__main__":
    main()
