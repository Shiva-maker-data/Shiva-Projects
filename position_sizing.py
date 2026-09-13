"""
Risk-based position sizing: never suggests deploying arbitrary or full
account capital. Sizes every trade so that IF the stop-loss is hit, the
rupee loss equals a fixed, configurable % of account capital -- and scales
that down further for lower-conviction grades, since a C-grade "weak setup"
warrants less capital at risk than an A+ setup even at the same nominal
risk-per-trade rule.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import config as cfg


@dataclass
class PositionSize:
    shares: int
    capital_deployed: float
    capital_at_risk: float
    pct_of_capital_deployed: float
    account_capital: float
    risk_per_trade_pct: float
    capped_by_max_position_pct: bool
    note: str


def get_account_capital() -> float:
    try:
        return float(os.getenv("ACCOUNT_CAPITAL", cfg.DEFAULT_ACCOUNT_CAPITAL))
    except ValueError:
        return cfg.DEFAULT_ACCOUNT_CAPITAL


def get_risk_per_trade_pct() -> float:
    try:
        return float(os.getenv("RISK_PER_TRADE_PCT", cfg.DEFAULT_RISK_PER_TRADE_PCT))
    except ValueError:
        return cfg.DEFAULT_RISK_PER_TRADE_PCT


def calculate_position_size(entry_price: float, stop_loss: float, grade: str,
                             account_capital: float | None = None,
                             risk_per_trade_pct: float | None = None) -> PositionSize:
    account_capital = account_capital if account_capital is not None else get_account_capital()
    risk_per_trade_pct = risk_per_trade_pct if risk_per_trade_pct is not None else get_risk_per_trade_pct()

    risk_per_share = max(entry_price - stop_loss, 0.01)
    grade_multiplier = cfg.GRADE_SIZE_MULTIPLIER.get(grade, 0.35)  # unknown/NO TRADE grades sized minimally
    risk_amount = account_capital * (risk_per_trade_pct / 100) * grade_multiplier

    shares = int(risk_amount // risk_per_share)
    capital_deployed = shares * entry_price

    max_capital = account_capital * (cfg.MAX_CAPITAL_PER_POSITION_PCT / 100)
    capped = False
    if capital_deployed > max_capital and entry_price > 0:
        shares = int(max_capital // entry_price)
        capital_deployed = shares * entry_price
        capped = True

    capital_at_risk = shares * risk_per_share
    pct_deployed = (capital_deployed / account_capital * 100) if account_capital else 0

    if shares <= 0:
        note = ("Calculated size rounds to 0 shares at this account capital / risk setting -- "
                "either the stop distance is wide relative to capital, or capital is set too low "
                "for this stock's price. Not a recommendation to force a trade.")
    elif capped:
        note = (f"Sized down to stay within the {cfg.MAX_CAPITAL_PER_POSITION_PCT:.0f}% "
                f"max-per-position guardrail, rather than the full risk-based size.")
    else:
        note = f"Sized to risk {risk_per_trade_pct:.1f}% x {grade_multiplier:.2f} (grade {grade}) of capital if stopped out."

    return PositionSize(
        shares=shares,
        capital_deployed=round(capital_deployed, 2),
        capital_at_risk=round(capital_at_risk, 2),
        pct_of_capital_deployed=round(pct_deployed, 1),
        account_capital=account_capital,
        risk_per_trade_pct=risk_per_trade_pct,
        capped_by_max_position_pct=capped,
        note=note,
    )
