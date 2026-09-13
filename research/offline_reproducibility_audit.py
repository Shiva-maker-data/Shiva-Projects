"""
RESEARCH ONLY -- experiment 12, offline audit step: recompute experiment 5's
master/trade population from the FROZEN local raw-OHLCV fixture only (built
by research/capture_raw_data_fixture.py), with network access actively
blocked at the socket layer (not merely unused), and compare the result to
the archived experiment-5 artifacts within a tolerance declared below,
BEFORE any comparison is run.

This script calls the UNCHANGED production functions
(analyzer.compute_bundle/score_short_term/score_long_term,
market_regime.compute_regime_bundle/classify_regime_at,
sector.compute_sector_trend_bundle/build_point_in_time_confirmation,
backtest._simulate_trade) and the UNCHANGED research functions
(research.factor_data.build_master_dataset/run_ablation) -- nothing is
reimplemented. The only new code here is an OFFLINE loader that builds the
same UniverseData shape research.factor_data.load_universe() builds, but
reads from local fixture files instead of fetching.

This is a reproducibility audit, not evidence that the STRONG_BEARISH
anomaly is real, and not permission to change strategy logic.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Network block MUST happen before any other import that could reach the
# network (yfinance/requests/urllib3 all eventually open a socket). This
# makes network access impossible for the rest of this process, not merely
# unused -- verified below by an explicit self-test.
# ---------------------------------------------------------------------------
import socket


class NetworkBlockedError(RuntimeError):
    pass


def _blocked(*_a, **_kw):
    raise NetworkBlockedError("Network access is blocked in this offline-only audit script (experiment 12).")


socket.socket.connect = _blocked
socket.socket.connect_ex = _blocked
socket.create_connection = _blocked

# ---------------------------------------------------------------------------

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import config as cfg
import sector as sector_mod
import symbols as sym
from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM, compute_bundle
from backtest import MIN_WARMUP_DAYS
from market_regime import compute_regime_bundle
from research.factor_data import UniverseData, build_master_dataset, run_ablation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "research" / "fixtures" / "raw_ohlcv"
MANIFEST_PATH = FIXTURE_DIR.parent / "raw_ohlcv_manifest.json"
RESULTS_DIR = PROJECT_ROOT / "research" / "results"
MASTER_PATH = RESULTS_DIR / "resistance_master_20260913_164146.csv"
TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"

NUMERIC_TOL = 1e-6  # predeclared BEFORE any comparison is run


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def self_test_network_blocked() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return False  # if this line is reached, blocking failed
    except NetworkBlockedError:
        return True
    except Exception:
        return False  # some other error -- not proof the block worked as intended


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("&", "AND").replace(".", "_")


def load_fixture_df(yf_ticker: str) -> pd.DataFrame | None:
    fname = f"{safe_name(yf_ticker)}.csv"
    fpath = FIXTURE_DIR / fname
    if not fpath.exists():
        return None
    df = pd.read_csv(fpath, index_col=0, parse_dates=True)
    df.index.name = None
    return df


def load_offline_universe(universe: list[str], report: list[str]) -> UniverseData:
    """Mirrors research.factor_data.load_universe()'s exact logic and
    filters (including the len(df) >= MIN_WARMUP_DAYS + 30 minimum), but
    reads from the frozen local fixture instead of fetching."""
    nifty_df = load_fixture_df(cfg.REGIME_INDEX_TICKER)
    regime_bundle = compute_regime_bundle(nifty_df) if nifty_df is not None else None
    if nifty_df is None:
        report.append(f"  WARNING: NIFTY fixture ({cfg.REGIME_INDEX_TICKER}) missing.")

    sector_bundles = {}
    missing_sectors = []
    for ticker in sorted(set(sector_mod.SECTOR_MAP.values())):
        df = load_fixture_df(ticker)
        if df is not None:
            sector_bundles[ticker] = sector_mod.compute_sector_trend_bundle(df)
        else:
            missing_sectors.append(ticker)
    if missing_sectors:
        report.append(f"  WARNING: sector fixtures missing: {missing_sectors}")

    daily, bundles = {}, {}
    missing_stocks, too_short_stocks = [], []
    for s in universe:
        df = load_fixture_df(sym.to_yf_ticker(s))
        if df is None:
            missing_stocks.append(s)
            continue
        if len(df) < MIN_WARMUP_DAYS + 30:
            too_short_stocks.append((s, len(df)))
            continue
        daily[s] = df
        bundles[s] = compute_bundle(df)
    if missing_stocks:
        report.append(f"  WARNING: stock fixtures missing: {missing_stocks}")
    if too_short_stocks:
        report.append(f"  WARNING: stock fixtures too short (<{MIN_WARMUP_DAYS + 30} rows): {too_short_stocks}")
    report.append(f"  Offline universe loaded: {len(daily)}/{len(universe)} symbols")

    return UniverseData(daily=daily, bundles=bundles, regime_bundle=regime_bundle, sector_bundles=sector_bundles)


def compare_datasets(offline: pd.DataFrame, archived: pd.DataFrame, key_cols: list[str], label: str, report: list[str]) -> bool:
    report.append(f"\n## Comparison: {label}")
    report.append(f"  Offline-recomputed rows: {len(offline)}  |  Archived rows: {len(archived)}")
    if len(offline) != len(archived):
        report.append(f"  ROW COUNT MISMATCH ({len(offline)} vs {len(archived)}) -- explaining, not tuning to match:")
        off_keys = set(map(tuple, offline[key_cols].astype(str).values))
        arc_keys = set(map(tuple, archived[key_cols].astype(str).values))
        only_offline = off_keys - arc_keys
        only_archived = arc_keys - off_keys
        report.append(f"    Keys only in offline recomputation: {len(only_offline)} "
                       f"(sample: {list(only_offline)[:10]})")
        report.append(f"    Keys only in archived experiment-5 output: {len(only_archived)} "
                       f"(sample: {list(only_archived)[:10]})")

    o = offline.sort_values(key_cols).reset_index(drop=True)
    a = archived.sort_values(key_cols).reset_index(drop=True)
    common_keys = set(map(tuple, o[key_cols].astype(str).values)) & set(map(tuple, a[key_cols].astype(str).values))
    o_idx = o.set_index(key_cols)
    a_idx = a.set_index(key_cols)
    common_index = o_idx.index.intersection(a_idx.index)
    o_common = o_idx.loc[common_index]
    a_common = a_idx.loc[common_index]
    report.append(f"  Rows with matching keys in both: {len(common_index)}")

    common_cols = [c for c in a_common.columns if c in o_common.columns]
    mismatches = []
    mismatch_rows_by_col = {}
    for col in common_cols:
        if pd.api.types.is_numeric_dtype(a_common[col]) and pd.api.types.is_numeric_dtype(o_common[col]):
            close = np.isclose(o_common[col].to_numpy(dtype=float), a_common[col].to_numpy(dtype=float),
                                rtol=NUMERIC_TOL, atol=NUMERIC_TOL, equal_nan=True)
            bad_mask = ~close
        else:
            # Normalize missing-value representations before comparing: e.g. sector_ticker is a pure
            # static SECTOR_MAP.get(symbol) lookup (independent of fetch time), where Python None
            # stringifies as "None" but a CSV-round-tripped NaN stringifies as "nan" -- a comparison-code
            # artifact identical to the one found and fixed in experiment 8, not a real data difference.
            o_norm = o_common[col].map(lambda x: "" if pd.isna(x) else str(x))
            a_norm = a_common[col].map(lambda x: "" if pd.isna(x) else str(x))
            bad_mask = (o_norm != a_norm).to_numpy()
        n_bad = int(bad_mask.sum())
        if n_bad:
            mismatches.append((col, n_bad))
            mismatch_rows_by_col[col] = common_index[bad_mask][:10].tolist()
    if mismatches:
        report.append(f"  VALUE MISMATCHES among matched-key rows, by column (predeclared tol={NUMERIC_TOL}, "
                       f"missing-value representations normalized before comparison): {mismatches}")
        for col, keys in mismatch_rows_by_col.items():
            detail = []
            for k in keys:
                detail.append({"key": k, "offline": o_common.loc[[k], col].iloc[0] if not isinstance(o_common.loc[k, col], pd.Series) else o_common.loc[k, col].tolist(),
                                "archived": a_common.loc[[k], col].iloc[0] if not isinstance(a_common.loc[k, col], pd.Series) else a_common.loc[k, col].tolist()})
            report.append(f"    Sample mismatches for '{col}' (up to 10): {detail}")
    else:
        report.append(f"  OK -- zero value mismatches across {len(common_cols)} compared columns among matched-key rows.")

    exact_match = (len(offline) == len(archived)) and (len(mismatches) == 0) and (len(common_index) == len(archived))
    report.append(f"  EXACT RECONSTRUCTION (row count identical, all keys matched, zero value mismatches): {exact_match}")
    return exact_match


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["OFFLINE RAW-DATA-FIXTURE REPRODUCIBILITY AUDIT (experiment 12, research only, network blocked)"]

    report.append("\n## Hypothesis and falsifier (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: an immutable local fixture, captured through the existing data-fetch path, allows the "
                   "canonical experiment-5 population and trade outcomes to be regenerated without network access "
                   "or production-code changes.")
    report.append("  Falsified if any required series/date-range/OHLCV field/provenance-hash record is missing, or "
                   "if an offline rerun cannot reproduce the archived experiment-5 master/trade artifacts within "
                   "predeclared numeric tolerances.")
    report.append("  This is a reproducibility audit only -- not evidence the STRONG_BEARISH anomaly is real, and "
                   "not permission to change strategy logic.")

    report.append("\n## Offline boundary: network-block self-test")
    blocked_ok = self_test_network_blocked()
    report.append(f"  socket.create_connection(('8.8.8.8', 53)) raised NetworkBlockedError as expected: {blocked_ok}")
    report.append("  This script's socket.socket.connect/connect_ex and socket.create_connection are monkey-patched "
                   "to raise before any other import (yfinance/requests/urllib3 all route through socket), so "
                   "network access is BLOCKED, not merely unused, for the remainder of this process.")
    if not blocked_ok:
        report.append("  ARTIFACT INTEGRITY FAILURE: network block self-test failed. Aborting before any further work.")
        _write(report, ts)
        return

    report.append("\n## Fixture provenance")
    if not MANIFEST_PATH.exists():
        report.append("  FALSIFIED: no fixture manifest found -- capture step (research/capture_raw_data_fixture.py) "
                       "was not run, or its output is missing. No further comparison is possible.")
        _write(report, ts)
        return
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest_sha = sha256_of(MANIFEST_PATH)
    report.append(f"  Manifest: {MANIFEST_PATH.name}  SHA-256={manifest_sha}")
    report.append(f"  Captured at (UTC): {manifest['captured_at_utc']}")
    report.append(f"  Fetch mechanism (quoted from manifest): {manifest['fetch_mechanism']}")
    report.append(f"  Library versions: yfinance={manifest['yfinance_version']}  pandas={manifest['pandas_version']}")
    report.append(f"  Requested period: {manifest['requested_period']}")
    report.append(f"  Capture summary: {manifest['summary']}")
    failed_entries = [e for e in manifest["entries"] if e["status"] != "OK"]
    if failed_entries:
        report.append(f"  FAILED capture entries (reported, not substituted): {failed_entries}")
    for e in manifest["entries"]:
        if e["status"] == "OK":
            report.append(f"    {e['logical_symbol']:20s} ({e['kind']}): {e['filename']}  sha256={e['sha256'][:16]}...  "
                           f"rows={e['rows']}  range={e['date_min']} to {e['date_max']}  "
                           f"columns={e['columns']}  tz_after_strip={e['index_tz_after_strip']}")

    report.append("\n## Canonical experiment-5 input hashes (re-checked, must be unchanged since capture)")
    master_sha = sha256_of(MASTER_PATH)
    trades_sha = sha256_of(TRADES_PATH)
    report.append(f"  {MASTER_PATH.name}: {master_sha}")
    report.append(f"  {TRADES_PATH.name}: {trades_sha}")

    universe = sym.get_universe()
    report.append(f"\n## Required universe (from symbols.get_universe(), quoted not re-derived): N={len(universe)}")

    report.append("\n## Offline universe load (from frozen fixture only -- no network call)")
    u = load_offline_universe(universe, report)
    loaded_universe = list(u.daily.keys())

    if len(loaded_universe) == 0 or u.regime_bundle is None:
        report.append("  FALSIFIED: offline universe load produced zero usable stock series or no regime bundle -- "
                       "cannot proceed to recomputation.")
        _write(report, ts)
        return

    report.append("\n## Offline recomputation (research.factor_data.build_master_dataset / run_ablation, UNCHANGED)")
    offline_master = build_master_dataset(u, loaded_universe)
    st_trades = run_ablation(u, loaded_universe, CATEGORY_SHORT_TERM, ablate_factor=None, min_score=40.0)
    lt_trades = run_ablation(u, loaded_universe, CATEGORY_LONG_TERM, ablate_factor=None, min_score=40.0)
    offline_trades = pd.concat([st_trades, lt_trades], ignore_index=True)
    report.append(f"  Offline master rows: {len(offline_master)}  |  Offline trades rows: {len(offline_trades)}")

    archived_master = pd.read_csv(MASTER_PATH, parse_dates=["date"])
    archived_trades = pd.read_csv(TRADES_PATH, parse_dates=["signal_date"])
    offline_master_cmp = offline_master.rename(columns={"date": "date"})
    master_exact = compare_datasets(offline_master_cmp, archived_master, ["symbol", "category", "date"],
                                     "master dataset (build_master_dataset)", report)
    trades_exact = compare_datasets(offline_trades, archived_trades, ["symbol", "category", "signal_date"],
                                     "trades dataset (run_ablation, threshold=40)", report)

    report.append("\n## Limitations (stated explicitly, not resolved by this audit)")
    report.append("  - Vendor data revisions: Yahoo Finance can silently revise historical OHLCV (e.g. corrected "
                   "closes) between the original experiment-5 fetch and this fixture's capture -- any such revision "
                   "would surface as a value mismatch above, indistinguishable from a genuine reproduction failure "
                   "without a third independent source.")
    report.append("  - Corporate actions: splits/bonuses/dividends between the two fetch times would shift "
                   "auto_adjust=False raw prices for all pre-action bars if yfinance restates them; not checked "
                   "independently here.")
    report.append("  - Timezone: both fetches use data_sources._strip_tz() to drop the Asia/Kolkata tz-awareness -- "
                   "identical handling, but a fetch-time boundary near midnight IST could shift which calendar date "
                   "a bar is stamped with; not observed to have occurred here unless flagged above.")
    report.append("  - Survivorship: symbols.get_universe() reflects TODAY's NIFTY 50 + SENSEX Extra constituents, "
                   "projected backward -- identical bias in both the original and this offline recomputation, not "
                   "newly introduced or resolved by this audit.")
    report.append("  - This fixture, even if reconstruction is exact, only proves LOCAL reproducibility of "
                   "experiment 5's specific master/trades outputs. It does not, by itself, restore the entry_date/"
                   "exit_date/visited-index information that experiments 9-11 found the archived artifacts lack -- "
                   "a future scheduler audit would need to run research.scheduler_attribution_experiment-equivalent "
                   "logic AGAINST this now-frozen fixture to get that (a separate, not-yet-run experiment).")

    report.append("\n## Verdict")
    if master_exact and trades_exact:
        report.append("  PROVISIONALLY SUPPORTED: the frozen local fixture reproduces the archived experiment-5 "
                       "master and trades outputs exactly (within the predeclared 1e-6 tolerance), entirely offline "
                       "(network access blocked at the socket layer, self-test confirmed). This fixture IS "
                       "sufficient to re-run experiment-5-equivalent recomputation offline. It does not by itself "
                       "make future SCHEDULER audits (experiments 8-11) reproducible, since those need "
                       "entry/exit-date and visited-index information beyond what build_master_dataset/run_ablation "
                       "output -- a separate follow-up would be needed to test that specifically.")
    else:
        report.append(f"  FALSIFIED: offline reconstruction did not match the archived experiment-5 artifacts "
                       f"exactly (master_exact={master_exact}, trades_exact={trades_exact}) -- see the comparison "
                       f"sections above for the specific mismatches, which were explained, not tuned away.")

    _write(report, ts, offline_master=offline_master, offline_trades=offline_trades)


def _write(report: list[str], ts: str, offline_master: pd.DataFrame | None = None, offline_trades: pd.DataFrame | None = None) -> None:
    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"offline_reproducibility_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")
    if offline_master is not None:
        offline_master.to_csv(RESULTS_DIR / f"offline_master_{ts}.csv", index=False)
    if offline_trades is not None:
        offline_trades.to_csv(RESULTS_DIR / f"offline_trades_{ts}.csv", index=False)


if __name__ == "__main__":
    main()
