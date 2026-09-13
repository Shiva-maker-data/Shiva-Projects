"""
Sector confirmation and relative-strength-vs-NIFTY, computed from free NSE
sector index data (verified reachable via yfinance -- see the tickers
below).

SECTOR_MAP is a manually curated, best-effort classification -- NOT pulled
from an authoritative NSE/AMFI classification file (no free API for that).
Where a stock doesn't have a genuinely good sector-index fit (diversified
conglomerates, single-of-a-kind businesses like Zomato/Eternal), it's
deliberately left unmapped (None) rather than force-fit to a wrong sector
-- a wrong sector signal is worse than no sector signal. Review
periodically, same caveat as symbols.py's NIFTY 50 list.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd

import config as cfg
import data_sources as ds
import indicators as ind

logger = logging.getLogger("nifty_agent.sector")

ALIGNED_BULLISH = "ALIGNED_BULLISH"
SECTOR_NEUTRAL = "SECTOR_NEUTRAL"
SECTOR_CONTRA = "SECTOR_CONTRA"
NO_SECTOR_DATA = "NO_SECTOR_DATA"

# symbol (no .NS suffix, matches symbols.py) -> NSE sector index Yahoo ticker
SECTOR_MAP: dict[str, str] = {
    # Banks
    "AXISBANK": "^NSEBANK", "HDFCBANK": "^NSEBANK", "ICICIBANK": "^NSEBANK",
    "INDUSINDBK": "^NSEBANK", "KOTAKBANK": "^NSEBANK", "SBIN": "^NSEBANK",
    # IT / Technology
    "HCLTECH": "^CNXIT", "INFY": "^CNXIT", "TCS": "^CNXIT", "TECHM": "^CNXIT", "WIPRO": "^CNXIT",
    # Auto
    "BAJAJ-AUTO": "^CNXAUTO", "EICHERMOT": "^CNXAUTO", "HEROMOTOCO": "^CNXAUTO",
    "M&M": "^CNXAUTO", "MARUTI": "^CNXAUTO", "TMPV": "^CNXAUTO",
    # Pharma
    "CIPLA": "^CNXPHARMA", "DRREDDY": "^CNXPHARMA", "SUNPHARMA": "^CNXPHARMA",
    # FMCG
    "HINDUNILVR": "^CNXFMCG", "ITC": "^CNXFMCG", "NESTLEIND": "^CNXFMCG", "TATACONSUM": "^CNXFMCG",
    # Metal / mining
    "HINDALCO": "^CNXMETAL", "JSWSTEEL": "^CNXMETAL", "TATASTEEL": "^CNXMETAL", "COALINDIA": "^CNXMETAL",
    # Energy / power
    "RELIANCE": "^CNXENERGY", "ONGC": "^CNXENERGY", "NTPC": "^CNXENERGY", "POWERGRID": "^CNXENERGY",
    # Financial services (non-bank) -- ^CNXFIN deliberately NOT used here:
    # verified it only ever returns 1 row of history via yfinance regardless
    # of period requested (a real data gap for that index, not a fetch
    # bug), so BAJFINANCE/BAJAJFINSV/SBILIFE/HDFCLIFE/SHRIRAMFIN/JIOFIN are
    # left unmapped rather than pointed at a source that can't serve a
    # trend calculation.
    # Infra / construction
    "LT": "^CNXINFRA", "ADANIPORTS": "^CNXINFRA",
    # Consumer durables (approximate fit)
    "TITAN": "^CNXCONSUM", "ASIANPAINT": "^CNXCONSUM",
    # Deliberately unmapped -- no genuinely good free sector-index fit:
    # ADANIENT (diversified conglomerate), APOLLOHOSP (hospitals -- no
    # healthcare-provider index available), BEL (defense/PSU), BHARTIARTL
    # (telecom -- no telecom index verified), BAJAJHLDNG (pure holding co),
    # ETERNAL (new-age tech/food delivery), GRASIM/ULTRACEMCO (cement --
    # no cement index verified), TRENT (retail -- no retail index verified).
}


@dataclass
class SectorConfirmation:
    sector_ticker: str | None
    sector_trend: str  # "BULLISH" | "BEARISH" | "NEUTRAL" | "UNKNOWN"
    alignment: str      # ALIGNED_BULLISH | SECTOR_NEUTRAL | SECTOR_CONTRA | NO_SECTOR_DATA
    score_multiplier: float
    relative_strength_pct: float | None  # stock return minus NIFTY return, lookback window
    reasons: list[str]


# Multiple stocks share the same sector index (e.g. 6 stocks -> ^CNXFIN) --
# without caching, each one independently re-fetches the identical sector
# data every run, which is wasteful and was observed to trigger Yahoo
# Finance failures under the resulting concurrent duplicate load. Cache per
# process run (cleared for a fresh run since this module is re-imported
# per process, e.g. each GitHub Actions run).
_sector_trend_cache: dict[str, str | None] = {}


def _sector_trend(sector_ticker: str) -> str | None:
    if sector_ticker in _sector_trend_cache:
        return _sector_trend_cache[sector_ticker]

    df = ds.fetch_daily_history(sector_ticker, period="6mo")
    if df is None or len(df) < cfg.SECTOR_SMA_WINDOW:
        _sector_trend_cache[sector_ticker] = None
        return None
    close = df["Close"]
    price = float(close.iloc[-1])
    sma = float(ind.sma(close, cfg.SECTOR_SMA_WINDOW).iloc[-1])
    if price > sma * 1.01:
        trend = "BULLISH"
    elif price < sma * 0.99:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"
    _sector_trend_cache[sector_ticker] = trend
    return trend


@dataclass
class SectorTrendBundle:
    """Vectorized sector-index inputs over full history -- same pattern as
    market_regime.RegimeBundle / analyzer.IndicatorBundle. Reading
    .iloc[idx] is point-in-time safe, which is what lets backtest.py
    evaluate 'what was this stock's sector trend on that historical day'
    using the SAME classification logic (_sector_trend's thresholds) the
    live path uses, instead of a separate reimplementation that could drift."""
    close: pd.Series
    sma: pd.Series


def compute_sector_trend_bundle(sector_df) -> SectorTrendBundle:
    close = sector_df["Close"]
    return SectorTrendBundle(close=close, sma=ind.sma(close, cfg.SECTOR_SMA_WINDOW))


def classify_sector_trend_at(bundle: SectorTrendBundle, idx: int) -> str:
    """Point-in-time sector trend label at row `idx`. Falls back to NEUTRAL
    if there isn't enough trailing history yet (mirrors _sector_trend's
    thresholds exactly: >1.01x SMA = BULLISH, <0.99x = BEARISH)."""
    sma = bundle.sma.iloc[idx]
    if pd.isna(sma):
        return "NEUTRAL"
    price = bundle.close.iloc[idx]
    if price > sma * 1.01:
        return "BULLISH"
    if price < sma * 0.99:
        return "BEARISH"
    return "NEUTRAL"


def compute_relative_strength_at(stock_close: pd.Series, stock_idx: int, nifty_close: pd.Series,
                                  lookback_days: int) -> float | None:
    """Point-in-time relative strength: stock's return over the lookback
    window (in the stock's own trading-day positions) minus NIFTY's return
    over the SAME calendar dates (found by aligning to NIFTY's own index,
    since the two calendars can differ slightly around holidays)."""
    if stock_idx - lookback_days < 0:
        return None
    stock_ret = (stock_close.iloc[stock_idx] / stock_close.iloc[stock_idx - lookback_days] - 1) * 100

    date_now = stock_close.index[stock_idx]
    date_then = stock_close.index[stock_idx - lookback_days]
    pos_now = nifty_close.index.searchsorted(date_now, side="right") - 1
    pos_then = nifty_close.index.searchsorted(date_then, side="right") - 1
    if pos_now < 0 or pos_then < 0:
        return None
    nifty_ret = (nifty_close.iloc[pos_now] / nifty_close.iloc[pos_then] - 1) * 100
    return round(float(stock_ret - nifty_ret), 2)


def build_point_in_time_confirmation(symbol: str, stock_bundle, stock_idx: int,
                                      sector_bundles: dict[str, SectorTrendBundle],
                                      nifty_close: pd.Series | None, lookback_days: int) -> "SectorConfirmation":
    """Assembles a SectorConfirmation at a specific historical point, using
    the SAME alignment/classification rules as the live path -- what
    backtest.py uses instead of passing sector_confirmation=None."""
    sector_ticker = SECTOR_MAP.get(symbol)

    rel_strength = None
    if nifty_close is not None:
        rel_strength = compute_relative_strength_at(stock_bundle.close, stock_idx, nifty_close, lookback_days)

    if sector_ticker is None or sector_ticker not in sector_bundles:
        return SectorConfirmation(
            sector_ticker=sector_ticker, sector_trend="UNKNOWN", alignment=NO_SECTOR_DATA,
            score_multiplier=cfg.SECTOR_SCORE_MULTIPLIER[NO_SECTOR_DATA],
            relative_strength_pct=rel_strength, reasons=[],
        )

    s_bundle = sector_bundles[sector_ticker]
    sec_idx = s_bundle.close.index.searchsorted(stock_bundle.close.index[stock_idx], side="right") - 1
    if sec_idx < 0:
        trend = "UNKNOWN"
    else:
        trend = classify_sector_trend_at(s_bundle, sec_idx)

    price = stock_bundle.close.iloc[stock_idx]
    sma50 = stock_bundle.sma50.iloc[stock_idx]
    stock_bullish = bool(pd.notna(sma50) and price > sma50)

    if trend == "UNKNOWN":
        alignment = NO_SECTOR_DATA
    elif stock_bullish and trend == "BULLISH":
        alignment = ALIGNED_BULLISH
    elif stock_bullish and trend == "BEARISH":
        alignment = SECTOR_CONTRA
    else:
        alignment = SECTOR_NEUTRAL

    return SectorConfirmation(
        sector_ticker=sector_ticker, sector_trend=trend, alignment=alignment,
        score_multiplier=cfg.SECTOR_SCORE_MULTIPLIER[alignment],
        relative_strength_pct=rel_strength, reasons=[],
    )


def compute_relative_strength(stock_close, nifty_close, lookback_days: int) -> float | None:
    """Stock's % return over the lookback window minus NIFTY's % return over
    the same window -- positive means the stock is outperforming the index,
    not just moving up in absolute terms."""
    if len(stock_close) <= lookback_days or len(nifty_close) <= lookback_days:
        return None
    stock_ret = (stock_close.iloc[-1] / stock_close.iloc[-lookback_days - 1] - 1) * 100
    nifty_ret = (nifty_close.iloc[-1] / nifty_close.iloc[-lookback_days - 1] - 1) * 100
    return round(float(stock_ret - nifty_ret), 2)


def prefetch_sector_trends() -> None:
    """Populate the sector-trend cache for every unique sector index ONCE,
    sequentially, before the main per-stock thread pool runs. Several
    stocks share a sector index (e.g. 6 -> ^NSEBANK) -- fetching lazily
    inside concurrent per-stock workers races on the cache (many threads
    can all miss it at once) and multiplies redundant network calls.
    Calling this upfront avoids both problems."""
    for ticker in set(SECTOR_MAP.values()):
        _sector_trend(ticker)


def get_sector_confirmation(symbol: str, stock_bullish: bool, nifty_close=None,
                             stock_close=None, lookback_days: int = None) -> SectorConfirmation:
    """stock_bullish: whether the stock's OWN technical signal is bullish
    (used to determine alignment with the sector trend). Relative strength
    is computed only if both close series are provided -- callers that
    don't have NIFTY data handy get sector-trend-only confirmation."""
    lookback_days = lookback_days or cfg.RS_LOOKBACK_DAYS
    sector_ticker = SECTOR_MAP.get(symbol)

    rel_strength = None
    if nifty_close is not None and stock_close is not None:
        rel_strength = compute_relative_strength(stock_close, nifty_close, lookback_days)

    if sector_ticker is None:
        return SectorConfirmation(
            sector_ticker=None, sector_trend="UNKNOWN", alignment=NO_SECTOR_DATA,
            score_multiplier=cfg.SECTOR_SCORE_MULTIPLIER[NO_SECTOR_DATA],
            relative_strength_pct=rel_strength,
            reasons=["No reliable free sector-index mapping for this stock -- sector confirmation skipped."],
        )

    trend = _sector_trend(sector_ticker)
    if trend is None:
        return SectorConfirmation(
            sector_ticker=sector_ticker, sector_trend="UNKNOWN", alignment=NO_SECTOR_DATA,
            score_multiplier=cfg.SECTOR_SCORE_MULTIPLIER[NO_SECTOR_DATA],
            relative_strength_pct=rel_strength,
            reasons=[f"Sector index {sector_ticker} data unavailable today -- sector confirmation skipped."],
        )

    reasons = [f"Sector index ({sector_ticker}) trend: {trend}."]
    if stock_bullish and trend == "BULLISH":
        alignment = ALIGNED_BULLISH
        reasons.append("Stock's bullish signal is confirmed by its sector also trending up.")
    elif stock_bullish and trend == "BEARISH":
        alignment = SECTOR_CONTRA
        reasons.append("Caution: stock shows a bullish signal while its own sector is trending down.")
    else:
        alignment = SECTOR_NEUTRAL

    if rel_strength is not None:
        if rel_strength >= cfg.RS_STRONG_OUTPERFORM_PP:
            reasons.append(f"Outperforming NIFTY by {rel_strength:+.1f}pp over {lookback_days}d -- strong relative strength.")
        elif rel_strength <= cfg.RS_WEAK_UNDERPERFORM_PP:
            reasons.append(f"Underperforming NIFTY by {rel_strength:+.1f}pp over {lookback_days}d -- weak relative strength.")

    return SectorConfirmation(
        sector_ticker=sector_ticker, sector_trend=trend, alignment=alignment,
        score_multiplier=cfg.SECTOR_SCORE_MULTIPLIER[alignment],
        relative_strength_pct=rel_strength, reasons=reasons,
    )
