# VYOM Research — NEXT EXPERIMENT

## Experiment: independent backtest-summary timing corroboration audit

### Single question and hypothesis

Experiment 10 found no raw-data fixture, but it identified seven pre-existing
`backtest_results/trades_*.csv` summaries that contain entry and exit dates.
Experiment 9 could independently verify that the seven cited blocking trades
exist, but not that they remained open through the seven Recent
STRONG_BEARISH candidate dates.

**Hypothesis:** at least one pre-experiment-8 backtest summary generated from
the same frozen strategy setup independently contains all seven cited blocking
trades and confirms each recorded exit date is on or after its associated
candidate date. This would corroborate the *open-trade timing* fact only; it
cannot by itself prove the scheduler skipped a candidate index.

### Strict scope and fixed inputs

This is a read-only artifact cross-check. Do not call network code,
`load_universe`, data sources, scoring, indicators, regime classification, or
trade simulation. Do not modify production, re-run a backtest, change settings,
or use a new data source.

Use only:

- the seven candidate/blocking-trade records in
  `research/results/scheduler_reproducibility_xcheck_20260913_193245.csv`;
- `research/results/resistance_trades_20260913_164146.csv` for the canonical
  blocking-trade identity; and
- every existing `backtest_results/trades_*.csv` with all required columns
  `symbol`, `category`, `threshold`, `signal_date`, `entry_date`, `exit_date`,
  `entry_price`, `exit_price`, `exit_reason`, `days_held`, and
  `strategy_return_pct`.

Discover the last group deterministically by filename and schema; do not select
one output after seeing its values. Record SHA-256, size, modification time,
schema, row count, and date range for every discovered summary. Explicitly
exclude files created after experiment 8's report timestamp
`2026-09-13 19:21:07`; report them but do not use them as independent evidence.

### Precommitted methodology

1. Verify from `backtest.py` by read-only code inspection what each summary's
   `signal_date`, `entry_date`, `exit_date`, threshold, non-overlap behavior,
   and return fields mean. Verify the file's threshold is exactly `40` and that
   category/symbol labels match the canonical trade convention. If any semantic
   equivalence is unknown, label that file incomparable rather than mapping it.
2. For each of the seven candidate records, match to every eligible summary on
   `(symbol, category, blocking_signal_date, threshold=40)`. Require exactly
   one match per candidate within a given comparable file; report zero or
   multiple matches as failures, with N. Compare matching entry price, exit
   reason, strategy return, and days held to the canonical trade CSV using a
   predeclared tolerance of `1e-6` for numeric CSV round-trip fields.
3. Independently compare the summary's stored `exit_date` to its associated
   candidate date. Report `exit_date > candidate_date`, `==`, `<`, missing, and
   unreadable separately, with N and a complete seven-row table. Do not infer
   dates from `days_held` or use calendar arithmetic.
4. Treat each qualifying backtest summary as a replication artifact, not an
   independent draw. Report agreement across all comparable pre-experiment-8
   files and flag repeated byte-identical files by SHA-256 so duplicate exports
   are not counted as independent corroboration.
5. Keep the evidence-closure distinction explicit: this experiment can at most
   upgrade `blocking_trade_remained_open_through_candidate_date`; it cannot
   establish `candidate_was_skipped_by_the_production_walk`, because a summary
   file does not record visited/skipped indices.

### Falsification criterion and required conclusion

The hypothesis is **falsified** unless at least one semantically comparable,
pre-experiment-8, non-duplicate summary matches all seven canonical blocking
trades exactly and has `exit_date >= candidate_date` for every one. Any missing,
multiple, conflicting, or semantically incomparable record is evidence against
timing corroboration and must be reported rather than filtered.

If supported, conclude only that open-trade timing is independently corroborated
by the specified archived summary. Retain the experiment-9 finding that the
walk-skipping fact remains unverified. If falsified, retain both facts as
unverified under the no-refetch boundary. Neither outcome is evidence for or
against the STRONG_BEARISH-versus-BULLISH return anomaly and neither supports a
production change.

### Required report and integrity verification

Create one additive research-only script and dated immutable report/CSV under
`research/results/`, including all file hashes, eligibility decisions, N,
seven-row match table, duplicate analysis, field/timing comparisons,
point-in-time/provenance caveats, and verdict.

Before and after execution, record `git status --short` and verify all 16
frozen production files and `tests/test_engine.py` are unchanged. Only additive
files under `research/` are allowed. Do not edit `research/STATE.md` or this
file. Syntax-check the audit script before execution and quote the verification
evidence in the report.
