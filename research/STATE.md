# VYOM Research — STATE

Single source of truth for the research program. Updated by Claude after
every completed experiment. Codex reads this (and the latest report) to
audit and write the next experiment to `NEXT_EXPERIMENT.md`. See root
`CLAUDE.md` / `AGENTS.md` for the rules both assistants follow here.

**Anomaly under investigation:** the production backtest population
(threshold=40, non-overlapping trades, 51-symbol NIFTY universe, 3-year
history, both Short-Term and Long-Term categories combined) shows
STRONG_BEARISH-regime signals meaningfully outperforming BULLISH-regime
signals:

| Regime | N | Win rate | Expectancy | Profit Factor |
|---|---|---|---|---|
| BULLISH | 324 | 50.3% | -0.333% | 0.83 |
| STRONG_BEARISH | 48 | 68.8% | +0.818% | 1.45 |

Every experiment below is testing one candidate explanation for this gap.
**No candidate has explained it yet.**

## Status: awaiting Codex audit

Last completed experiment: **Resistance / "room-to-run" distance**
(2026-09-13). Codex has not yet audited it or written
`NEXT_EXPERIMENT.md`. Next action is the human asking Codex to perform the
handoff per the short prompt in the VYOM handoff README.

## Experiment log (chronological)

### 1. Factor-level audit — 2026-09-13
- **Report:** `research/results/factor_audit_report_20260913_160607.txt`
- **Dataset:** `research/results/master_dataset_20260913_160607.csv` (48,552 rows)
- **Question:** does the compound production score contain genuine
  predictive power (correlation, quantile bucketing, ablation, redundancy,
  cross-sectional, time-stability)?
- **Verdict:** mixed — most factors weak/noisy; Risk/Reward Quality
  identified as the one clean positive factor; surfaced the
  STRONG_BEARISH > BULLISH regime anomaly as an open question.
- **Verification:** `git status` → only `?? research/`; production files
  unchanged; all scoring done via unmodified `analyzer.score_short_term` /
  `score_long_term`.

### 2. RR-Quality independence experiment — 2026-09-13
- **Report:** `research/results/rr_quality_experiment_20260913_161645.txt`
- **Question:** is Risk/Reward Quality independent or conditional?
  Includes an anti-trend test (HIGH RR + LOW Momentum vs HIGH RR + HIGH
  Momentum).
- **Verdict:** RR-Quality is a genuine conditional predictor but does
  **not** explain the regime anomaly (inverts within STRONG_BEARISH
  specifically). Median-split degenerated for Long-Term (>75% of values
  at the same ceiling) — switched to a uniformly-applied top-quartile
  split and reported the degeneracy itself rather than keep tuning.
- **Verification:** production files unchanged; reused already-saved
  master dataset from experiment 1 (no re-fetch).

### 3. Volatility / ATR-regime experiment — 2026-09-13
- **Report:** `research/results/volatility_regime_report_20260913_162448.txt`
- **Dataset:** `research/results/volatility_trades_20260913_162448.csv` (2,083 rows)
- **Question:** does ATR/volatility explain the anomaly, given the
  fixed-ATR-multiple target/stop construction?
- **Verdict:** **Rejected.** Anomaly persists almost unchanged within
  matched LOW-ATR buckets (the only volatility bucket with adequate data);
  no HIGH-volatility population exists to test further. Symbol-exclusion
  and sector checks both consistent with prior findings.
- **Verification:** production files unchanged; ATR buckets used the
  exact fixed thresholds `analyzer._volatility_profile` already uses in
  production (≤3% / 3-5% / >5%), not a data-dependent quantile.

### 4. Support-proximity experiment — 2026-09-13
- **Report:** `research/results/support_proximity_report_20260913_163205.txt`
- **Datasets:** `research/results/support_trades_20260913_163205.csv` (2,083 rows),
  `research/results/support_master_20260913_163205.csv` (48,552 rows)
- **Question:** does proximity to production `support20`/`resistance20`
  explain the anomaly (mean-reversion-off-support hypothesis)?
- **Verdict:** **Rejected.** Support-distance is a real general predictor
  (closest quintile best at every horizon) but does not explain the
  anomaly: persists/strengthens in 2 of 3 buckets, reverses in the
  farthest; decisive falsification in the Middle time-split (near-equal
  support-distances between regimes, largest performance gap of the three
  periods). Resistance-distance found to correlate more consistently with
  forward returns than support-distance — motivated experiment 5.
- **Verification:** verified `support20`/`resistance20` definitions
  directly from `analyzer.py` (lines 155-156) before use; production
  files unchanged; extended `research/factor_data.py` additively only
  (new columns, nothing removed/renamed).

### 5. Resistance / "room-to-run" experiment — 2026-09-13
- **Report:** `research/results/resistance_room_report_20260913_164146.txt`
- **Datasets:** `research/results/resistance_trades_20260913_164146.csv` (2,083 rows),
  `research/results/resistance_master_20260913_164146.csv` (48,552 rows)
- **Question:** does "room to run" toward `resistance20` or `high52w`
  explain the anomaly?
- **Verdict:** **Rejected.** Resistance-distance is a real but weak
  general predictor (correlation 0.02→0.08, strengthening with horizon)
  and geometry is comparable across regimes at matched distance (directional-
  prediction effect confirmed, not geometric advantage) — but the
  regime×bucket interaction is non-monotonic and **reverses** in the
  farthest-room bucket; `resistance20` and `high52w` disagree in direction
  at the regime level; 52-week-high distance adds no explanatory power
  beyond `resistance20` (near-identical correlations, 25.9% of days the
  two fields coincide); and the same Middle-period falsification pattern
  as experiment 4 recurs (near-equal distance gap, largest performance
  gap). RR-Quality and Momentum control cells for STRONG_BEARISH were
  mostly too small (n=1–14) to draw conclusions — explicitly flagged as
  untestable rather than forced.
- **Report's own recommended next experiment:** bootstrap/permutation
  test of the STRONG_BEARISH (n=48) vs BULLISH (n=324) expectancy/win-rate
  gap for statistical reliability, since four candidate mechanical
  explanations (volatility, support-distance, resistance-distance,
  52-week-high-distance) have now all been rejected — the open question
  shifting from "what explains it" to "is n=48 even distinguishable from
  noise."
- **Verification:** verified `resistance20`/`high52w` formulas directly
  from `analyzer.py` (lines 130, 155-157, 459-502) before use, including
  confirming ST and LT use an identical definition; `git status` →
  `?? research/` only, all 16 production files unchanged; extended
  `research/factor_data.py` additively (added `high52w` column to
  `build_master_dataset` and `run_ablation`, nothing removed/renamed);
  new file `research/resistance_room_experiment.py` added, syntax-checked
  before the full run.

## Cumulative robustness findings (hold across every experiment above)

- **Symbol concentration:** ruled out. Excluding the same top-3 symbols
  per regime (`BULLISH: LT, BAJFINANCE, JSWSTEEL`; `STRONG_BEARISH: WIPRO,
  HINDALCO, TATASTEEL`) leaves BULLISH negative and STRONG_BEARISH
  positive-and-stronger every time.
- **Sector concentration:** ruled out. Both regimes spread across 7-10
  sectors in every experiment, no dominant sector.
- **Recent time period:** STRONG_BEARISH produced zero trades in the most
  recent third of the 3-year window in the last two experiments — flagged
  but not yet investigated as a possible regime-frequency artifact.

## Production code status

Unchanged since commit `ac2802a` ("Fix 4 audit-verified weaknesses...").
Every experiment above confirmed via `git status` immediately after
running. All 16 production files and `tests/test_engine.py` (34 tests)
untouched throughout the entire VYOM research program to date.
