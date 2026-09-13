# VYOM Research — NEXT EXPERIMENT

## Experiment: exact signal-gate versus non-overlap-censoring attribution

### Why this experiment

Experiment 7 correctly falsified the strict "zero regime dates" hypothesis:
Recent has two point-in-time STRONG_BEARISH dates. Its funnel, however,
combined score qualification, `_classify_signal`, and the non-overlap walk in
one `score >= 40 -> trade` transition. The report therefore does **not**
establish its claim that non-overlap, rather than an upstream signal rule,
accounts for every missing Recent trade. Audit that distinction exactly.

### Single hypothesis and falsifier

**Hypothesis:** every Recent STRONG_BEARISH row which would pass the production
pre-scheduler eligibility gate (`score >= 40` and `signal != 'NO TRADE'`) was
actually bypassed because the canonical non-overlap walk was already inside a
prior selected trade for the same symbol/category. Existing production signal
classification is therefore not sufficient to account for the zero Recent
STRONG_BEARISH trades.

The hypothesis is **falsified** if either:

1. no Recent STRONG_BEARISH row passes that exact pre-scheduler eligibility
   gate (then upstream score/classification fully accounts for zero trades);
2. any such row is reached by the canonical walk and is neither selected nor
   rejected by the documented production `score < 40` / `signal == NO TRADE`
   gate; or
3. the exact canonical scheduling path cannot be reproduced against the
   archived master/trade outputs. In case 3, report the attribution as
   **unverified**, not as non-overlap evidence, and do not substitute another
   data source or run.

This is a research audit of a frozen simulation path. It is not a proposal to
change the non-overlap rule, signal policy, threshold, entry/exit logic, or
anything in production.

### Fixed inputs and reproducibility guard

- Canonical comparison files are exactly
  `research/results/resistance_master_20260913_164146.csv` (SHA-256
  `7d6d623480e64c37ac606f45909074134b96257630f43230a51b476f5981e6c7`) and
  `research/results/resistance_trades_20260913_164146.csv` (SHA-256
  `05b11415a0979d224048e6e993d24c9a064f25a7b622e13a60ab5bbfe9026369`).
  Record hashes before and after; never edit them.
- Use the same 51-symbol universe, both categories, history/censor buffer,
  fixed `min_score=40`, date ordering, and non-overlap behavior as experiment
  5. Do not refetch, replace, or modify the data source. If the original
  point-in-time OHLC fixture is unavailable locally, the experiment may inspect
  source/code and the canonical CSVs only; it must return the reproducibility
  failure in the report rather than downloading different data.
- Directly verify and use unchanged production functions:
  `compute_bundle`, `market_regime.compute_regime_bundle`,
  `classify_regime_at`, `score_short_term` / `score_long_term`,
  `_grade_from_score`, `_classify_signal`, and `backtest._simulate_trade`.
  Reuse the existing `run_ablation` traversal semantics exactly; do not
  reimplement scoring, indicators, classification, or simulation.

### Precommitted methodology

1. First create an exact gate taxonomy for **all 102** master rows on the two
   Recent STRONG_BEARISH dates, without selecting examples: `score < 40`,
   `40 <= score < 60`, `grade present + signal NO TRADE`, and
   `pre-scheduler eligible` (`score >= 40` and `signal != NO TRADE`). Report
   N, symbol, date, category, score, grade, `rr_ratio`, `chase_flag`, signal,
   and the exact first production condition responsible for any `NO TRADE`.
2. Build an additive research-only *instrumented wrapper* around the canonical
   `run_ablation` walk. The wrapper must call the production functions named
   above directly and preserve its iteration/update expression
   `i = max(exit_idx + 1, i + 1)` verbatim. It may add audit records only; it
   must not alter decisions or output selection.
3. For every symbol/category, record each selected trade's signal date, entry
   date, exit index/date, and the inclusive skipped-index interval created by
   that exact update. At every Recent STRONG_BEARISH index, record one mutually
   exclusive state: `reached_and_rejected_upstream`, `reached_and_selected`, or
   `skipped_by_open_trade`, with the blocking selected trade's identifiers and
   dates for the last state.
4. Exact reconstruction check before interpreting attribution: compare the
   wrapper's selected-trade keys and all canonical output columns available in
   the CSV (including symbol, category, regime, signal date, return, exit
   reason, entry, target, stop, and days held) against the fixed canonical
   trade file. Require identical row count and zero mismatches. Compare the
   master-level values on all two Recent dates as well. Do not loosen numerical
   tolerances after seeing a mismatch; declare the result unverified if the
   fixed comparison fails.
5. As a fixed context-only robustness table, repeat the same state taxonomy for
   every STRONG_BEARISH date in Early and Middle. Show N by split/category and
   flag all cells below 20 as descriptive. Do not evaluate returns or test new
   factors.

### Required conclusion discipline

Report the three hypothesis conditions explicitly, with their N. Only a
zero-mismatch reconstruction plus at least one documented
`skipped_by_open_trade` Recent pre-scheduler-eligible row supports the
hypothesis. Any other result is evidence against it or unverified. Distinguish
an observed scheduler effect from a causal explanation of the return anomaly;
neither outcome supports a production recommendation.

### Deliverables and integrity verification

Create one additive research script and dated immutable report/CSV audit output
under `research/results/`. Include source hashes, exact command, runtime,
production-code line/function verification, taxonomy and event tables with N,
full reconciliation results, limitations, and the falsification verdict.

Before and after execution, record `git status --short` and verify all 16
frozen production files plus `tests/test_engine.py` remain unchanged. Only
additive `research/` files are allowed. Do not edit `research/STATE.md` or this
file. Syntax-check the research script before execution and quote the status
evidence in the report.
