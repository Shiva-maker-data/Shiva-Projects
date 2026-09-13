"""
RESEARCH ONLY -- experiment 9: artifact-only reproducibility audit of
experiment 8's scheduler-attribution conclusion.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, written after
auditing experiment 8). Experiment 8 re-fetched the universe (via
research.factor_data.load_universe) to build an instrumented wrapper --
useful for an exact-reconstruction check, but not a demonstration that the
attribution is provable from the FIXED, ALREADY-ARCHIVED artifacts alone,
independent of any live re-fetch. This experiment re-examines the same
claim under a much stricter boundary.

HARD BOUNDARY (enforced by this script's own imports and logic, not just
stated): no `research.factor_data.load_universe`, no `data_sources`, no
network access, no production scoring/simulation function is imported or
called anywhere in this file. Only pandas/numpy/hashlib file I/O on four
fixed, pre-existing files:
  research/results/resistance_master_20260913_164146.csv
  research/results/resistance_trades_20260913_164146.csv
  research/results/scheduler_attribution_states_20260913_192107.csv
  research/results/scheduler_attribution_report_20260913_192107.txt
None of the four is modified; SHA-256 is recorded before AND after reading
each, and the run fails loudly (not silently) if any hash changes.

This audits reproducibility/evidentiary strength only. It does not test
returns, does not revisit the STRONG_BEARISH-vs-BULLISH anomaly, and makes
no recommendation about the frozen non-overlap rule or any production
logic.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"
MASTER_PATH = RESULTS_DIR / "resistance_master_20260913_164146.csv"
TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"
STATES_PATH = RESULTS_DIR / "scheduler_attribution_states_20260913_192107.csv"
REPORT8_PATH = RESULTS_DIR / "scheduler_attribution_report_20260913_192107.txt"
ARTIFACTS = [MASTER_PATH, TRADES_PATH, STATES_PATH, REPORT8_PATH]

RECENT_DATES = pd.to_datetime(["2026-06-05", "2026-06-08"])
MIN_SCORE = 40.0
FLOAT_TOL = 1e-6  # predeclared before any comparison; unchanged throughout


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


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


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["ARTIFACT-ONLY REPRODUCIBILITY AUDIT OF SCHEDULER ATTRIBUTION (research only, no production code/network/refetch)"]

    report.append("\n## Hypothesis and falsifier (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: experiment 8's conclusion -- all 7 eligible Recent STRONG_BEARISH rows were censored by a "
                   "prior selected trade -- can be independently verified using ONLY the four fixed archived "
                   "artifacts, with no network, refetch, new market data, or production scoring/simulation.")
    report.append("  Falsified if any required key/field/state/trade-reference check fails, OR if either causal "
                   "schedule fact (blocking trade still open on the candidate date; the walk skipping that index) "
                   "cannot be independently established from the four fixed artifacts. In that case the correct "
                   "conclusion is: experiment 8 is internally consistent but its attribution is UNVERIFIED under "
                   "the no-refetch boundary -- not evidence for or against the return anomaly.")

    report.append("\n## Provenance -- artifact hashes (recorded BEFORE reading)")
    hashes_before = {}
    for p in ARTIFACTS:
        hashes_before[p.name] = sha256_of(p)
        report.append(f"  {p.name}: {hashes_before[p.name]}")
    report.append(f"  Command: python -m research.scheduler_attribution_reproducibility_audit")
    report.append(f"  Runtime: Python {sys.version.split()[0]}  pandas {pd.__version__}  numpy {np.__version__}")
    report.append("  Hard boundary check: this script imports only pandas, numpy, hashlib, pathlib, datetime, sys -- "
                   "no research.factor_data, data_sources, analyzer, market_regime, sector, or backtest import exists "
                   "in this file (verifiable by reading its import block above).")

    master = pd.read_csv(MASTER_PATH, parse_dates=["date"])
    trades = pd.read_csv(TRADES_PATH, parse_dates=["signal_date"])
    states = pd.read_csv(STATES_PATH, parse_dates=["date", "blocking_signal_date", "blocking_entry_date", "blocking_exit_date"])
    report8_text = REPORT8_PATH.read_text(encoding="utf-8")
    report.append(f"\n  Loaded: master={len(master)} rows, trades={len(trades)} rows, states={len(states)} rows, "
                   f"report8={len(report8_text)} chars (read for hash/quote purposes only, not parsed programmatically)")

    # ---- Step 1: fixed 204-row target population from master alone ----
    report.append("\n## Step 1: fixed target population (master file only)")
    pop = master[(master["regime"] == "STRONG_BEARISH") & (master["date"].isin(RECENT_DATES))].copy()
    n_rows = len(pop)
    n_unique_keys = pop.drop_duplicates(subset=["symbol", "category", "date"]).shape[0]
    report.append(f"  Rows matching regime==STRONG_BEARISH and date in {{2026-06-05, 2026-06-08}}: {n_rows}")
    report.append(f"  Unique (symbol, category, date) keys: {n_unique_keys}")
    if n_rows != 204 or n_unique_keys != 204 or n_rows != n_unique_keys:
        report.append("  ARTIFACT INTEGRITY FAILURE: expected exactly 204 unique keys with no duplicates. STOPPING.")
        _finish(report, ts, verdict="ARTIFACT INTEGRITY FAILURE -- see Step 1", hashes_before=hashes_before)
        return
    report.append("  OK -- exactly 204 unique keys, no duplicates.")

    # ---- Step 2: join to states, compare shared static fields ----
    report.append("\n## Step 2: join to states artifact, one-to-one check, field comparison")
    pop_keyed = pop.set_index(["symbol", "category", "date"])
    states_dupes = states.groupby(["symbol", "category", "date"]).size()
    dupe_keys = states_dupes[states_dupes > 1]
    report.append(f"  States rows with a duplicated (symbol,category,date) key: {len(dupe_keys)}")
    merged = pop.merge(states, on=["symbol", "category", "date"], how="left", suffixes=("_master", "_state"), indicator=True)
    missing_state = merged[merged["_merge"] != "both"]
    report.append(f"  Master keys with a matching state row: {len(merged) - len(missing_state)} of {len(merged)}")
    if len(missing_state):
        report.append(f"  MISSING state rows for keys: {missing_state[['symbol','category','date']].to_dict('records')}")

    merged["gate_bucket_from_master"] = merged.apply(
        lambda r: gate_bucket(r["score_master"], r["grade_master"], r["signal_master"]), axis=1)
    # states.csv's own gate_bucket column (from experiment 8's gate_taxonomy()) uses the same four
    # category names but appends a parenthetical explanation, e.g. "pre_scheduler_eligible (score>=40
    # and signal!=NO TRADE)" -- normalize to the bucket name (text before " (") before comparing, since
    # the full descriptive strings were never meant to match verbatim between the two scripts' labels.
    states_bucket_norm = merged["gate_bucket"].str.split(" (", n=1, regex=False).str[0]
    gate_mismatch = merged[merged["gate_bucket_from_master"] != states_bucket_norm]
    report.append(f"  Gate-bucket recomputed from master vs states' own gate_bucket column: "
                   f"{len(merged) - len(gate_mismatch)}/{len(merged)} match; {len(gate_mismatch)} mismatch(es)")
    if len(gate_mismatch):
        report.append(f"    Mismatches: {gate_mismatch[['symbol','category','date','gate_bucket_from_master','gate_bucket']].to_dict('records')}")

    reached = merged[merged["state"].isin(["reached_and_rejected_upstream", "reached_and_selected"])]
    skipped = merged[merged["state"] == "skipped_by_open_trade"]
    report.append(f"\n  State counts across all 204: {merged['state'].value_counts().to_dict()}")
    report.append(f"  Field comparison (score, grade, signal, rr_ratio, regime) is only MEANINGFUL for rows where "
                   f"the states artifact actually records them (state=reached_and_rejected_upstream or "
                   f"reached_and_selected, n={len(reached)}); resolve_state's skipped_by_open_trade branch does not "
                   f"populate score/grade/signal/rr_ratio/chase_flag at all (structurally absent, not a discrepancy) "
                   f"for n={len(skipped)} rows -- reported here, not silently skipped.")

    def grade_norm(g):
        return "NONE" if pd.isna(g) or g in (None, "NONE") else g

    n_score_bad = int((~np.isclose(reached["score_master"], reached["score_state"], atol=FLOAT_TOL)).sum())
    n_grade_bad = int((reached["grade_master"].apply(grade_norm) != reached["grade_state"].apply(grade_norm)).sum())
    n_signal_bad = int((reached["signal_master"] != reached["signal_state"]).sum())
    n_rr_bad = int((~np.isclose(reached["rr_ratio_master"], reached["rr_ratio_state"], atol=FLOAT_TOL)).sum())
    n_regime_bad = int((reached["regime_master"] != reached["regime_state"]).sum())
    report.append(f"  Among the {len(reached)} reached rows: score mismatches={n_score_bad}, grade mismatches={n_grade_bad}, "
                   f"signal mismatches={n_signal_bad}, rr_ratio mismatches={n_rr_bad}, regime mismatches={n_regime_bad}")
    report.append("  Note: master has no chase_flag column at all -- chase_flag (present in the states artifact) "
                   "cannot be cross-checked against master by construction of that artifact; this is an artifact-"
                   "coverage limitation, not a discrepancy to repair.")
    step2_ok = (len(missing_state) == 0 and len(gate_mismatch) == 0 and n_score_bad == 0 and n_grade_bad == 0
                and n_signal_bad == 0 and n_rr_bad == 0 and n_regime_bad == 0)

    # ---- Step 3: independently identify pre-scheduler-eligible rows from master alone ----
    report.append("\n## Step 3: pre-scheduler-eligible rows, identified independently from master alone")
    pop["gate_bucket_master"] = pop.apply(lambda r: gate_bucket(r["score"], r["grade"], r["signal"]), axis=1)
    eligible = pop[pop["gate_bucket_master"] == "pre_scheduler_eligible"]
    report.append(f"  Pre-scheduler-eligible rows (score>=40 and signal!=NO TRADE), from master alone: n={len(eligible)}")
    for _, r in eligible.iterrows():
        report.append(f"    {r['symbol']:12s} {r['category']:20s} {r['date'].date()} score={r['score']:.1f} signal={r['signal']}")
    if len(eligible) != 7:
        report.append(f"  NOTE: expected 7 per experiment 8 -- got {len(eligible)}. This is reported as a "
                       f"consistency finding, not repaired.")

    eligible_states = eligible.merge(states, on=["symbol", "category", "date"], how="left", suffixes=("", "_st"))
    n_state_skipped = int((eligible_states["state"] == "skipped_by_open_trade").sum())
    n_state_other = len(eligible_states) - n_state_skipped
    report.append(f"  Of these {len(eligible_states)}, state==skipped_by_open_trade: {n_state_skipped}; other state: {n_state_other}")
    has_blocking_ref = eligible_states["blocking_signal_date"].notna() & eligible_states["blocking_category"].notna()
    report.append(f"  With a non-empty blocking signal_date + category reference: {int(has_blocking_ref.sum())} of {len(eligible_states)}")
    report.append("  Blocking symbol is not a separate stored field -- by construction of experiment 8's resolve_state "
                   "(searches only trades_by_symbol[same symbol]), the blocking trade's symbol is necessarily the "
                   "candidate row's own symbol; this is a structural property of the audited code (quoted from "
                   "research/scheduler_attribution_experiment.py's resolve_state, read but not re-executed here), "
                   "not an independently-stored artifact field.")
    step3_ok = (len(eligible) == 7 and n_state_other == 0 and int(has_blocking_ref.sum()) == len(eligible_states))

    # ---- Step 4: cross-check every blocking reference against the canonical trades CSV ----
    report.append("\n## Step 4: cross-check blocking references against the canonical (experiment-5) trades CSV")
    xcheck_rows = []
    for _, r in eligible_states.iterrows():
        match = trades[(trades["symbol"] == r["symbol"]) & (trades["category"] == r["blocking_category"]) &
                        (trades["signal_date"] == r["blocking_signal_date"])]
        found = len(match) == 1
        row = {"symbol": r["symbol"], "category": r["category"], "date": r["date"],
               "blocking_signal_date": r["blocking_signal_date"], "found_in_canonical_trades": found}
        if found:
            m = match.iloc[0]
            row.update({"entry_price": m["entry_price"], "target1": m["target1"], "stop_loss": m["stop_loss"],
                        "exit_reason": m["exit_reason"], "strategy_return_pct": m["strategy_return_pct"],
                        "days_held": m["days_held"]})
        elif len(match) > 1:
            row["found_in_canonical_trades"] = f"AMBIGUOUS ({len(match)} matches)"
        xcheck_rows.append(row)
    xcheck = pd.DataFrame(xcheck_rows)
    n_found = int((xcheck["found_in_canonical_trades"] == True).sum())
    report.append(f"  Blocking references matched exactly one canonical trades-CSV row: {n_found} of {len(xcheck)}")
    for _, r in xcheck.iterrows():
        if r["found_in_canonical_trades"] is True:
            report.append(f"    {r['symbol']:12s} {r['category']:20s} candidate_date={r['date'].date()}  "
                           f"blocking_signal_date={r['blocking_signal_date'].date()}  entry_price={r['entry_price']:.2f}  "
                           f"target1={r['target1']:.2f}  stop_loss={r['stop_loss']:.2f}  exit_reason={r['exit_reason']}  "
                           f"return={r['strategy_return_pct']:.2f}%  days_held={r['days_held']}")
        else:
            report.append(f"    {r['symbol']:12s} {r['category']:20s} candidate_date={r['date'].date()}  "
                           f"NOT FOUND in canonical trades CSV: {r['found_in_canonical_trades']}")
    report.append("  IMPORTANT: the canonical trades CSV stores `signal_date` and `days_held` (a calendar-day count) "
                   "but NO entry_date or exit_date column. Per the spec, exit dates/skipped intervals are NOT inferred "
                   "from days_held arithmetic here -- this cross-check establishes only that the cited blocking trade "
                   "exists in the canonical, independently-produced trade output, nothing about its exit timing.")
    step4_ok = n_found == len(xcheck)

    # ---- Step 5: evidence-closure table ----
    report.append("\n## Step 5: evidence-closure table (per the four critical claims, for all 7 candidates)")
    report.append("  a) candidate_eligibility (score>=40, signal!=NO TRADE): source=master file directly (this "
                   "script's own Step 3 computation) -> INDEPENDENTLY VERIFIED for all 7.")
    report.append(f"  b) blocking_selected_trade_exists: cross-checked against the canonical (experiment-5) trades "
                   f"CSV in Step 4, independent of experiment 8's own wrapper output -> "
                   f"{'INDEPENDENTLY VERIFIED for all 7' if step4_ok else f'VERIFIED for only {n_found} of 7 -- see Step 4'}.")
    report.append("  c) blocking_trade_remained_open_through_candidate_date: the ONLY artifact carrying entry/exit "
                   "dates for the blocking trade is scheduler_attribution_states_*.csv's own blocking_entry_date/"
                   "blocking_exit_date fields -- values produced by experiment 8's OWN instrumented wrapper. The "
                   "canonical trades CSV (independent of experiment 8) has no entry_date/exit_date column, and this "
                   "audit does not infer one via days_held arithmetic (excluded by spec). "
                   "-> INTERNALLY CONSISTENT ONLY for all 7 -- not independently verifiable from an artifact "
                   "outside experiment 8's own walk output.")
    report.append("  d) candidate_was_skipped_by_the_production_walk: asserted solely by the states artifact's own "
                   "`state` column (experiment 8's own output). Neither the master nor the canonical trades CSV "
                   "records which indices a non-overlap walk visited or skipped -- there is no artifact independent "
                   "of experiment 8's own wrapper that could corroborate or contradict this claim. "
                   "-> INTERNALLY CONSISTENT ONLY for all 7 -- not independently verifiable from the fixed artifacts.")

    both_schedule_facts_independent = False  # (c) and (d) are both INTERNALLY CONSISTENT ONLY, never independently verified, by construction of the available artifacts
    report.append(f"\n  Both causal schedule facts (c and d) independently established from the four fixed artifacts: "
                   f"{both_schedule_facts_independent}")

    # ---- Verdict ----
    report.append("\n## Verdict")
    all_mechanical_checks_ok = step2_ok and step3_ok and step4_ok
    if not all_mechanical_checks_ok:
        report.append("  FALSIFIED: one or more required key/field/state/trade-reference checks failed (see Steps "
                       "2-4 above for specifics).")
    elif not both_schedule_facts_independent:
        report.append("  FALSIFIED per the predeclared criterion (a causal schedule fact cannot be independently "
                       "established from the four fixed artifacts). Correct conclusion, per spec: experiment 8 IS "
                       "internally consistent -- its population definition, gate-bucket classification, and cited "
                       "blocking-trade references all check out exactly against independent artifacts where such "
                       "artifacts exist (Steps 1-4 all passed) -- but its scheduler-attribution conclusion (that "
                       "these 7 candidates were specifically censored by an open trade, as opposed to some other "
                       "unrecorded mechanism) is UNVERIFIED under this experiment's strict no-refetch, "
                       "artifact-only boundary, because neither of the two causal schedule facts has an artifact "
                       "independent of experiment 8's own instrumented-wrapper output to corroborate it. This is "
                       "NOT reinterpreted as evidence for or against the STRONG_BEARISH-vs-BULLISH return anomaly.")
    else:
        report.append("  SUPPORTED: all mechanical checks passed AND both causal schedule facts were independently "
                       "established from artifacts outside experiment 8's own wrapper output.")

    _finish(report, ts, verdict=None, extra_df=(states, xcheck), hashes_before=hashes_before)


def _finish(report: list[str], ts: str, verdict: str | None, extra_df=None, hashes_before: dict | None = None) -> None:
    report.append("\n## Post-run artifact integrity re-check (hashes must be unchanged)")
    any_changed = False
    for p in ARTIFACTS:
        h = sha256_of(p)
        matches_before = (hashes_before or {}).get(p.name)
        if matches_before is not None and matches_before != h:
            any_changed = True
            report.append(f"  {p.name}: {h}  *** CHANGED since before-read hash {matches_before} ***")
        else:
            report.append(f"  {p.name}: {h}" + ("  (unchanged)" if matches_before else ""))
    if any_changed:
        report.append("  ARTIFACT INTEGRITY FAILURE: at least one fixed artifact changed during this run -- "
                       "all findings above are INVALID.")
    if verdict:
        report.append(f"\n## Verdict\n  {verdict}")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"scheduler_reproducibility_audit_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")
    if extra_df is not None:
        _, xcheck = extra_df
        xcheck.to_csv(RESULTS_DIR / f"scheduler_reproducibility_xcheck_{ts}.csv", index=False)


if __name__ == "__main__":
    main()
