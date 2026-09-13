"""
Tracks "open" Short-Term and Long-Term picks across daily runs so the same
idea isn't re-suggested every day while it's still active -- and reports
what actually happened to it once it resolves (hit target1, hit stop-loss,
or timed out past its horizon).

Intraday picks are NOT tracked here: they square off same-day by design, so
there's nothing meaningful to carry forward, and fresh daily variety is
already the correct behavior for that category (confirmed empirically --
Intraday/Short-Term conditions are transient day to day; Long-Term
conditions like "above the 200-day SMA" are not, which is exactly why this
module exists).

State lives in state/open_positions.json -- plain JSON, no database needed
for a single-user personal tool.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from analyzer import CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM, TradeIdea

logger = logging.getLogger("nifty_agent.positions")

STATE_PATH = Path(__file__).resolve().parent / "state" / "open_positions.json"
STATE_PATH.parent.mkdir(exist_ok=True)

# Force-close a position that never hit target or stop after this many
# calendar days, matching each category's stated horizon with some slack.
EXPIRY_DAYS = {
    CATEGORY_SHORT_TERM: 25,
    CATEGORY_LONG_TERM: 200,
}


@dataclass
class OpenPosition:
    symbol: str
    category: str
    first_shown_date: str
    entry_price: float
    target1: float
    target2: float
    stop_loss: float
    score_at_signal: float


@dataclass
class ClosedPosition(OpenPosition):
    closed_date: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""       # "target1" | "stop_loss" | "time_exit"
    return_pct: float = 0.0


def load_open_positions() -> list[OpenPosition]:
    if not STATE_PATH.exists():
        return []
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return [OpenPosition(**p) for p in raw]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read %s (%s) -- starting with no open positions.", STATE_PATH, exc)
        return []


def save_open_positions(positions: list[OpenPosition]) -> None:
    STATE_PATH.write_text(
        json.dumps([asdict(p) for p in positions], indent=2), encoding="utf-8")


def _check_position(pos: OpenPosition, daily_df: pd.DataFrame, today: pd.Timestamp) -> ClosedPosition | None:
    """Check whether `pos` has hit target1, stop-loss, or expired, using
    daily bars strictly after first_shown_date up to today (conservative:
    stop-loss checked before target on any day both are plausible). Returns
    a ClosedPosition if resolved, else None (still open)."""
    first_shown = pd.Timestamp(pos.first_shown_date)
    subsequent = daily_df[(daily_df.index > first_shown) & (daily_df.index <= today)]

    for date, row in subsequent.iterrows():
        if row["Low"] <= pos.stop_loss:
            return ClosedPosition(
                **asdict(pos), closed_date=str(date.date()), exit_price=pos.stop_loss,
                exit_reason="stop_loss", return_pct=round((pos.stop_loss / pos.entry_price - 1) * 100, 2))
        if row["High"] >= pos.target1:
            return ClosedPosition(
                **asdict(pos), closed_date=str(date.date()), exit_price=pos.target1,
                exit_reason="target1", return_pct=round((pos.target1 / pos.entry_price - 1) * 100, 2))

    days_open = (today - first_shown).days
    if days_open >= EXPIRY_DAYS.get(pos.category, 90) and not daily_df.empty:
        last_close = float(daily_df["Close"].iloc[-1])
        return ClosedPosition(
            **asdict(pos), closed_date=str(today.date()), exit_price=last_close,
            exit_reason="time_exit", return_pct=round((last_close / pos.entry_price - 1) * 100, 2))
    return None


def reconcile(open_positions: list[OpenPosition], daily_data: dict[str, pd.DataFrame],
              today: pd.Timestamp) -> tuple[list[OpenPosition], list[ClosedPosition]]:
    """Split existing open positions into (still_open, newly_closed) using
    today's freshly fetched daily data per symbol."""
    still_open, closed = [], []
    for pos in open_positions:
        df = daily_data.get(pos.symbol)
        if df is None or df.empty:
            still_open.append(pos)  # couldn't fetch data today -- don't lose track of it
            continue
        result = _check_position(pos, df, today)
        (closed if result else still_open).append(result or pos)
    return still_open, closed


def already_open_keys(open_positions: list[OpenPosition]) -> set[tuple[str, str]]:
    return {(p.symbol, p.category) for p in open_positions}


def idea_to_open_position(idea: TradeIdea, today: pd.Timestamp) -> OpenPosition:
    return OpenPosition(
        symbol=idea.symbol, category=idea.category, first_shown_date=str(today.date()),
        entry_price=idea.last_price, target1=idea.target1, target2=idea.target2,
        stop_loss=idea.stop_loss, score_at_signal=idea.score,
    )
