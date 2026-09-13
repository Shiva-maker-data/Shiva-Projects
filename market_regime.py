"""
Classifies the broad market regime using the NIFTY 50 index itself, so
stock-level signals can be adjusted for (not just labeled with) whether
they're happening in a favorable or hostile macro backdrop.

This directly implements the "strong breakout + weak market = lower score"
requirement: the regime multiplier in config.py is applied MULTIPLICATIVELY
to every stock's raw technical score, not just displayed as a side-note.

Deliberately simple and auditable -- three independent readings (trend,
momentum, volatility), each computed from the same indicator library
already used everywhere else in this project, combined into one label.
No new indicator concepts invented just for this.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

import config as cfg
import data_sources as ds
import indicators as ind

logger = logging.getLogger("nifty_agent.market_regime")

REGIME_STRONG_BULLISH = "STRONG_BULLISH"
REGIME_BULLISH = "BULLISH"
REGIME_NEUTRAL = "NEUTRAL"
REGIME_BEARISH = "BEARISH"
REGIME_STRONG_BEARISH = "STRONG_BEARISH"
REGIME_HIGH_VOLATILITY = "HIGH_VOLATILITY"


@dataclass
class MarketRegime:
    label: str
    score_multiplier: float
    index_price: float
    pct_from_sma_fast: float
    pct_from_sma_slow: float
    atr_pct: float
    atr_percentile: float
    rsi: float
    reasons: list[str]


def _classify(price: float, sma_fast: float, sma_slow: float, rsi: float,
              atr_pct: float, atr_percentile: float) -> tuple[str, list[str]]:
    reasons = []

    # Volatility gate takes priority: an unstable tape undermines every
    # signal regardless of direction, so it's checked first.
    if atr_percentile >= cfg.REGIME_HIGH_VOL_ATR_PCTILE:
        reasons.append(f"NIFTY's volatility (ATR) is in the top {100 - cfg.REGIME_HIGH_VOL_ATR_PCTILE:.0f}% "
                        f"of its last {cfg.REGIME_ATR_HISTORY_WINDOW} sessions -- conditions are unstable.")
        return REGIME_HIGH_VOLATILITY, reasons

    above_fast = price > sma_fast
    above_slow = price > sma_slow
    fast_above_slow = sma_fast > sma_slow

    if above_fast and above_slow and fast_above_slow and rsi >= 55:
        reasons.append(f"NIFTY above both {cfg.REGIME_SMA_FAST}/{cfg.REGIME_SMA_SLOW}-day SMAs "
                        f"with RSI {rsi:.0f} -- broad market trending strongly higher.")
        return REGIME_STRONG_BULLISH, reasons
    if above_fast and above_slow:
        reasons.append(f"NIFTY above both {cfg.REGIME_SMA_FAST}/{cfg.REGIME_SMA_SLOW}-day SMAs -- market in an uptrend.")
        return REGIME_BULLISH, reasons
    if not above_fast and not above_slow and not fast_above_slow and rsi <= 45:
        reasons.append(f"NIFTY below both SMAs with RSI {rsi:.0f} -- broad market trending strongly lower.")
        return REGIME_STRONG_BEARISH, reasons
    if not above_fast and not above_slow:
        reasons.append("NIFTY below both SMAs -- market in a downtrend.")
        return REGIME_BEARISH, reasons

    reasons.append("NIFTY is mixed relative to its own trend SMAs -- no clear market-wide direction.")
    return REGIME_NEUTRAL, reasons


@dataclass
class RegimeBundle:
    """Vectorized regime inputs over full NIFTY history -- same pattern as
    analyzer.IndicatorBundle. Reading .iloc[idx] from any series here is
    point-in-time safe, so this is what lets backtest.py evaluate 'what was
    the market regime on that historical day' without lookahead bias, using
    the SAME classification logic the live path uses (not a reimplementation
    that could silently drift)."""
    close: pd.Series
    sma_fast: pd.Series
    sma_slow: pd.Series
    rsi: pd.Series
    atr_pct: pd.Series
    atr_percentile: pd.Series


def compute_regime_bundle(nifty_df: pd.DataFrame) -> RegimeBundle:
    close = nifty_df["Close"]
    atr_series = ind.atr(nifty_df, cfg.REGIME_ATR_LOOKBACK)
    atr_pct = (atr_series / close) * 100
    atr_percentile = atr_pct.rolling(cfg.REGIME_ATR_HISTORY_WINDOW, min_periods=20).apply(
        lambda w: (w < w.iloc[-1]).mean() * 100, raw=False
    )
    return RegimeBundle(
        close=close,
        sma_fast=ind.sma(close, cfg.REGIME_SMA_FAST),
        sma_slow=ind.sma(close, cfg.REGIME_SMA_SLOW),
        rsi=ind.rsi(close, 14),
        atr_pct=atr_pct,
        atr_percentile=atr_percentile,
    )


def classify_regime_at(bundle: RegimeBundle, idx: int) -> str:
    """Point-in-time regime label at row `idx` of a RegimeBundle. Falls
    back to NEUTRAL if there isn't enough trailing history yet at this idx
    (e.g. very early in the backtest window)."""
    sma_slow = bundle.sma_slow.iloc[idx]
    atr_percentile = bundle.atr_percentile.iloc[idx]
    if pd.isna(sma_slow) or pd.isna(atr_percentile):
        return REGIME_NEUTRAL
    label, _ = _classify(
        float(bundle.close.iloc[idx]), float(bundle.sma_fast.iloc[idx]), float(sma_slow),
        float(bundle.rsi.iloc[idx]), float(bundle.atr_pct.iloc[idx]), float(atr_percentile),
    )
    return label


def get_market_regime(period: str = "1y") -> MarketRegime | None:
    """Fetch NIFTY 50 and classify the current market regime. Returns None
    if the index itself can't be fetched -- callers must treat that as
    'regime unknown' and degrade gracefully (see analyzer.py), not crash."""
    df = ds.fetch_daily_history(cfg.REGIME_INDEX_TICKER, period=period)
    if df is None or len(df) < cfg.REGIME_SMA_SLOW + cfg.REGIME_ATR_HISTORY_WINDOW:
        logger.warning("Not enough NIFTY history to classify market regime.")
        return None

    close = df["Close"]
    price = float(close.iloc[-1])
    sma_fast = float(ind.sma(close, cfg.REGIME_SMA_FAST).iloc[-1])
    sma_slow = float(ind.sma(close, cfg.REGIME_SMA_SLOW).iloc[-1])
    rsi = float(ind.rsi(close, 14).iloc[-1])

    atr_series = ind.atr(df, cfg.REGIME_ATR_LOOKBACK)
    atr_pct_series = (atr_series / close) * 100
    atr_pct = float(atr_pct_series.iloc[-1])
    recent_window = atr_pct_series.tail(cfg.REGIME_ATR_HISTORY_WINDOW).dropna()
    atr_percentile = float((recent_window < atr_pct).mean() * 100) if len(recent_window) else 50.0

    label, reasons = _classify(price, sma_fast, sma_slow, rsi, atr_pct, atr_percentile)

    return MarketRegime(
        label=label,
        score_multiplier=cfg.REGIME_SCORE_MULTIPLIER[label],
        index_price=round(price, 2),
        pct_from_sma_fast=round((price / sma_fast - 1) * 100, 2),
        pct_from_sma_slow=round((price / sma_slow - 1) * 100, 2),
        atr_pct=round(atr_pct, 2),
        atr_percentile=round(atr_percentile, 1),
        rsi=round(rsi, 1),
        reasons=reasons,
    )
