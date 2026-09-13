# VYOM Research — NEXT EXPERIMENT

## Experiment: STRONG_BEARISH regime-frequency and opportunity-funnel audit

### Single question and hypothesis

Experiment 6 could not establish that the 48-versus-324 performance gap is
distinguishable from noise, and both experiments 5 and 6 show zero
STRONG_BEARISH trades in the Recent split. Test the documented unresolved
possibility that this is a **regime-frequency / opportunity-availability**
artifact rather than a change in the strategy's eligibility or trade-selection
gates.

**Hypothesis:** the zero Recent STRONG_BEARISH trades are fully accounted for by
zero (or near-zero) point-in-time NIFTY dates classified `STRONG_BEARISH`; they
are not caused by the score, signal-classification, or non-overlap trade gate.
This is a sample-composition audit only. It does not explain or validate the
historical return gap and makes no causal or production claim.

### Fixed population, definitions, and provenance

- Use exactly the immutable canonical outputs from experiment 5:
  `research/results/resistance_master_20260913_164146.csv` and
  `research/results/resistance_trades_20260913_164146.csv`. Record each
  SHA-256, row count, date range, and all filtered N values. Do not refetch
  data or regenerate the population.
- Use only the fixed 51-symbol universe, both production categories, and the
  production `score >= 40` threshold already embodied in this canonical
  backtest. Do not introduce a new score/signal threshold or alter the
  non-overlap convention.
- Before using `regime`, `score`, `grade`, or `signal`, directly inspect and
  report their exact point-in-time definitions in `market_regime.py`,
  `analyzer.py`, and `research/factor_data.py`: verify the Bundle pattern,
  `.iloc[idx]` use, lookbacks, `classify_regime_at`,
  `score_short_term` / `score_long_term`, `_grade_from_score`,
  `_classify_signal`, and `backtest._simulate_trade`. These production
  functions must be reused unchanged; do not reimplement scoring or regime
  logic in research.

### Precommitted methodology

1. Reuse exactly these chronological splits and state the endpoint convention:
   Early 2024-07-09–2025-01-31, Middle 2025-01-31–2025-10-17, Recent
   2025-10-20–2026-06-03. Do not derive new splits from the data.
2. From the master dataset, deduplicate only on `date` to form the daily NIFTY
   regime denominator. For each split and every regime label present, report
   distinct regime dates, calendar/market dates observed, and the regime-date
   share. Then report the same counts for BULLISH and STRONG_BEARISH explicitly.
3. Build a fixed four-stage funnel separately by `time_split × regime ×
   category`:
   (a) distinct regime dates; (b) master symbol-category observations;
   (c) observations with `score >= 40`; and (d) non-overlapping simulated
   trades from the canonical trade dataset. Report counts and the conditional
   stage-to-stage rates, including zero denominators as `N/A`, never silently
   dropped.
4. Trace every Recent STRONG_BEARISH master row, if any, through stages (c) and
   (d), showing symbol, date, category, score, grade, signal, and whether it
   appears in the trade file. This is a fixed exhaustive trace, not a selected
   case study. If there are no such master rows, state that explicitly.
5. For descriptive uncertainty only, use a fixed 5-trading-day moving-block
   bootstrap of dates within each split (seed `20260913`, 20,000 draws) for the
   STRONG_BEARISH regime-date share and the score-qualified rate conditional on
   STRONG_BEARISH dates. Preserve all same-date symbol/category observations in
   every resampled block. Report percentile 95% CIs and label them dependent,
   descriptive estimates—not independent-trade inference.

### Falsification and robustness

The hypothesis is **falsified** if the Recent split contains one or more
point-in-time `STRONG_BEARISH` regime dates in the master data: the report must
then identify which downstream fixed gate(s)—score threshold, production signal
classification, or non-overlap simulation—account for every missing trade,
without changing a rule or proposing a remedy. If Recent has zero
STRONG_BEARISH regime dates, the hypothesis is supported only as an explanation
of the zero Recent *opportunities*, not of the return anomaly.

Required fixed robustness checks:

- Repeat the daily regime-date counts independently from the trade dataset's
  unique `signal_date` values, and reconcile any difference with the master
  dates. Do not use trade absence as the regime denominator.
- Repeat the funnel with the established top-symbol exclusions (`BULLISH:
  LT, BAJFINANCE, JSWSTEEL`; `STRONG_BEARISH: WIPRO, HINDALCO, TATASTEEL`) only
  at symbol-level stages; the regime-date denominator must remain unchanged.
- Show a month-by-month table of regime dates and final trades for all three
  splits, flagging every cell below 20 observations as descriptive/undersized.
- Verify that a regime label is identical across all master rows on the same
  date; report and investigate any exception as a data-integrity failure rather
  than resolving it by filtering.

Do not test return performance, add factors, optimize boundaries, seek alternate
block lengths/seeds/splits, alter the universe, or make a strategy proposal.

### Required deliverables and integrity evidence

Create one additive research script and immutable dated CSV/report outputs in
`research/results/`. The report must include: hypothesis and falsifier; source
hashes and reproducibility command; production-field / point-in-time
verification; all funnel tables with N; exhaustive Recent trace; bootstrap
settings/CIs and limitations; robustness/reconciliation results; and a final
conclusion limited to regime-frequency evidence.

Before and after execution, record `git status --short` and verify that all 16
frozen production files and `tests/test_engine.py` are unchanged. Only additive
files under `research/` are allowed. Do not edit `research/STATE.md` or this
file. Syntax-check the research script before running and quote the verification
evidence in the report.
