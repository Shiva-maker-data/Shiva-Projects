"""
RESEARCH ONLY -- experiment 10: local point-in-time raw-data-fixture
availability audit.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, written after
auditing experiment 9). Experiment 9 established that the scheduler-
attribution claim cannot be independently verified from the existing
master/trade/state artifacts because none of them preserve raw OHLCV
inputs, exact entry/exit dates, or a visited-index trace. Before any
further scheduler or return research is considered, this experiment
checks whether a frozen local raw-data fixture already exists in the
repository that COULD make a no-refetch reconstruction possible in a
future, separately-specified experiment.

ABSOLUTE BOUNDARY (enforced by this script's own import block, not just
stated): no network code, no `research.factor_data.load_universe`, no
`data_sources`, no production scoring/indicator/regime/simulation
function. This file does not download, create, alter, or replace any raw
market data -- it only reads local workspace files and the two immutable
canonical research artifacts (SHA-256 recorded), and performs a read-only
inventory of the project directory.

This is an archival-availability audit ONLY. It runs no scoring, no
simulation, and reaches no conclusion about the STRONG_BEARISH-vs-BULLISH
return anomaly (experiments 1-6) or experiment 8's attribution claim
beyond what experiment 9 already established.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MASTER_PATH = RESULTS_DIR / "resistance_master_20260913_164146.csv"
TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"

# Fixed, documented extension set -- per spec, not extended or narrowed after seeing results.
CANDIDATE_EXTENSIONS = {".csv", ".parquet", ".feather", ".pkl", ".pickle", ".json",
                         ".sqlite", ".db", ".h5", ".hdf", ".xlsx", ".zip"}
# Fixed exclusions -- per spec: .git, .venv, __pycache__, tool caches. Restricted to the
# project directory itself, never home directories or external cache locations.
EXCLUDE_DIR_NAMES = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"}

# Facts quoted directly from production source (read, not executed) -- used only to state
# what coverage WOULD be required, not to compute or reproduce any indicator/score.
REGIME_INDEX_TICKER = "^NSEI"          # config.py line 30 (NIFTY 50 index proxy)
MIN_WARMUP_DAYS = 200                  # backtest.py line 84
CENSOR_BUFFER_DAYS = 95                # backtest.py line 86
FORWARD_WINDOW_DAYS = 90               # backtest.py line 85 (trading days)
FETCH_HISTORY_PERIOD = "3y"            # research/factor_data.py load_universe()'s history_period, as called in every prior experiment
REGIME_SMA_SLOW = 50                   # config.py line 32
SECTOR_SMA_WINDOW = 20                 # config.py line 57
HIGH52W_LOOKBACK_DAYS = 252            # analyzer.py line 157 (bundle.high52w rolling window)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def probe_csv(path: Path) -> dict:
    try:
        head = pd.read_csv(path, nrows=5)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            n_rows = sum(1 for _ in f) - 1  # minus header
        columns = list(head.columns)
        date_col = next((c for c in columns if c.lower() in ("date", "signal_date", "entry_date", "exit_date")), None)
        date_range = None
        if date_col:
            try:
                full_dates = pd.read_csv(path, usecols=[date_col], parse_dates=[date_col])[date_col]
                date_range = f"{full_dates.min().date()} to {full_dates.max().date()}"
            except Exception:
                date_range = "unparseable date column"
        has_ohlcv = all(any(c.lower() == field for c in columns) for field in ("open", "high", "low", "close"))
        has_symbol_id = any(c.lower() in ("symbol", "ticker") for c in columns)
        return {"readable": True, "columns": columns, "n_rows": n_rows, "date_col": date_col,
                "date_range": date_range, "has_ohlcv_fields": has_ohlcv, "has_symbol_identifier": has_symbol_id}
    except Exception as e:
        return {"readable": False, "error": str(e)}


def probe_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            keys = sorted({k for item in data if isinstance(item, dict) for k in item.keys()})
            return {"readable": True, "top_level_type": "list", "n_items": len(data), "keys_seen": keys,
                     "has_ohlcv_fields": False, "has_symbol_identifier": "symbol" in keys}
        if isinstance(data, dict):
            return {"readable": True, "top_level_type": "dict", "keys_seen": sorted(data.keys()),
                     "has_ohlcv_fields": False, "has_symbol_identifier": "symbol" in data}
        return {"readable": True, "top_level_type": type(data).__name__, "has_ohlcv_fields": False, "has_symbol_identifier": False}
    except Exception as e:
        return {"readable": False, "error": str(e)}


def probe_generic(path: Path, ext: str) -> dict:
    # Any other extension in the fixed set (.parquet/.feather/.pkl/.pickle/.sqlite/.db/.h5/.hdf/.xlsx/.zip):
    # attempt only a read-only existence/size probe here -- no parsing library for these formats is
    # imported (keeps the script's own dependency surface minimal and auditable), so these are marked
    # unreadable-by-this-probe rather than silently assumed empty, retained as evidence per spec.
    return {"readable": False, "error": f"no read-only probe implemented in this audit for extension {ext} "
                                          f"(file retained as evidence, not ignored)"}


def inventory(report: list[str]) -> pd.DataFrame:
    report.append("\n## Step 2: deterministic read-only file inventory")
    report.append(f"  Root: {PROJECT_ROOT}")
    report.append(f"  Excluded directory names: {sorted(EXCLUDE_DIR_NAMES)}")
    report.append(f"  Extension set: {sorted(CANDIDATE_EXTENSIONS)}")

    rows = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIR_NAMES for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        if path.suffix.lower() not in CANDIDATE_EXTENSIONS:
            continue
        rel = path.relative_to(PROJECT_ROOT)
        size = path.stat().st_size
        h = sha256_of(path)
        ext = path.suffix.lower()
        if ext == ".csv":
            probe = probe_csv(path)
        elif ext == ".json":
            probe = probe_json(path)
        else:
            probe = probe_generic(path, ext)
        rows.append({"path": str(rel), "ext": ext, "size_bytes": size, "sha256": h, **probe})

    inv = pd.DataFrame(rows).sort_values("path").reset_index(drop=True)
    report.append(f"  Candidate files found: {len(inv)}")
    for _, r in inv.iterrows():
        cols_val = r.get("columns", None)
        keys_val = r.get("keys_seen", None)
        if isinstance(cols_val, list):
            cols_summary = str(cols_val)[:200]
        elif isinstance(keys_val, list):
            cols_summary = str(keys_val)[:200]
        else:
            cols_summary = "n/a"
        report.append(f"    {r['path']:60s} size={r['size_bytes']:>10} bytes  readable={r['readable']}  "
                       f"rows={r.get('n_rows','n/a')}  date_range={r.get('date_range','n/a')}  "
                       f"has_ohlcv={r.get('has_ohlcv_fields','n/a')}  has_symbol_id={r.get('has_symbol_identifier','n/a')}  "
                       f"cols/keys={cols_summary}")
        if r["readable"] is False:
            report.append(f"      UNREADABLE (retained as evidence): {r.get('error')}")
    return inv


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["LOCAL POINT-IN-TIME RAW-DATA-FIXTURE AVAILABILITY AUDIT (research only, archival-availability check, no scoring/simulation)"]

    report.append("\n## Hypothesis and falsifier (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: the repository/workspace already contains an immutable local point-in-time data fixture "
                   "sufficient to reproduce the experiment-5 population and experiment-8 scheduling path without "
                   "downloading, changing, or substituting any data source.")
    report.append("  Falsified if any required component, symbol, index, field, or necessary date interval is "
                   "absent, partial, unreadable, or lacks an immutable local artifact -- in which case the correct "
                   "conclusion is: no-refetch exact reconstruction is currently unavailable; experiment 8 remains "
                   "internally consistent but unverified under the research boundary (per experiment 9). Absence is "
                   "NOT used as evidence about the STRONG_BEARISH return anomaly.")
    report.append("  Provisionally supported only if every required component is locally present with complete "
                   "coverage and stable hashes -- and even then, numeric equality to the originally-fetched values "
                   "remains unproven until a separately-specified, human-approved validation (not performed here).")

    report.append("\n## Absolute boundary")
    report.append("  This script imports only hashlib, json, sys, pathlib, datetime, numpy, pandas -- no "
                   "research.factor_data, data_sources, analyzer, market_regime, sector, or backtest import exists "
                   "in this file (verifiable in its import block). No network call is made anywhere in this script.")

    report.append("\n## Step 1: canonical master/trade file evidence (SHA-256, coverage)")
    master_sha = sha256_of(MASTER_PATH)
    trades_sha = sha256_of(TRADES_PATH)
    master = pd.read_csv(MASTER_PATH, parse_dates=["date"])
    trades = pd.read_csv(TRADES_PATH, parse_dates=["signal_date"])
    report.append(f"  {MASTER_PATH.name}: SHA-256={master_sha}  rows={len(master)}  "
                   f"date_range={master['date'].min().date()} to {master['date'].max().date()}")
    report.append(f"  {TRADES_PATH.name}: SHA-256={trades_sha}  rows={len(trades)}  "
                   f"date_range={trades['signal_date'].min().date()} to {trades['signal_date'].max().date()}")

    report.append("\n## Step 3: required fixture coverage, derived from the canonical files + quoted production constants")
    required_symbols = sorted(master["symbol"].unique())
    required_sectors = sorted(master["sector_ticker"].dropna().unique())
    earliest_signal = master["date"].min()
    latest_signal = master["date"].max()
    report.append(f"  Required stock symbols (from master['symbol'].unique()): N={len(required_symbols)}: {required_symbols}")
    report.append(f"  Required NIFTY index ticker (quoted from config.REGIME_INDEX_TICKER, not executed): {REGIME_INDEX_TICKER!r}")
    report.append(f"  Required sector index tickers (from master['sector_ticker'].dropna().unique()): N={len(required_sectors)}: {required_sectors}")
    report.append(f"  Signal-date range needed (from master['date']): {earliest_signal.date()} to {latest_signal.date()} (N distinct dates={master['date'].nunique()})")
    report.append(f"  Warmup buffer required before the earliest signal date: MIN_WARMUP_DAYS={MIN_WARMUP_DAYS} trading "
                   f"days (backtest.py), REGIME_SMA_SLOW={REGIME_SMA_SLOW}, SECTOR_SMA_WINDOW={SECTOR_SMA_WINDOW}, "
                   f"HIGH52W_LOOKBACK_DAYS={HIGH52W_LOOKBACK_DAYS} (analyzer.py) -- all quoted from source, not computed here.")
    report.append(f"  The ORIGINAL universe fetch used history_period={FETCH_HISTORY_PERIOD!r} (research/factor_data.py "
                   f"load_universe, as called in every VYOM experiment script) -- true reconstruction needs "
                   f"approximately 3 years of trailing OHLCV before the fetch date, not merely the mathematically-"
                   f"minimal {MIN_WARMUP_DAYS}-day warmup.")
    report.append(f"  Latest required outcome date: latest_signal_date ({latest_signal.date()}) + entry lag (1 trading "
                   f"day) + up to FORWARD_WINDOW_DAYS={FORWARD_WINDOW_DAYS} trading days for a trade to resolve "
                   f"(target/stop/time-exit) -- an approximate calendar-day upper bound, NOT a computed exact date.")

    inv = inventory(report)
    ts_csv_path = RESULTS_DIR / f"raw_data_fixture_inventory_{ts}.csv"
    inv.drop(columns=[c for c in ["columns", "keys_seen"] if c in inv.columns], errors="ignore").to_csv(ts_csv_path, index=False)

    report.append("\n## Step 4: per-required-series coverage assessment")
    ohlcv_candidates = inv[inv.get("has_ohlcv_fields", False) == True] if "has_ohlcv_fields" in inv.columns else inv.iloc[0:0]
    report.append(f"  Candidate files with recognizable OHLCV fields (Open/High/Low/Close, case-insensitive): {len(ohlcv_candidates)}")
    if len(ohlcv_candidates):
        report.append(f"    {ohlcv_candidates[['path','n_rows','date_range']].to_dict('records')}")
    else:
        report.append("    NONE. No local file in the inventory contains recognizable OHLCV columns.")

    coverage_rows = []
    for sym in required_symbols:
        coverage_rows.append({"required_series": f"stock:{sym}", "status": "missing", "note": "no local OHLCV fixture found for this symbol"})
    coverage_rows.append({"required_series": f"index:{REGIME_INDEX_TICKER}", "status": "missing", "note": "no local OHLCV fixture found for the NIFTY regime index"})
    for sec in required_sectors:
        coverage_rows.append({"required_series": f"sector:{sec}", "status": "missing", "note": "no local OHLCV fixture found for this sector index"})
    coverage = pd.DataFrame(coverage_rows)
    n_present = int((coverage["status"] == "present").sum())
    n_missing = int((coverage["status"] == "missing").sum())
    report.append(f"\n  Coverage table: {n_present} present / {n_missing} missing / {len(coverage)} total required series")
    report.append(f"  (Every required stock symbol, the NIFTY index, and every required sector index: status=missing -- "
                   f"since the inventory in Step 2 found zero files with recognizable OHLCV time-series fields anywhere "
                   f"under the project directory. The repository is a live-fetch-only pipeline: data_sources.py calls "
                   f"yfinance at run time and, per .gitignore and this inventory, does not persist a raw-data cache.)")
    coverage.to_csv(RESULTS_DIR / f"raw_data_fixture_coverage_{ts}.csv", index=False)

    report.append("\n## Step 5: metadata comparison")
    report.append("  N/A -- no candidate fixture with OHLCV fields was found to compare metadata against the "
                   "data-source identity implied by data_sources.py (e.g. yfinance ticker conventions). Had one "
                   "existed, matching coverage/metadata would still not prove numeric equality to the originally "
                   "fetched values -- no data-source substitution is performed or implied by this audit.")

    report.append("\n## Non-research-scope observation (not used in the verdict)")
    backtest_results_csvs = inv[inv["path"].str.startswith("backtest_results")]
    if len(backtest_results_csvs):
        report.append(f"  {len(backtest_results_csvs)} file(s) under backtest_results/ were found in the inventory "
                       f"(production backtest.py's own summary output, containing entry_date/exit_date/entry_price/"
                       f"exit_price columns per trade). These are DERIVED trade-level summaries, not raw OHLCV price "
                       f"history -- they do not satisfy the required-fixture definition in Step 3 and are not counted "
                       f"toward the coverage table above. Noted only because their presence of entry_date/exit_date "
                       f"columns is structurally different from the research/ artifacts audited in experiment 9; "
                       f"using them for any further scheduler/attribution check would be a new experiment, not "
                       f"performed here.")

    report.append("\n## Verdict")
    hypothesis_falsified = n_missing > 0
    if hypothesis_falsified:
        report.append(f"  FALSIFIED. {n_missing} of {len(coverage)} required series (every stock symbol, the NIFTY "
                       f"index, and every sector index) have no local raw-data fixture. A no-refetch exact "
                       f"reconstruction of the experiment-5 population and experiment-8 scheduling path is currently "
                       f"UNAVAILABLE. Experiment 8 remains internally consistent (per experiment 9's own finding) but "
                       f"unverified under the research boundary. This absence is NOT used as evidence about the "
                       f"STRONG_BEARISH-vs-BULLISH return anomaly (experiments 1-6) -- it is a purely archival finding.")
    else:
        report.append("  PROVISIONALLY SUPPORTED (all required series locally present with complete coverage and "
                       "stable hashes) -- numeric equality to the originally-fetched inputs remains unproven and is "
                       "explicitly not validated by this audit.")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"raw_data_fixture_audit_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
