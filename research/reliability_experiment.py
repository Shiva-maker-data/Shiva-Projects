"""
RESEARCH ONLY -- statistical-reliability experiment.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, 2026-09-13),
audited from research/results/resistance_room_report_20260913_164146.txt.

Question: is the STRONG_BEARISH-minus-BULLISH expectancy/win-rate gap in
the canonical resistance_trades dataset statistically distinguishable from
sampling noise -- NOT whether any factor causally explains it. Four
candidate mechanical explanations (volatility, support-distance,
resistance-distance, 52-week-high-distance) were already rejected in prior
experiments; this asks whether n=48 vs n=324 is even large enough for the
gap to mean anything.

Fixed input: research/results/resistance_trades_20260913_164146.csv,
UNMODIFIED (SHA-256 recorded in the report). That population was produced
by research.factor_data.run_ablation, which calls the UNCHANGED production
functions analyzer.score_short_term/score_long_term, analyzer._grade_from_score,
analyzer._classify_signal, and backtest._simulate_trade -- verified by
inspecting research/factor_data.py (not re-verified by re-running; this
script only reads the already-produced CSV, never regenerates it).

Method implemented literally per NEXT_EXPERIMENT.md, precommitted, no
alternate seeds/definitions/subsets explored:
  1. Baseline descriptive stats (reusing research.rr_quality_experiment's
     factor_stats/fmt formatting helpers -- descriptive only, not scoring).
  2. Primary null test: stratified (time_split x category) label
     permutation, seed 20260913, exactly 100,000 draws. Within each
     stratum containing both regime labels, the regime label is shuffled
     across that stratum's trades while preserving the stratum's own
     BULLISH/STRONG_BEARISH counts; single-label strata are left
     unchanged (nothing to permute). Because every stratum's per-label
     count is preserved exactly, the pooled totals (48 STRONG_BEARISH /
     324 BULLISH) are identical in every draw -- verified in code via
     assertion, not assumed.
  3. Uncertainty: stratified calendar-month-cluster bootstrap within each
     regime independently, seed 20260913+1, exactly 20,000 draws --
     resampling whole signal-month clusters (with all their trades) with
     replacement, computed via per-month sum/count aggregates (exact,
     not an approximation of the cluster bootstrap).
  4. Sensitivity: symbol-exclusion repeat (same procedure, same seeds),
     ST/LT descriptive breakdown, STRONG_BEARISH concentration by symbol
     and calendar month.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from research.rr_quality_experiment import factor_stats, fmt, RESULTS_DIR

INPUT_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"
PERM_SEED = 20260913
BOOT_SEED = 20260913 + 1  # documented deterministic offset from the permutation seed
R_PERM = 100_000
R_BOOT = 20_000

TOP_SYMBOLS = {  # reused verbatim from every prior VYOM experiment, not re-derived
    "BULLISH": ["LT", "BAJFINANCE", "JSWSTEEL"],
    "STRONG_BEARISH": ["WIPRO", "HINDALCO", "TATASTEEL"],
}

# Fixed calendar splits, copied verbatim from experiment 5's reported date
# ranges (not re-derived by re-splitting this filtered population into
# thirds, which would silently change the boundaries).
SPLIT_EARLY_END = pd.Timestamp("2025-01-31")     # Early: date <= this
SPLIT_MIDDLE_END = pd.Timestamp("2025-10-17")    # Middle: EARLY_END < date <= this ; Recent: date > this


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def assign_time_split(dates: pd.Series) -> pd.Series:
    return np.select(
        [dates <= SPLIT_EARLY_END, dates <= SPLIT_MIDDLE_END],
        ["Early", "Middle"],
        default="Recent",
    )


def load_filtered() -> tuple[pd.DataFrame, int]:
    df = pd.read_csv(INPUT_PATH, parse_dates=["signal_date"])
    total_rows = len(df)
    df = df[df["regime"].isin(["BULLISH", "STRONG_BEARISH"])].copy()
    df["time_split"] = assign_time_split(df["signal_date"])
    return df.reset_index(drop=True), total_rows


def permutation_test(df: pd.DataFrame, seed: int, r: int) -> dict:
    """Stratified (time_split x category) label-permutation null test.
    Returns observed gaps, null-draw arrays, and two-sided empirical
    p-values."""
    returns = df["strategy_return_pct"].to_numpy(dtype=float)
    wins = (returns > 0).astype(float)
    is_bear_actual = (df["regime"] == "STRONG_BEARISH").to_numpy()
    n = len(df)
    total_k = int(is_bear_actual.sum())

    obs_exp_gap = returns[is_bear_actual].mean() - returns[~is_bear_actual].mean()
    obs_win_gap = wins[is_bear_actual].mean() * 100 - wins[~is_bear_actual].mean() * 100

    strata_keys = sorted((df["time_split"] + "|" + df["category"]).unique())
    rng = np.random.default_rng(seed)
    is_bear_matrix = np.zeros((r, n), dtype=bool)

    for key in strata_keys:  # fixed, deterministic iteration order
        mask = (df["time_split"] + "|" + df["category"]) == key
        positions = np.where(mask.to_numpy())[0]
        m = len(positions)
        k = int(is_bear_actual[positions].sum())
        if k == 0 or k == m:
            is_bear_matrix[:, positions] = is_bear_actual[positions]
            continue
        rand_vals = rng.random((r, m))
        order = np.argsort(rand_vals, axis=1)
        bear_local = order[:, :k]
        stratum_bool = np.zeros((r, m), dtype=bool)
        rows = np.repeat(np.arange(r), k)
        cols = bear_local.ravel()
        stratum_bool[rows, cols] = True
        is_bear_matrix[:, positions] = stratum_bool

    bear_counts = is_bear_matrix.sum(axis=1)
    assert np.all(bear_counts == total_k), "stratified permutation must preserve total STRONG_BEARISH count in every draw"

    bear_sum = is_bear_matrix @ returns
    bull_sum = returns.sum() - bear_sum
    null_exp_gap = bear_sum / total_k - bull_sum / (n - total_k)

    winbear_sum = is_bear_matrix @ wins
    winbull_sum = wins.sum() - winbear_sum
    null_win_gap = (winbear_sum / total_k - winbull_sum / (n - total_k)) * 100

    p_exp = (1 + np.sum(np.abs(null_exp_gap) >= np.abs(obs_exp_gap))) / (r + 1)
    p_win = (1 + np.sum(np.abs(null_win_gap) >= np.abs(obs_win_gap))) / (r + 1)

    return {
        "n": n, "n_bear": total_k, "n_bull": n - total_k,
        "obs_exp_gap": obs_exp_gap, "obs_win_gap": obs_win_gap,
        "p_exp": p_exp, "p_win": p_win,
        "null_exp_gap": null_exp_gap, "null_win_gap": null_win_gap,
        "strata": strata_keys,
    }


def cluster_bootstrap(df: pd.DataFrame, seed: int, r: int) -> dict:
    """Stratified calendar-month-cluster bootstrap, independent per regime.
    Exact via per-month (sum, count, win-sum) aggregates -- resampling a
    month cluster pulls in its full aggregate, equivalent to resampling
    all of that month's individual trades together."""
    rng = np.random.default_rng(seed)
    d = df.copy()
    d["month"] = d["signal_date"].dt.to_period("M").astype(str)

    per_regime = {}
    for regime in ["BULLISH", "STRONG_BEARISH"]:  # fixed order -> deterministic rng draw sequence
        g = d[d["regime"] == regime]
        agg = g.groupby("month")["strategy_return_pct"].agg(["sum", "count"])
        agg["winsum"] = g.assign(win=(g["strategy_return_pct"] > 0).astype(float)).groupby("month")["win"].sum()
        n_clusters = len(agg)
        idx = rng.integers(0, n_clusters, size=(r, n_clusters))
        sums = agg["sum"].to_numpy()[idx].sum(axis=1)
        counts = agg["count"].to_numpy()[idx].sum(axis=1)
        winsums = agg["winsum"].to_numpy()[idx].sum(axis=1)
        per_regime[regime] = {
            "mean": sums / counts, "winrate": winsums / counts * 100,
            "n_clusters": n_clusters, "months": list(agg.index),
        }

    exp_gap = per_regime["STRONG_BEARISH"]["mean"] - per_regime["BULLISH"]["mean"]
    win_gap = per_regime["STRONG_BEARISH"]["winrate"] - per_regime["BULLISH"]["winrate"]
    return {
        "exp_gap": exp_gap, "win_gap": win_gap,
        "exp_ci": (np.percentile(exp_gap, 2.5), np.percentile(exp_gap, 97.5)),
        "win_ci": (np.percentile(win_gap, 2.5), np.percentile(win_gap, 97.5)),
        "n_clusters_bull": per_regime["BULLISH"]["n_clusters"],
        "n_clusters_bear": per_regime["STRONG_BEARISH"]["n_clusters"],
    }


def run_full_procedure(df: pd.DataFrame, label: str, ts: str, report: list[str], save_draws: bool) -> dict:
    report.append(f"\n#### {label} (n_total={len(df)}) ####")
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        g = df[df["regime"] == regime]
        s = factor_stats(g["strategy_return_pct"])
        report.append(f"  {regime}: {fmt(s)}")

    perm = permutation_test(df, PERM_SEED, R_PERM)
    report.append(f"  Observed gaps: expectancy={perm['obs_exp_gap']:+.3f}pp  win_rate={perm['obs_win_gap']:+.1f}pp")
    report.append(f"  Strata used ({len(perm['strata'])}): {perm['strata']}")
    report.append(f"  Permutation ({R_PERM} draws, seed={PERM_SEED}): "
                   f"p_expectancy={perm['p_exp']:.5f}  p_win_rate={perm['p_win']:.5f}")

    boot = cluster_bootstrap(df, BOOT_SEED, R_BOOT)
    report.append(f"  Bootstrap ({R_BOOT} draws, seed={BOOT_SEED}, "
                   f"clusters: BULLISH={boot['n_clusters_bull']} months, STRONG_BEARISH={boot['n_clusters_bear']} months):")
    report.append(f"    Expectancy-gap 95% CI: [{boot['exp_ci'][0]:+.3f}, {boot['exp_ci'][1]:+.3f}] pp")
    report.append(f"    Win-rate-gap 95% CI:   [{boot['win_ci'][0]:+.1f}, {boot['win_ci'][1]:+.1f}] pp")

    if save_draws:
        null_path = RESULTS_DIR / f"reliability_null_draws_{label.lower().replace(' ', '_')}_{ts}.csv"
        pd.DataFrame({"null_exp_gap": perm["null_exp_gap"], "null_win_gap": perm["null_win_gap"]}).to_csv(null_path, index=False)
        report.append(f"  Null draws saved: {null_path.name} ({R_PERM} rows)")
        boot_path = RESULTS_DIR / f"reliability_bootstrap_draws_{label.lower().replace(' ', '_')}_{ts}.csv"
        pd.DataFrame({"boot_exp_gap": boot["exp_gap"], "boot_win_gap": boot["win_gap"]}).to_csv(boot_path, index=False)
        report.append(f"  Bootstrap draws saved: {boot_path.name} ({R_BOOT} rows)")

    return {"perm": perm, "boot": boot}


def time_split_descriptive(df: pd.DataFrame, report: list[str]) -> dict:
    report.append("\n### Time-split descriptive check (Early/Middle each need a positive expectancy gap; Recent untestable if STRONG_BEARISH n=0) ###")
    gaps = {}
    for split in ["Early", "Middle", "Recent"]:
        part = df[df["time_split"] == split]
        bull = part[part["regime"] == "BULLISH"]
        bear = part[part["regime"] == "STRONG_BEARISH"]
        bull_s, bear_s = factor_stats(bull["strategy_return_pct"]), factor_stats(bear["strategy_return_pct"])
        if len(bear) == 0:
            report.append(f"  {split}: BULLISH {fmt(bull_s)}  |  STRONG_BEARISH n=0 -- UNTESTABLE")
            gaps[split] = None
            continue
        gap = bear_s["mean"] - bull_s["mean"]
        flag = "  [STRONG_BEARISH n<15 -- split significance not claimed]" if len(bear) < 15 else ""
        report.append(f"  {split}: BULLISH {fmt(bull_s)}  |  STRONG_BEARISH {fmt(bear_s)}  |  expectancy_gap={gap:+.3f}pp{flag}")
        gaps[split] = gap
    return gaps


def category_breakdown(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### Descriptive breakdown by category (Short-Term vs Long-Term) ###")
    for category in ["Short-Term (Swing)", "Long-Term"]:
        part = df[df["category"] == category]
        report.append(f"\n  --- {category} ---")
        for regime in ["BULLISH", "STRONG_BEARISH"]:
            g = part[part["regime"] == regime]
            s = factor_stats(g["strategy_return_pct"])
            flag = "  [UNDERPOWERED n<20]" if len(g) < 20 else ""
            report.append(f"    {regime}: {fmt(s)}{flag}")


def concentration_tables(df: pd.DataFrame, report: list[str]) -> None:
    report.append("\n### STRONG_BEARISH concentration (symbol and calendar month) ###")
    bear = df[df["regime"] == "STRONG_BEARISH"].copy()
    bear["month"] = bear["signal_date"].dt.to_period("M").astype(str)
    report.append(f"  By symbol: {bear['symbol'].value_counts().to_dict()}")
    report.append(f"  By month:  {bear['month'].value_counts().sort_index().to_dict()}")


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["STATISTICAL RELIABILITY EXPERIMENT -- STRONG_BEARISH vs BULLISH anomaly (research only, no production changes)"]

    report.append("\n## Provenance and fixed input")
    report.append(f"  Input file: {INPUT_PATH.relative_to(INPUT_PATH.parents[2])}")
    report.append(f"  SHA-256: {sha256_of(INPUT_PATH)}")
    report.append(f"  Command: python -m research.reliability_experiment")
    report.append(f"  Runtime: Python {sys.version.split()[0]}  pandas {pd.__version__}  numpy {np.__version__}")
    report.append(f"  Seeds: permutation={PERM_SEED}  bootstrap={BOOT_SEED} (documented offset = permutation seed + 1)")
    report.append(f"  Draws: permutation={R_PERM}  bootstrap={R_BOOT}")
    report.append("  Source verification (from research/factor_data.py, inspected not re-run): this input was produced by "
                   "run_ablation(), which calls analyzer.score_short_term/score_long_term, analyzer._grade_from_score, "
                   "analyzer._classify_signal, and backtest._simulate_trade UNCHANGED -- no reimplemented scoring logic.")
    report.append("  Point-in-time note: this experiment performs no new indicator/score computation; it only resamples "
                   "already-realized trade outcomes from a frozen, previously-verified point-in-time-safe population. "
                   "No future information is introduced by permutation or bootstrap resampling of realized outcomes.")

    df, total_rows = load_filtered()
    report.append(f"\n  Rows in file (all regimes): {total_rows}")
    report.append(f"  Rows after filtering regime in {{BULLISH, STRONG_BEARISH}}: {len(df)} "
                   f"(BULLISH={len(df[df.regime=='BULLISH'])}, STRONG_BEARISH={len(df[df.regime=='STRONG_BEARISH'])})")

    report.append("\n## Time-split convention (fixed before inspecting outcomes)")
    report.append(f"  Early:  signal_date <= {SPLIT_EARLY_END.date()}")
    report.append(f"  Middle: {SPLIT_EARLY_END.date()} < signal_date <= {SPLIT_MIDDLE_END.date()}")
    report.append(f"  Recent: signal_date > {SPLIT_MIDDLE_END.date()}")

    report.append("\n## Hypothesis and falsification rule (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: the positive STRONG_BEARISH expectancy/win-rate gap is statistically reliable, not a small-sample artefact.")
    report.append("  Falsified (or 'insufficient evidence') UNLESS ALL of:")
    report.append("    1. expectancy-gap permutation p<0.05 AND bootstrap 95% CI entirely above zero")
    report.append("    2. win-rate-gap permutation p<0.05 AND bootstrap 95% CI entirely above zero")
    report.append("    3. Early AND Middle both show a positive expectancy gap")

    report.append("\n## PRIMARY PROCEDURE (full population)")
    primary = run_full_procedure(df, "Primary", ts, report, save_draws=True)
    time_gaps = time_split_descriptive(df, report)

    report.append("\n## SENSITIVITY CHECKS (must not override the primary decision)")

    report.append("\n### Sensitivity 1: symbol-exclusion repeat (same seeds, same procedure) ###")
    excl_mask = ~(((df["regime"] == "BULLISH") & (df["symbol"].isin(TOP_SYMBOLS["BULLISH"]))) |
                  ((df["regime"] == "STRONG_BEARISH") & (df["symbol"].isin(TOP_SYMBOLS["STRONG_BEARISH"]))))
    df_excl = df[excl_mask].reset_index(drop=True)
    sensitivity = run_full_procedure(df_excl, "Excl top-3 symbols", ts, report, save_draws=True)

    category_breakdown(df, report)
    concentration_tables(df, report)

    report.append("\n## PRIMARY DECISION")
    cond1 = primary["perm"]["p_exp"] < 0.05 and primary["boot"]["exp_ci"][0] > 0
    cond2 = primary["perm"]["p_win"] < 0.05 and primary["boot"]["win_ci"][0] > 0
    cond3 = (time_gaps.get("Early") is not None and time_gaps["Early"] > 0 and
             time_gaps.get("Middle") is not None and time_gaps["Middle"] > 0)
    report.append(f"  Condition 1 (expectancy p<0.05 and CI>0): {cond1}  "
                   f"(p={primary['perm']['p_exp']:.5f}, CI={primary['boot']['exp_ci']})")
    report.append(f"  Condition 2 (win-rate p<0.05 and CI>0):   {cond2}  "
                   f"(p={primary['perm']['p_win']:.5f}, CI={primary['boot']['win_ci']})")
    report.append(f"  Condition 3 (Early and Middle both positive): {cond3}  "
                   f"(Early={time_gaps.get('Early')}, Middle={time_gaps.get('Middle')})")
    reliable = cond1 and cond2 and cond3
    report.append(f"\n  ALL CONDITIONS MET: {reliable}")
    report.append(f"  Verdict: {'Gap is statistically distinguishable from noise under the precommitted test (reliable).' if reliable else 'Insufficient evidence that the gap is distinguishable from noise under the precommitted test -- NOT proof of no effect, and NOT a causal claim either way.'}")
    report.append("  Note: a non-rejection here is not proof of a causal regime effect, and this experiment makes no production recommendation regardless of outcome.")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"reliability_experiment_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
