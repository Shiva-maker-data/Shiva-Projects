"""
RESEARCH ONLY -- experiment 12, capture step: build a frozen local raw-OHLCV
fixture using the EXISTING, UNCHANGED repository fetch mechanism
(data_sources.fetch_daily_history), so a later, strictly offline script can
attempt to reproduce experiment 5's master/trade artifacts without any
network access.

This script DOES use the network (that is the point -- it is the one-time
capture step the spec explicitly authorizes: "Use the existing repository
data-fetch mechanism only"). It calls data_sources.fetch_daily_history()
unchanged, for the exact same universe/tickers/period as experiment 5's
research.factor_data.load_universe(..., history_period="3y"), and persists
the raw OHLCV DataFrames plus full provenance metadata to
research/fixtures/raw_ohlcv/. Nothing here is refetched selectively or
substituted -- every required series is captured in one pass, and if any
fails to fetch, that failure is recorded, not silently skipped.

No production code is modified. No scoring/indicator/regime function is
called here -- this script only fetches and saves raw price history.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

import data_sources as ds
import sector as sector_mod
import symbols as sym
import config as cfg

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "research" / "fixtures" / "raw_ohlcv"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_PERIOD = "3y"  # identical to research/factor_data.py's load_universe(..., history_period="3y") used by experiment 5


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def safe_name(ticker: str) -> str:
    return ticker.replace("^", "IDX_").replace("&", "AND").replace(".", "_")


def capture_one(logical_symbol: str, yf_ticker: str, kind: str) -> dict:
    retrieval_ts = datetime.now(timezone.utc).isoformat()
    df = ds.fetch_daily_history(yf_ticker, period=HISTORY_PERIOD)  # UNCHANGED production function
    if df is None:
        return {"logical_symbol": logical_symbol, "yf_ticker": yf_ticker, "kind": kind,
                "status": "FETCH_FAILED", "retrieval_timestamp_utc": retrieval_ts}
    fname = f"{safe_name(yf_ticker)}.csv"
    fpath = FIXTURE_DIR / fname
    df_to_save = df.copy()
    df_to_save.index.name = "Date"
    df_to_save.to_csv(fpath)
    return {
        "logical_symbol": logical_symbol, "yf_ticker": yf_ticker, "kind": kind, "status": "OK",
        "filename": fname, "sha256": sha256_of(fpath), "size_bytes": fpath.stat().st_size,
        "rows": len(df), "date_min": str(df.index.min().date()), "date_max": str(df.index.max().date()),
        "columns": list(df.columns), "index_tz_after_strip": str(df.index.tz),
        "retrieval_timestamp_utc": retrieval_ts, "requested_period": HISTORY_PERIOD, "interval": "1d",
        "auto_adjust": False,
    }


def main():
    manifest = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version, "yfinance_version": yf.__version__, "pandas_version": pd.__version__,
        "fetch_mechanism": "data_sources.fetch_daily_history (unchanged production function): "
                            "yf.Ticker(ticker).history(period=period, interval='1d', auto_adjust=False), "
                            "then data_sources._strip_tz() removes the Asia/Kolkata tz-awareness Yahoo Finance "
                            "returns for NSE tickers, leaving a tz-naive DatetimeIndex.",
        "requested_period": HISTORY_PERIOD,
        "entries": [],
    }

    universe = sym.get_universe()
    print(f"Capturing {len(universe)} stock symbols...")
    for s in universe:
        rec = capture_one(s, sym.to_yf_ticker(s), "stock")
        manifest["entries"].append(rec)
        print(f"  {s}: {rec['status']}")

    print("Capturing NIFTY regime index...")
    manifest["entries"].append(capture_one("NIFTY_REGIME_INDEX", cfg.REGIME_INDEX_TICKER, "regime_index"))

    sector_tickers = sorted(set(sector_mod.SECTOR_MAP.values()))
    print(f"Capturing {len(sector_tickers)} sector indices...")
    for t in sector_tickers:
        manifest["entries"].append(capture_one(t, t, "sector_index"))

    n_ok = sum(1 for e in manifest["entries"] if e["status"] == "OK")
    n_failed = sum(1 for e in manifest["entries"] if e["status"] != "OK")
    manifest["summary"] = {"total": len(manifest["entries"]), "ok": n_ok, "failed": n_failed}

    manifest_path = FIXTURE_DIR.parent / "raw_ohlcv_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nCaptured {n_ok} OK, {n_failed} FAILED, out of {len(manifest['entries'])}")
    print(f"Manifest saved: {manifest_path}")
    if n_failed:
        print("FAILED entries:", [e for e in manifest["entries"] if e["status"] != "OK"])


if __name__ == "__main__":
    main()
