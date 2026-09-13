"""
Core rule-based analysis engine.

For every stock we compute a transparent, explainable 0-100 score in each
of three horizons (Intraday / Short-Term swing / Long-Term), derive entry /
target / stop-loss levels from ATR and recent support-resistance, and keep
the plain-English reasons behind the score so the email can show its work.

This is a heuristic technical screener, not a backtested alpha model or
financial advice -- see README.md for the full disclaimer. Treat the score
as "how many textbook bullish conditions line up right now", not a
probability of profit.

DESIGN NOTE -- shared with the backtester (backtest.py): all indicators are
computed ONCE per stock into an `IndicatorBundle` of full-history Series
(compute_bundle), and every scoring/level function takes that bundle plus a
row position `idx` (defaulting to the latest row). Because pandas rolling /
ewm windows at position i only ever look at positions <= i, reading
`.iloc[idx]` from a bundle built off the *entire* history is exactly
equivalent to truncating the DataFrame to that day and recomputing from
scratch -- i.e. it's point-in-time safe, with no lookahead bias, and it's
the SAME code path live runs and backtests use. This matters: a backtest
that quietly reimplements the rules separately can silently drift from what
actually runs live, making its results meaningless.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import indicators as ind

CATEGORY_INTRADAY = "Intraday"
CATEGORY_SHORT_TERM = "Short-Term (Swing)"
CATEGORY_LONG_TERM = "Long-Term"


@dataclass
class TradeIdea:
    symbol: str
    category: str
    score: float
    last_price: float
    entry_low: float
    entry_high: float
    target1: float
    target2: float
    stop_loss: float
    horizon: str
    reasons: list[str] = field(default_factory=list)
    data_note: str = ""
    rr_ratio: float = 0.0  # reward:risk on target1
    target1_pct: float = 0.0   # % gain from last_price if target1 is hit
    target2_pct: float = 0.0   # % gain from last_price if target2 is hit
    stop_loss_pct: float = 0.0  # % loss from last_price if stop-loss is hit (negative)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class IndicatorBundle:
    """All indicator series computed once over a stock's full daily history."""
    close: pd.Series
    sma20: pd.Series
    sma50: pd.Series
    sma200: pd.Series
    rsi14: pd.Series
    macd_line: pd.Series
    signal_line: pd.Series
    hist: pd.Series
    upper_bb: pd.Series
    mid_bb: pd.Series
    lower_bb: pd.Series
    vol_sma20: pd.Series
    vol_sma60: pd.Series
    vol_ratio20: pd.Series
    atr14: pd.Series
    support20: pd.Series
    resistance20: pd.Series
    high52w: pd.Series


def compute_bundle(df: pd.DataFrame) -> IndicatorBundle:
    """Compute every indicator series once (vectorized) over the full
    history in `df`. Reading `.iloc[idx]` from the result for any idx is
    point-in-time correct -- see module docstring."""
    close = df["Close"]
    macd_line, signal_line, hist = ind.macd(close)
    upper_bb, mid_bb, lower_bb = ind.bollinger_bands(close, 20, 2)
    vol_sma20 = ind.sma(df["Volume"], 20)
    vol_sma60 = ind.sma(df["Volume"], 60)
    return IndicatorBundle(
        close=close,
        sma20=ind.sma(close, 20),
        sma50=ind.sma(close, 50),
        sma200=ind.sma(close, 200),
        rsi14=ind.rsi(close, 14),
        macd_line=macd_line,
        signal_line=signal_line,
        hist=hist,
        upper_bb=upper_bb,
        mid_bb=mid_bb,
        lower_bb=lower_bb,
        vol_sma20=vol_sma20,
        vol_sma60=vol_sma60,
        vol_ratio20=df["Volume"] / vol_sma20.replace(0, np.nan),
        atr14=ind.atr(df, 14),
        support20=df["Low"].rolling(20, min_periods=1).min(),
        resistance20=df["High"].rolling(20, min_periods=1).max(),
        high52w=df["High"].rolling(252, min_periods=1).max(),
    )


def _resolve_idx(series: pd.Series, idx: int | None) -> int:
    if idx is None:
        return len(series) - 1
    return idx if idx >= 0 else len(series) + idx


def _clamp_score(x: float) -> float:
    return max(0.0, min(100.0, x))


def score_long_term(bundle: IndicatorBundle, idx: int | None = None) -> tuple[float, list[str]]:
    idx = _resolve_idx(bundle.close, idx)
    price = float(bundle.close.iloc[idx])
    sma50, sma200 = bundle.sma50, bundle.sma200
    rsi14 = bundle.rsi14
    macd_line, signal_line = bundle.macd_line, bundle.signal_line
    vol_ratio_20_60 = bundle.vol_sma20.iloc[idx] / max(bundle.vol_sma60.iloc[idx], 1)
    high_52w = float(bundle.high52w.iloc[idx])

    score, reasons = 0.0, []

    if pd.notna(sma200.iloc[idx]) and price > sma200.iloc[idx]:
        score += 20
        reasons.append("Price is above the 200-day SMA (established long-term uptrend).")

    if pd.notna(sma50.iloc[idx]) and pd.notna(sma200.iloc[idx]) and sma50.iloc[idx] > sma200.iloc[idx]:
        score += 15
        reasons.append("50-day SMA is above the 200-day SMA (golden-cross regime, bullish structure).")

    if pd.notna(sma50.iloc[idx]) and price > sma50.iloc[idx]:
        score += 15
        reasons.append("Price is above the 50-day SMA.")

    r = rsi14.iloc[idx]
    if 45 <= r <= 65:
        score += 15
        reasons.append(f"RSI(14) at {r:.0f} is in a healthy zone (trending, not yet overbought).")
    elif 65 < r <= 75:
        score += 7
        reasons.append(f"RSI(14) at {r:.0f} is strong but getting stretched -- fine for long-term, watch for a pullback entry.")

    if pd.notna(high_52w) and high_52w > 0:
        pct_from_high = (high_52w - price) / high_52w * 100
        if pct_from_high <= 15:
            score += 15
            reasons.append(f"Trading within {pct_from_high:.0f}% of its 52-week high -- participating in the uptrend.")

    if pd.notna(vol_ratio_20_60) and vol_ratio_20_60 > 1.05:
        score += 10
        reasons.append("20-day average volume is rising vs the 60-day average (growing participation).")

    if pd.notna(macd_line.iloc[idx]) and pd.notna(signal_line.iloc[idx]) and macd_line.iloc[idx] > signal_line.iloc[idx]:
        score += 10
        reasons.append("MACD line is above its signal line (positive medium-term momentum).")

    return _clamp_score(score), reasons


def score_short_term(bundle: IndicatorBundle, idx: int | None = None) -> tuple[float, list[str]]:
    idx = _resolve_idx(bundle.close, idx)
    price = float(bundle.close.iloc[idx])
    sma20, sma50 = bundle.sma20, bundle.sma50
    rsi14 = bundle.rsi14
    hist = bundle.hist
    upper_bb, mid_bb, lower_bb = bundle.upper_bb, bundle.mid_bb, bundle.lower_bb
    vratio = bundle.vol_ratio20.iloc[idx]

    score, reasons = 0.0, []

    # MACD bullish crossover in the last session
    if idx >= 1 and pd.notna(hist.iloc[idx - 1]) and pd.notna(hist.iloc[idx]) and hist.iloc[idx - 1] <= 0 < hist.iloc[idx]:
        score += 25
        reasons.append("MACD just crossed bullish (signal line crossover in the last session).")
    elif pd.notna(hist.iloc[idx]) and hist.iloc[idx] > 0:
        score += 12
        reasons.append("MACD histogram is positive (momentum favors buyers).")

    r = rsi14.iloc[idx]
    r_prev = rsi14.iloc[idx - 1] if idx >= 1 else r
    if 40 <= r <= 60 and r > r_prev:
        score += 20
        reasons.append(f"RSI(14) at {r:.0f} and turning up from a neutral zone -- room to run before overbought.")
    elif 60 < r <= 70:
        score += 10
        reasons.append(f"RSI(14) at {r:.0f} shows solid momentum.")

    if pd.notna(sma20.iloc[idx]) and price > sma20.iloc[idx] > (sma50.iloc[idx] if pd.notna(sma50.iloc[idx]) else 0):
        score += 15
        reasons.append("Price above a rising 20-day SMA, itself above the 50-day SMA (short-term uptrend intact).")

    if pd.notna(lower_bb.iloc[idx]) and pd.notna(mid_bb.iloc[idx]):
        prev_close = bundle.close.iloc[idx - 1] if idx >= 1 else price
        prev_lower = lower_bb.iloc[idx - 1] if idx >= 1 else None
        if prev_lower is not None and pd.notna(prev_lower) and prev_close <= prev_lower * 1.01 and price > lower_bb.iloc[idx]:
            score += 15
            reasons.append("Bounced off the lower Bollinger Band -- potential mean-reversion entry.")
        elif price > upper_bb.iloc[idx]:
            score += 10
            reasons.append("Breaking above the upper Bollinger Band on the move -- momentum breakout.")

    if pd.notna(vratio) and vratio > 1.5:
        score += 15
        reasons.append(f"Volume is {vratio:.1f}x the 20-day average -- strong confirmation for the move.")
    elif pd.notna(vratio) and vratio > 1.1:
        score += 7
        reasons.append(f"Volume is {vratio:.1f}x the 20-day average -- decent participation.")

    return _clamp_score(score), reasons


def score_intraday(daily_df: pd.DataFrame, intraday_df: pd.DataFrame | None) -> tuple[float, list[str]]:
    """Not part of the 90-day backtest (intraday positions square off same
    day) -- kept operating directly on the latest daily/intraday fetch as
    before, only used by the live daily run."""
    score, reasons = 0.0, []
    close = daily_df["Close"]
    prev_close = float(close.iloc[-2]) if len(close) > 1 else float(close.iloc[-1])

    if intraday_df is None or intraday_df.empty:
        reasons.append("Intraday (15-min) data unavailable today -- score based on prior-day setup only.")
    else:
        vw = ind.vwap(intraday_df)
        last_price = float(intraday_df["Close"].iloc[-1])
        last_vwap = float(vw.iloc[-1])

        if last_price > last_vwap:
            score += 25
            reasons.append("Trading above today's VWAP -- intraday buyers in control.")

        # Opening range (first ~1 hour = first 4 candles of 15m data) breakout
        session_today = intraday_df[intraday_df.index.date == intraday_df.index[-1].date()]
        if len(session_today) >= 5:
            opening_range = session_today.iloc[:4]
            or_high = float(opening_range["High"].max())
            or_low = float(opening_range["Low"].min())
            if last_price > or_high:
                score += 25
                reasons.append(f"Broken above the opening-range high (~{or_high:.1f}) -- bullish breakout setup.")
            elif last_price < or_low:
                reasons.append(f"Trading below the opening-range low (~{or_low:.1f}) -- weak setup, deprioritized.")

        # Gap analysis
        gap_pct = (float(session_today["Open"].iloc[0]) - prev_close) / prev_close * 100 if len(session_today) else 0
        if 0.3 <= gap_pct <= 3:
            score += 15
            reasons.append(f"Opened with a healthy gap-up of {gap_pct:.1f}% and holding.")

        # Volume surge vs recent intraday average
        vr = ind.volume_ratio(intraday_df["Volume"], min(20, len(intraday_df) - 1)).iloc[-1]
        if pd.notna(vr) and vr > 1.5:
            score += 15
            reasons.append(f"Intraday volume running {vr:.1f}x its recent average -- confirms the move.")

    # Daily-level backdrop still matters for intraday bias
    rsi14 = ind.rsi(close, 14).iloc[-1]
    if 45 <= rsi14 <= 70:
        score += 20
        reasons.append(f"Daily RSI(14) at {rsi14:.0f} supports further upside without being extended.")

    return _clamp_score(score), reasons


def _levels_from_atr(price: float, atr_value: float, support: float, resistance: float,
                      sl_mult: float, t1_mult: float, t2_mult: float) -> tuple[float, float, float, float, float]:
    """Blend ATR-based levels with nearby swing support/resistance, taking
    whichever is more conservative (tighter) for the stop-loss, and the
    nearer of the two for target1."""
    atr_sl = price - sl_mult * atr_value
    stop_loss = max(atr_sl, support * 0.995) if support > 0 else atr_sl
    # never let SL sit above price due to bad data
    stop_loss = min(stop_loss, price * 0.995)

    atr_t1 = price + t1_mult * atr_value
    target1 = min(atr_t1, resistance * 1.01) if resistance > price else atr_t1
    target1 = max(target1, price * 1.002)

    target2 = price + t2_mult * atr_value

    entry_low = price * 0.998
    entry_high = price * 1.006
    return entry_low, entry_high, target1, target2, stop_loss


def build_idea(symbol: str, category: str, bundle: IndicatorBundle, idx: int | None,
               score: float, reasons: list[str], data_note: str) -> TradeIdea:
    idx = _resolve_idx(bundle.close, idx)
    price = float(bundle.close.iloc[idx])
    atr_value = float(bundle.atr14.iloc[idx])
    support = float(bundle.support20.iloc[idx])
    resistance = float(bundle.resistance20.iloc[idx])

    if category == CATEGORY_INTRADAY:
        intraday_atr = atr_value * 0.35  # heuristic: typical intraday range is a fraction of daily ATR
        entry_low, entry_high, t1, t2, sl = _levels_from_atr(
            price, intraday_atr, support, resistance, sl_mult=1.0, t1_mult=1.2, t2_mult=2.0)
        horizon = "Intraday -- square off same session"
    elif category == CATEGORY_SHORT_TERM:
        entry_low, entry_high, t1, t2, sl = _levels_from_atr(
            price, atr_value, support, resistance, sl_mult=1.5, t1_mult=2.0, t2_mult=3.2)
        horizon = "1-3 weeks (swing)"
    else:  # long-term
        high_52w = float(bundle.high52w.iloc[idx])
        # Deliberately do NOT blend in the 20-day support here: that lookback
        # is a swing-trading concept and would clamp the stop far too tight
        # for a multi-month hold (gets noise-stopped constantly). Pure ATR
        # gives the position room to breathe; the 20-day resistance is still
        # useful as a target1 cap so we don't overshoot past a real ceiling.
        entry_low, entry_high, t1, t2, sl = _levels_from_atr(
            price, atr_value, 0, max(resistance, high_52w), sl_mult=3.0, t1_mult=4.5, t2_mult=8.0)
        horizon = "3-6+ months (positional)"

    risk = max(price - sl, 0.01)
    reward = max(t1 - price, 0)
    rr = round(reward / risk, 2)

    return TradeIdea(
        symbol=symbol,
        category=category,
        score=round(score, 1),
        last_price=round(price, 2),
        entry_low=round(entry_low, 2),
        entry_high=round(entry_high, 2),
        target1=round(t1, 2),
        target2=round(t2, 2),
        stop_loss=round(sl, 2),
        horizon=horizon,
        reasons=reasons,
        data_note=data_note,
        rr_ratio=rr,
        target1_pct=round((t1 / price - 1) * 100, 2),
        target2_pct=round((t2 / price - 1) * 100, 2),
        stop_loss_pct=round((sl / price - 1) * 100, 2),
    )


def rank_and_select(ideas: list[TradeIdea], top_n: int = 3, min_score: float = 40.0) -> list[TradeIdea]:
    qualified = [i for i in ideas if i.score >= min_score]
    qualified.sort(key=lambda i: i.score, reverse=True)
    return qualified[:top_n]
