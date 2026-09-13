"""
RESEARCH ONLY -- read-only data collection for the factor audit.

This module does not modify, retrain, or reparameterize anything. It walks
forward through history using the EXACT existing production functions
(analyzer.score_short_term / score_long_term / compute_bundle,
market_regime.compute_regime_bundle / classify_regime_at,
sector.compute_sector_trend_bundle / build_point_in_time_confirmation,
backtest._simulate_trade / compute_performance_metrics) -- imported and
called unchanged, never reimplemented -- so every number produced here
traces back to the real production scoring formula, not a parallel model.

Two outputs:
1. A per-signal-day "master" observational dataset: every individual score
   factor's fraction (points_earned/max_points), the resulting total
   score/grade/signal, regime/sector/RS context, the entry price and
   target1/stop_loss levels the production code would set, and RAW forward
   returns (price only, no exit-rule simulation) at 1/5/10/20/60/90 trading
   days. Used for factor-level correlation/quantile/cross-sectional/
   time-robustness analysis.
2. An ablation trade-simulation engine: given a function that maps a row's
   factor breakdown to an "ablated" score, replays the SAME non-overlapping
   target1/stop-loss trade selection logic as backtest.py (reusing its
   _simulate_trade and compute_performance_metrics unchanged) to produce
   real win-rate/expectancy/profit-factor/drawdown/Sharpe-Sortino numbers
   for that variant.

KNOWN LIMITATION shared with backtest.py: no transaction costs/slippage;
today's index list projected backward; per-stock daily-bar sampling means
forward-return observations for the same stock overlap in time and are NOT
independent draws -- treat correlations/quantile patterns as descriptive
evidence, not p-value-backed hypothesis tests, per the audit's own request
to avoid manufactured statistical rigor.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

import config as cfg
import data_sources as ds
import market_regime as regime_mod
import sector as sector_mod
import symbols as sym
from analyzer import (
    CATEGORY_LONG_TERM, CATEGORY_SHORT_TERM, IndicatorBundle, TradeIdea,
    _classify_signal, _grade_from_score, compute_bundle, score_long_term, score_short_term,
)
from backtest import CENSOR_BUFFER_DAYS, MIN_WARMUP_DAYS, _simulate_trade, compute_performance_metrics

logger = logging.getLogger("nifty_agent.research")

FORWARD_HORIZONS = [1, 5, 10, 20, 60, 90]  # trading days

SCORERS = {CATEGORY_SHORT_TERM: score_short_term, CATEGORY_LONG_TERM: score_long_term}


@dataclass
class UniverseData:
    """Everything fetched once, reused across every stock/category/idx so
    the (expensive, rate-limit-prone) data fetching happens exactly once."""
    daily: dict[str, pd.DataFrame]
    bundles: dict[str, IndicatorBundle]
    regime_bundle: regime_mod.RegimeBundle | None
    sector_bundles: dict[str, sector_mod.SectorTrendBundle]


def load_universe(universe: list[str], history_period: str = "3y") -> UniverseData:
    logger.info("Fetching NIFTY regime bundle...")
    nifty_df = ds.fetch_daily_history(cfg.REGIME_INDEX_TICKER, period=history_period)
    regime_bundle = regime_mod.compute_regime_bundle(nifty_df) if nifty_df is not None else None

    logger.info("Fetching sector index bundles...")
    sector_bundles = {}
    for ticker in set(sector_mod.SECTOR_MAP.values()):
        df = ds.fetch_daily_history(ticker, period=history_period)
        if df is not None:
            sector_bundles[ticker] = sector_mod.compute_sector_trend_bundle(df)

    daily, bundles = {}, {}
    for s in universe:
        df = ds.fetch_daily_history(sym.to_yf_ticker(s), period=history_period)
        if df is None or len(df) < MIN_WARMUP_DAYS + 30:
            continue
        daily[s] = df
        bundles[s] = compute_bundle(df)
    logger.info("Loaded %d/%d symbols.", len(daily), len(universe))

    return UniverseData(daily=daily, bundles=bundles, regime_bundle=regime_bundle, sector_bundles=sector_bundles)


def _regime_at(u: UniverseData, date: pd.Timestamp) -> str | None:
    if u.regime_bundle is None:
        return None
    idx = u.regime_bundle.close.index.searchsorted(date, side="right") - 1
    return regime_mod.classify_regime_at(u.regime_bundle, idx) if idx >= 0 else None


def build_master_dataset(u: UniverseData, universe: list[str]) -> pd.DataFrame:
    """One row per (symbol, category, signal-day) for every stock/category/
    day, using the UNCHANGED production scoring functions. No trade
    selection/non-overlap logic here -- every eligible day is recorded,
    since this dataset is for factor correlation/quantile analysis, not
    trade simulation (see run_ablation for that)."""
    rows = []
    for symbol in universe:
        df = u.daily.get(symbol)
        bundle = u.bundles.get(symbol)
        if df is None or bundle is None:
            continue
        censor_date = df.index[-1] - pd.Timedelta(days=CENSOR_BUFFER_DAYS)

        for category in (CATEGORY_SHORT_TERM, CATEGORY_LONG_TERM):
            scorer = SCORERS[category]
            rs_lookback = cfg.RS_LOOKBACK_DAYS_LONG if category == CATEGORY_LONG_TERM else cfg.RS_LOOKBACK_DAYS

            i = MIN_WARMUP_DAYS
            while i < len(df) - 1:
                date = df.index[i]
                if date > censor_date:
                    break

                regime_label = _regime_at(u, date)
                sector_confirmation = sector_mod.build_point_in_time_confirmation(
                    symbol, bundle, i, u.sector_bundles, u.regime_bundle.close if u.regime_bundle else None, rs_lookback)

                idea: TradeIdea = scorer(symbol, bundle, i, regime_label=regime_label,
                                          sector_confirmation=sector_confirmation, data_note="")

                entry_idx = i + 1
                entry_price = float(df["Open"].iloc[entry_idx])

                row = {
                    "symbol": symbol, "category": category, "date": date,
                    "sector_ticker": sector_confirmation.sector_ticker, "sector_trend": sector_confirmation.sector_trend,
                    "regime": regime_label or "UNKNOWN",
                    "score": idea.score, "grade": idea.grade or "NONE", "signal": idea.signal,
                    "rr_ratio": idea.rr_ratio, "entry_price": entry_price,
                    "target1": idea.target1, "stop_loss": idea.stop_loss,
                    "relative_strength_pct": idea.relative_strength_pct,
                    "support20": float(bundle.support20.iloc[i]), "resistance20": float(bundle.resistance20.iloc[i]),
                    "high52w": float(bundle.high52w.iloc[i]),
                }
                for factor_name, (earned, maxpts) in idea.score_breakdown.items():
                    row[f"factor__{factor_name}"] = (earned / maxpts) if maxpts > 0 else np.nan

                for h in FORWARD_HORIZONS:
                    fwd_idx = entry_idx + h
                    row[f"fwd_ret_{h}d"] = (float(df["Close"].iloc[fwd_idx]) / entry_price - 1) * 100 if fwd_idx < len(df) else np.nan

                rows.append(row)
                i += 1

    return pd.DataFrame(rows)


def run_ablation(u: UniverseData, universe: list[str], category: str,
                  ablate_factor: str | None, min_score: float = 40.0) -> pd.DataFrame:
    """Replays the SAME non-overlapping target1/stop-loss trade-selection
    logic as backtest.py (reusing its _simulate_trade unchanged), but the
    score used to decide whether/what grade a signal gets has `ablate_factor`
    zeroed out first (score recomputed as sum of all OTHER factor points,
    re-graded via the real analyzer._grade_from_score /_classify_signal).
    Entry/target/stop-loss levels are NOT recomputed -- they come from the
    original (full-score) idea, since those are ATR/structure-derived and
    don't depend on which score factors are ablated; only the
    grade/signal-classification gate changes per variant."""
    scorer = SCORERS[category]
    rs_lookback = cfg.RS_LOOKBACK_DAYS_LONG if category == CATEGORY_LONG_TERM else cfg.RS_LOOKBACK_DAYS
    results = []

    for symbol in universe:
        df = u.daily.get(symbol)
        bundle = u.bundles.get(symbol)
        if df is None or bundle is None:
            continue
        censor_date = df.index[-1] - pd.Timedelta(days=CENSOR_BUFFER_DAYS)

        i = MIN_WARMUP_DAYS
        while i < len(df) - 1:
            date = df.index[i]
            if date > censor_date:
                break

            regime_label = _regime_at(u, date)
            sector_confirmation = sector_mod.build_point_in_time_confirmation(
                symbol, bundle, i, u.sector_bundles, u.regime_bundle.close if u.regime_bundle else None, rs_lookback)
            idea = scorer(symbol, bundle, i, regime_label=regime_label,
                           sector_confirmation=sector_confirmation, data_note="")

            if ablate_factor and ablate_factor in idea.score_breakdown:
                ablated_score = round(idea.score - idea.score_breakdown[ablate_factor][0], 1)
            else:
                ablated_score = idea.score
            grade = _grade_from_score(ablated_score)
            signal = _classify_signal(grade, idea.chase_flag, idea.rr_ratio, regime_label or "NEUTRAL")

            if ablated_score < min_score or signal == "NO TRADE":
                i += 1
                continue

            entry_idx = i + 1
            entry_price = float(df["Open"].iloc[entry_idx])
            exit_idx, exit_price, exit_reason = _simulate_trade(df, entry_idx, idea.target1, idea.stop_loss)
            strategy_return_pct = (exit_price / entry_price - 1) * 100
            days_held = (df.index[exit_idx] - df.index[entry_idx]).days

            row = {
                "symbol": symbol, "category": category, "regime": regime_label or "UNKNOWN",
                "signal_date": date, "sector_ticker": sector_confirmation.sector_ticker,
                "ablated_score": ablated_score, "exit_reason": exit_reason,
                "strategy_return_pct": strategy_return_pct, "days_held": days_held,
                "entry_price": entry_price, "target1": idea.target1, "stop_loss": idea.stop_loss,
                "target_distance_pct": (idea.target1 / entry_price - 1) * 100,
                "stop_distance_pct": (1 - idea.stop_loss / entry_price) * 100,
                "atr_pct": float(bundle.atr_pct.iloc[i]) if pd.notna(bundle.atr_pct.iloc[i]) else np.nan,
                # Raw production fields, unmodified -- support20/resistance20 as
                # actually computed in analyzer.compute_bundle (20-day trailing
                # rolling min(Low)/max(High), inclusive of the signal day itself).
                "support20": float(bundle.support20.iloc[i]),
                "resistance20": float(bundle.resistance20.iloc[i]),
                "high52w": float(bundle.high52w.iloc[i]),
            }
            for factor_name, (earned, maxpts) in idea.score_breakdown.items():
                row[f"factor__{factor_name}"] = (earned / maxpts) if maxpts > 0 else np.nan

            results.append(row)
            i = max(exit_idx + 1, i + 1)

    return pd.DataFrame(results)
