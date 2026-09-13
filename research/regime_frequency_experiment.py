"""
RESEARCH ONLY -- STRONG_BEARISH regime-frequency / opportunity-funnel audit.

Spec source: research/NEXT_EXPERIMENT.md (Codex-approved, written after
auditing experiment 6's reliability report).

Question: are the zero Recent-split STRONG_BEARISH trades (seen in
experiments 5 and 6) explained by zero point-in-time STRONG_BEARISH NIFTY
regime-dates in that window, or by a downstream gate (score threshold,
production signal classification, or the non-overlap trade simulation)?
This is a SAMPLE-COMPOSITION audit only -- it does not test, explain, or
validate the historical return gap (experiments 1-6), and makes no
production recommendation regardless of outcome.

Fixed, unmodified inputs (SHA-256 recorded in the report):
  research/results/resistance_master_20260913_164146.csv   (experiment 5)
  research/results/resistance_trades_20260913_164146.csv   (experiment 5)
Neither is refetched, regenerated, deduplicated beyond what's specified, or
altered. Both were produced by research/factor_data.py's
build_master_dataset()/run_ablation(), which call the UNCHANGED production
functions market_regime.classify_regime_at, analyzer.score_short_term/
score_long_term, analyzer._grade_from_score, analyzer._classify_signal,
and backtest._simulate_trade -- verified here by direct code inspection
(quoted in the report), not re-verified by re-running.

Regime is a NIFTY-index-level (not stock-level) point-in-time label: see
market_regime.classify_regime_at, which reads RegimeBundle series (built
once over full NIFTY history) via .iloc[idx] -- point-in-time safe by the
same Bundle pattern as analyzer.IndicatorBundle. Because of this, a given
calendar date must carry exactly ONE regime label across every symbol and
category in the master dataset; that invariant is checked here, not
assumed (see verify_regime_date_uniqueness).
"""
from __future__ import annotations

import hashlib
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from research.rr_quality_experiment import RESULTS_DIR

MASTER_PATH = RESULTS_DIR / "resistance_master_20260913_164146.csv"
TRADES_PATH = RESULTS_DIR / "resistance_trades_20260913_164146.csv"

MIN_SCORE = 40.0  # the exact threshold experiment 5's run_ablation used to build the canonical trade file
BLOCK_LEN = 5
BOOT_SEED = 20260913
BOOT_DRAWS = 20_000

TOP_SYMBOLS = {  # reused verbatim from every prior VYOM experiment, not re-derived
    "BULLISH": ["LT", "BAJFINANCE", "JSWSTEEL"],
    "STRONG_BEARISH": ["WIPRO", "HINDALCO", "TATASTEEL"],
}
CATEGORIES = ["Short-Term (Swing)", "Long-Term"]
SPLITS = ["Early", "Middle", "Recent"]

SPLIT_EARLY_END = pd.Timestamp("2025-01-31")
SPLIT_MIDDLE_END = pd.Timestamp("2025-10-17")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def assign_time_split(dates: pd.Series) -> pd.Series:
    return np.select(
        [dates <= SPLIT_EARLY_END, dates <= SPLIT_MIDDLE_END],
        ["Early", "Middle"],
        default="Recent",
    )


def safe_rate(num: float, denom: float) -> str:
    if denom == 0:
        return "N/A"
    return f"{num / denom * 100:.1f}%"


def load_master() -> pd.DataFrame:
    df = pd.read_csv(MASTER_PATH, parse_dates=["date"])
    df["time_split"] = assign_time_split(df["date"])
    return df


def load_trades() -> pd.DataFrame:
    df = pd.read_csv(TRADES_PATH, parse_dates=["signal_date"])
    df["time_split"] = assign_time_split(df["signal_date"])
    return df


def verify_regime_date_uniqueness(master: pd.DataFrame, report: list[str]) -> None:
    report.append("\n## Robustness: regime label uniqueness per calendar date")
    per_date = master.groupby("date")["regime"].nunique()
    bad_dates = per_date[per_date > 1]
    if len(bad_dates) == 0:
        report.append(f"  OK -- all {len(per_date)} distinct master dates carry exactly one regime label "
                       f"(consistent with regime being a NIFTY-index-level, not stock-level, point-in-time label).")
    else:
        report.append(f"  DATA-INTEGRITY EXCEPTION: {len(bad_dates)} dates carry more than one regime label "
                       f"(reported as a finding, not filtered out): {bad_dates.to_dict()}")


def distinct_regime_dates_table(master: pd.DataFrame, report: list[str]) -> dict:
    report.append("\n## Section 1: Distinct point-in-time regime dates per split (master-dataset denominator)")
    date_regime = master.drop_duplicates(subset="date")[["date", "time_split", "regime"]]
    shares = {}
    for split in SPLITS:
        part = date_regime[date_regime["time_split"] == split]
        total_dates = len(part)
        counts = part["regime"].value_counts()
        report.append(f"\n  --- {split} (total distinct dates={total_dates}) ---")
        for label, n in counts.items():
            report.append(f"    {label}: {n} dates ({safe_rate(n, total_dates)} of split dates)")
        for label in ["BULLISH", "STRONG_BEARISH"]:
            n = int(counts.get(label, 0))
            report.append(f"    >> {label} explicit: {n} dates, share={safe_rate(n, total_dates)}")
            shares[(split, label)] = (n, total_dates)
    return shares


def funnel_table(master: pd.DataFrame, trades: pd.DataFrame, report: list[str],
                  exclude_symbols: bool = False) -> None:
    title = "Section 2: Four-stage funnel (time_split x regime x category)" if not exclude_symbols else \
            "Section 2b (robustness): same funnel excluding established top-3 symbols per regime (symbol-level stages only; date denominator unchanged)"
    report.append(f"\n## {title}")
    date_regime = master.drop_duplicates(subset="date")[["date", "time_split", "regime"]]

    m, t = master, trades
    if exclude_symbols:
        m = master[~((master["regime"] == "BULLISH") & (master["symbol"].isin(TOP_SYMBOLS["BULLISH"]))) &
                   ~((master["regime"] == "STRONG_BEARISH") & (master["symbol"].isin(TOP_SYMBOLS["STRONG_BEARISH"])))]
        t = trades[~((trades["regime"] == "BULLISH") & (trades["symbol"].isin(TOP_SYMBOLS["BULLISH"]))) &
                   ~((trades["regime"] == "STRONG_BEARISH") & (trades["symbol"].isin(TOP_SYMBOLS["STRONG_BEARISH"])))]

    for split in SPLITS:
        report.append(f"\n  --- {split} ---")
        for regime in ["BULLISH", "STRONG_BEARISH"]:
            stage_a = int(((date_regime["time_split"] == split) & (date_regime["regime"] == regime)).sum())
            report.append(f"    {regime}: stage(a) distinct regime dates = {stage_a}  [category-invariant, from date-level dedup]")
            if stage_a == 0:
                report.append(f"      -> zero regime dates this split: stages (b)/(c)/(d) are all necessarily 0/N-A, not evaluated further.")
            for category in CATEGORIES:
                mb = m[(m["time_split"] == split) & (m["regime"] == regime) & (m["category"] == category)]
                stage_b = len(mb)
                stage_c = int((mb["score"] >= MIN_SCORE).sum())
                td = t[(t["time_split"] == split) & (t["regime"] == regime) & (t["category"] == category)]
                stage_d = len(td)
                report.append(f"      {category}: (b) obs={stage_b}  (c) score>=40={stage_c} [rate b->c: {safe_rate(stage_c, stage_b)}]  "
                               f"(d) trades={stage_d} [rate c->d: {safe_rate(stage_d, stage_c)}]")


def recent_strong_bearish_trace(master: pd.DataFrame, trades: pd.DataFrame, report: list[str]) -> None:
    report.append("\n## Section 3: Exhaustive trace of every Recent-split STRONG_BEARISH master row (fixed, not a selected sample)")
    rows = master[(master["time_split"] == "Recent") & (master["regime"] == "STRONG_BEARISH")]
    if rows.empty:
        report.append("  There are ZERO Recent-split STRONG_BEARISH master rows across the entire 51-symbol/2-category "
                       "universe -- stated explicitly, per spec, rather than left implicit.")
        return
    trades_keys = set(zip(trades["symbol"], trades["category"], trades["signal_date"]))
    for _, r in rows.sort_values(["date", "symbol", "category"]).iterrows():
        in_trades = (r["symbol"], r["category"], r["date"]) in trades_keys
        report.append(f"  {r['symbol']:12s} {r['date'].date()} {r['category']:20s} score={r['score']:.1f} "
                       f"grade={r['grade']}  signal={r['signal']}  in_trade_file={in_trades}")


def reconcile_dates(master: pd.DataFrame, trades: pd.DataFrame, report: list[str]) -> None:
    report.append("\n## Section 4 (robustness): trade-dataset date/regime reconciliation against master "
                   "(trade dates are NOT used as the regime denominator -- they are far sparser by construction, "
                   "since only score>=40-and-signal!=NO-TRADE rows reach the trade file)")
    master_date_regime = master.drop_duplicates(subset="date").set_index("date")["regime"]
    trade_dates = trades.drop_duplicates(subset=["signal_date", "regime"])
    mismatches = []
    for _, r in trade_dates.iterrows():
        master_regime = master_date_regime.get(r["signal_date"])
        if master_regime is not None and master_regime != r["regime"]:
            mismatches.append((r["signal_date"], r["regime"], master_regime))
    report.append(f"  Distinct (signal_date) values present in trade file: {trades['signal_date'].nunique()} "
                   f"(vs {master['date'].nunique()} distinct dates in master -- expected to be much smaller)")
    if mismatches:
        report.append(f"  RECONCILIATION EXCEPTION: {len(mismatches)} trade-file dates disagree with master's regime label for the same date: {mismatches}")
    else:
        report.append("  OK -- every date present in the trade file has a regime label matching the master dataset for that same date.")


def month_by_month_table(master: pd.DataFrame, trades: pd.DataFrame, report: list[str]) -> None:
    report.append("\n## Section 5 (robustness): month-by-month regime dates and final trades, all three splits "
                   "(cells below 20 observations flagged as descriptive/undersized)")
    date_regime = master.drop_duplicates(subset="date")[["date", "regime"]].copy()
    date_regime["month"] = date_regime["date"].dt.to_period("M").astype(str)
    trades_m = trades.copy()
    trades_m["month"] = trades_m["signal_date"].dt.to_period("M").astype(str)

    months = sorted(date_regime["month"].unique())
    for regime in ["BULLISH", "STRONG_BEARISH"]:
        report.append(f"\n  --- {regime} ---")
        for month in months:
            n_dates = int(((date_regime["month"] == month) & (date_regime["regime"] == regime)).sum())
            n_trades = int(((trades_m["month"] == month) & (trades_m["regime"] == regime)).sum())
            flag = "  [UNDERSIZED n<20]" if max(n_dates, n_trades) < 20 else ""
            if n_dates == 0 and n_trades == 0:
                continue
            report.append(f"    {month}: regime_dates={n_dates}  final_trades={n_trades}{flag}")


def block_bootstrap(master: pd.DataFrame, report: list[str]) -> None:
    report.append(f"\n## Section 6: Descriptive 5-trading-day moving-block bootstrap (seed={BOOT_SEED}, draws={BOOT_DRAWS}) "
                   f"-- STRONG_BEARISH regime-date share and score>=40-conditional-on-STRONG_BEARISH rate, per split. "
                   f"Dependent/descriptive estimates only -- NOT independent-trade inference.")
    rng = np.random.default_rng(BOOT_SEED)

    for split in SPLITS:
        date_level = master[master["time_split"] == split].drop_duplicates(subset="date").sort_values("date")
        dates_sorted = date_level["date"].to_numpy()
        regime_arr = date_level["regime"].to_numpy()
        n = len(dates_sorted)
        report.append(f"\n  --- {split} (n dates={n}) ---")
        if n < BLOCK_LEN:
            report.append(f"    Insufficient dates (<{BLOCK_LEN}) for a {BLOCK_LEN}-day block bootstrap -- skipped, not forced.")
            continue

        obs_by_date = master[master["time_split"] == split].groupby("date").agg(
            obs=("score", "size"), qualified=("score", lambda s: (s >= MIN_SCORE).sum()))
        obs_count_arr = obs_by_date.reindex(dates_sorted)["obs"].to_numpy()
        qualified_count_arr = obs_by_date.reindex(dates_sorted)["qualified"].to_numpy()

        num_blocks = -(-n // BLOCK_LEN)  # ceil
        max_start = n - BLOCK_LEN
        starts = rng.integers(0, max_start + 1, size=(BOOT_DRAWS, num_blocks))
        offsets = np.arange(BLOCK_LEN)
        positions = (starts[:, :, None] + offsets[None, None, :]).reshape(BOOT_DRAWS, num_blocks * BLOCK_LEN)[:, :n]

        is_bear = (regime_arr[positions] == "STRONG_BEARISH")
        n_bear_dates = is_bear.sum(axis=1)
        regime_share = n_bear_dates / n

        obs_resampled = obs_count_arr[positions]
        qual_resampled = qualified_count_arr[positions]
        bear_obs_sum = (obs_resampled * is_bear).sum(axis=1)
        bear_qual_sum = (qual_resampled * is_bear).sum(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            score_qual_rate = np.where(bear_obs_sum > 0, bear_qual_sum / bear_obs_sum * 100, np.nan)

        share_ci = np.percentile(regime_share, [2.5, 97.5])
        n_valid = np.sum(~np.isnan(score_qual_rate))
        report.append(f"    STRONG_BEARISH regime-date share: observed={ (regime_arr=='STRONG_BEARISH').mean()*100:.1f}%  "
                       f"95% CI=[{share_ci[0]*100:.1f}%, {share_ci[1]*100:.1f}%]")
        if n_valid == 0:
            report.append("    Score>=40-conditional-on-STRONG_BEARISH rate: N/A -- zero STRONG_BEARISH dates in every resample "
                           "(consistent with an empty or near-empty STRONG_BEARISH population this split).")
        else:
            qual_ci = np.nanpercentile(score_qual_rate, [2.5, 97.5])
            observed_bear_obs = obs_count_arr[regime_arr == "STRONG_BEARISH"].sum()
            observed_bear_qual = qualified_count_arr[regime_arr == "STRONG_BEARISH"].sum()
            observed_rate = (observed_bear_qual / observed_bear_obs * 100) if observed_bear_obs > 0 else float("nan")
            report.append(f"    Score>=40-conditional-on-STRONG_BEARISH rate: observed={observed_rate:.1f}%  "
                           f"95% CI=[{qual_ci[0]:.1f}%, {qual_ci[1]:.1f}%]  (valid draws={n_valid}/{BOOT_DRAWS})")


def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = ["STRONG_BEARISH REGIME-FREQUENCY / OPPORTUNITY-FUNNEL AUDIT (research only, no production changes)"]

    report.append("\n## Hypothesis and falsifier (fixed, from research/NEXT_EXPERIMENT.md)")
    report.append("  H: zero Recent-split STRONG_BEARISH trades are fully accounted for by zero (or near-zero) point-in-time "
                   "STRONG_BEARISH NIFTY regime-dates in that window -- not by the score/signal/non-overlap gates. "
                   "Sample-composition audit only; does not explain or validate the historical return gap.")
    report.append("  Falsified if Recent contains >=1 point-in-time STRONG_BEARISH regime date in the master data -- "
                   "then every missing trade must be traced to a specific downstream gate. If Recent has zero such "
                   "dates, the hypothesis is supported only as an explanation of zero Recent OPPORTUNITIES, not of "
                   "the historical return anomaly.")

    report.append("\n## Provenance and fixed inputs")
    report.append(f"  Master file:  {MASTER_PATH.relative_to(MASTER_PATH.parents[2])}  SHA-256={sha256_of(MASTER_PATH)}")
    report.append(f"  Trades file:  {TRADES_PATH.relative_to(TRADES_PATH.parents[2])}  SHA-256={sha256_of(TRADES_PATH)}")
    report.append(f"  Command: python -m research.regime_frequency_experiment")
    report.append(f"  Runtime: Python {sys.version.split()[0]}  pandas {pd.__version__}  numpy {np.__version__}")
    report.append(f"  Fixed production threshold reused (not a new threshold): score >= {MIN_SCORE} "
                   f"(the exact min_score experiment 5's run_ablation used to build resistance_trades).")
    report.append("  Production-field / point-in-time verification (quoted from direct code inspection):")
    report.append("    - market_regime.RegimeBundle is built once over full NIFTY history (compute_regime_bundle); "
                   "classify_regime_at reads bundle.sma_fast/sma_slow/rsi/atr_pct/atr_percentile via .iloc[idx] -- "
                   "point-in-time safe by the same Bundle pattern as analyzer.IndicatorBundle.")
    report.append("    - _classify(): STRONG_BEARISH requires price below BOTH SMA20/SMA50 AND NIFTY RSI<=45 "
                   "(market_regime.py lines 71-73) -- a genuinely rare, extreme-oversold-market condition by "
                   "construction, checked AFTER the HIGH_VOLATILITY gate (ATR-percentile >= threshold) takes priority.")

    report.append("    - analyzer._grade_from_score: grade is None below score 60 (config.GRADE_THRESHOLDS: "
                   "C=60, B=70, A=80, A+=90) -- so the funnel's score>=40 stage (c) is DELIBERATELY looser than "
                   "the production grade floor; rows scoring 40-59 can never receive a grade and are therefore "
                   "always classified NO TRADE by _classify_signal, regardless of regime.")
    report.append("    - analyzer._classify_signal (lines 323-336): grade is None -> NO TRADE; rr_ratio < "
                   "RR_MIN_ACCEPTABLE (1.5) -> WATCH; chase_flag -> WATCH; **regime_label=='STRONG_BEARISH' AND "
                   "grade in ('B','C') -> NO TRADE** (an existing, deliberate production rule that suppresses "
                   "merely-decent setups specifically in a STRONG_BEARISH tape) -- this is a distinct, real "
                   "candidate explanation for STRONG_BEARISH funnel attrition that this audit can directly "
                   "observe in the trace (Section 3), quoted here rather than assumed.")
    report.append("    - backtest._simulate_trade (via research.factor_data.run_ablation, called unchanged) "
                   "provides the non-overlapping target1/stop-loss trade simulation for funnel stage (d); "
                   "run_ablation's own gate is `score < min_score or signal == 'NO TRADE'` -> skipped.")
    report.append("  No production function was reimplemented; all of the above is quoted from analyzer.py, "
                   "market_regime.py, config.py, backtest.py, and research/factor_data.py as they exist on disk.")

    master = load_master()
    trades = load_trades()
    report.append(f"\n  Master rows: {len(master)}  (distinct dates={master['date'].nunique()}, "
                   f"date range {master['date'].min().date()} to {master['date'].max().date()})")
    report.append(f"  Trades rows: {len(trades)}  (distinct signal_dates={trades['signal_date'].nunique()}, "
                   f"date range {trades['signal_date'].min().date()} to {trades['signal_date'].max().date()})")

    report.append("\n## Time-split convention (fixed, identical to experiments 5 and 6 -- not re-derived)")
    report.append(f"  Early:  date <= {SPLIT_EARLY_END.date()}")
    report.append(f"  Middle: {SPLIT_EARLY_END.date()} < date <= {SPLIT_MIDDLE_END.date()}")
    report.append(f"  Recent: date > {SPLIT_MIDDLE_END.date()}")

    verify_regime_date_uniqueness(master, report)
    distinct_regime_dates_table(master, report)
    funnel_table(master, trades, report, exclude_symbols=False)
    recent_strong_bearish_trace(master, trades, report)
    reconcile_dates(master, trades, report)
    funnel_table(master, trades, report, exclude_symbols=True)
    month_by_month_table(master, trades, report)
    block_bootstrap(master, report)

    report.append("\n## Conclusion (limited to regime-frequency evidence -- no causal or production claim)")
    recent_bear_dates = int(((master["time_split"] == "Recent") & (master["regime"] == "STRONG_BEARISH")).drop_duplicates().sum())
    recent_bear_date_count = master[(master["time_split"] == "Recent") & (master["regime"] == "STRONG_BEARISH")]["date"].nunique()
    if recent_bear_date_count == 0:
        report.append("  Recent split contains ZERO point-in-time STRONG_BEARISH regime dates. The hypothesis is "
                       "SUPPORTED as an explanation of zero Recent STRONG_BEARISH *opportunities* -- there was "
                       "nothing for the score/signal/non-overlap gates to act on. This is a regime-frequency finding "
                       "only: it does not explain, validate, or quantify the STRONG_BEARISH-vs-BULLISH return "
                       "anomaly documented in experiments 1-6, and recommends no production change.")
    else:
        report.append(f"  Recent split contains {recent_bear_date_count} point-in-time STRONG_BEARISH regime date(s) -- "
                       "the hypothesis is FALSIFIED. See Section 3's exhaustive trace and the quoted production-gate "
                       "verification above for which specific downstream gate(s) account for the missing trades.")

    full_report = "\n".join(str(x) for x in report)
    report_path = RESULTS_DIR / f"regime_frequency_report_{ts}.txt"
    report_path.write_text(full_report, encoding="utf-8")
    print(full_report)
    print(f"\n\nSaved: {report_path}")


if __name__ == "__main__":
    main()
