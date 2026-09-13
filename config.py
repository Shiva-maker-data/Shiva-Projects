"""
Centralized, named configuration for every scoring weight, threshold, and
multiplier used by the rule engine. Nothing in analyzer.py / market_regime.py
/ sector.py / position_sizing.py should have a bare magic number -- if a
value affects a decision, it lives here, named, with a comment explaining
its purpose. This is what makes every recommendation traceable back to an
explicit, auditable rule rather than a number buried in a formula.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Signal classification thresholds (post-regime-adjustment final score, 0-100)
# ---------------------------------------------------------------------------
# NOT blindly trusted as gospel -- backtest.py's score-bucket breakdown is
# what actually tells you whether higher buckets outperform lower ones for
# a given target. These are the *starting* thresholds to test against, per
# the spec's own instruction ("do not blindly use these if backtesting
# demonstrates better thresholds").
GRADE_THRESHOLDS = {
    "A+": 90,  # Exceptional setup
    "A": 80,   # Strong setup
    "B": 70,   # Watch / selective
    "C": 60,   # Weak
    # below 60 -> NO TRADE
}

# ---------------------------------------------------------------------------
# Market regime (NIFTY 50) classification -- see market_regime.py
# ---------------------------------------------------------------------------
REGIME_INDEX_TICKER = "^NSEI"  # NIFTY 50 index, used as the market-regime proxy
REGIME_SMA_FAST = 20
REGIME_SMA_SLOW = 50
REGIME_ATR_LOOKBACK = 14
REGIME_ATR_HISTORY_WINDOW = 100  # trailing window to judge "is ATR unusually high right now"
REGIME_HIGH_VOL_ATR_PCTILE = 85  # ATR% above this percentile of its own recent history -> "unstable"

# Fraction of the "Market Regime" factor's max points (see analyzer.py's
# weighted breakdown) awarded for each regime label. This is what actually
# implements "strong breakout + weak market = lower score": regime is a
# real, meaningfully-weighted line item IN the additive 100-point score
# (not a separate multiplier bolted on after, which would double-penalize
# in a way that's hard to reason about) -- a bearish market structurally
# caps how high any stock's score can go, because it can never earn full
# Market Regime points while the label is BEARISH/STRONG_BEARISH.
REGIME_SCORE_MULTIPLIER = {
    "STRONG_BULLISH": 1.00,
    "BULLISH": 0.85,
    "NEUTRAL": 0.55,
    "BEARISH": 0.25,
    "STRONG_BEARISH": 0.00,
    "HIGH_VOLATILITY": 0.30,  # unstable conditions -- suppress conviction regardless of direction
}

# ---------------------------------------------------------------------------
# Sector confirmation -- see sector.py
# ---------------------------------------------------------------------------
SECTOR_SMA_WINDOW = 20
# Fraction of the "Sector Strength" factor's max points. NO_SECTOR_DATA
# awards a neutral 60% rather than 0% or 100% -- missing data shouldn't be
# treated as either a penalty or a free pass.
SECTOR_SCORE_MULTIPLIER = {
    "ALIGNED_BULLISH": 1.00,    # stock, sector, and (separately-scored) market all agree bullish
    "SECTOR_NEUTRAL": 0.60,
    "SECTOR_CONTRA": 0.15,      # sector trending opposite to the stock's own signal
    "NO_SECTOR_DATA": 0.60,     # graceful degradation -- don't penalize for missing data
}

# ---------------------------------------------------------------------------
# Relative strength vs NIFTY 50
# ---------------------------------------------------------------------------
RS_LOOKBACK_DAYS = 20      # short-window relative strength
RS_LOOKBACK_DAYS_LONG = 60  # longer-window relative strength (used for Long-Term category)
RS_STRONG_OUTPERFORM_PP = 5.0   # percentage points ahead of NIFTY to count as "strong" RS
RS_WEAK_UNDERPERFORM_PP = -5.0  # percentage points behind NIFTY to count as "weak" RS

# ---------------------------------------------------------------------------
# Entry-zone / chase detection
# ---------------------------------------------------------------------------
# If the current price has already moved this many multiples of ATR beyond
# the calculated entry zone, the setup is considered "chased" -- output
# ENTRY MISSED instead of a normal entry zone.
CHASE_ATR_MULTIPLE = 1.2

# ---------------------------------------------------------------------------
# Data quality gate
# ---------------------------------------------------------------------------
MAX_STALE_DAYS = 5          # daily bar older than this vs "today" -> stale data, no signal
ABNORMAL_DAILY_MOVE_PCT = 20.0  # single-day move beyond this -> flag possible corporate action/bad print

# ---------------------------------------------------------------------------
# Position sizing (see position_sizing.py) -- override via .env
# ---------------------------------------------------------------------------
DEFAULT_ACCOUNT_CAPITAL = 100_000.0   # INR, purely illustrative default
DEFAULT_RISK_PER_TRADE_PCT = 1.0      # % of capital risked per trade if stop-loss is hit
MAX_CAPITAL_PER_POSITION_PCT = 20.0   # never suggest deploying more than this % of capital in one name

# Position size is scaled down for lower-conviction grades -- a C-grade
# "weak setup" risks less capital than an A+ setup even at the same
# nominal risk-per-trade, because the evidence behind it is weaker.
GRADE_SIZE_MULTIPLIER = {
    "A+": 1.00,
    "A": 0.85,
    "B": 0.60,
    "C": 0.35,
}

# ---------------------------------------------------------------------------
# Risk/reward quality scoring
# ---------------------------------------------------------------------------
RR_MIN_ACCEPTABLE = 1.5   # below this, the RR-quality score component is 0
RR_GOOD = 2.0             # at/above this, RR-quality score component is maxed

# ---------------------------------------------------------------------------
# Factor weights -- every category's 100-point breakdown, named and
# centralized so no weight is a bare magic number inside analyzer.py.
# Each category's weights must sum to 100.
# ---------------------------------------------------------------------------
WEIGHTS_SHORT_TERM = {
    "Market Regime": 15, "Sector Strength": 10, "Momentum": 20,
    "Price Structure": 15, "Volume Confirmation": 15,
    "Relative Strength": 10, "Volatility Profile": 5, "Risk/Reward Quality": 10,
}
WEIGHTS_LONG_TERM = {
    "Market Regime": 15, "Sector Strength": 10, "Price Trend": 25,
    "Momentum": 15, "Volume Trend": 10, "Relative Strength": 15, "Risk/Reward Quality": 10,
}
WEIGHTS_INTRADAY = {
    "Market Regime": 10, "VWAP Position": 20, "Opening Range Breakout": 20,
    "Volume Surge": 15, "Gap Analysis": 10, "Daily Trend Alignment": 15, "Daily RSI Support": 10,
}
assert sum(WEIGHTS_SHORT_TERM.values()) == 100
assert sum(WEIGHTS_LONG_TERM.values()) == 100
assert sum(WEIGHTS_INTRADAY.values()) == 100
