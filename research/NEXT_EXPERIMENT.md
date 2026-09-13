# Experiment 13 — Offline scheduler-attribution reconstruction from the frozen fixture

## Why this is the one next experiment

Experiment 12 is correctly classified **FALSIFIED** under its strict predeclared rule: the trade dataset reproduced exactly (2,083/2,083 rows; zero mismatches), but the master dataset had 11 `score`/`factor__Momentum` mismatches, so both required outputs did not match exactly. The proposed fetch-time/vendor-revision mechanism for those 11 rows is plausible but not independently proved and must not be upgraded to a finding.

The important new capability is narrower: the exact canonical trade population can now be regenerated offline from a hashed 61-series fixture. Experiments 9–11 could not independently verify experiment 8's scheduler attribution because the repository lacked frozen raw inputs. This experiment tests whether the new fixture closes that specific evidence gap. It does **not** test whether the STRONG_BEARISH return anomaly is real.

## Single hypothesis

Using only the frozen experiment-12 OHLCV fixture and unchanged production functions, a fresh offline instrumented reconstruction of the canonical `research.factor_data.run_ablation` walk will:

1. reproduce the canonical 2,083 experiment-5 trades exactly; and
2. independently identify the same seven pre-scheduler-eligible Recent/STRONG_BEARISH Long-Term rows as skipped by a prior selected trade whose reconstructed open interval covers each candidate date.

## Fixed artifacts

Use these existing artifacts only; do not refetch, replace, edit, or regenerate them:

- `research/fixtures/raw_ohlcv/raw_ohlcv_manifest.json` and its 61 referenced CSV files;
- `research/results/resistance_master_20260913_164146.csv`;
- `research/results/resistance_trades_20260913_164146.csv`;
- `research/results/offline_master_20260913_225716.csv`;
- `research/results/offline_trades_20260913_225716.csv`;
- `research/results/scheduler_attribution_states_20260913_192107.csv`, for a final secondary comparison only.

Record SHA-256 hashes before and after. The manifest hash recorded by experiment 12 was `235e4f3c0991715bdd7363e7516238d85ad7255d6696bb94124616628ff0214b`; verify it rather than assuming it.

## Fixed population and seven predeclared candidate keys

Recompute the population from the frozen fixture, using the same fixed Early/Middle/Recent split boundaries and production regime/score/signal definitions used in experiments 5, 7, and 8. The primary attribution population is all Recent rows with `regime == STRONG_BEARISH`, both categories and all 51 symbols.

The exact predeclared candidate keys from experiment 8 are:

| Symbol | Category | Candidate date |
|---|---|---|
| ADANIENT | Long-Term | 2026-06-05 |
| APOLLOHOSP | Long-Term | 2026-06-05 |
| APOLLOHOSP | Long-Term | 2026-06-08 |
| COALINDIA | Long-Term | 2026-06-05 |
| COALINDIA | Long-Term | 2026-06-08 |
| TITAN | Long-Term | 2026-06-05 |
| TITAN | Long-Term | 2026-06-08 |

Do not add, remove, or redefine candidates after observing results. A row is pre-scheduler-eligible only when its unchanged production result has `score >= 40` and `signal != "NO TRADE"`.

## Mandatory offline boundary

- Block `socket.socket.connect`, `socket.socket.connect_ex`, and `socket.create_connection` before importing any project module that could reach the network.
- Self-test the block with a real attempted connection and stop if it does not raise.
- Load all stocks, NIFTY, and sector histories only from the frozen fixture.
- Do not call `data_sources.fetch_daily_history`, yfinance, or any other network/data source.

## Required method

1. Record `git status --short`, hashes of all fixed artifacts, and byte hashes of all 16 frozen production files plus `tests/test_engine.py` before work.
2. Create one new research script. It must not import or call `research.scheduler_attribution_experiment`; implement a fresh instrumented wrapper while calling the unchanged production scoring, grading, classification, and trade-simulation functions directly.
3. Mirror the canonical per-symbol/category scheduler exactly, including the entry-index handling and `i = max(exit_idx + 1, i + 1)` update. Record every visited index, every selected trade, and every skipped interval.
4. Before interpreting attribution, compare the reconstructed trade dataset with `resistance_trades_20260913_164146.csv`: identical row count and keys, and zero value mismatches across all comparable columns after only documented missing-value normalization. Use `rtol=1e-6` and `atol=1e-6`; do not loosen tolerances after seeing results.
5. Independently recompute the Recent/STRONG_BEARISH population and pre-scheduler eligibility from the frozen fixture. Report every row and N at each gate. Explicitly check whether the candidate-key set equals the seven-row predeclared set.
6. For each eligible candidate, identify its state (`reached_and_selected`, `reached_and_rejected_upstream`, `skipped_by_open_trade`, or unresolved), the blocking selected trade if applicable, and its signal/entry/exit dates. Verify `blocking_entry_date <= candidate_date <= blocking_exit_date` and that the scheduler's skip-index interval actually covers the candidate index.
7. Only after completing steps 1–6, compare the newly produced attribution table with `scheduler_attribution_states_20260913_192107.csv`. Treat agreement as corroboration, not as the primary derivation.
8. Re-report the 11 experiment-12 master mismatches and establish whether any intersects the primary Recent/STRONG_BEARISH population or the seven candidate keys. Do not attempt to explain or repair them in this experiment.
9. Recheck all fixed-artifact and production-file hashes and record final `git status --short`.

## Predeclared decision rule

Classify **SUPPORTED** only if all conditions hold:

1. the offline network block self-test passes and all fixture/artifact hashes remain unchanged;
2. the fresh wrapper reproduces all 2,083 canonical trades exactly under the fixed tolerance;
3. the independently recomputed eligible-candidate set is exactly the seven predeclared keys, with no missing or additional rows;
4. all seven are `skipped_by_open_trade`, each has a canonical reconstructed blocking trade, and both its date interval and index interval cover the candidate; and
5. no experiment-12 master mismatch intersects the seven keys.

Classify **FALSIFIED** if any condition is contradicted. Classify **INCONCLUSIVE** only for a genuine execution/evidence failure that prevents a condition from being tested; do not reinterpret a failed condition as inconclusive.

## Required robustness and limitations

- Report N for every gate, category, state, and comparison; flag all cells below 20.
- Provide the same state taxonomy for Early and Middle STRONG_BEARISH rows as descriptive context only; it cannot override the primary decision.
- State clearly that scheduler attribution on seven rows is a simulation-path finding, not evidence of predictive edge, causality, or a reason to change the non-overlap rule.
- State that exact offline reproduction validates this frozen fixture/run only; it does not eliminate survivorship bias, vendor revisions before fixture capture, corporate-action risk, or generalize to future data.

## Required outputs

Save:

- one dated report under `research/results/`;
- one dated per-row attribution CSV under `research/results/` containing the full primary population and all blocking fields;
- optionally one compact trade-reconstruction comparison CSV only if mismatches exist.

The report must include the hypothesis, fixed inputs and hashes, point-in-time/offline verification, reconstruction results, seven-row table, gate/state counts with N, experiment-12 mismatch intersection, decision-rule table, limitations, exact commands/tests, files changed, and before/after Git status.

## Integrity gate

Do not modify production code, `tests/test_engine.py`, prior reports/datasets, fixture files, strategy logic, indicators, weights, thresholds, entry/exit rules, holding periods, or data sources. All new work must remain under `research/`. If any protected file hash changes, stop and mark the experiment invalid.

After reporting the verdict, propose exactly one evidence-based next experiment but do not run it.
