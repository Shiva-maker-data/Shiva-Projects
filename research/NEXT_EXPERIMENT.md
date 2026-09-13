# VYOM Research — NEXT EXPERIMENT

## Experiment: statistical reliability of the STRONG_BEARISH versus BULLISH anomaly

### Single question and hypothesis

Using only the completed canonical trade population, test whether the observed STRONG_BEARISH-minus-BULLISH expectancy and win-rate gaps are statistically distinguishable from noise after preserving fixed time and strategy-category composition. This tests reliability, not causality or a strategy change.

**Hypothesis:** the positive STRONG_BEARISH gap is statistically reliable rather than an artefact of its small sample (`n=48` versus BULLISH `n=324`).

### Fixed input and provenance

- Use exactly `research/results/resistance_trades_20260913_164146.csv`; record its SHA-256, row count, filtered counts, command, package/runtime versions, seed(s), and output filenames. Do not refetch, regenerate, alter, deduplicate, or change the signal/trade population.
- Filter only `regime in {BULLISH, STRONG_BEARISH}`, retain both categories, and define the gaps as STRONG_BEARISH minus BULLISH for (a) mean `strategy_return_pct` and (b) `strategy_return_pct > 0` win rate.
- Before analysis, verify and report from the existing research script/frozen source that this canonical input used the unchanged production scoring and simulation path: `analyzer.score_short_term`, `score_long_term`, grading and classification, and `backtest._simulate_trade`. Never reimplement or alter it.

### Precommitted, point-in-time-safe method

1. Parse `signal_date` and use precisely experiment 5's fixed splits: Early 2024-07-09–2025-01-31, Middle 2025-01-31–2025-10-17, Recent 2025-10-20–2026-06-03. State an inclusive/exclusive endpoint convention before inspecting outcomes; do not change dates, samples, or thresholds.
2. Report the raw baseline first: N, mean, median, standard deviation, win rate, expectancy and both gaps. N is mandatory for every table cell.
3. Primary null test: use fixed strata `time_split × category`. Within every stratum containing both labels, permute regime labels while preserving their observed counts; leave one-label strata unchanged. With seed `20260913` and exactly 100,000 draws, calculate two-sided empirical p-values for each gap: `(1 + count(abs(null_gap) >= abs(observed_gap))) / 100001`. Save all null draws to a dated CSV in `research/results/`.
4. Uncertainty: with exactly 20,000 draws and a documented deterministic seed offset, run a stratified calendar-month-cluster bootstrap within each observed regime, resampling whole signal-month clusters with replacement and retaining all their trades. Report percentile 95% CIs for both gaps. This explicitly accommodates within-month dependence; no claim of 372 independent trades is permitted. No future data or fitted/optimized boundary is used.

### Genuine falsification and fixed robustness checks

The hypothesis is **falsified / not statistically distinguishable from noise** unless all predeclared conditions hold:

1. expectancy-gap permutation p `< 0.05` and its bootstrap 95% CI is entirely above zero;
2. win-rate-gap permutation p `< 0.05` and its bootstrap 95% CI is entirely above zero; and
3. Early and Middle each have a positive expectancy gap. Report their N and estimates only; do not claim split significance if STRONG_BEARISH `n < 15`. Report Recent as untestable if it has no STRONG_BEARISH trades.

The decision above is primary and must not be changed by these sensitivity checks:

- repeat both procedures after excluding only the established symbols: BULLISH `LT, BAJFINANCE, JSWSTEEL`; STRONG_BEARISH `WIPRO, HINDALCO, TATASTEEL`;
- report descriptive results separately for Short-Term (Swing) and Long-Term, flagging every `n < 20` cell as underpowered; and
- show STRONG_BEARISH counts by symbol and calendar month, to expose concentration and sparse clusters.

Do not seek alternate seeds, test definitions, resampling units, dates, or subsets. A non-rejection is not proof of a causal regime effect. If either primary outcome fails, conclude that this sample provides insufficient evidence that the anomaly is distinguishable from noise; make no production recommendation.

### Required report and integrity evidence

Add one research-only script and immutable dated report/CSV outputs. The report must include the hypothesis/falsifier; source/provenance and point-in-time verification; baseline, permutation and bootstrap tables; all robustness checks; sample-dependence/small-N limitations; and a conclusion explicitly limited to statistical reliability, not causal explanation.

Before and after execution, record `git status --short` and verify that none of the 16 frozen production files nor `tests/test_engine.py` changed. Only additive files under `research/` are allowed. Do not edit `research/STATE.md` or this file. Syntax-check the new research script before running and quote the verification evidence in the report.
