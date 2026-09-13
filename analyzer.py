"""
Core rule-based analysis engine -- v2.

Redesigned around a few explicit principles (see README's "Rule engine v2"
section for the full audit that motivated this):

1. Every scoring factor is additive and weighted (config.WEIGHTS_*), so the
   0-100 score is always traceable back to named, individually-visible
   contributions (score_breakdown on TradeIdea) -- never a bare number.
2. Correlated indicators are merged into ONE factor with an explicit
   agreement/conflict rule (see _momentum_short/_momentum_long), instead of
   being scored independently and summed -- a stock no longer racks up
   points three times for what is substantially one "momentum turning up"
   signal (RSI + MACD + Bollinger all measure overlapping information).
3. Market regime (NIFTY) and sector trend are real, meaningfully-weighted
   factors IN the score (not cosmetic labels) -- a hostile market/sector
   structurally caps how high any stock's score can go.
4. SCORE (how many rule-based conditions line up) and CONFIDENCE (how much
   the available evidence agrees, and how complete the data is) are
   separate numbers -- conflating them was a real gap in v1.
5. Entry zones are structure-derived (breakout / pullback / trend
   continuation), and a stock that has already run too far past its entry
   zone is flagged "ENTRY MISSED -- DO NOT CHASE" rather than silently
   re-centering the entry on wherever price currently is.
6. This is long-only, retail NSE cash-equity in scope (no F&O, no
   shorting -- established scope). Signals are STRONG BUY / BUY / WATCH /
   NO TRADE for new entries. There is no fabricated SELL/STRONG SELL entry
   signal, since retail cash accounts can't act on one; "should I exit an
   existing position" is answered by positions.py's target/stop-loss
   tracking instead.

DESIGN NOTE -- shared with the backtester (backtest.py): all indicators
(and, as of v2, market regime) are computed ONCE per stock/index into a
full-history bundle, and every scoring function takes that bundle plus a
row position `idx` (defaulting to the latest row). Because pandas rolling /
ewm windows at position i only ever look at positions <= i, reading
`.iloc[idx]` from a bundle built off the *entire* history is point-in-time
safe with no lookahead bias -- and it's the SAME code path live runs and
backtests use, so a backtest result can't silently diverge from what
actually runs live.

This is a heuristic technical + regime/sector screener, not a validated
alpha model or financial advice -- see README.md for the full disclaimer
and the real, measured backtest numbers (including where it does NOT show
a demonstrated edge). Never claim a specific win-probability or accuracy
figure that hasn't actually been measured via out-of-sample backtesting.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config as cfg
import indicators as ind

CATEGORY_INTRADAY = "Intraday"
CATEGORY_SHORT_TERM = "Short-Term (Swing)"
CATEGORY_LONG_TERM = "Long-Term"

SIGNAL_STRONG_BUY = "STRONG BUY"
SIGNAL_BUY = "BUY"
SIGNAL_WATCH = "WATCH"
SIGNAL_NO_TRADE = "NO TRADE"

ENTRY_BREAKOUT = "Breakout entry"
ENTRY_PULLBACK = "Pullback / support-bounce entry"
ENTRY_CONTINUATION = "Trend-continuation entry"
ENTRY_MISSED = "ENTRY MISSED -- DO NOT CHASE"


@dataclass
class TradeIdea:
    symbol: str
    category: str
    score: float                 # 0-100, weighted-factor sum (see score_breakdown)
    last_price: float
    entry_low: float
    entry_high: float
    target1: float
    target2: float
    stop_loss: float
    horizon: str
    reasons: list[str] = field(default_factory=list)
    data_note: str = ""
    rr_ratio: float = 0.0
    target1_pct: float = 0.0
    target2_pct: float = 0.0
    stop_loss_pct: float = 0.0
    # v2 fields (all have safe defaults so older callers/tests still work)
    confidence: float = 0.0            # 0-100, separate from score -- see module docstring
    grade: str | None = None           # "A+" | "A" | "B" | "C" | None (below C floor)
    signal: str = SIGNAL_NO_TRADE
    score_breakdown: dict = field(default_factory=dict)  # factor name -> (points_earned, max_points)
    market_regime_label: str = "UNKNOWN"
    sector_ticker: str | None = None
    sector_trend: str = "UNKNOWN"
    relative_strength_pct: float | None = None
    entry_type: str = ENTRY_CONTINUATION
    chase_flag: bool = False
    data_quality_ok: bool = True
    data_quality_note: str = ""

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
    atr_pct: pd.Series
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
    atr14 = ind.atr(df, 14)
    return IndicatorBundle(
        close=close,
        sma20=ind.sma(close, 20),
        sma50=ind.sma(close, 50),
        sma200=ind.sma(close, 200),
        rsi14=ind.rsi(close, 14),
        macd_line=macd_line, signal_line=signal_line, hist=hist,
        upper_bb=upper_bb, mid_bb=mid_bb, lower_bb=lower_bb,
        vol_sma20=vol_sma20, vol_sma60=vol_sma60,
        vol_ratio20=df["Volume"] / vol_sma20.replace(0, np.nan),
        atr14=atr14,
        atr_pct=(atr14 / close) * 100,
        support20=df["Low"].rolling(20, min_periods=1).min(),
        resistance20=df["High"].rolling(20, min_periods=1).max(),
        high52w=df["High"].rolling(252, min_periods=1).max(),
    )


def _resolve_idx(series: pd.Series, idx: int | None) -> int:
    if idx is None:
        return len(series) - 1
    return idx if idx >= 0 else len(series) + idx


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Data quality gate
# ---------------------------------------------------------------------------

def check_data_quality(df: pd.DataFrame, idx: int, now: pd.Timestamp | None = None) -> tuple[bool, str]:
    """Returns (ok, note). A caller that gets ok=False should treat this as
    'DATA QUALITY INSUFFICIENT -- NO SIGNAL' rather than scoring on it."""
    if df is None or df.empty or idx >= len(df):
        return False, "No data available."

    if now is not None and idx == len(df) - 1:
        staleness_days = (now.normalize() - df.index[idx].normalize()).days
        if staleness_days > cfg.MAX_STALE_DAYS:
            return False, f"Latest available bar is {staleness_days} days old -- data looks stale."

    if idx >= 1:
        prev_close = df["Close"].iloc[idx - 1]
        cur_close = df["Close"].iloc[idx]
        if prev_close and prev_close > 0:
            move_pct = abs(cur_close / prev_close - 1) * 100
            if move_pct > cfg.ABNORMAL_DAILY_MOVE_PCT:
                return False, (f"Abnormal single-day move of {move_pct:.0f}% detected -- possible corporate "
                               f"action (split/bonus/demerger) or bad print; verify before trusting this signal.")

    row = df.iloc[idx]
    if row[["Open", "High", "Low", "Close"]].isna().any() or row["Close"] <= 0:
        return False, "Missing or invalid OHLC values for this session."

    return True, ""


# ---------------------------------------------------------------------------
# Shared factor helpers (regime / sector / relative-strength / RR-quality /
# confidence / grading / signal classification) -- used by every category.
# ---------------------------------------------------------------------------

def _regime_fraction(regime_label: str | None) -> tuple[float, str]:
    label = regime_label or "NEUTRAL"
    frac = cfg.REGIME_SCORE_MULTIPLIER.get(label, 0.55)
    note = f"Market regime (NIFTY 50): {label}." if regime_label else "Market regime not evaluated for this run (defaulted to neutral)."
    return frac, note


def _sector_fraction(sector_confirmation) -> tuple[float, list[str], str | None, str]:
    if sector_confirmation is None:
        return cfg.SECTOR_SCORE_MULTIPLIER["NO_SECTOR_DATA"], ["Sector confirmation not evaluated for this run."], None, "UNKNOWN"
    frac = cfg.SECTOR_SCORE_MULTIPLIER.get(sector_confirmation.alignment, 0.60)
    return frac, list(sector_confirmation.reasons), sector_confirmation.sector_ticker, sector_confirmation.sector_trend


def _relative_strength_fraction(rel_strength_pct: float | None) -> tuple[float, str]:
    if rel_strength_pct is None:
        return 0.5, "Relative strength vs NIFTY unavailable today."
    lo, hi = cfg.RS_WEAK_UNDERPERFORM_PP, cfg.RS_STRONG_OUTPERFORM_PP
    frac = _clamp01((rel_strength_pct - lo) / (hi - lo)) if hi > lo else 0.5
    tag = "outperforming" if rel_strength_pct >= 0 else "underperforming"
    return frac, f"Relative strength vs NIFTY: {rel_strength_pct:+.1f}pp ({tag})."


def _rr_quality_fraction(rr: float) -> float:
    if rr <= 0:
        return 0.0
    if rr <= cfg.RR_MIN_ACCEPTABLE:
        return 0.15 * (rr / cfg.RR_MIN_ACCEPTABLE)
    if rr >= cfg.RR_GOOD:
        return 1.0
    return 0.15 + 0.85 * (rr - cfg.RR_MIN_ACCEPTABLE) / (cfg.RR_GOOD - cfg.RR_MIN_ACCEPTABLE)


def _momentum_short(bundle: IndicatorBundle, idx: int) -> tuple[float, str]:
    """Merges MACD + RSI into ONE momentum verdict via an explicit
    agreement/conflict rule, instead of scoring each independently (which
    double-counts what is substantially one underlying signal)."""
    rsi = bundle.rsi14.iloc[idx]
    rsi_prev = bundle.rsi14.iloc[idx - 1] if idx >= 1 else rsi
    hist = bundle.hist.iloc[idx]
    hist_prev = bundle.hist.iloc[idx - 1] if idx >= 1 else None

    macd_bullish = pd.notna(hist) and hist > 0
    just_crossed = idx >= 1 and pd.notna(hist_prev) and pd.notna(hist) and hist_prev <= 0 < hist
    rsi_bullish = pd.notna(rsi) and 40 <= rsi <= 70 and rsi >= rsi_prev
    rsi_overbought = pd.notna(rsi) and rsi > 75
    rsi_bearish = pd.notna(rsi) and rsi < 35

    if just_crossed and rsi_bullish:
        return 1.0, "MACD just crossed bullish, confirmed by RSI turning up from a neutral zone -- momentum agreement."
    if macd_bullish and rsi_overbought:
        return 0.35, "MACD positive but RSI overbought -- momentum may already be extended."
    if macd_bullish and rsi_bearish:
        return 0.2, "MACD and RSI momentum readings conflict -- treat with caution."
    if macd_bullish and rsi_bullish:
        return 0.85, "MACD and RSI both support upward momentum."
    if macd_bullish or rsi_bullish:
        return 0.5, "Only one of MACD/RSI supports momentum -- partial confirmation."
    return 0.0, "No clear momentum confirmation from MACD/RSI."


def _momentum_long(bundle: IndicatorBundle, idx: int) -> tuple[float, str]:
    rsi = bundle.rsi14.iloc[idx]
    macd_line = bundle.macd_line.iloc[idx]
    signal_line = bundle.signal_line.iloc[idx]
    macd_bullish = pd.notna(macd_line) and pd.notna(signal_line) and macd_line > signal_line
    rsi_healthy = pd.notna(rsi) and 45 <= rsi <= 65
    rsi_stretched = pd.notna(rsi) and 65 < rsi <= 75

    if macd_bullish and rsi_healthy:
        return 1.0, f"MACD above signal line and RSI at {rsi:.0f} -- healthy, agreeing medium-term momentum."
    if macd_bullish and rsi_stretched:
        return 0.6, f"MACD positive but RSI at {rsi:.0f} is stretched -- momentum intact but extended."
    if macd_bullish or rsi_healthy:
        return 0.5, "Only one of MACD/RSI supports medium-term momentum -- partial confirmation."
    return 0.0, "No clear medium-term momentum confirmation."


def _price_structure_short(bundle: IndicatorBundle, idx: int, price: float) -> tuple[float, str]:
    sma20 = bundle.sma20.iloc[idx]
    sma50 = bundle.sma50.iloc[idx]
    upper = bundle.upper_bb.iloc[idx]
    lower = bundle.lower_bb.iloc[idx]
    trend_ok = pd.notna(sma20) and pd.notna(sma50) and price > sma20 > sma50
    breakout = pd.notna(upper) and price > upper
    prev_close = bundle.close.iloc[idx - 1] if idx >= 1 else price
    prev_lower = bundle.lower_bb.iloc[idx - 1] if idx >= 1 else None
    bounce = idx >= 1 and prev_lower is not None and pd.notna(prev_lower) and prev_close <= prev_lower * 1.01 and pd.notna(lower) and price > lower

    if trend_ok and breakout:
        return 1.0, "Price above a rising 20/50-day SMA structure AND breaking the upper Bollinger Band."
    if trend_ok:
        return 0.75, "Price above a rising 20-day SMA, itself above the 50-day SMA."
    if bounce:
        return 0.55, "Bounced off the lower Bollinger Band -- potential mean-reversion structure."
    return 0.0, "No clear supportive price structure."


def _volatility_profile(atr_pct: float) -> tuple[float, str]:
    if pd.isna(atr_pct):
        return 0.5, "Volatility profile unavailable."
    if atr_pct <= 3.0:
        return 1.0, f"ATR is {atr_pct:.1f}% of price -- orderly volatility."
    if atr_pct <= 5.0:
        return 0.5, f"ATR is {atr_pct:.1f}% of price -- moderately choppy."
    return 0.0, f"ATR is {atr_pct:.1f}% of price -- excessively volatile for a clean setup."


def _grade_from_score(score: float) -> str | None:
    for grade, floor in (("A+", cfg.GRADE_THRESHOLDS["A+"]), ("A", cfg.GRADE_THRESHOLDS["A"]),
                          ("B", cfg.GRADE_THRESHOLDS["B"]), ("C", cfg.GRADE_THRESHOLDS["C"])):
        if score >= floor:
            return grade
    return None


def _classify_signal(grade: str | None, chase_flag: bool, rr: float, regime_label: str) -> str:
    if grade is None:
        return SIGNAL_NO_TRADE
    if rr < cfg.RR_MIN_ACCEPTABLE:
        return SIGNAL_WATCH  # decent score but the math doesn't justify the risk taken
    if chase_flag:
        return SIGNAL_WATCH  # good setup, but price has already run -- wait for a better entry
    if regime_label == "STRONG_BEARISH" and grade in ("B", "C"):
        return SIGNAL_NO_TRADE  # don't fight a hostile tape on a merely-decent setup
    if grade == "A+":
        return SIGNAL_STRONG_BUY
    if grade == "A":
        return SIGNAL_BUY
    return SIGNAL_WATCH  # B/C grades: real setup, but selective/lower-conviction


def _compute_confidence(breakdown: dict[str, tuple[float, float]], data_flags: dict[str, bool]) -> float:
    """Confidence = what fraction of factors are in strong agreement
    (>=70% of their own max), penalized for missing data sources. This is
    deliberately NOT calibrated to a win-probability -- it's an honest
    'how much of the evidence agrees' measure, not a fabricated percentage."""
    scored = [(pts, mx) for pts, mx in breakdown.values() if mx > 0]
    if not scored:
        return 0.0
    agreeing = sum(1 for pts, mx in scored if pts / mx >= 0.7)
    base = agreeing / len(scored) * 100
    penalty = sum(5 for flag in data_flags.values() if flag)
    return round(max(0.0, min(100.0, base - penalty)), 1)


def _entry_and_chase(price: float, atr_value: float, support: float, resistance: float,
                      near_breakout: bool, near_pullback: bool) -> tuple[float, float, str, bool]:
    """Structure-derived entry zone, with chase detection: if price has
    already moved more than CHASE_ATR_MULTIPLE x ATR beyond the ideal
    entry, flag it instead of silently re-centering on current price."""
    if near_breakout and resistance > 0:
        entry_low, entry_high, entry_type = resistance * 0.997, resistance * 1.01, ENTRY_BREAKOUT
    elif near_pullback and support > 0:
        entry_low, entry_high, entry_type = support * 0.995, support * 1.02, ENTRY_PULLBACK
    else:
        entry_low, entry_high, entry_type = price * 0.998, price * 1.006, ENTRY_CONTINUATION

    chase_flag = price > entry_high + cfg.CHASE_ATR_MULTIPLE * atr_value
    return entry_low, entry_high, entry_type, chase_flag


def _levels_from_atr(price: float, atr_value: float, support: float, resistance: float,
                      sl_mult: float, t1_mult: float, t2_mult: float) -> tuple[float, float, float]:
    """Target/stop-loss math (entry is handled separately by
    _entry_and_chase now). Blends ATR with real support/resistance, taking
    whichever is more conservative (tighter) for the stop-loss."""
    atr_sl = price - sl_mult * atr_value
    stop_loss = max(atr_sl, support * 0.995) if support > 0 else atr_sl
    stop_loss = min(stop_loss, price * 0.995)

    atr_t1 = price + t1_mult * atr_value
    target1 = min(atr_t1, resistance * 1.01) if resistance > price else atr_t1
    target1 = max(target1, price * 1.002)

    target2 = price + t2_mult * atr_value
    return target1, target2, stop_loss


def _finalize_idea(symbol: str, category: str, price: float, entry_low: float, entry_high: float,
                    target1: float, target2: float, stop_loss: float, horizon: str, entry_type: str,
                    chase_flag: bool, breakdown: dict, reasons: list[str], data_note: str,
                    regime_label: str, sector_ticker: str | None, sector_trend: str,
                    relative_strength_pct: float | None, data_flags: dict[str, bool]) -> TradeIdea:
    risk = max(price - stop_loss, 0.01)
    reward = max(target1 - price, 0)
    rr = round(reward / risk, 2)

    rr_frac = _rr_quality_fraction(rr)
    rr_max = breakdown["Risk/Reward Quality"][1] if "Risk/Reward Quality" in breakdown else 0
    breakdown["Risk/Reward Quality"] = (round(rr_max * rr_frac, 1), rr_max)
    if rr < cfg.RR_MIN_ACCEPTABLE:
        reasons.append(f"Risk:Reward to Target 1 is only {rr:.2f}:1 -- below the {cfg.RR_MIN_ACCEPTABLE}:1 minimum bar.")
    else:
        reasons.append(f"Risk:Reward to Target 1 is {rr:.2f}:1.")

    final_score = round(min(100.0, sum(pts for pts, _ in breakdown.values())), 1)
    grade = _grade_from_score(final_score)
    confidence = _compute_confidence(breakdown, data_flags)
    signal = _classify_signal(grade, chase_flag, rr, regime_label)

    if chase_flag:
        reasons.append(f"Price has moved >{cfg.CHASE_ATR_MULTIPLE}x ATR beyond the ideal entry zone -- {ENTRY_MISSED}.")

    return TradeIdea(
        symbol=symbol, category=category, score=final_score, last_price=round(price, 2),
        entry_low=round(entry_low, 2), entry_high=round(entry_high, 2),
        target1=round(target1, 2), target2=round(target2, 2), stop_loss=round(stop_loss, 2),
        horizon=horizon, reasons=reasons, data_note=data_note, rr_ratio=rr,
        target1_pct=round((target1 / price - 1) * 100, 2), target2_pct=round((target2 / price - 1) * 100, 2),
        stop_loss_pct=round((stop_loss / price - 1) * 100, 2),
        confidence=confidence, grade=grade, signal=signal, score_breakdown=breakdown,
        market_regime_label=regime_label, sector_ticker=sector_ticker, sector_trend=sector_trend,
        relative_strength_pct=relative_strength_pct, entry_type=entry_type if not chase_flag else ENTRY_MISSED,
        chase_flag=chase_flag, data_quality_ok=True, data_quality_note="",
    )


def _no_trade_idea(symbol: str, category: str, price: float, reason: str) -> TradeIdea:
    return TradeIdea(
        symbol=symbol, category=category, score=0.0, last_price=round(price, 2) if price else 0.0,
        entry_low=0.0, entry_high=0.0, target1=0.0, target2=0.0, stop_loss=0.0, horizon="",
        reasons=[reason], data_note="", signal=SIGNAL_NO_TRADE, grade=None,
        data_quality_ok=False, data_quality_note=reason,
    )


# ---------------------------------------------------------------------------
# Category evaluators -- each returns a complete TradeIdea (scoring +
# levels + grading in one traceable pass).
# ---------------------------------------------------------------------------

def score_long_term(symbol: str, bundle: IndicatorBundle, idx: int | None = None,
                     regime_label: str | None = None, sector_confirmation=None,
                     data_note: str = "", data_quality_now: pd.Timestamp | None = None) -> TradeIdea:
    idx = _resolve_idx(bundle.close, idx)
    price = float(bundle.close.iloc[idx])
    W = cfg.WEIGHTS_LONG_TERM
    breakdown: dict[str, tuple[float, float]] = {}
    reasons: list[str] = []
    data_flags = {"nse_unavailable": "unavailable" in data_note.lower()}

    regime_frac, regime_note = _regime_fraction(regime_label)
    breakdown["Market Regime"] = (round(W["Market Regime"] * regime_frac, 1), W["Market Regime"])
    reasons.append(regime_note)

    sector_frac, sector_reasons, sector_ticker, sector_trend = _sector_fraction(sector_confirmation)
    breakdown["Sector Strength"] = (round(W["Sector Strength"] * sector_frac, 1), W["Sector Strength"])
    reasons.extend(sector_reasons)
    data_flags["sector_unavailable"] = sector_confirmation is None or sector_ticker is None

    sma50, sma200 = bundle.sma50.iloc[idx], bundle.sma200.iloc[idx]
    high_52w = float(bundle.high52w.iloc[idx])
    trend_frac = 0.0
    if pd.notna(sma200) and price > sma200:
        trend_frac += 0.40
        reasons.append("Price is above the 200-day SMA (established long-term uptrend).")
    if pd.notna(sma50) and pd.notna(sma200) and sma50 > sma200:
        trend_frac += 0.30
        reasons.append("50-day SMA is above the 200-day SMA (golden-cross regime).")
    if pd.notna(sma50) and price > sma50:
        trend_frac += 0.15
        reasons.append("Price is above the 50-day SMA.")
    pct_from_high = (high_52w - price) / high_52w * 100 if high_52w > 0 else 100.0
    if pct_from_high <= 15:
        trend_frac += 0.15
        reasons.append(f"Trading within {pct_from_high:.0f}% of its 52-week high.")
    breakdown["Price Trend"] = (round(W["Price Trend"] * _clamp01(trend_frac), 1), W["Price Trend"])

    mom_frac, mom_reason = _momentum_long(bundle, idx)
    breakdown["Momentum"] = (round(W["Momentum"] * mom_frac, 1), W["Momentum"])
    reasons.append(mom_reason)

    vol_ratio = bundle.vol_sma20.iloc[idx] / max(bundle.vol_sma60.iloc[idx], 1)
    vol_frac = 1.0 if pd.notna(vol_ratio) and vol_ratio > 1.05 else 0.3
    breakdown["Volume Trend"] = (round(W["Volume Trend"] * vol_frac, 1), W["Volume Trend"])
    if vol_frac == 1.0:
        reasons.append("20-day average volume is rising vs the 60-day average.")

    rs_pct = sector_confirmation.relative_strength_pct if sector_confirmation else None
    rs_frac, rs_reason = _relative_strength_fraction(rs_pct)
    breakdown["Relative Strength"] = (round(W["Relative Strength"] * rs_frac, 1), W["Relative Strength"])
    reasons.append(rs_reason)

    breakdown["Risk/Reward Quality"] = (0.0, W["Risk/Reward Quality"])  # finalized after levels

    atr_value = float(bundle.atr14.iloc[idx])
    support, resistance = float(bundle.support20.iloc[idx]), float(bundle.resistance20.iloc[idx])
    near_breakout = price > resistance * 0.995
    near_pullback = pd.notna(sma50) and abs(price - sma50) / price < 0.02
    entry_low, entry_high, entry_type, chase_flag = _entry_and_chase(
        price, atr_value, support, max(resistance, high_52w), near_breakout, near_pullback)

    m = cfg.ATR_MULTIPLIERS["long_term"]
    target1, target2, stop_loss = _levels_from_atr(
        price, atr_value, 0, max(resistance, high_52w), sl_mult=m["sl"], t1_mult=m["t1"], t2_mult=m["t2"])

    return _finalize_idea(
        symbol, CATEGORY_LONG_TERM, price, entry_low, entry_high, target1, target2, stop_loss,
        "3-6+ months (positional)", entry_type, chase_flag, breakdown, reasons, data_note,
        regime_label or "NEUTRAL", sector_ticker, sector_trend, rs_pct, data_flags,
    )


def score_short_term(symbol: str, bundle: IndicatorBundle, idx: int | None = None,
                      regime_label: str | None = None, sector_confirmation=None,
                      data_note: str = "", data_quality_now: pd.Timestamp | None = None) -> TradeIdea:
    idx = _resolve_idx(bundle.close, idx)
    price = float(bundle.close.iloc[idx])
    W = cfg.WEIGHTS_SHORT_TERM
    breakdown: dict[str, tuple[float, float]] = {}
    reasons: list[str] = []
    data_flags = {"nse_unavailable": "unavailable" in data_note.lower()}

    regime_frac, regime_note = _regime_fraction(regime_label)
    breakdown["Market Regime"] = (round(W["Market Regime"] * regime_frac, 1), W["Market Regime"])
    reasons.append(regime_note)

    sector_frac, sector_reasons, sector_ticker, sector_trend = _sector_fraction(sector_confirmation)
    breakdown["Sector Strength"] = (round(W["Sector Strength"] * sector_frac, 1), W["Sector Strength"])
    reasons.extend(sector_reasons)
    data_flags["sector_unavailable"] = sector_confirmation is None or sector_ticker is None

    mom_frac, mom_reason = _momentum_short(bundle, idx)
    breakdown["Momentum"] = (round(W["Momentum"] * mom_frac, 1), W["Momentum"])
    reasons.append(mom_reason)

    struct_frac, struct_reason = _price_structure_short(bundle, idx, price)
    breakdown["Price Structure"] = (round(W["Price Structure"] * struct_frac, 1), W["Price Structure"])
    reasons.append(struct_reason)

    vratio = bundle.vol_ratio20.iloc[idx]
    if pd.notna(vratio) and vratio > 1.5:
        vol_frac = 1.0
        reasons.append(f"Volume is {vratio:.1f}x the 20-day average -- strong confirmation.")
    elif pd.notna(vratio) and vratio > 1.1:
        vol_frac = 0.5
        reasons.append(f"Volume is {vratio:.1f}x the 20-day average -- decent participation.")
    else:
        vol_frac = 0.0
    breakdown["Volume Confirmation"] = (round(W["Volume Confirmation"] * vol_frac, 1), W["Volume Confirmation"])

    rs_pct = sector_confirmation.relative_strength_pct if sector_confirmation else None
    rs_frac, rs_reason = _relative_strength_fraction(rs_pct)
    breakdown["Relative Strength"] = (round(W["Relative Strength"] * rs_frac, 1), W["Relative Strength"])
    reasons.append(rs_reason)

    vol_profile_frac, vol_profile_reason = _volatility_profile(bundle.atr_pct.iloc[idx])
    breakdown["Volatility Profile"] = (round(W["Volatility Profile"] * vol_profile_frac, 1), W["Volatility Profile"])
    reasons.append(vol_profile_reason)

    breakdown["Risk/Reward Quality"] = (0.0, W["Risk/Reward Quality"])  # finalized after levels

    atr_value = float(bundle.atr14.iloc[idx])
    support, resistance = float(bundle.support20.iloc[idx]), float(bundle.resistance20.iloc[idx])
    sma20 = bundle.sma20.iloc[idx]
    near_breakout = price > resistance * 0.995
    near_pullback = pd.notna(sma20) and abs(price - sma20) / price < 0.015
    entry_low, entry_high, entry_type, chase_flag = _entry_and_chase(
        price, atr_value, support, resistance, near_breakout, near_pullback)

    m = cfg.ATR_MULTIPLIERS["short_term"]
    target1, target2, stop_loss = _levels_from_atr(
        price, atr_value, support, resistance, sl_mult=m["sl"], t1_mult=m["t1"], t2_mult=m["t2"])

    return _finalize_idea(
        symbol, CATEGORY_SHORT_TERM, price, entry_low, entry_high, target1, target2, stop_loss,
        "1-3 weeks (swing)", entry_type, chase_flag, breakdown, reasons, data_note,
        regime_label or "NEUTRAL", sector_ticker, sector_trend, rs_pct, data_flags,
    )


def score_intraday(symbol: str, daily_bundle: IndicatorBundle, intraday_df: pd.DataFrame | None,
                    regime_label: str | None = None, data_note: str = "") -> TradeIdea:
    """Not part of the point-in-time backtest (intraday squares off same
    day) -- only used by the live daily run, operating on the latest daily
    bundle plus today's freshest intraday fetch."""
    idx = len(daily_bundle.close) - 1
    price = float(daily_bundle.close.iloc[idx])
    prev_close = float(daily_bundle.close.iloc[idx - 1]) if idx >= 1 else price
    W = cfg.WEIGHTS_INTRADAY
    breakdown: dict[str, tuple[float, float]] = {}
    reasons: list[str] = []
    data_flags = {"nse_unavailable": "unavailable" in data_note.lower(),
                  "intraday_unavailable": intraday_df is None or intraday_df.empty}

    regime_frac, regime_note = _regime_fraction(regime_label)
    breakdown["Market Regime"] = (round(W["Market Regime"] * regime_frac, 1), W["Market Regime"])
    reasons.append(regime_note)

    daily_bullish = price > daily_bundle.sma50.iloc[idx] if pd.notna(daily_bundle.sma50.iloc[idx]) else None
    intraday_bullish = None
    or_high = or_low = None

    if intraday_df is None or intraday_df.empty:
        reasons.append("Intraday (15-min) data unavailable today -- scored on daily setup only.")
        breakdown["VWAP Position"] = (0.0, W["VWAP Position"])
        breakdown["Opening Range Breakout"] = (0.0, W["Opening Range Breakout"])
        breakdown["Volume Surge"] = (0.0, W["Volume Surge"])
        breakdown["Gap Analysis"] = (0.0, W["Gap Analysis"])
    else:
        vw = ind.vwap(intraday_df)
        last_price = float(intraday_df["Close"].iloc[-1])
        last_vwap = float(vw.iloc[-1])
        vwap_bullish = last_price > last_vwap
        breakdown["VWAP Position"] = (W["VWAP Position"] if vwap_bullish else 0.0, W["VWAP Position"])
        if vwap_bullish:
            reasons.append("Trading above today's VWAP -- intraday buyers in control.")
        intraday_bullish = vwap_bullish

        session_today = intraday_df[intraday_df.index.date == intraday_df.index[-1].date()]
        or_frac = 0.0
        if len(session_today) >= 5:
            opening_range = session_today.iloc[:4]
            or_high = float(opening_range["High"].max())
            or_low = float(opening_range["Low"].min())
            if last_price > or_high:
                or_frac = 1.0
                reasons.append(f"Broken above the opening-range high (~{or_high:.1f}) -- bullish breakout setup.")
            elif last_price < or_low:
                reasons.append(f"Trading below the opening-range low (~{or_low:.1f}) -- weak setup.")
        breakdown["Opening Range Breakout"] = (round(W["Opening Range Breakout"] * or_frac, 1), W["Opening Range Breakout"])

        vr = ind.volume_ratio(intraday_df["Volume"], min(20, len(intraday_df) - 1)).iloc[-1]
        vsurge_frac = 1.0 if pd.notna(vr) and vr > 1.5 else 0.0
        breakdown["Volume Surge"] = (round(W["Volume Surge"] * vsurge_frac, 1), W["Volume Surge"])
        if vsurge_frac:
            reasons.append(f"Intraday volume running {vr:.1f}x its recent average -- confirms the move.")

        gap_pct = (float(session_today["Open"].iloc[0]) - prev_close) / prev_close * 100 if len(session_today) else 0
        gap_frac = 1.0 if 0.3 <= gap_pct <= 3 else 0.0
        breakdown["Gap Analysis"] = (round(W["Gap Analysis"] * gap_frac, 1), W["Gap Analysis"])
        if gap_frac:
            reasons.append(f"Opened with a healthy gap-up of {gap_pct:.1f}% and holding.")

    # Multi-timeframe conflict check: does the higher (daily) timeframe
    # agree with the lower (15-min) execution timeframe? A 5/15-min bullish
    # signal inside a bearish daily trend is explicitly flagged, not
    # silently allowed to override the higher timeframe.
    if daily_bullish is not None and intraday_bullish is not None:
        if daily_bullish and intraday_bullish:
            align_frac = 1.0
        elif daily_bullish is False and intraday_bullish:
            align_frac = 0.15
            reasons.append("CONFLICT: daily trend is below its 50-day SMA while the intraday setup looks bullish -- elevated reversal risk.")
        else:
            align_frac = 0.5
    else:
        align_frac = 0.5
    breakdown["Daily Trend Alignment"] = (round(W["Daily Trend Alignment"] * align_frac, 1), W["Daily Trend Alignment"])

    rsi14 = daily_bundle.rsi14.iloc[idx]
    rsi_frac = 1.0 if pd.notna(rsi14) and 45 <= rsi14 <= 70 else 0.3
    breakdown["Daily RSI Support"] = (round(W["Daily RSI Support"] * rsi_frac, 1), W["Daily RSI Support"])
    if rsi_frac == 1.0:
        reasons.append(f"Daily RSI(14) at {rsi14:.0f} supports further upside without being extended.")

    breakdown["Risk/Reward Quality"] = (0.0, 0.0)  # not a separate weighted factor for intraday (already implicit in tight ATR-based levels)

    atr_value = float(daily_bundle.atr14.iloc[idx]) * 0.35  # heuristic: intraday range is a fraction of daily ATR
    support, resistance = float(daily_bundle.support20.iloc[idx]), float(daily_bundle.resistance20.iloc[idx])
    if or_high and price > or_high * 0.995:
        entry_low, entry_high, entry_type = or_high * 0.998, or_high * 1.005, ENTRY_BREAKOUT
    else:
        entry_low, entry_high, entry_type = price * 0.998, price * 1.006, ENTRY_CONTINUATION
    chase_flag = price > entry_high + cfg.CHASE_ATR_MULTIPLE * atr_value

    m = cfg.ATR_MULTIPLIERS["intraday"]
    target1, target2, stop_loss = _levels_from_atr(
        price, atr_value, support, resistance, sl_mult=m["sl"], t1_mult=m["t1"], t2_mult=m["t2"])

    return _finalize_idea(
        symbol, CATEGORY_INTRADAY, price, entry_low, entry_high, target1, target2, stop_loss,
        "Intraday -- square off same session", entry_type, chase_flag, breakdown, reasons, data_note,
        regime_label or "NEUTRAL", None, "UNKNOWN", None, data_flags,
    )


def rank_and_select(ideas: list[TradeIdea], top_n: int = 3, min_score: float = 40.0) -> list[TradeIdea]:
    qualified = [i for i in ideas if i.data_quality_ok and i.score >= min_score and i.signal != SIGNAL_NO_TRADE]
    qualified.sort(key=lambda i: i.score, reverse=True)
    return qualified[:top_n]
