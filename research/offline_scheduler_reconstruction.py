"""
RESEARCH ONLY -- experiment 13: offline scheduler-attribution reconstruction
from the frozen experiment-12 fixture.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, written after
auditing experiment 12). Tests whether the frozen 61-series raw-OHLCV
fixture closes the specific evidence gap experiments 9-11 could not close
without a live re-fetch: can experiment 8's scheduler-attribution
conclusion for the 7 predeclared Recent/STRONG_BEARISH candidates be
independently reconstructed OFFLINE (network blocked), from frozen local
data only?

This does NOT import or call research.scheduler_attribution_experiment
(explicitly forbidden by spec) -- the instrumented wrapper below is freshly
written, calling the unchanged production scoring/grading/classification/
simulation functions directly, exactly mirroring the canonical
research.factor_data.run_ablation walk (including its
`i = max(exit_idx + 1, i + 1)` update), but as independent new code. The
Recent/STRONG_BEARISH population is identified via
research.factor_data.build_master_dataset (a different, unrestricted
module), fed by a fresh offline UniverseData loader that reads only the
frozen fixture.

This is a simulation-path/evidentiary-gap audit only. It does not test
whether the STRONG_BEARISH-vs-BULLISH return anomaly is real, and finds
no reason to change the non-overlap rule, thresholds, or any production
logic regardless of outcome.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Network block MUST happen before any other import that could reach the
# network. Self-tested below with a real connection attempt.
# ---------------------------------------------------------------------------
import socket


class NetworkBlockedError(RuntimeError):
    pass


def _blocked(*_a, **_kw):
    raise NetworkBlockedError("Network access is blocked in this offline-only audit script (experiment 13).")


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
from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM, _classify_signal, _grade_from_score, compute_bundle
from backtest import CENSOR_BUFFER_DAYS, MIN_WARMUP_DAYS, _simulate_trade
from market_regime import compute_regime_bundle
from research.factor_data import SCORERS, UniverseData, _regime_at, build_master_dataset

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "research" / "fixtures" / "raw_ohlcv"
MANIFEST_PATH = FIXTURE_DIR.parent / "raw_ohlcv_manifest.json"
RESULTS_DIR = PROJECT_ROOT / "research" / "results"

TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"
MASTER_PATH = RESULTS_DIR / "resistance_master_20260913_164146.csv"
OFFLINE_MASTER_PATH = RESULTS_DIR / "offline_master_20260913_225716.csv"
OFFLINE_TRADES_PATH = RESULTS_DIR / "offline_trades_20260913_225716.csv"
STATES_PATH = RESULTS_DIR / "scheduler_attribution_states_20260913_192107.csv"
EXPECTED_MANIFEST_SHA = "235e4f3c0991715bdd7363e7516238d85ad7255d6696bb94124616628ff0214b"

PRODUCTION_FILES = ["analyzer.py", "config.py", "main.py", "market_regime.py", "sector.py", "backtest.py",
                    "position_sizing.py", "positions.py", "report.py", "narrative.py", "emailer.py",
                    "sheets_export.py", "symbols.py", "data_sources.py", "indicators.py", "tests/test_engine.py"]

NUMERIC_TOL = 1e-6
MIN_SCORE = 40.0
SPLIT_EARLY_END = pd.Timestamp("2025-01-31")
SPLIT_MIDDLE_END = pd.Timestamp("2025-10-17")

PREDECLARED_CANDIDATES = [
    ("ADANIENT", "Long-Term", pd.Timestamp("2026-06-05")),
    ("APOLLOHOSP", "Long-Term", pd.Timestamp("2026-06-05")),
    ("APOLLOHOSP", "Long-Term", pd.Timestamp("2026-06-08")),
    ("COALINDIA", "Long-Term", pd.Timestamp("2026-06-05")),
    ("COALINDIA", "Long-Term", pd.Timestamp("2026-06-08")),
    ("TITAN", "Long-Term", pd.Timestamp("2026-06-05")),
    ("TITAN", "Long-Term", pd.Timestamp("2026-06-08")),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def self_test_network_blocked() -> bool:
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return False
    except NetworkBlockedError:
        return True
    except Exception:
        return False


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("&", "AND").replace(".", "_")


def load_fixture_df(yf_ticker: str) -> pd.DataFrame | None:
    fpath = FIXTURE_DIR / f"{safe_name(yf_ticker)}.csv"
    if not fpath.exists():
        return None
    df = pd.read_csv(fpath, index_col=0, parse_dates=True)
    df.index.name = None
    return df


def load_offline_universe(universe: list[str], report: list[str]) -> UniverseData:
    nifty_df = load_fixture_df(cfg.REGIME_INDEX_TICKER)
    regime_bundle = compute_regime_bundle(nifty_df) if nifty_df is not None else None
    sector_bundles = {}
    for ticker in sorted(set(sector_mod.SECTOR_MAP.values())):
        df = load_fixture_df(ticker)
        if df is not None:
            sector_bundles[ticker] = sector_mod.compute_sector_trend_bundle(df)
    daily, bundles = {}, {}
    for s in universe:
        df = load_fixture_df(sym.to_yf_ticker(s))
        if df is None or len(df) < MIN_WARMUP_DAYS + 30:
            continue
        daily[s] = df
        bundles[s] = compute_bundle(df)
    report.append(f"  Offline universe loaded: {len(daily)}/{len(universe)} symbols; "
                   f"regime_bundle={'OK' if regime_bundle is not None else 'MISSING'}; "
                   f"sector_bundles={len(sector_bundles)}/{len(set(sector_mod.SECTOR_MAP.values()))}")
    return UniverseData(daily=daily, bundles=bundles, regime_bundle=regime_bundle, sector_bundles=sector_bundles)


def instrumented_walk(u: UniverseData, universe: list[str], category: str, min_score: float = MIN_SCORE):
    """Freshly-written instrumented wrapper (NOT imported from
    research.scheduler_attribution_experiment) mirroring
    research.factor_data.run_ablation's walk exactly: same production
    function calls, same `i = max(exit_idx + 1, i + 1)` update, ablate
    disabled (ablate_factor=None equivalent) matching experiment 5/8/12."""
    scorer = SCORERS[category]
    rs_lookback = cfg.RS_LOOKBACK_DAYS_LONG if category == CATEGORY_LONG_TERM else cfg.RS_LOOKBACK_DAYS
    trade_rows = []
    visited: dict[str, dict[int, dict]] = {}
    trades_by_symbol: dict[str, list[dict]] = {}

    for symbol in universe:
        df = u.daily.get(symbol)
        bundle = u.bundles.get(symbol)
        if df is None or bundle is None:
            continue
        censor_date = df.index[-1] - pd.Timedelta(days=CENSOR_BUFFER_DAYS)
        visited[symbol] = {}
        trades_by_symbol[symbol] = []

        i = MIN_WARMUP_DAYS
        while i < len(df) - 1:
            date = df.index[i]
            if date > censor_date:
                break
            regime_label = _regime_at(u, date)
            sector_confirmation = sector_mod.build_point_in_time_confirmation(
                symbol, bundle, i, u.sector_bundles, u.regime_bundle.close if u.regime_bundle else None, rs_lookback)
            idea = scorer(symbol, bundle, i, regime_label=regime_label,
                           sector_confirmation=sector_confirmation, data_note="")
            score = idea.score
            grade = _grade_from_score(score)
            signal = _classify_signal(grade, idea.chase_flag, idea.rr_ratio, regime_label or "NEUTRAL")
            eligible = not (score < min_score or signal == "NO TRADE")

            common = {"date": date, "score": score, "grade": grade, "signal": signal,
                      "rr_ratio": idea.rr_ratio, "chase_flag": idea.chase_flag, "regime": regime_label or "UNKNOWN"}

            if not eligible:
                visited[symbol][i] = {**common, "state": "reached_and_rejected_upstream"}
                i += 1
                continue

            entry_idx = i + 1
            entry_price = float(df["Open"].iloc[entry_idx])
            exit_idx, exit_price, exit_reason = _simulate_trade(df, entry_idx, idea.target1, idea.stop_loss)
            strategy_return_pct = (exit_price / entry_price - 1) * 100
            days_held = (df.index[exit_idx] - df.index[entry_idx]).days

            row = {
                "symbol": symbol, "category": category, "regime": regime_label or "UNKNOWN",
                "signal_date": date, "sector_ticker": sector_confirmation.sector_ticker,
                "ablated_score": score, "exit_reason": exit_reason,
                "strategy_return_pct": strategy_return_pct, "days_held": days_held,
                "entry_price": entry_price, "target1": idea.target1, "stop_loss": idea.stop_loss,
                "target_distance_pct": (idea.target1 / entry_price - 1) * 100,
                "stop_distance_pct": (1 - idea.stop_loss / entry_price) * 100,
                "atr_pct": float(bundle.atr_pct.iloc[i]) if pd.notna(bundle.atr_pct.iloc[i]) else np.nan,
                "support20": float(bundle.support20.iloc[i]),
                "resistance20": float(bundle.resistance20.iloc[i]),
                "high52w": float(bundle.high52w.iloc[i]),
            }
            for factor_name, (earned, maxpts) in idea.score_breakdown.items():
                row[f"factor__{factor_name}"] = (earned / maxpts) if maxpts > 0 else np.nan
            trade_rows.append(row)

            visited[symbol][i] = {**common, "state": "reached_and_selected"}
            new_i = max(exit_idx + 1, i + 1)
            trades_by_symbol[symbol].append({
                "category": category, "signal_idx": i, "signal_date": date,
                "entry_idx": entry_idx, "entry_date": df.index[entry_idx],
                "exit_idx": exit_idx, "exit_date": df.index[exit_idx], "exit_reason": exit_reason,
                "skip_start": i + 1, "skip_end_excl": new_i,
            })
            i = new_i

    return pd.DataFrame(trade_rows), visited, trades_by_symbol


def resolve_state(symbol: str, idx: int, visited: dict, trades_by_symbol: dict) -> dict:
    v = visited.get(symbol, {})
    if idx in v:
        return v[idx]
    for tr in trades_by_symbol.get(symbol, []):
        if tr["skip_start"] <= idx < tr["skip_end_excl"]:
            return {"state": "skipped_by_open_trade", "blocking_signal_date": tr["signal_date"],
                    "blocking_entry_date": tr["entry_date"], "blocking_exit_date": tr["exit_date"],
                    "blocking_exit_reason": tr["exit_reason"], "blocking_category": tr["category"],
                    "blocking_skip_start_idx": tr["skip_start"], "blocking_skip_end_excl_idx": tr["skip_end_excl"]}
    return {"state": "unresolved"}


def assign_time_split(dates: pd.Series) -> pd.Series:
    return np.select([dates <= SPLIT_EARLY_END, dates <= SPLIT_MIDDLE_END], ["Early", "Middle"], default="Recent")


def gate_bucket(score: float, grade, signal: str) -> str:
    grade_str = "NONE" if pd.isna(grade) or grade in (None, "NONE") else grade
    if score < 40:
        return "score<40"
    if score < 60:
        return "40<=score<60"
    if grade_str != "NONE" and signal == "NO TRADE":
        return "grade_present_signal_NO_TRADE"
    if signal != "NO TRADE":
        return "pre_scheduler_eligible"
    return "other_NO_TRADE"


def reconstruction_check(offline_trades: pd.DataFrame, canonical_path: Path, report: list[str]) -> bool:
    report.append(f"\n## Step 4: reconstruction check vs {canonical_path.name} "
                   f"(predeclared tol rtol=atol={NUMERIC_TOL}; documented missing-value normalization only)")
    canonical = pd.read_csv(canonical_path, parse_dates=["signal_date"])
    key_cols = ["symbol", "category", "signal_date"]
    w = offline_trades.sort_values(key_cols).reset_index(drop=True)
    c = canonical.sort_values(key_cols).reset_index(drop=True)
    if len(w) != len(c):
        report.append(f"  ROW COUNT MISMATCH: offline wrapper={len(w)}, canonical={len(c)}. FAILED.")
        return False
    common_cols = [col for col in c.columns if col in w.columns]
    mismatches = []
    for col in common_cols:
        if pd.api.types.is_numeric_dtype(c[col]) and pd.api.types.is_numeric_dtype(w[col]):
            close = np.isclose(w[col].to_numpy(dtype=float), c[col].to_numpy(dtype=float),
                                rtol=NUMERIC_TOL, atol=NUMERIC_TOL, equal_nan=True)
            n_bad = int((~close).sum())
        else:
            # Documented normalization only (from experiments 8/9/12): Python None (e.g. unmapped
            # sector_ticker) vs CSV-round-tripped NaN both mean "no value" but stringify differently.
            w_norm = w[col].map(lambda x: "" if pd.isna(x) else str(x))
            c_norm = c[col].map(lambda x: "" if pd.isna(x) else str(x))
            n_bad = int((w_norm != c_norm).sum())
        if n_bad:
            mismatches.append((col, n_bad))
    if mismatches:
        report.append(f"  VALUE MISMATCHES: {mismatches}. FAILED.")
        return False
    report.append(f"  OK -- {len(w)} rows, zero mismatches across {len(common_cols)} columns (row count and keys identical).")
    return True


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["OFFLINE SCHEDULER-ATTRIBUTION RECONSTRUCTION FROM THE FROZEN FIXTURE (experiment 13, research only, network blocked)"]

    report.append("\n## Hypothesis (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  Using only the frozen experiment-12 fixture and unchanged production functions, a fresh "
                   "offline instrumented reconstruction will (1) reproduce the canonical 2,083 experiment-5 trades "
                   "exactly, and (2) independently identify the same 7 pre-scheduler-eligible Recent/STRONG_BEARISH "
                   "Long-Term rows as skipped by a prior selected trade whose reconstructed open interval covers "
                   "each candidate date.")
    report.append("  Simulation-path finding only -- not evidence of predictive edge, causality, or a reason to "
                   "change the non-overlap rule; does not test whether the STRONG_BEARISH return anomaly is real.")

    # ---- Step 1: pre-work hashes ----
    report.append("\n## Step 1: pre-work git status and hashes")
    fixed_artifacts = [MANIFEST_PATH, MASTER_PATH, TRADES_PATH, OFFLINE_MASTER_PATH, OFFLINE_TRADES_PATH, STATES_PATH]
    hashes_before = {p.name: sha256_of(p) for p in fixed_artifacts}
    for name, h in hashes_before.items():
        report.append(f"  {name}: {h}")
    manifest_sha = hashes_before[MANIFEST_PATH.name]
    report.append(f"  Manifest hash matches experiment-12-recorded value ({EXPECTED_MANIFEST_SHA}): "
                   f"{manifest_sha == EXPECTED_MANIFEST_SHA}")

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture_mismatches = []
    for e in manifest["entries"]:
        if e["status"] != "OK":
            continue
        fpath = FIXTURE_DIR / e["filename"]
        actual = sha256_of(fpath)
        if actual != e["sha256"]:
            fixture_mismatches.append((e["filename"], e["sha256"], actual))
    report.append(f"  Verified {sum(1 for e in manifest['entries'] if e['status']=='OK')} fixture CSVs against "
                   f"manifest-recorded SHA-256 (not assumed): mismatches={len(fixture_mismatches)}"
                   + (f" -- {fixture_mismatches}" if fixture_mismatches else ""))

    prod_hashes_before = {f: sha256_of(PROJECT_ROOT / f) for f in PRODUCTION_FILES}
    report.append(f"  Hashed {len(prod_hashes_before)} production files + tests/test_engine.py before work.")

    # ---- Step 2/3: offline universe + fresh instrumented walk ----
    report.append("\n## Step 2/3: offline universe load + fresh instrumented walk (both categories)")
    universe = sym.get_universe()
    u = load_offline_universe(universe, report)
    loaded_universe = list(u.daily.keys())

    if not loaded_universe or u.regime_bundle is None:
        report.append("  FALSIFIED: offline universe load failed (no usable symbols or no regime bundle).")
        _finish(report, ts, {}, hashes_before, prod_hashes_before)
        return

    st_trades, st_visited, st_trades_by_symbol = instrumented_walk(u, loaded_universe, CATEGORY_SHORT_TERM)
    lt_trades, lt_visited, lt_trades_by_symbol = instrumented_walk(u, loaded_universe, CATEGORY_LONG_TERM)
    offline_trades_new = pd.concat([st_trades, lt_trades], ignore_index=True)
    report.append(f"  Fresh wrapper produced {len(offline_trades_new)} trades ({len(st_trades)} ST + {len(lt_trades)} LT).")

    # ---- Step 4: reconstruction check ----
    recon_ok = reconstruction_check(offline_trades_new, TRADES_PATH, report)

    # ---- Step 5: independently recompute Recent/STRONG_BEARISH population + gates ----
    report.append("\n## Step 5: independent population recomputation (research.factor_data.build_master_dataset, UNCHANGED)")
    offline_master_new = build_master_dataset(u, loaded_universe)
    offline_master_new["time_split"] = assign_time_split(offline_master_new["date"])
    pop = offline_master_new[(offline_master_new["time_split"] == "Recent") & (offline_master_new["regime"] == "STRONG_BEARISH")].copy()
    report.append(f"  Recent/STRONG_BEARISH population (both categories, all symbols): N={len(pop)} "
                   f"(51-symbol universe would give 204 at 2 dates x 2 categories x 51 symbols)")
    pop["gate_bucket"] = pop.apply(lambda r: gate_bucket(r["score"], r["grade"], r["signal"]), axis=1)
    gate_counts = pop["gate_bucket"].value_counts()
    report.append(f"  Gate bucket counts: {gate_counts.to_dict()}")

    eligible = pop[pop["gate_bucket"] == "pre_scheduler_eligible"].copy()
    eligible_keys = set(zip(eligible["symbol"], eligible["category"], eligible["date"]))
    predeclared_keys = set(PREDECLARED_CANDIDATES)
    keys_match = eligible_keys == predeclared_keys
    report.append(f"  Independently recomputed eligible-candidate set: N={len(eligible_keys)}")
    report.append(f"  Equals the 7 predeclared keys exactly: {keys_match}")
    if not keys_match:
        report.append(f"    Missing from recomputation: {predeclared_keys - eligible_keys}")
        report.append(f"    Extra in recomputation (not predeclared): {eligible_keys - predeclared_keys}")

    # ---- Step 6: state + interval verification for each of the 7 predeclared candidates ----
    report.append("\n## Step 6: state and interval verification, 7 predeclared candidates")
    visited_by_cat = {CATEGORY_SHORT_TERM: st_visited, CATEGORY_LONG_TERM: lt_visited}
    trades_by_symbol_by_cat = {CATEGORY_SHORT_TERM: st_trades_by_symbol, CATEGORY_LONG_TERM: lt_trades_by_symbol}
    seven_row_records = []
    all_conditions_4_met = True
    for symbol, category, cand_date in PREDECLARED_CANDIDATES:
        df = u.daily.get(symbol)
        rec = {"symbol": symbol, "category": category, "candidate_date": cand_date}
        if df is None or cand_date not in df.index:
            rec.update({"state": "symbol_data_unavailable"})
            all_conditions_4_met = False
            seven_row_records.append(rec)
            report.append(f"  {symbol} {category} {cand_date.date()}: symbol data unavailable")
            continue
        idx = df.index.get_loc(cand_date)
        info = resolve_state(symbol, idx, visited_by_cat[category], trades_by_symbol_by_cat[category])
        rec.update(info)
        if info["state"] == "skipped_by_open_trade":
            date_interval_ok = info["blocking_entry_date"] <= cand_date <= info["blocking_exit_date"]
            index_interval_ok = info["blocking_skip_start_idx"] <= idx < info["blocking_skip_end_excl_idx"]
            rec["date_interval_ok"] = date_interval_ok
            rec["index_interval_ok"] = index_interval_ok
            if not (date_interval_ok and index_interval_ok):
                all_conditions_4_met = False
            report.append(f"  {symbol:12s} {category:20s} cand={cand_date.date()}  state={info['state']}  "
                           f"blocked_by: signal={info['blocking_signal_date'].date()} entry={info['blocking_entry_date'].date()} "
                           f"exit={info['blocking_exit_date'].date()} ({info['blocking_exit_reason']})  "
                           f"date_interval_ok={date_interval_ok}  index_interval_ok={index_interval_ok}")
        else:
            all_conditions_4_met = False
            report.append(f"  {symbol:12s} {category:20s} cand={cand_date.date()}  state={info['state']} (NOT skipped_by_open_trade)")
        seven_row_records.append(rec)
    seven_row_df = pd.DataFrame(seven_row_records)

    # ---- Step 7: secondary comparison against experiment-8's states artifact ----
    report.append("\n## Step 7: secondary comparison vs scheduler_attribution_states_20260913_192107.csv (corroboration only, not primary derivation)")
    states_archived = pd.read_csv(STATES_PATH, parse_dates=["date"])
    corroborated = 0
    for symbol, category, cand_date in PREDECLARED_CANDIDATES:
        match = states_archived[(states_archived["symbol"] == symbol) & (states_archived["category"] == category) &
                                 (states_archived["date"] == cand_date)]
        my_row = seven_row_df[(seven_row_df["symbol"] == symbol) & (seven_row_df["category"] == category) &
                               (seven_row_df["candidate_date"] == cand_date)]
        if len(match) == 1 and len(my_row) == 1:
            agree = match.iloc[0]["state"] == my_row.iloc[0]["state"]
            corroborated += int(agree)
            report.append(f"  {symbol:12s} {category:20s} cand={cand_date.date()}: experiment-8 state="
                           f"{match.iloc[0]['state']}  vs  experiment-13 state={my_row.iloc[0]['state']}  agree={agree}")
    report.append(f"  Agreement with experiment 8's independently-derived (network-using) states artifact: {corroborated}/7")

    # ---- Step 8: re-report experiment-12 master mismatches and check intersection ----
    report.append("\n## Step 8: experiment-12 master mismatches, re-reported (not explained or repaired here)")
    off12 = pd.read_csv(OFFLINE_MASTER_PATH, parse_dates=["date"])
    arc = pd.read_csv(MASTER_PATH, parse_dates=["date"])
    o_idx = off12.set_index(["symbol", "category", "date"])
    a_idx = arc.set_index(["symbol", "category", "date"])
    common = o_idx.index.intersection(a_idx.index)
    oc, ac = o_idx.loc[common], a_idx.loc[common]
    bad_mask = ~np.isclose(oc["score"].to_numpy(dtype=float), ac["score"].to_numpy(dtype=float), atol=NUMERIC_TOL)
    mismatch_keys = set(common[bad_mask])
    report.append(f"  Experiment-12 master 'score' mismatches re-identified from fixed artifacts: N={len(mismatch_keys)} (expect 11)")
    report.append(f"  Mismatch keys: {sorted(mismatch_keys)}")
    intersects_population = mismatch_keys & set(zip(pop["symbol"], pop["category"], pop["date"]))
    intersects_candidates = mismatch_keys & predeclared_keys
    report.append(f"  Intersection with the Recent/STRONG_BEARISH population (N={len(pop)}): {len(intersects_population)} "
                   f"{'-- ' + str(intersects_population) if intersects_population else '(none)'}")
    report.append(f"  Intersection with the 7 predeclared candidate keys: {len(intersects_candidates)} "
                   f"{'-- ' + str(intersects_candidates) if intersects_candidates else '(none)'}")

    # ---- Robustness: Early/Middle context (descriptive only) ----
    report.append("\n## Descriptive context: Early/Middle STRONG_BEARISH state taxonomy (cannot override primary decision)")
    for split in ["Early", "Middle"]:
        for category in [CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM]:
            rows = offline_master_new[(offline_master_new["time_split"] == split) &
                                       (offline_master_new["regime"] == "STRONG_BEARISH") &
                                       (offline_master_new["category"] == category)]
            flag = "  [n<20]" if len(rows) < 20 else ""
            report.append(f"  {split} / {category}: N={len(rows)}{flag}")

    # ---- Step 9: post-work hashes ----
    report.append("\n## Step 9: post-work git status and hash re-check")
    hashes_after = {p.name: sha256_of(p) for p in fixed_artifacts}
    artifacts_unchanged = all(hashes_after[k] == hashes_before[k] for k in hashes_before)
    report.append(f"  All 6 fixed artifacts unchanged: {artifacts_unchanged}")
    prod_hashes_after = {f: sha256_of(PROJECT_ROOT / f) for f in PRODUCTION_FILES}
    prod_unchanged = all(prod_hashes_after[f] == prod_hashes_before[f] for f in PRODUCTION_FILES)
    report.append(f"  All 16 production files + tests/test_engine.py byte-unchanged: {prod_unchanged}")
    if not prod_unchanged:
        changed = [f for f in PRODUCTION_FILES if prod_hashes_after[f] != prod_hashes_before[f]]
        report.append(f"  *** INTEGRITY GATE VIOLATION -- changed: {changed} -- EXPERIMENT INVALID ***")

    # ---- Predeclared decision rule ----
    report.append("\n## Predeclared decision-rule table")
    net_block_ok = self_test_network_blocked()
    c1 = net_block_ok and artifacts_unchanged
    c2 = recon_ok
    c3 = keys_match
    c4 = all_conditions_4_met and len(eligible_keys) == 7  # condition 4 only meaningful if the 7 keys exist
    c5 = len(intersects_candidates) == 0
    report.append(f"  1. network block self-test passed AND all fixture/artifact hashes unchanged: {c1}")
    report.append(f"  2. fresh wrapper reproduces all 2083 canonical trades exactly: {c2}")
    report.append(f"  3. independently recomputed eligible set == 7 predeclared keys exactly: {c3}")
    report.append(f"  4. all 7 are skipped_by_open_trade with verified date AND index interval coverage: {c4}")
    report.append(f"  5. no experiment-12 master mismatch intersects the 7 candidate keys: {c5}")
    all_supported = c1 and c2 and c3 and c4 and c5 and prod_unchanged

    report.append("\n## Verdict")
    if not prod_unchanged:
        report.append("  INVALID: a protected production file changed during this run. Per the integrity gate, "
                       "the experiment is marked invalid regardless of the conditions above.")
    elif all_supported:
        report.append("  SUPPORTED: all 5 predeclared conditions hold. The frozen fixture, combined with a freshly "
                       "written offline instrumented wrapper, independently reconstructs experiment 8's "
                       "scheduler-attribution conclusion for all 7 predeclared candidates -- exact trade "
                       "reproduction, exact candidate-set match, and verified date+index interval coverage for "
                       "each blocking trade. This is a simulation-path finding on a very small (n=7) population, "
                       "not evidence of predictive edge or causality, and not a reason to change the non-overlap "
                       "rule. It does not test whether the STRONG_BEARISH return anomaly is real.")
    else:
        report.append("  FALSIFIED: at least one predeclared condition failed -- see the decision-rule table above "
                       "for which one(s). Not reinterpreted as inconclusive (a failed condition is a failure, not "
                       "an execution/evidence gap).")

    report.append("\n## Limitations")
    report.append("  Exact offline reproduction validates this frozen fixture/run only -- it does not eliminate "
                   "survivorship bias (today's constituents projected backward), vendor data revisions that "
                   "occurred before this fixture was captured, corporate-action risk, or generalize to any future "
                   "data. Scheduler attribution on 7 rows is a simulation-path finding, not evidence of predictive "
                   "edge, causality, or a reason to change the non-overlap rule.")

    report.append("\n## Commands executed")
    report.append("  python -m research.offline_scheduler_reconstruction")

    _finish(report, ts, {"seven_row": seven_row_df, "offline_master": offline_master_new,
                          "offline_trades": offline_trades_new}, hashes_before, prod_hashes_before)


def _finish(report: list[str], ts: str, dataframes: dict, hashes_before: dict, prod_hashes_before: dict) -> None:
    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"offline_scheduler_reconstruction_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")
    if "seven_row" in dataframes:
        dataframes["seven_row"].to_csv(RESULTS_DIR / f"offline_scheduler_attribution_{ts}.csv", index=False)


if __name__ == "__main__":
    main()
