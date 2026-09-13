# AGENTS.md — VYOM Research Rules

This file governs any work done under `research/`. It is read automatically
by Codex. The identical rules also live in `CLAUDE.md` for Claude — the two
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

1. A human reads `research/STATE.md` and tells Codex: "Continue the VYOM
   research handoff. Read `research/STATE.md` and the latest report."
2. Codex **audits** the latest report in `research/results/` — checks that
   its claims match its own numbers, that the classification is actually
   supported by the evidence, that N is reported everywhere, that no
   production file was touched, and that the falsification attempt was
   genuine.
3. Codex writes **exactly one** next research-only experiment to
   `research/NEXT_EXPERIMENT.md` — a clear, self-contained spec (question,
   required sections, populations to use, robustness checks to preserve)
   that Claude can run without further clarification.
4. Codex does **not** run the experiment, does not touch production code,
   and does not edit `research/STATE.md` (that's Claude's job after
   running the experiment Codex specified).

## Non-negotiable rules for every experiment

- **Research only.** Never modify production strategy code, weights,
  score thresholds, entry/exit logic, target/stop parameters, indicators,
  or anything that changes live trading behavior. Everything happens
  under `research/`.
- **No parameter optimization.** Do not propose tuning thresholds, bucket
  boundaries, or splits to make a hypothesis look better. If a boundary
  must be chosen (e.g. a quantile split), it should be chosen once and
  applied uniformly across every group being compared.
- **No cherry-picking.** Do not propose selecting symbols, sectors, date
  ranges, or buckets after seeing which ones support a hypothesis. Prefer
  reusing the same robustness exclusions (`TOP_SYMBOLS`), the same 3-way
  time split, and the same universe across experiments unless a human
  asks for new ones.
- **No look-ahead / no future information.** Any experiment spec must
  require point-in-time-safe computation: reuse the existing production
  Bundle pattern (`IndicatorBundle`, `RegimeBundle`, `SectorTrendBundle`)
  and reads via `.iloc[idx]` off series built over full history — never a
  rolling/aggregate statistic computed using data after the signal date.
- **Require reuse of production scoring functions unchanged.** Any
  experiment spec must call `analyzer.score_short_term` /
  `score_long_term`, `_grade_from_score`, `_classify_signal`,
  `backtest._simulate_trade`, etc. directly — never ask for scoring logic
  to be reimplemented in `research/`.
- **No causal claims from correlation.** A next-experiment spec should
  keep "is this factor predictive?" and "does this factor explain the
  anomaly?" as separate questions, and should require the report to say
  "no evidence" or "evidence against" when that's what the data shows.
- **Always require N.** Any experiment spec must require every reported
  cell/bucket to show its sample size, with small samples (<~15-20)
  flagged rather than used to draw conclusions.
- **Require an explicit falsification attempt** in every experiment spec
  — the report must actively try to disprove the hypothesis, not just
  confirm it.
- **One experiment at a time.** `research/NEXT_EXPERIMENT.md` must contain
  exactly one experiment, not a menu of options.
- **Verify before assuming.** An experiment spec that depends on a
  production field's exact meaning must require Claude to (re)verify that
  field's formula, lookback, and point-in-time safety directly from the
  code before using it.

## File roles

- `research/results/` — immutable, dated completed reports and datasets,
  written by Claude. Codex reads these but never edits or deletes them.
- `research/STATE.md` — single source of truth, maintained by Claude.
  Codex reads it to know what's been done; does not write to it.
- `research/NEXT_EXPERIMENT.md` — Codex's output. Exactly one approved
  next experiment, written after auditing the latest report.
- `research/*.py` — reusable data-collection/experiment code, written by
  Claude. Codex may read these to write an accurate, runnable spec but
  should not edit them.

## Audit checklist before writing `NEXT_EXPERIMENT.md`

- [ ] The latest report's classification matches the numbers it presents.
- [ ] Every claim in the report traces to a table/number in that same
      report (no unsupported claims).
- [ ] `git status` evidence in the report shows production untouched.
- [ ] The report's own "one recommended next experiment" was considered —
      Codex may adopt it, refine it, or propose something better, but
      should say which and why.
- [ ] The new spec written to `NEXT_EXPERIMENT.md` is self-contained
      (a human should be able to hand it to Claude with no extra context)
      and is exactly one experiment.
