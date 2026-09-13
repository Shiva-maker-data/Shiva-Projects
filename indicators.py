"""
Technical indicator calculations, implemented directly on pandas Series/
DataFrames (no TA-Lib dependency, which is painful to install on Windows).

All functions are pure and side-effect free: given a price series / OHLCV
DataFrame, they return the indicator series/values.
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # avg_loss == 0 with real gains present means zero down-days in the
    # lookback -- maximally overbought (RSI=100), not "insufficient data".
    # Only fall back to neutral 50 when there's truly no data to judge from
    # (e.g. still within the warmup window, or a completely flat series).
    out = out.where(~((avg_loss == 0) & (avg_gain > 0)), 100.0)
    return out.fillna(50)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range. df must have High, Low, Close columns."""
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def volume_ratio(volume: pd.Series, window: int = 20) -> pd.Series:
    """Latest volume vs its trailing average -- >1 means above-average interest."""
    avg = volume.rolling(window=window, min_periods=window).mean()
    return volume / avg.replace(0, np.nan)


def recent_support_resistance(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Simple swing support/resistance from the last `lookback` sessions."""
    recent = df.tail(lookback)
    return float(recent["Low"].min()), float(recent["High"].max())


def week52_high_low(df: pd.DataFrame) -> tuple[float, float]:
    recent = df.tail(252)
    return float(recent["High"].max()), float(recent["Low"].min())


def vwap(df: pd.DataFrame) -> pd.Series:
    """Volume-weighted average price, computed cumulatively (for intraday df)."""
    typical_price = (df["High"] + df["Low"] + df["Close"]) / 3
    cum_vol = df["Volume"].cumsum().replace(0, np.nan)
    return (typical_price * df["Volume"]).cumsum() / cum_vol
