"""
Market data fetching with cross-checking across two independent free sources:

  1. Yahoo Finance (via yfinance)      -- primary source for OHLCV history
     (daily, for swing/long-term signals, and intraday, for intraday signals)
  2. NSE India's own public quote API  -- secondary source, used only to
     cross-check the latest traded price against Yahoo Finance and flag any
     material disagreement in the report.

Both sources are free and require no API key. Either can fail/rate-limit at
any time (Yahoo throttles aggressive polling; NSE blocks non-browser-like
requests fairly often) -- every function here degrades gracefully and
returns None rather than raising, so one bad symbol never kills the whole
daily run.

Extension point: to add a broker API (Zerodha Kite / Upstox) as a third,
exchange-grade source, add a `get_broker_quote(symbol)` function here
following the same (dict | None) contract and wire it into
`cross_check_price()`.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger("nifty_agent.data_sources")

NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_nse_session: requests.Session | None = None


def _get_nse_session() -> requests.Session:
    """Create (or reuse) a requests session warmed up with NSE's cookies.

    NSE's API rejects requests that don't look like they came from a
    browser that first visited the site, so we visit the homepage once to
    pick up cookies before hitting the JSON endpoint.
    """
    global _nse_session
    if _nse_session is not None:
        return _nse_session
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com", timeout=6)
    except Exception as exc:  # noqa: BLE001
        logger.warning("NSE session warm-up failed (will still try requests): %s", exc)
    _nse_session = session
    return session


def get_nse_quote(symbol: str) -> dict | None:
    """Best-effort fetch of the latest quote for `symbol` from NSE India.

    Returns a dict with last_price / prev_close / day_high / day_low, or
    None if NSE couldn't be reached or blocked the request.
    """
    try:
        session = _get_nse_session()
        # Use `params=` (not an f-string) so symbols with special characters
        # (e.g. "M&M") get properly percent-encoded instead of corrupting
        # the query string.
        url = "https://www.nseindia.com/api/quote-equity"
        resp = session.get(url, params={"symbol": symbol}, timeout=8)
        if resp.status_code != 200:
            logger.info("NSE quote HTTP %s for %s", resp.status_code, symbol)
            return None
        data = resp.json()
        price_info = data.get("priceInfo", {})
        intraday = price_info.get("intraDayHighLow", {}) or {}
        last_price = price_info.get("lastPrice")
        if last_price is None:
            return None
        return {
            "last_price": float(last_price),
            "prev_close": float(price_info.get("previousClose", 0) or 0) or None,
            "day_high": float(intraday.get("max", 0) or 0) or None,
            "day_low": float(intraday.get("min", 0) or 0) or None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("NSE quote fetch failed for %s: %s", symbol, exc)
        return None


def _strip_tz(df: pd.DataFrame) -> pd.DataFrame:
    """Yahoo Finance returns NSE data with an Asia/Kolkata-aware index.
    Every downstream consumer (analyzer, backtest, positions) works with
    plain dates and would otherwise have to special-case tz-aware vs
    tz-naive comparisons -- normalize to tz-naive once, here, at the source."""
    if df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def fetch_daily_history(yf_ticker: str, period: str = "1y", retries: int = 2) -> pd.DataFrame | None:
    """Fetch daily OHLCV history from Yahoo Finance, with light retrying."""
    for attempt in range(retries + 1):
        try:
            df = yf.Ticker(yf_ticker).history(period=period, interval="1d", auto_adjust=False)
            if df is not None and not df.empty and len(df) >= 60:
                return _strip_tz(df)
        except Exception as exc:  # noqa: BLE001
            logger.info("yfinance daily fetch failed for %s (attempt %d): %s", yf_ticker, attempt, exc)
        time.sleep(1.5)
    logger.warning("Giving up on daily history for %s after %d attempts", yf_ticker, retries + 1)
    return None


def fetch_intraday_history(yf_ticker: str, period: str = "5d", interval: str = "15m",
                            retries: int = 1) -> pd.DataFrame | None:
    """Fetch recent intraday OHLCV from Yahoo Finance (used for intraday signals).

    NOTE: Yahoo's intraday feed for NSE symbols can lag the live market by
    up to ~15 minutes and is occasionally unavailable outside market hours.
    Treat intraday output as directional, not tick-accurate.
    """
    for attempt in range(retries + 1):
        try:
            df = yf.Ticker(yf_ticker).history(period=period, interval=interval, auto_adjust=False)
            if df is not None and not df.empty and len(df) >= 10:
                return _strip_tz(df)
        except Exception as exc:  # noqa: BLE001
            logger.info("yfinance intraday fetch failed for %s (attempt %d): %s", yf_ticker, attempt, exc)
        time.sleep(1.5)
    return None


@dataclass
class PriceCheck:
    yf_price: float | None
    nse_price: float | None
    agreed: bool
    note: str


def cross_check_price(yf_last_close: float | None, nse_quote: dict | None,
                       tolerance_pct: float = 1.5) -> PriceCheck:
    """Compare Yahoo Finance's last close against NSE's latest traded price.

    A mismatch beyond `tolerance_pct` is expected sometimes (NSE quote is
    live/latest, yfinance daily close is end-of-day) -- it's surfaced in the
    report as a transparency note, not treated as an error.
    """
    nse_price = nse_quote["last_price"] if nse_quote else None
    if yf_last_close is None and nse_price is None:
        return PriceCheck(None, None, False, "No price data available from either source.")
    if yf_last_close is None:
        return PriceCheck(None, nse_price, False, "Yahoo Finance unavailable; using NSE quote only.")
    if nse_price is None:
        return PriceCheck(yf_last_close, None, False, "NSE quote unavailable; using Yahoo Finance only.")

    diff_pct = abs(yf_last_close - nse_price) / max(nse_price, 1e-9) * 100
    if diff_pct <= tolerance_pct:
        return PriceCheck(yf_last_close, nse_price, True, "Yahoo Finance and NSE agree.")
    return PriceCheck(
        yf_last_close, nse_price, False,
        f"Yahoo Finance ({yf_last_close:.2f}) and NSE ({nse_price:.2f}) differ by {diff_pct:.1f}% "
        f"-- likely a stale/delayed quote from one source; treat levels with extra caution.",
    )
