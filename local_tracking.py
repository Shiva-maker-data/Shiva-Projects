"""
Appends every day's suggestions and resolved position outcomes to local CSV
files under tracking/, so they accumulate over time with no external
service required -- exactly what's needed to come back after a few months
and check whether the suggestions were actually correct.

Mirrors sheets_export.py's column schema exactly (imported, not
duplicated), so the two stay directly comparable. This module never raises
-- a failure to write the local log must never break the email pipeline.

Two files (created automatically on first run):
  tracking/daily_suggestions.csv -- one row per pick, the day it's suggested
                                     (every category, including Intraday).
  tracking/resolutions.csv       -- one row per Short-Term/Long-Term position
                                     once it actually resolves (target1 hit,
                                     stop-loss hit, or timed out), with the
                                     real return_pct -- this is the "was it
                                     correct" half of the data. Join back to
                                     daily_suggestions.csv on
                                     (Symbol, Category, FirstShownDate) to
                                     see the original call next to its
                                     outcome. Intraday picks are NOT
                                     resolved here -- same documented
                                     limitation as sheets_export.py, since
                                     nothing tracks same-day intraday
                                     outcomes yet.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from analyzer import TradeIdea
from positions import ClosedPosition
from sheets_export import RESOLUTIONS_HEADERS, SUGGESTIONS_HEADERS

logger = logging.getLogger("nifty_agent.local_tracking")

TRACKING_DIR = Path(__file__).resolve().parent / "tracking"
SUGGESTIONS_PATH = TRACKING_DIR / "daily_suggestions.csv"
RESOLUTIONS_PATH = TRACKING_DIR / "resolutions.csv"


def _append_rows(path: Path, headers: list[str], rows: list[list]) -> None:
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(headers)
        writer.writerows(rows)


def export_daily_results_local(picks_by_category: dict[str, list[TradeIdea]],
                                closed_positions: list[ClosedPosition], run_date) -> None:
    """Best-effort local CSV log -- never raises, so the email pipeline is
    never affected by a logging problem."""
    try:
        TRACKING_DIR.mkdir(exist_ok=True)
        date_str = str(run_date.date())

        suggestion_rows = []
        for ideas in picks_by_category.values():
            for idea in ideas:
                suggestion_rows.append([
                    date_str, idea.symbol, idea.category, idea.score, idea.last_price,
                    idea.entry_low, idea.entry_high, idea.target1, idea.target1_pct,
                    idea.target2, idea.target2_pct, idea.stop_loss, idea.stop_loss_pct,
                    idea.rr_ratio, idea.horizon, " | ".join(idea.reasons), idea.data_note,
                ])
        if suggestion_rows:
            _append_rows(SUGGESTIONS_PATH, SUGGESTIONS_HEADERS, suggestion_rows)

        if closed_positions:
            resolution_rows = [
                [p.symbol, p.category, p.first_shown_date, p.entry_price, p.closed_date,
                 p.exit_price, p.exit_reason, p.return_pct, p.score_at_signal]
                for p in closed_positions
            ]
            _append_rows(RESOLUTIONS_PATH, RESOLUTIONS_HEADERS, resolution_rows)

        logger.info("Logged %d suggestion(s) and %d resolution(s) to local tracking CSVs.",
                     len(suggestion_rows), len(closed_positions))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Local tracking CSV export failed (email was still sent normally): %s", exc)
