"""
Exports each day's suggestions and resolved position outcomes to a Google
Sheet, so they accumulate into clean, aggregatable, labeled data over time
-- exactly the kind of dataset you'd need to properly measure this system's
real-world accuracy, or eventually train an actual model on the same
features instead of hand-tuned rule weights.

Two worksheets (tabs), created automatically on first use:
  "Daily Suggestions" -- one row per pick, the day it's suggested
                         (every category, including Intraday)
  "Resolutions"        -- one row per position once it actually resolves
                         (target hit / stopped out / timed out), with the
                         real return -- this is the "ground truth" half of
                         the dataset. NOTE: only Short-Term/Long-Term picks
                         get resolution-tracked (positions.py) -- Intraday
                         suggestions are logged here but never get a
                         matching resolution row, since nothing tracks
                         same-day intraday outcomes yet. If you want
                         accuracy testing on Intraday too, that would need
                         a same-day version of positions.py added.

This entire module degrades gracefully to a no-op if Google credentials
aren't configured -- the email pipeline never depends on this succeeding.
"""
from __future__ import annotations

import json
import logging
import os

from analyzer import TradeIdea
from positions import ClosedPosition

logger = logging.getLogger("nifty_agent.sheets_export")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SUGGESTIONS_HEADERS = [
    "Date", "Symbol", "Category", "Score", "LastPrice", "EntryLow", "EntryHigh",
    "Target1", "Target1Pct", "Target2", "Target2Pct", "StopLoss", "StopLossPct",
    "RRRatio", "Horizon", "Reasons", "DataNote",
]
RESOLUTIONS_HEADERS = [
    "Symbol", "Category", "FirstShownDate", "EntryPrice", "ClosedDate",
    "ExitPrice", "ExitReason", "ReturnPct", "ScoreAtSignal",
]

_client = None
_client_checked = False


def _get_client():
    """Lazily build an authorized gspread client from a service account,
    or None if not configured (caller treats that as "export disabled")."""
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    creds_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not creds_json:
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _client = gspread.authorize(creds)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not set up Google Sheets client: %s", exc)
        _client = None
    return _client


def _get_or_create_worksheet(sheet, title: str, headers: list[str]):
    import gspread
    try:
        return sheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.append_row(headers)
        return ws


def export_daily_results(picks_by_category: dict[str, list[TradeIdea]],
                          closed_positions: list[ClosedPosition], run_date) -> None:
    """Best-effort export -- logs and returns quietly on any failure so the
    email pipeline is never affected by a Sheets problem."""
    client = _get_client()
    if client is None:
        logger.info("Google Sheets export skipped (GOOGLE_SERVICE_ACCOUNT_JSON not set).")
        return

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.warning("GOOGLE_SHEET_ID not set -- skipping Sheets export.")
        return

    try:
        sheet = client.open_by_key(sheet_id)
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
            ws = _get_or_create_worksheet(sheet, "Daily Suggestions", SUGGESTIONS_HEADERS)
            ws.append_rows(suggestion_rows, value_input_option="USER_ENTERED")

        if closed_positions:
            resolution_rows = [
                [p.symbol, p.category, p.first_shown_date, p.entry_price, p.closed_date,
                 p.exit_price, p.exit_reason, p.return_pct, p.score_at_signal]
                for p in closed_positions
            ]
            ws = _get_or_create_worksheet(sheet, "Resolutions", RESOLUTIONS_HEADERS)
            ws.append_rows(resolution_rows, value_input_option="USER_ENTERED")

        logger.info("Exported %d suggestion(s) and %d resolution(s) to Google Sheets.",
                     len(suggestion_rows), len(closed_positions))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Google Sheets export failed (email was still sent normally): %s", exc)
