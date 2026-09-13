# CLAUDE.md — VYOM Research Rules

This file governs any work done under `research/`. It is read automatically
by Claude. The identical rules also live in `AGENTS.md` for Codex — the two
files must stay in sync; if you edit one for a rule change, edit both.

## What this project is

This repository (VYOM) runs a rule-based technical-analysis engine that
emails daily NIFTY/SENSEX trade ideas. The production code (`analyzer.py`,
`config.py`, `main.py`, `market_regime.py`, `sector.py`, `backtest.py`,
`position_sizing.py`, `positions.py`, `report.py`, `narrative.py`,
`emailer.py`, `sheets_export.py`, `symbols.py`, `data_sources.py`,
`indicators.py`, and `tests/`) is considered **frozen** for the purposes of
the VYOM research program described below.

## The VYOM research loop

1. A human reads `research/STATE.md` and `research/NEXT_EXPERIMENT.md` and
   tells Claude to run the one approved experiment there.
2. Claude runs **exactly that one experiment** — nothing else, no
   substitutions, no "while I'm at it" extras.
3. Claude saves the complete report under `research/results/` (dated,
   immutable — never overwrite a prior report).
4. Claude updates `research/STATE.md`: report path, verdict/classification,
   and verification evidence (`git status` output proving production is
   untouched, commands executed, N for every population used).
5. Claude does **not** write `research/NEXT_EXPERIMENT.md`. That file is
   Codex's output after auditing Claude's report — Claude must not replace
   it with a different experiment or pre-empt it with its own pick.

## Non-negotiable rules for every experiment

- **Research only.** Never modify production strategy code, weights,
  score thresholds, entry/exit logic, target/stop parameters, indicators,
  or anything that changes live trading behavior. Everything happens
  under `research/`.
- **No parameter optimization.** Do not tune thresholds, bucket
  boundaries, or splits to make a hypothesis look better. If a boundary
  must be chosen (e.g. a quantile split), choose it once, apply it
  uniformly across every group being compared, and say so explicitly.
- **No cherry-picking.** Do not select symbols, sectors, date ranges, or
  buckets after seeing which ones support the hypothesis. Reuse the same
  robustness exclusions (`TOP_SYMBOLS`), the same 3-way time split, and
  the same universe across experiments unless a human asks for new ones.
- **No look-ahead / no future information.** Every computation must be
  point-in-time safe: reuse the existing production Bundle pattern
  (`IndicatorBundle`, `RegimeBundle`, `SectorTrendBundle`) and read via
  `.iloc[idx]` off series built over full history — never compute a
  rolling/aggregate statistic using data after the signal date.
- **Reuse production scoring functions unchanged.** Import and call
  `analyzer.score_short_term` / `score_long_term`, `_grade_from_score`,
  `_classify_signal`, `backtest._simulate_trade`, etc. directly. Never
  reimplement scoring logic in `research/` — every number must trace back
  to the real production formula.
- **No causal claims from correlation.** Distinguish "evidence" /
  "weak evidence" / "no evidence" / "evidence against" explicitly. A
  factor can be a good standalone predictor and still fail to explain a
  specific anomaly — keep those two questions separate.
- **Always report N.** Flag any cell/bucket below ~15-20 observations as
  a small sample; do not draw conclusions from it.
- **Actively try to falsify**, not confirm, the hypothesis under test.
  State plainly when a result does not support it.
- **One experiment, one report, one classification.** Every report ends
  with exactly one recommended next experiment — described, not
  implemented — and a classification the evidence actually supports
  (never picked to make the strategy look better).
- **Verify before assuming.** Inspect the actual production code for any
  field's definition before using it (formula, lookback, whether today's
  bar is included, whether it's point-in-time safe) rather than trusting
  a variable name or a prior summary.

## File roles

- `research/results/` — immutable, dated completed reports and datasets.
  Commit these. Never overwrite an existing file here.
- `research/STATE.md` — single source of truth: what's complete, what's
  running, what may happen next. Claude updates this after every run.
- `research/NEXT_EXPERIMENT.md` — Codex's one approved next experiment.
  Claude reads it, runs it, and must not substitute a different one.
- `research/*.py` — reusable data-collection/experiment code. Purely
  additive changes (new columns, new scripts) are fine; never change what
  an existing column means without saying so in the report.

## Verification checklist before ending any research turn

- [ ] `git status` shows no production files changed.
- [ ] The experiment run reused production scoring functions, not
      reimplementations.
- [ ] Every reported number has an N attached.
- [ ] `research/STATE.md` is updated with report path + verdict + evidence.
- [ ] `research/NEXT_EXPERIMENT.md` was read, not written, by Claude.
