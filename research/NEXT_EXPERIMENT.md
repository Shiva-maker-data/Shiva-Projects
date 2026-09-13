# Experiment 12 — Frozen raw-data fixture and baseline reproducibility audit

## Status

Approved research-only specification. Do not run until this file is reviewed.

## Hypothesis

An immutable local fixture, captured through the existing data-fetch path, will allow the canonical experiment-5 population and trade outcomes to be regenerated without network access or production-code changes.

## Falsification criterion

Reject the hypothesis if any required series, date range, required OHLCV field, or required provenance/hash record is missing, or if an offline rerun cannot reproduce the archived experiment-5 master/trade artifacts within predeclared numeric tolerances.

## Fixed scope

- Use exactly the existing 51-stock universe, NIFTY regime index, and nine sector indices documented in `research/STATE.md`.
- Use the same historical window, warm-up, lookback, forward-outcome horizon, categories, threshold, and non-overlap settings as experiment 5.
- Use the existing repository data-fetch mechanism only. Do not add a data source, alter fetch parameters, or change production code.
- Capture raw OHLCV plus ticker, interval, retrieval timestamp, requested range, timezone, library/version metadata, and SHA-256 for every file.

## Required method

1. Record `git status --short` and hashes of the canonical experiment-5 inputs before capture.
2. Capture the complete fixed fixture once; do not refetch or substitute missing series.
3. Write an offline-only audit script under `research/` that reads only the fixture and existing research code needed for comparison; network access must be impossible or explicitly asserted absent.
4. Recompute the experiment-5 master population and trade summary offline using the frozen production functions, without editing them.
5. Compare row keys and all numeric outputs against the archived experiment-5 artifacts using tolerances declared before the comparison. Explain any mismatch; do not tune until it matches.
6. Record fixture hashes and before/after hashes of all canonical inputs.

## Required report

Report coverage, provenance, hashes, offline boundary, exact reconstruction results, mismatch diagnostics, and limitations including vendor data revisions, corporate actions, timezone, and survivorship. State sample counts and whether the fixture is sufficient for future scheduler audits. This is a reproducibility audit, not evidence that the STRONG_BEARISH anomaly is real and not permission to change strategy logic.

## Integrity gate

Production files, `tests/test_engine.py`, entry/exit rules, indicators, thresholds, weights, and data-source code must remain byte-for-byte unchanged. If any production file changes, stop and mark the experiment invalid. End with the exact files changed and commands/tests executed.

## One next experiment

Propose exactly one follow-up based on the result; do not execute it.

