# VYOM Research — NEXT EXPERIMENT

## Experiment: artifact-only reproducibility audit of scheduler attribution

### Rationale, question, and hypothesis

Experiment 8 reports seven Recent STRONG_BEARISH pre-scheduler-eligible rows
as `skipped_by_open_trade`, but its script explicitly re-fetched the universe
despite the approved specification's no-refetch guard. The output values match
the canonical trade CSV, but an external re-fetch cannot establish a
point-in-time reproducible schedule attribution by itself.

**Hypothesis:** the experiment-8 conclusion—that all seven eligible Recent
STRONG_BEARISH rows were censored by a prior selected trade—can be independently
verified using only immutable archived research artifacts, without network,
refetching, new market data, or rerunning production scoring/simulation.

This is an integrity/reproducibility audit only. It neither tests returns nor
recommends any change to the frozen non-overlap rule or strategy.

### Fixed artifacts and hard boundary

Use only these files, recording SHA-256 before and after reading each:

- `research/results/resistance_master_20260913_164146.csv`
- `research/results/resistance_trades_20260913_164146.csv`
- `research/results/scheduler_attribution_states_20260913_192107.csv`
- `research/results/scheduler_attribution_report_20260913_192107.txt`

No network access, `load_universe`, `data_sources`, data download, production
function invocation, new scoring, simulation, or data replacement is allowed.
The existing canonical artifacts are the complete fixed evidence. Do not edit
them or use a surrogate source.

### Precommitted methodology

1. Define the fixed 204-row target population solely from the master file:
   both categories, `regime == 'STRONG_BEARISH'`, and the two Recent dates
   2026-06-05 and 2026-06-08. Assert exactly 204 unique
   `(symbol, category, date)` keys; otherwise stop and report an artifact
   integrity failure.
2. Join the state CSV to that population by the same key. Require one and only
   one state row per master key; compare all shared static fields exactly
   (`score`, `grade`, `signal`, `rr_ratio`, `chase_flag`, `regime`, and gate
   bucket implied by the predeclared score/grade/signal taxonomy). Report N for
   every state and gate cell. Do not repair discrepancies.
3. Independently identify the pre-scheduler-eligible rows from the master
   definition already used in experiment 8: `score >= 40` and
   `signal != 'NO TRADE'`. Assert/report their N and keys; it must be seven if
   the archived inputs are internally consistent. For each, require state
   `skipped_by_open_trade` and a non-empty blocking symbol/category/signal-date
   reference.
4. Cross-check every blocking reference against the immutable canonical trade
   CSV on `(symbol, category, blocking_signal_date)`, including entry price,
   target, stop, exit reason, return, and days held. Report every match/missing
   reference with N. This establishes that the cited blocking trade exists in
   the canonical output, but must not claim to reconstruct its exit date or
   skipped interval unless those fields exist in the canonical files.
5. Make an explicit evidence-closure table for the critical claims:
   `candidate eligibility`, `blocking selected trade exists`, `blocking trade
   remained open through candidate date`, and `candidate was skipped by the
   production walk`. Mark each as **independently verified**, **internally
   consistent only**, or **not verifiable from archived artifacts**. No label
   may be upgraded based on the experiment-8 re-fetch report.

### Falsification criterion and conclusion rule

The hypothesis is **falsified** if any required key/field/state/trade-reference
check fails, or if either of the two causal schedule facts—blocking trade still
open on the candidate date, or the production walk skipping that index—cannot
be independently established from the four fixed artifacts. In either case,
the correct conclusion is: experiment 8 is internally consistent but its
scheduler-attribution conclusion is **unverified under the no-refetch research
boundary**. Do not reinterpret this as evidence against or for the return
anomaly.

If every check, including both schedule facts, is actually supportable from the
archived artifacts, state exactly which artifact fields prove each fact. Do not
infer missing exit-index/date information from calendar arithmetic.

### Required report and integrity verification

Create one additive research script and dated immutable audit report/CSV under
`research/results/`. Include artifact hashes; command/runtime; all assertions
and N; a complete mismatch/reference table; the evidence-closure table;
limitations; and the predeclared verdict.

Before and after execution, record `git status --short` and verify all 16
frozen production files and `tests/test_engine.py` are unchanged. Only additive
files under `research/` are allowed. Do not edit `research/STATE.md` or this
file. Syntax-check the audit script before running and quote the verification
evidence in the report.
