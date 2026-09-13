# VYOM Research — NEXT EXPERIMENT

## Experiment: local point-in-time raw-data-fixture availability audit

### Single question and hypothesis

Experiment 9 established that the scheduler-attribution claim cannot be
independently verified from the existing master/trade/state artifacts because
they do not preserve the raw OHLC inputs, exact exit dates, or visited-index
trace. Before any further scheduler or return research is considered, test
whether a frozen local source-data fixture exists that could make a no-refetch
reconstruction possible.

**Hypothesis:** the repository/workspace already contains an immutable local
point-in-time data fixture sufficient to reproduce the experiment-5 population
and experiment-8 scheduling path without downloading, changing, or substituting
any data source.

This is an archival-availability audit, not a backtest, factor test, or strategy
proposal. It must not run scoring, simulate trades, or make any causal claim.

### Absolute boundary

Do not call network code, `load_universe`, `data_sources`, or any production
scoring/indicator/regime/simulation function. Do not download, create, alter,
or replace raw market data. Read-only inspection of local workspace files and
the immutable research artifacts is the entire experiment.

### Fixed evidence and required inventory

1. Record SHA-256 and row/date coverage for the canonical master/trade files:
   `resistance_master_20260913_164146.csv` and
   `resistance_trades_20260913_164146.csv`.
2. Perform a deterministic, read-only file inventory under the VYOM repository
   excluding `.git`, `.venv`, `__pycache__`, and tool caches. Use a fixed,
   documented extension set only: `.csv`, `.parquet`, `.feather`, `.pkl`,
   `.pickle`, `.json`, `.sqlite`, `.db`, `.h5`, `.hdf`, `.xlsx`, and `.zip`.
   List relative path, size, SHA-256, and a non-mutating schema/date-range
   probe for every candidate. Do not inspect home directories or external
   cache locations.
3. Define the necessary fixture coverage before examining candidates:
   daily OHLCV rows for each of the canonical 51 symbols, sufficient NIFTY
   index history for `RegimeBundle`, required sector-index history for
   `SectorTrendBundle`, and the signal-to-exit historical span needed by the
   canonical master/trade dates. The report must derive the required symbol set,
   signal-date range, and latest required outcome date from the canonical files,
   showing N throughout.
4. For every candidate that plausibly contains market data, assess only whether
   it has the required identifiers, Date/OHLCV fields, row counts, and date
   coverage. Do not compute indicators or scores. Create a per-required-series
   coverage table with `present`, `missing`, `partial`, or `unreadable` and N
   dates/rows; retain unreadable files as evidence rather than ignoring them.
5. Compare any discovered fixture's listed source/metadata fields, if present,
   to the data-source identity implied by the existing research code. State
   explicitly that matching coverage does not prove values are identical to the
   originally fetched data; no data-source substitution is allowed.

### Falsification and conclusion rule

The hypothesis is **falsified** if any required component, symbol, index,
field, or necessary date interval is absent, partial, unreadable, or lacks an
immutable local artifact. In that case conclude only that a no-refetch exact
reconstruction is currently unavailable; experiment 8 remains internally
consistent but unverified under the research boundary. Do not use the absence
as evidence about the STRONG_BEARISH return anomaly.

The hypothesis may be called **provisionally supported** only if every required
component is locally present with complete coverage and stable hashes. Even
then, state that numeric equality to the original fetched inputs remains
unproven until a future human-approved, separately specified validation can use
the archived fixture—do not perform that validation here.

### Required report and integrity verification

Add one research-only audit script and immutable dated report/coverage CSV in
`research/results/`. Include the exact inventory command, exclusions,
extensions, artifact hashes, schema/coverage table with N, all missing or
unreadable inputs, point-in-time/provenance limitations, hypothesis verdict,
and no-strategy-change statement.

Before and after execution, record `git status --short` and verify all 16
frozen production files and `tests/test_engine.py` are unchanged. Only additive
files under `research/` are allowed. Do not edit `research/STATE.md` or this
file. Syntax-check the audit script before execution and quote the verification
evidence in the report.
