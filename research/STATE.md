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

Experiments 1-5 each tested one candidate explanation for this gap — **no
candidate has explained it.** Experiment 6 stepped back to ask a different
question: is the gap itself statistically reliable, independent of any
explanation? Result: only 2 of the predeclared 3 reliability conditions
were met — **insufficient evidence the gap is distinguishable from noise**
under that precommitted test (see experiment 6 below).

## Status: awaiting Codex audit

Last completed experiment: **STRONG_BEARISH regime-frequency /
opportunity-funnel audit** (2026-09-13, Codex-specified via
`research/NEXT_EXPERIMENT.md`). Codex has not yet audited it or written a
new `NEXT_EXPERIMENT.md`. Next action is the human asking Codex to perform
the handoff per the short prompt in the VYOM handoff README.

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

### 6. Statistical reliability experiment — 2026-09-13
- **Spec:** written by Codex in `research/NEXT_EXPERIMENT.md` after
  auditing experiment 5; run exactly as specified, no substitutions.
- **Report:** `research/results/reliability_experiment_report_20260913_171735.txt`
- **Fixed input:** `research/results/resistance_trades_20260913_164146.csv`
  (SHA-256 `05b11415a0979d224048e6e993d24c9a064f25a7b622e13a60ab5bbfe9026369`),
  unmodified — 2,083 total rows, 372 after filtering to
  `regime in {BULLISH, STRONG_BEARISH}` (BULLISH=324, STRONG_BEARISH=48).
- **Datasets:** `research/results/reliability_null_draws_primary_20260913_171735.csv`
  (100,000 rows), `research/results/reliability_bootstrap_draws_primary_20260913_171735.csv`
  (20,000 rows), plus the same two for the symbol-excluded sensitivity run.
- **Question:** is the STRONG_BEARISH-minus-BULLISH expectancy/win-rate gap
  (+1.151pp / +18.4pp observed) statistically distinguishable from noise
  given the small STRONG_BEARISH sample (n=48), or consistent with what
  that sample size could produce by chance? Reliability only — not a
  causal-explanation question (four mechanical candidates already rejected
  in experiments 3-5).
- **Method:** stratified (time_split × category) label permutation
  (seed 20260913, 100,000 draws — preserves 48/324 counts exactly in every
  draw, verified by assertion in code) for two-sided p-values; independent
  stratified calendar-month-cluster bootstrap per regime (seed 20260914,
  20,000 draws, exact via per-month sum/count aggregates) for 95% CIs.
- **Result:**
  - Expectancy gap: permutation p=0.09652 (not <0.05); bootstrap 95% CI
    **[-0.244, +2.657]pp — includes zero.** Condition 1: **FAILED.**
  - Win-rate gap: permutation p=0.02899 (<0.05); bootstrap 95% CI
    [+3.4, +36.8]pp — entirely above zero. Condition 2: **PASSED.**
  - Early/Middle expectancy gaps both positive (+0.945pp, +1.591pp).
    Recent has zero STRONG_BEARISH trades — untestable, as predeclared.
    Condition 3: **PASSED.**
- **Verdict:** Per the predeclared all-3-conditions rule, **NOT all
  conditions met (2 of 3)** → **insufficient evidence that the gap is
  statistically distinguishable from noise** under this precommitted test.
  This is not proof the anomaly is fake, and not a causal claim either
  way — the win-rate gap alone clears the bar; the expectancy gap does
  not, and the predeclared rule required both.
- **Sensitivity (does not override the primary decision):** excluding the
  same top-3 symbols per regime *strengthens* both signals (expectancy
  p=0.05822, still >0.05; win-rate p=0.03396; expectancy CI
  [+0.330, +2.740]pp — now excludes zero) — directionally consistent with
  "not purely noise" but the primary population's own predeclared test is
  the one that governs the verdict above, per the spec's own rule that
  sensitivity checks must not change the primary decision. ST/LT
  breakdown: STRONG_BEARISH outperforms BULLISH in both categories
  descriptively (n=27 ST, n=21 LT — both flagged small). STRONG_BEARISH
  trades concentrate somewhat by month (16 of 48 in 2025-01) but spread
  across 27 different symbols with no single symbol dominant.
- **Verification:** input file SHA-256 recorded and matched before/after;
  `git status --short` before and after run showed only new files under
  `research/`, all 16 production files and `tests/test_engine.py`
  unchanged; permutation code asserts stratum-count preservation
  (48/324 in every one of 100,000 draws) rather than assuming it; no
  new indicator/score computation performed — this experiment only
  resamples already-realized, previously point-in-time-verified trade
  outcomes; script syntax-checked before running; single run, no
  alternate seeds/definitions/subsets explored, per spec.
- **This experiment does not begin or recommend a next experiment** —
  awaiting Codex's next audit per the VYOM loop.

### 7. STRONG_BEARISH regime-frequency / opportunity-funnel audit — 2026-09-13
- **Spec:** written by Codex in `research/NEXT_EXPERIMENT.md` after
  auditing experiment 6; run exactly as specified, no substitutions.
- **Report:** `research/results/regime_frequency_report_20260913_172830.txt`
- **Fixed inputs (unmodified, unrefetched):**
  `research/results/resistance_master_20260913_164146.csv`
  (SHA-256 `7d6d623480e64c37ac606f45909074134b96257630f43230a51b476f5981e6c7`,
  48,552 rows, 476 distinct dates, 2024-07-09 to 2026-06-08) and
  `research/results/resistance_trades_20260913_164146.csv`
  (SHA-256 `05b11415a0979d224048e6e993d24c9a064f25a7b622e13a60ab5bbfe9026369`,
  2,083 rows, 402 distinct signal dates).
- **Question:** is the zero-Recent-STRONG_BEARISH-trades pattern (seen in
  experiments 5 and 6) a regime-frequency artifact (no STRONG_BEARISH
  NIFTY dates existed in that window) rather than a scoring/signal/
  non-overlap gate effect? Sample-composition audit only — does not test,
  explain, or validate the return anomaly itself.
- **Result: hypothesis FALSIFIED.** The Recent split does contain 2
  point-in-time STRONG_BEARISH regime dates (2026-06-05, 2026-06-08;
  1.3% of that split's 157 dates, vs 17.5% Early / 19.9% Middle) — not
  zero. So the absence of Recent STRONG_BEARISH trades is NOT explained
  by an absence of opportunities.
- **What the funnel + exhaustive trace showed instead:** on both Recent
  STRONG_BEARISH dates, of 102 symbol-category observations, only 14-46
  per category scored ≥40 (13.7%/45.1% — in line with other splits), and
  **zero of those became trades (0% stage c→d, vs 1.4-5.5% in Early/
  Middle)** — a complete stall at the final, non-overlap-simulation
  stage, not at scoring or signal classification. The exhaustive trace
  (every one of the 102 rows) showed several genuine WATCH-grade
  candidates (e.g. COALINDIA Long-Term score=71.6 grade=B, TITAN
  Long-Term score=60.7-60.3 grade=C) that never reached the trade file.
  Verified from code: `research/factor_data.py`'s `build_master_dataset`
  walks every day unconditionally (`i += 1`), while `run_ablation`'s walk
  skips ahead after taking a trade (`i = max(exit_idx+1, i+1)`) — so a
  WATCH/BUY-eligible row recorded in the master dataset at a given date
  does not guarantee `run_ablation`'s non-overlap walk for that
  symbol/category ever reached that date; an earlier open trade extending
  toward the end of the 3-year history is the specific mechanism
  identified (not a specific trade individually traced further, per the
  audit's own no-new-analysis-beyond-spec scope).
- **Also verified and quoted from code (not assumed):** `analyzer.
  _classify_signal` has a deliberate production rule —
  `regime_label=='STRONG_BEARISH' and grade in ('B','C') -> NO TRADE` —
  that suppresses merely-decent setups specifically in a STRONG_BEARISH
  tape; and `_grade_from_score` returns no grade below score 60, so the
  funnel's score≥40 stage is deliberately looser than the real grade
  floor. Both are genuine standing production rules, correctly
  reproduced by this audit, not something to change.
- **Robustness:** regime-label uniqueness holds (all 476 master dates
  carry exactly one regime label — no data-integrity exceptions);
  trade-file dates reconcile exactly with master regime labels (no
  mismatches, trade dates correctly NOT used as the regime denominator);
  symbol-exclusion funnel repeat shows the same pattern (0 Recent
  STRONG_BEARISH trades survives exclusion); month-by-month table flags
  every STRONG_BEARISH month as small (n<20 dates), consistent with prior
  experiments' small-sample caveats.
- **Bootstrap (descriptive, dependent estimates only):** 5-day
  moving-block bootstrap (seed 20260913, 20,000 draws) gives Recent's
  STRONG_BEARISH regime-date share a 95% CI of [0.0%, 1.9%] (vs Early
  [6.3%, 30.8%], Middle [9.1%, 33.0%]) — consistent with Recent being a
  genuinely low-STRONG_BEARISH-frequency window, not just a point
  estimate artifact, even though it wasn't literally zero.
- **Conclusion (regime-frequency evidence only, no causal/production
  claim):** the hypothesis as stated is falsified, but a *softer* version
  is supported — Recent had very few (not zero) STRONG_BEARISH
  opportunities, and the ones that existed were disproportionately
  filtered out by the non-overlap trade-simulation walk rather than by
  scoring or signal classification. This says nothing about whether the
  STRONG_BEARISH-vs-BULLISH return anomaly (experiments 1-6) is real.
- **Verification:** both input file SHA-256s recorded; `git status
  --short` before and after showed only new files under `research/`, all
  16 production files and `tests/test_engine.py` unchanged; regime,
  score, grade, and signal definitions verified directly from
  `market_regime.py`, `analyzer.py`, `config.py`, and
  `research/factor_data.py` and quoted in the report rather than assumed;
  script syntax-checked before running; single run, no alternate
  seeds/splits/block-lengths explored, per spec.
- **This experiment does not begin or recommend a next experiment** —
  awaiting Codex's next audit per the VYOM loop.

## Cumulative robustness findings (hold across every experiment above)

- **Symbol concentration:** ruled out. Excluding the same top-3 symbols
  per regime (`BULLISH: LT, BAJFINANCE, JSWSTEEL`; `STRONG_BEARISH: WIPRO,
  HINDALCO, TATASTEEL`) leaves BULLISH negative and STRONG_BEARISH
  positive-and-stronger every time.
- **Sector concentration:** ruled out. Both regimes spread across 7-10
  sectors in every experiment, no dominant sector.
- **Recent time period:** STRONG_BEARISH produced zero trades in the most
  recent third of the 3-year window in experiments 5 and 6. Experiment 7
  investigated this directly: it is NOT zero regime opportunities (2
  genuine STRONG_BEARISH dates existed, vs 25/35 in Early/Middle) — the
  zero trades instead trace to the non-overlap trade-simulation walk
  never reaching those dates for the symbols with qualifying scores. Not
  a regime-frequency artifact in the strict sense; a downstream
  simulation-gate effect on an already-thin population.

## Production code status

Unchanged since commit `ac2802a` ("Fix 4 audit-verified weaknesses...").
Every experiment above confirmed via `git status` immediately after
running. All 16 production files and `tests/test_engine.py` (34 tests)
untouched throughout the entire VYOM research program to date.
