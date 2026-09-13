"""
Stock universe for the NIFTY 50 / SENSEX daily tipper agent.

Tickers use the Yahoo Finance NSE suffix (".NS") since almost every SENSEX
constituent also trades on NSE, and using one exchange keeps price data
consistent across the whole universe.

NOTE: Index constituents change over time (index reshuffles happen ~twice a
year, plus corporate actions like demergers change tickers between
rebalances). This list is accurate as of September 2026 but you should
sanity check it against the official lists periodically:
  - NIFTY 50 : https://www.nseindia.com/products-services/indices-nifty50-index
  - SENSEX   : https://www.bseindia.com/sensex/code/16/

Known upcoming change to watch for: NSE Indices announced BSE Ltd (ticker
"BSE") will replace WIPRO in the NIFTY 50 effective 30 Sep 2026. This list
still has WIPRO as of this writing -- update it once that takes effect.

Already applied: Tata Motors demerged (effective Oct 2025) into Tata Motors
Passenger Vehicles ("TMPV", incl. Jaguar Land Rover -- the index
constituent, used below) and a separately listed commercial-vehicle entity
("TMCV"). The old "TATAMOTORS" ticker no longer resolves.
"""

NIFTY_50 = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "ITC", "INDUSINDBK",
    "INFY", "JSWSTEEL", "JIOFIN", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SHRIRAMFIN", "SBIN",
    "SUNPHARMA", "TCS", "TATACONSUM", "TMPV", "TATASTEEL",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

# SENSEX 30 constituents that are NOT already in the NIFTY 50 list above.
# (Most SENSEX names overlap heavily with NIFTY 50 large-caps.)
SENSEX_EXTRA = [
    "BAJAJHLDNG", "ZOMATO" if "ETERNAL" not in NIFTY_50 else None,
]
SENSEX_EXTRA = [s for s in SENSEX_EXTRA if s]

# Yahoo Finance ticker suffix for NSE-listed equities.
YF_SUFFIX = ".NS"


def get_universe() -> list[str]:
    """Return the de-duplicated list of raw NSE symbols (no suffix)."""
    combined = list(dict.fromkeys(NIFTY_50 + SENSEX_EXTRA))  # de-dup, keep order
    return combined


def to_yf_ticker(symbol: str) -> str:
    return f"{symbol}{YF_SUFFIX}"


def get_yf_universe() -> list[str]:
    """Return the universe as Yahoo Finance tickers, e.g. 'RELIANCE.NS'."""
    return [to_yf_ticker(s) for s in get_universe()]
