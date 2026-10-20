"""Tests for pure, point-in-time evidence snapshots."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trader.config import StrategySettings
from trader.models import Candidate, Candle
from trader.strategy import build_snapshot, evaluate_candle, snapshot_from_json, snapshot_to_json


def _candle(index: int, high: str, low: str, close: str, volume: str) -> Candle:
    high_value, low_value, close_value = Decimal(high), Decimal(low), Decimal(close)
    return Candle(
        symbol="BTCUSDT",
        open_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=Decimal(volume),
    )


def _config(*, lookback: int = 3, trend_period: int = 3) -> StrategySettings:
    return StrategySettings(
        symbol="BTCUSDT",
        interval="1h",
        atr_period=3,
        breakout_lookback=lookback,
        trend_sma_period=trend_period,
    )


def _fixture_candles() -> list[Candle]:
    return [
        _candle(0, "10", "8", "9", "2"),
        _candle(1, "11", "9", "10", "4"),
        _candle(2, "13", "10", "11", "6"),
        _candle(3, "18", "11", "15", "12"),
    ]


def _candidate(candles: list[Candle], index: int) -> Candidate:
    candle = candles[index]
    return Candidate(
        symbol="BTCUSDT",
        bar_index=index,
        signal_time=candle.open_time,
        reference_price=candle.close,
        atr=Decimal("1"),
        breakout_level=Decimal("1"),
        idempotency_key=f"BTCUSDT:1h:{candle.open_time.isoformat()}",
    )


def test_snapshot_fields_match_hand_computed_fixture() -> None:
    candles = _fixture_candles()
    config = _config()
    candidate = evaluate_candle(candles, 3, config)
    assert candidate is not None

    snapshot = build_snapshot(candles, candidate, config)

    # Prior volume mean = (2 + 4 + 6) / 3 = 4; volume ratio = 12 / 4 = 3.
    # TRs = 2, 3, and 7, so ATR = (2 + 3 + 7)/3 = 4; breakout strength = (15 - 13)/4 = 1/2.
    # ATR fraction = 4/15. Inclusive range = (18 - 9)/15 = 3/5.
    # Inclusive close SMA = (10 + 11 + 15)/3 = 12; trend = 15/12 - 1 = 1/4.
    assert snapshot.volume_ratio == Decimal("3")
    assert snapshot.breakout_strength_atr == Decimal("1") / Decimal("2")
    assert snapshot.atr_pct == Decimal("4") / Decimal("15")
    assert snapshot.range_24h_pct == Decimal("3") / Decimal("5")
    assert snapshot.trend_vs_sma == Decimal("1") / Decimal("4")


def test_snapshot_ignores_appended_changed_and_removed_future_candles() -> None:
    signal_candles = _fixture_candles()
    config = _config()
    candidate = evaluate_candle(signal_candles, 3, config)
    assert candidate is not None
    expected = build_snapshot(signal_candles, candidate, config)
    later = [_candle(4, "30", "1", "2", "99"), _candle(5, "40", "1", "3", "88")]
    changed_later = [_candle(4, "1000", "1", "2", "0")]

    assert build_snapshot(signal_candles + later, candidate, config) == expected
    assert build_snapshot(signal_candles + changed_later, candidate, config) == expected
    assert build_snapshot(signal_candles[:4], candidate, config) == expected


def test_snapshot_json_round_trip_is_lossless_and_versioned() -> None:
    candles = _fixture_candles()
    candidate = evaluate_candle(candles, 3, _config())
    assert candidate is not None

    payload = snapshot_to_json(build_snapshot(candles, candidate, _config()))

    encoded = json.loads(payload)
    assert encoded["schema_version"] == 1
    assert encoded["signal_time"].endswith("Z")
    assert snapshot_from_json(payload) == build_snapshot(candles, candidate, _config())


def test_history_boundaries_return_null_without_errors() -> None:
    candles = _fixture_candles()
    config = _config(lookback=3, trend_period=3)
    one_short = build_snapshot(candles[:2], _candidate(candles, 1), config)
    exact_range_and_trend = build_snapshot(candles[:3], _candidate(candles, 2), config)
    exact_volume = build_snapshot(candles, _candidate(candles, 3), config)

    assert one_short.volume_ratio is None
    assert one_short.range_24h_pct is None
    assert one_short.trend_vs_sma is None
    assert exact_range_and_trend.volume_ratio is None
    assert exact_range_and_trend.range_24h_pct is not None
    assert exact_range_and_trend.trend_vs_sma is not None
    assert exact_volume.volume_ratio is not None


def test_zero_prior_volume_is_null_and_signal_is_excluded_from_mean() -> None:
    candles = [
        _candle(0, "10", "8", "9", "0"),
        _candle(1, "12", "9", "11", "0"),
        _candle(2, "13", "10", "12", "0"),
        _candle(3, "16", "12", "15", "12"),
    ]
    candidate = evaluate_candle(candles, 3, _config())
    assert candidate is not None

    assert build_snapshot(candles, candidate, _config()).volume_ratio is None


def test_signal_candle_is_included_in_range_and_sma() -> None:
    candles = _fixture_candles()
    candidate = evaluate_candle(candles, 3, _config())
    assert candidate is not None

    snapshot = build_snapshot(candles, candidate, _config())

    assert snapshot.range_24h_pct == Decimal("3") / Decimal("5")
    assert snapshot.trend_vs_sma == Decimal("1") / Decimal("4")
