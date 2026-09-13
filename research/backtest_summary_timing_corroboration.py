"""
RESEARCH ONLY -- experiment 11: independent backtest-summary timing
corroboration audit.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, written after
auditing experiment 10). Experiment 9 established that
`blocking_trade_remained_open_through_candidate_date` could not be
independently verified because the canonical resistance_trades CSV has no
entry_date/exit_date columns. Experiment 10 found that pre-existing
`backtest_results/trades_*.csv` summaries (produced by the PRODUCTION
`backtest.py` module, independent of experiment 8's own instrumented
wrapper) DO carry entry_date/exit_date. This experiment checks whether any
of those summaries independently corroborates the open-trade timing fact
for all seven candidates -- and ONLY that fact; it cannot establish
whether the scheduler actually skipped a candidate index (no summary file
records visited/skipped indices).

STRICT SCOPE (enforced by this script's own import block): read-only
artifact cross-check. No network, no `load_universe`/`data_sources`, no
scoring/indicator/regime function, no trade simulation, no production
file modified, no new backtest run.
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS_DIR = Path(__file__).resolve().parent / "results"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_RESULTS_DIR = PROJECT_ROOT / "backtest_results"

XCHECK_PATH = RESULTS_DIR / "scheduler_reproducibility_xcheck_20260913_193245.csv"
TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"
EXPERIMENT8_REPORT_TS = pd.Timestamp("2026-09-13 19:21:07")

REQUIRED_COLUMNS = ["symbol", "category", "threshold", "signal_date", "entry_date", "exit_date",
                    "entry_price", "exit_price", "exit_reason", "days_held", "strategy_return_pct"]
NUMERIC_TOL = 1e-6  # predeclared, applied to CSV round-trip values


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["INDEPENDENT BACKTEST-SUMMARY TIMING CORROBORATION AUDIT (research only, read-only artifact cross-check)"]

    report.append("\n## Hypothesis and falsifier (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: at least one pre-experiment-8 backtest_results/trades_*.csv summary independently contains "
                   "all 7 cited blocking trades and confirms each exit_date >= its associated candidate date. "
                   "Corroborates open-trade TIMING only -- cannot prove the scheduler skipped a candidate index.")
    report.append("  Falsified unless at least one semantically comparable, pre-experiment-8, non-duplicate summary "
                   "matches all 7 canonical blocking trades exactly AND has exit_date >= candidate_date for every "
                   "one. Missing/multiple/conflicting/incomparable records count as evidence against, not filtered.")
    report.append("  Neither outcome is evidence for or against the STRONG_BEARISH-vs-BULLISH return anomaly, and "
                   "neither supports a production change. This can at most upgrade "
                   "blocking_trade_remained_open_through_candidate_date; candidate_was_skipped_by_the_production_walk "
                   "remains unverified regardless (no summary file records visited/skipped indices).")

    report.append("\n## Scope boundary")
    report.append("  This script imports only hashlib, sys, pathlib, datetime, numpy, pandas -- no production or "
                   "data_sources import, no network call, no new backtest run anywhere in this file.")

    report.append("\n## Fixed inputs")
    xcheck_sha = sha256_of(XCHECK_PATH)
    trades_sha = sha256_of(TRADES_PATH)
    report.append(f"  {XCHECK_PATH.name}: SHA-256={xcheck_sha}")
    report.append(f"  {TRADES_PATH.name}: SHA-256={trades_sha}")
    xcheck = pd.read_csv(XCHECK_PATH, parse_dates=["date", "blocking_signal_date"])
    canonical = pd.read_csv(TRADES_PATH, parse_dates=["signal_date"])
    report.append(f"  Candidate/blocking-trade records: {len(xcheck)} rows (expect 7)")

    # ---- Step 1: verify backtest.py semantics by read-only code inspection (quoted, not executed) ----
    report.append("\n## Step 1: backtest.py semantics, verified by read-only code inspection (quoted, not executed)")
    report.append("  signal_date = str(df.index[i].date()) -- the day the score/signal was computed (same meaning "
                   "as run_ablation's signal_date/master's date). entry_date = str(df.index[i+1].date()) -- next "
                   "trading day's Open (same convention). exit_date = str(df.index[exit_idx].date()) via "
                   "_simulate_trade's target1/stop_loss/time_exit logic -- structurally the SAME simulation rule "
                   "as backtest._simulate_trade, which research/factor_data.py's run_ablation also calls unchanged.")
    report.append("  threshold column = the min_score value passed to that backtest pass (backtest.py lines 176-177); "
                   "filtering threshold==40 selects the pass equivalent to run_ablation's min_score=40.0.")
    report.append("  entry_price/exit_price/strategy_return_pct are ROUND()ed to 2 decimal places at construction "
                   "(backtest.py TradeResult, lines 180-184) -- UNLIKE research/factor_data.py's run_ablation, which "
                   "stores full float precision. This is a VERIFIED, code-level representation difference (not a "
                   "data error), so comparisons below normalize by rounding the canonical (unrounded) value to 2dp "
                   "before applying the predeclared 1e-6 numeric tolerance, rather than comparing raw floats.")
    report.append("  ** MATERIAL NON-OVERLAP SEMANTIC DIFFERENCE, VERIFIED FROM CODE **: backtest.py's _backtest_one "
                   "walk gate is `if idea.score < min_score: skip` (score ONLY, backtest.py line 157) -- it does NOT "
                   "check `signal == 'NO TRADE'`. research/factor_data.py's run_ablation walk gate is "
                   "`if ablated_score < min_score or signal == 'NO TRADE': skip` (score AND signal). This means a "
                   "score>=40 row with signal=='NO TRADE' (known to exist -- see experiment 9/10's gate taxonomy, "
                   "e.g. the STRONG_BEARISH B/C-grade override) would be TAKEN as a trade by backtest.py's walk but "
                   "SKIPPED by run_ablation's walk. The two walks can therefore diverge in which trades are selected "
                   "and which indices get skipped, even at the same symbol/category/threshold=40. This is a KNOWN, "
                   "quantified caveat -- not an unknown one -- so files are NOT marked wholesale incomparable, but "
                   "any match found below does not by itself prove run_ablation's specific walk; it corroborates "
                   "backtest.py's independently-run walk, which used a looser (superset) selection rule.")
    report.append("  Category/symbol labels: both paths use analyzer.CATEGORY_SHORT_TERM/CATEGORY_LONG_TERM string "
                   "constants and symbols.py's raw symbol strings -- confirmed identical convention by inspection.")

    # ---- File discovery: deterministic by filename+schema, before seeing any values ----
    report.append("\n## File discovery (deterministic by filename pattern + required-column schema)")
    candidates = sorted(BACKTEST_RESULTS_DIR.glob("trades_*.csv"))
    report.append(f"  Glob pattern: backtest_results/trades_*.csv -> {len(candidates)} files found")
    file_records = []
    for p in candidates:
        stat = p.stat()
        h = sha256_of(p)
        try:
            head = pd.read_csv(p, nrows=1)
            has_all_cols = all(c in head.columns for c in REQUIRED_COLUMNS)
        except Exception as e:
            has_all_cols = False
            head = None
        mtime = pd.Timestamp.fromtimestamp(stat.st_mtime)
        pre_exp8 = mtime < EXPERIMENT8_REPORT_TS
        rec = {"path": str(p.relative_to(PROJECT_ROOT)), "sha256": h, "size_bytes": stat.st_size,
               "mtime": mtime, "has_required_columns": has_all_cols, "pre_experiment8": pre_exp8}
        file_records.append(rec)
    files_df = pd.DataFrame(file_records)

    dupe_groups = files_df.groupby("sha256")["path"].apply(list)
    dupes = {h: paths for h, paths in dupe_groups.items() if len(paths) > 1}
    for _, r in files_df.iterrows():
        report.append(f"    {r['path']:45s} sha256={r['sha256'][:16]}...  size={r['size_bytes']:>9}  "
                       f"mtime={r['mtime']}  required_cols_present={r['has_required_columns']}  "
                       f"pre_experiment8={r['pre_experiment8']}")
    if dupes:
        report.append(f"  Byte-identical duplicate groups (by SHA-256): {len(dupes)}")
        for h, paths in dupes.items():
            report.append(f"    {h[:16]}...: {paths}")
    else:
        report.append("  No byte-identical duplicate files found.")

    excluded_post = files_df[~files_df["pre_experiment8"]]
    report.append(f"  Files created at/after experiment-8 report timestamp ({EXPERIMENT8_REPORT_TS}): "
                   f"{len(excluded_post)} -- reported, excluded from independent-evidence use: "
                   f"{excluded_post['path'].tolist()}")

    eligible = files_df[files_df["has_required_columns"] & files_df["pre_experiment8"]].copy()
    # First-seen-per-hash: keep every eligible file for reporting, but mark non-first duplicates
    # so they are not double-counted as independent corroboration (still a replication artifact).
    eligible["is_first_of_duplicate_group"] = ~eligible.duplicated(subset="sha256", keep="first")
    report.append(f"\n  Eligible (schema-complete, pre-experiment-8) files: {len(eligible)} of {len(files_df)}")
    report.append(f"  Of these, first-of-duplicate-group (counted as one replication artifact each): "
                   f"{int(eligible['is_first_of_duplicate_group'].sum())}")

    # ---- Canonical blocking-trade identity, re-derived independently from resistance_trades.csv ----
    report.append("\n## Canonical blocking-trade identity (independently re-derived from resistance_trades.csv, not from the xcheck cache)")
    canon_rows = []
    for _, r in xcheck.iterrows():
        match = canonical[(canonical["symbol"] == r["symbol"]) & (canonical["category"] == r["category"]) &
                           (canonical["signal_date"] == r["blocking_signal_date"])]
        if len(match) == 1:
            m = match.iloc[0]
            canon_rows.append({"symbol": r["symbol"], "category": r["category"], "candidate_date": r["date"],
                                "blocking_signal_date": r["blocking_signal_date"],
                                "canon_entry_price": m["entry_price"], "canon_exit_reason": m["exit_reason"],
                                "canon_strategy_return_pct": m["strategy_return_pct"], "canon_days_held": m["days_held"]})
        else:
            canon_rows.append({"symbol": r["symbol"], "category": r["category"], "candidate_date": r["date"],
                                "blocking_signal_date": r["blocking_signal_date"], "canon_entry_price": None,
                                "canon_exit_reason": None, "canon_strategy_return_pct": None, "canon_days_held": None})
            report.append(f"  WARNING: {len(match)} canonical matches for {r['symbol']}/{r['category']}/"
                           f"{r['blocking_signal_date'].date()} (expected exactly 1)")
    canon_df = pd.DataFrame(canon_rows)
    report.append(f"  Re-derived canonical identity for {canon_df['canon_entry_price'].notna().sum()} of {len(canon_df)} candidates.")

    # ---- Step 2/3: match each candidate against each eligible file ----
    report.append("\n## Step 2/3: per-file matching (symbol, category, blocking_signal_date, threshold=40) and field/timing comparison")
    per_file_results = {}
    for _, frow in eligible.iterrows():
        fpath = PROJECT_ROOT / frow["path"]
        df = pd.read_csv(fpath, parse_dates=["signal_date", "entry_date", "exit_date"])
        df40 = df[df["threshold"] == 40.0]
        rows_out = []
        for _, c in canon_df.iterrows():
            m = df40[(df40["symbol"] == c["symbol"]) & (df40["category"] == c["category"]) &
                      (df40["signal_date"] == c["blocking_signal_date"])]
            n_match = len(m)
            row = {"symbol": c["symbol"], "category": c["category"], "candidate_date": c["candidate_date"],
                   "blocking_signal_date": c["blocking_signal_date"], "n_match": n_match}
            if n_match == 1:
                mm = m.iloc[0]
                row["exit_date"] = mm["exit_date"]
                row["entry_price"] = mm["entry_price"]
                row["exit_reason"] = mm["exit_reason"]
                row["strategy_return_pct"] = mm["strategy_return_pct"]
                row["days_held"] = mm["days_held"]
                # Field comparison, normalized for backtest.py's verified round(...,2)
                if pd.notna(c["canon_entry_price"]):
                    ep_ok = abs(round(c["canon_entry_price"], 2) - mm["entry_price"]) <= NUMERIC_TOL
                    ret_ok = abs(round(c["canon_strategy_return_pct"], 2) - mm["strategy_return_pct"]) <= NUMERIC_TOL
                    reason_ok = c["canon_exit_reason"] == mm["exit_reason"]
                    days_ok = c["canon_days_held"] == mm["days_held"]
                    row["fields_match_canonical"] = bool(ep_ok and ret_ok and reason_ok and days_ok)
                    row["field_mismatch_detail"] = "" if row["fields_match_canonical"] else \
                        f"entry_price_ok={ep_ok} return_ok={ret_ok} reason_ok={reason_ok} days_ok={days_ok}"
                else:
                    row["fields_match_canonical"] = None
                    row["field_mismatch_detail"] = "no canonical identity to compare (see warning above)"
                rel = ("missing" if pd.isna(mm["exit_date"]) else
                       ">=" if mm["exit_date"] >= c["candidate_date"] else "<")
                row["exit_vs_candidate"] = rel
            else:
                row["exit_date"] = None
                row["fields_match_canonical"] = False
                row["field_mismatch_detail"] = f"{n_match} matches (expected exactly 1)"
                row["exit_vs_candidate"] = "missing" if n_match == 0 else "multiple"
            rows_out.append(row)
        per_file_results[frow["path"]] = pd.DataFrame(rows_out)
        all7_match = all(r["n_match"] == 1 and r["fields_match_canonical"] for r in rows_out)
        all7_timing_ok = all(r["exit_vs_candidate"] == ">=" for r in rows_out)
        report.append(f"\n  --- {frow['path']} (dup_group_first={frow['is_first_of_duplicate_group']}) ---")
        report.append(f"    All 7 matched exactly with fields agreeing: {all7_match}  |  All 7 exit_date>=candidate_date: {all7_timing_ok}")
        for r in rows_out:
            report.append(f"      {r['symbol']:12s} {r['category']:20s} cand={r['candidate_date'].date()}  "
                           f"blocking_sig={r['blocking_signal_date'].date()}  n_match={r['n_match']}  "
                           f"exit_date={r['exit_date'].date() if pd.notna(r.get('exit_date')) else 'N/A'}  "
                           f"vs_candidate={r['exit_vs_candidate']}  fields_match={r['fields_match_canonical']} "
                           f"{r['field_mismatch_detail']}")

    # ---- Step 4: agreement across comparable files, duplicate-aware ----
    report.append("\n## Step 4: agreement across all comparable pre-experiment-8 files (duplicates flagged, not double-counted)")
    unique_result_files = eligible[eligible["is_first_of_duplicate_group"]]["path"].tolist()
    fully_qualifying_files = []
    for path in unique_result_files:
        r = per_file_results[path]
        if (r["n_match"] == 1).all() and r["fields_match_canonical"].fillna(False).all() and (r["exit_vs_candidate"] == ">=").all():
            fully_qualifying_files.append(path)
    report.append(f"  Unique (non-duplicate) eligible files: {len(unique_result_files)}")
    report.append(f"  Of these, fully qualifying (all 7 matched, fields agree, all exit_date>=candidate_date): "
                   f"{len(fully_qualifying_files)}: {fully_qualifying_files}")

    # ---- Complete seven-row summary table (consensus across qualifying files where possible) ----
    report.append("\n## Complete seven-row summary table")
    summary_rows = []
    for _, c in canon_df.iterrows():
        key = (c["symbol"], c["category"], c["blocking_signal_date"])
        relations = set()
        n_match_values = set()
        for path in unique_result_files:
            r = per_file_results[path]
            rr = r[(r["symbol"] == c["symbol"]) & (r["category"] == c["category"]) & (r["blocking_signal_date"] == c["blocking_signal_date"])]
            if len(rr):
                relations.add(rr.iloc[0]["exit_vs_candidate"])
                n_match_values.add(int(rr.iloc[0]["n_match"]))
        summary_rows.append({"symbol": c["symbol"], "category": c["category"], "candidate_date": c["candidate_date"].date(),
                              "blocking_signal_date": c["blocking_signal_date"].date(),
                              "exit_vs_candidate_across_unique_files": sorted(relations),
                              "n_match_across_unique_files": sorted(n_match_values)})
    summary_df = pd.DataFrame(summary_rows)
    for _, r in summary_df.iterrows():
        report.append(f"  {r['symbol']:12s} {r['category']:20s} cand={r['candidate_date']}  "
                       f"blocking_sig={r['blocking_signal_date']}  exit_vs_candidate={r['exit_vs_candidate_across_unique_files']}  "
                       f"n_match={r['n_match_across_unique_files']}")
    n_consistent_ge = sum(1 for _, r in summary_df.iterrows() if r["exit_vs_candidate_across_unique_files"] == [">="])
    report.append(f"  Candidates with consistent exit_date>=candidate_date across every unique comparable file: {n_consistent_ge} of 7")

    # ---- Step 5: evidence-closure impact ----
    report.append("\n## Step 5: evidence-closure impact")
    report.append("  This experiment can at most upgrade claim (c) blocking_trade_remained_open_through_candidate_date.")
    report.append("  Claim (d) candidate_was_skipped_by_the_production_walk remains UNVERIFIED regardless of this "
                   "experiment's outcome -- no backtest_results summary records which indices a walk visited or "
                   "skipped, only which trades it ultimately selected.")

    # ---- Verdict ----
    report.append("\n## Verdict")
    if fully_qualifying_files:
        report.append(f"  SUPPORTED (with the semantic caveat above quoted, not waived): {fully_qualifying_files[0]} "
                       f"(and any others listed in Step 4) independently contains all 7 cited blocking trades with "
                       f"matching entry_price/exit_reason/strategy_return_pct/days_held (normalized for backtest.py's "
                       f"verified round(...,2)) and exit_date >= candidate_date for every one. This corroborates "
                       f"open-trade TIMING only. The experiment-9 finding that walk-skipping "
                       f"(candidate_was_skipped_by_the_production_walk) remains unverified is UNCHANGED. Not evidence "
                       f"for or against the STRONG_BEARISH-vs-BULLISH return anomaly; no production change implied.")
    else:
        report.append("  FALSIFIED: no unique, pre-experiment-8, schema-complete summary matched all 7 canonical "
                       "blocking trades with agreeing fields and exit_date>=candidate_date for every one (see Step 4 "
                       "for which candidates/files fell short). Both blocking_trade_remained_open_through_"
                       "candidate_date and candidate_was_skipped_by_the_production_walk remain UNVERIFIED under the "
                       "no-refetch boundary, consistent with experiment 9. Not evidence for or against the "
                       "STRONG_BEARISH-vs-BULLISH return anomaly; no production change implied.")

    report.append("\n## Post-run artifact integrity re-check")
    report.append(f"  {XCHECK_PATH.name}: {'unchanged' if sha256_of(XCHECK_PATH) == xcheck_sha else 'CHANGED -- INVALID RUN'}")
    report.append(f"  {TRADES_PATH.name}: {'unchanged' if sha256_of(TRADES_PATH) == trades_sha else 'CHANGED -- INVALID RUN'}")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"backtest_summary_timing_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    files_df.assign(mtime=files_df["mtime"].astype(str)).to_csv(RESULTS_DIR / f"backtest_summary_timing_files_{ts}.csv", index=False)
    summary_df.assign(
        exit_vs_candidate_across_unique_files=summary_df["exit_vs_candidate_across_unique_files"].astype(str),
        n_match_across_unique_files=summary_df["n_match_across_unique_files"].astype(str),
    ).to_csv(RESULTS_DIR / f"backtest_summary_timing_sevenrow_{ts}.csv", index=False)
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
