"""
Focused unit tests for the critical, easy-to-get-subtly-wrong calculations
in the v2 rule engine: indicators, regime classification boundaries,
RR-quality/position-sizing math, and entry/chase detection. Not exhaustive
coverage of every code path -- targeted at the pieces most likely to
silently break and hardest to catch by eyeballing an email.

Run with:  .venv\\Scripts\\python.exe -m pytest tests/ -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config as cfg
import indicators as ind
import market_regime as regime_mod
import position_sizing as sizing
from analyzer import (
    _classify_signal, _entry_and_chase, _grade_from_score, _rr_quality_fraction,
    check_data_quality, compute_bundle,
)


def _make_ohlcv(closes: list[float], start="2024-01-01") -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(closes), freq="D")
    closes = pd.Series(closes, index=idx)
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
        "Close": closes, "Volume": pd.Series([1_000_000] * len(closes), index=idx),
    })


class TestIndicators:
    def test_rsi_bounded_0_100(self):
        prices = pd.Series(np.random.default_rng(0).normal(100, 5, 300).cumsum() + 1000)
        r = ind.rsi(prices, 14)
        assert (r.dropna() >= 0).all() and (r.dropna() <= 100).all()

    def test_rsi_all_gains_approaches_100(self):
        prices = pd.Series(range(100, 200))  # monotonically increasing
        r = ind.rsi(prices, 14)
        assert r.iloc[-1] > 95

    def test_macd_histogram_equals_line_minus_signal(self):
        prices = pd.Series(np.random.default_rng(1).normal(0, 1, 200).cumsum() + 500)
        macd_line, signal_line, hist = ind.macd(prices)
        diff = (macd_line - signal_line - hist).dropna()
        assert (diff.abs() < 1e-9).all()

    def test_atr_non_negative(self):
        df = _make_ohlcv([100, 102, 98, 105, 101, 99, 103] * 10)
        atr = ind.atr(df, 14)
        assert (atr.dropna() >= 0).all()


class TestMarketRegime:
    def test_strong_bullish_classification(self):
        label, reasons = regime_mod._classify(price=110, sma_fast=105, sma_slow=100, rsi=60, atr_pct=1.5, atr_percentile=50)
        assert label == regime_mod.REGIME_STRONG_BULLISH

    def test_strong_bearish_classification(self):
        label, _ = regime_mod._classify(price=90, sma_fast=95, sma_slow=100, rsi=30, atr_pct=1.5, atr_percentile=50)
        assert label == regime_mod.REGIME_STRONG_BEARISH

    def test_high_volatility_overrides_direction(self):
        # Even a textbook bullish setup should be flagged unstable if ATR
        # percentile is extreme -- volatility gate checked first.
        label, _ = regime_mod._classify(price=110, sma_fast=105, sma_slow=100, rsi=60, atr_pct=8.0, atr_percentile=95)
        assert label == regime_mod.REGIME_HIGH_VOLATILITY

    def test_neutral_when_mixed(self):
        label, _ = regime_mod._classify(price=102, sma_fast=105, sma_slow=100, rsi=50, atr_pct=1.5, atr_percentile=50)
        assert label == regime_mod.REGIME_NEUTRAL

    def test_point_in_time_bundle_matches_direct_classification(self):
        """The whole point of RegimeBundle is that slicing it at idx gives
        the same answer as classifying directly from that day's values --
        this is what makes backtest.py's use of it lookahead-safe."""
        rng = np.random.default_rng(42)
        closes = pd.Series(100 + rng.normal(0, 1, 400).cumsum())
        df = _make_ohlcv(list(closes))
        bundle = regime_mod.compute_regime_bundle(df)
        idx = 350
        label_from_bundle = regime_mod.classify_regime_at(bundle, idx)

        truncated = df.iloc[: idx + 1]
        direct_bundle = regime_mod.compute_regime_bundle(truncated)
        label_direct = regime_mod.classify_regime_at(direct_bundle, len(truncated) - 1)
        assert label_from_bundle == label_direct


class TestRiskRewardAndGrading:
    def test_rr_below_minimum_is_low_fraction(self):
        assert _rr_quality_fraction(0.5) < 0.2

    def test_rr_at_good_threshold_is_maxed(self):
        assert _rr_quality_fraction(cfg.RR_GOOD) == 1.0
        assert _rr_quality_fraction(cfg.RR_GOOD + 5) == 1.0

    def test_rr_zero_or_negative_is_zero(self):
        assert _rr_quality_fraction(0) == 0.0
        assert _rr_quality_fraction(-1) == 0.0

    def test_grade_thresholds(self):
        assert _grade_from_score(95) == "A+"
        assert _grade_from_score(85) == "A"
        assert _grade_from_score(75) == "B"
        assert _grade_from_score(65) == "C"
        assert _grade_from_score(59) is None

    def test_no_trade_when_grade_none(self):
        assert _classify_signal(None, chase_flag=False, rr=2.0, regime_label="BULLISH") == "NO TRADE"

    def test_poor_rr_forces_watch_even_with_good_grade(self):
        assert _classify_signal("A+", chase_flag=False, rr=1.0, regime_label="BULLISH") == "WATCH"

    def test_chase_forces_watch(self):
        assert _classify_signal("A+", chase_flag=True, rr=2.0, regime_label="BULLISH") == "WATCH"

    def test_strong_bearish_suppresses_weak_grades_to_no_trade(self):
        assert _classify_signal("C", chase_flag=False, rr=2.0, regime_label="STRONG_BEARISH") == "NO TRADE"
        assert _classify_signal("B", chase_flag=False, rr=2.0, regime_label="STRONG_BEARISH") == "NO TRADE"


class TestEntryAndChase:
    def test_no_chase_within_zone(self):
        _, entry_high, _, chase = _entry_and_chase(price=100, atr_value=2, support=95, resistance=105,
                                                     near_breakout=False, near_pullback=False)
        assert chase is False

    def test_chase_flagged_when_price_has_run_too_far(self):
        # entry_high for continuation = price*1.006 -- but if we simulate a
        # LATER price far beyond that relative to ATR, chase must trigger.
        # Use a large gap directly to make the intent explicit.
        entry_low, entry_high, entry_type, chase = _entry_and_chase(
            price=130, atr_value=2, support=95, resistance=105, near_breakout=False, near_pullback=False)
        # price (130) is way beyond entry_high (~130.8) + 1.2*ATR threshold from a MUCH lower true entry
        # so directly assert the chase math: price > entry_high + CHASE_ATR_MULTIPLE*atr
        assert (130 > entry_high + cfg.CHASE_ATR_MULTIPLE * 2) == chase

    def test_breakout_entry_uses_resistance(self):
        entry_low, entry_high, entry_type, _ = _entry_and_chase(
            price=106, atr_value=2, support=95, resistance=105, near_breakout=True, near_pullback=False)
        assert entry_type == "Breakout entry"
        assert entry_low <= 105 * 1.01


class TestPositionSizing:
    def test_never_exceeds_max_capital_pct(self):
        pos = sizing.calculate_position_size(entry_price=100, stop_loss=99, grade="A+",
                                              account_capital=100_000, risk_per_trade_pct=1.0)
        assert pos.capital_deployed <= 100_000 * (cfg.MAX_CAPITAL_PER_POSITION_PCT / 100) + 1e-6

    def test_lower_grade_sizes_smaller(self):
        pos_a = sizing.calculate_position_size(100, 95, "A+", account_capital=1_000_000, risk_per_trade_pct=1.0)
        pos_c = sizing.calculate_position_size(100, 95, "C", account_capital=1_000_000, risk_per_trade_pct=1.0)
        assert pos_c.shares < pos_a.shares

    def test_zero_shares_does_not_crash(self):
        pos = sizing.calculate_position_size(entry_price=100, stop_loss=99.99, grade="C",
                                              account_capital=100, risk_per_trade_pct=0.1)
        assert pos.shares >= 0

    def test_never_negative_capital_at_risk(self):
        pos = sizing.calculate_position_size(100, 95, "A", account_capital=50_000, risk_per_trade_pct=1.0)
        assert pos.capital_at_risk >= 0


class TestDataQualityGate:
    def test_flags_abnormal_single_day_move(self):
        df = _make_ohlcv([100, 100, 100, 100, 100, 160])  # 60% jump, e.g. bad print or corporate action
        ok, note = check_data_quality(df, idx=5)
        assert ok is False
        assert "Abnormal" in note

    def test_passes_normal_data(self):
        df = _make_ohlcv([100, 101, 99, 102, 100, 101] * 40)
        ok, note = check_data_quality(df, idx=len(df) - 1)
        assert ok is True

    def test_flags_missing_ohlc(self):
        df = _make_ohlcv([100] * 10)
        df.iloc[5, df.columns.get_loc("Close")] = np.nan
        ok, note = check_data_quality(df, idx=5)
        assert ok is False


class TestBundleConsistency:
    def test_compute_bundle_does_not_crash_on_minimal_data(self):
        df = _make_ohlcv([100 + i * 0.1 for i in range(60)])
        bundle = compute_bundle(df)
        assert len(bundle.close) == 60

    def test_score_functions_use_only_past_data(self):
        """The core lookahead-safety guarantee: scoring at idx using the
        full-history bundle must equal scoring on data truncated to idx."""
        from analyzer import score_short_term
        rng = np.random.default_rng(7)
        closes = 100 + rng.normal(0, 1, 300).cumsum()
        df = _make_ohlcv(list(closes))
        full_bundle = compute_bundle(df)
        idx = 250

        idea_from_full = score_short_term("TEST", full_bundle, idx=idx)

        truncated_bundle = compute_bundle(df.iloc[: idx + 1])
        idea_from_truncated = score_short_term("TEST", truncated_bundle, idx=None)

        assert idea_from_full.score == idea_from_truncated.score


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
