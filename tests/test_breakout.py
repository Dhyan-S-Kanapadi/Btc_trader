"""Tests for the pure point-in-time ATR breakout rule."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trader.config import StrategySettings
from trader.models import Candle
from trader.strategy import atr_at, evaluate_candle, scan_candidates


def _candle(
    index: int,
    high: str,
    low: str,
    close: str,
    *,
    symbol: str = "BTCUSDT",
) -> Candle:
    high_value, low_value, close_value = Decimal(high), Decimal(low), Decimal(close)
    return Candle(
        symbol=symbol,
        open_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=index),
        open=close_value,
        high=high_value,
        low=low_value,
        close=close_value,
        volume=Decimal("1"),
    )


def _strategy(*, atr_period: int = 3, breakout_lookback: int = 3) -> StrategySettings:
    return StrategySettings(
        symbol="BTCUSDT",
        interval="1h",
        atr_period=atr_period,
        breakout_lookback=breakout_lookback,
    )


def test_atr_matches_hand_computed_simple_average() -> None:
    candles = [
        _candle(0, "10", "8", "9"),
        _candle(1, "12", "10", "11"),
        _candle(2, "13", "11", "12"),
        _candle(3, "15", "12", "14"),
    ]

    # TR[1] = max(12-10, |12-9|, |10-9|) = 3.
    # TR[2] = max(13-11, |13-11|, |11-11|) = 2.
    # TR[3] = max(15-12, |15-12|, |12-12|) = 3; ATR = (3+2+3)/3 = 8/3.
    assert atr_at(candles, 3, _strategy()) == Decimal("8") / Decimal("3")


def test_future_candles_do_not_change_earlier_atr_or_signal() -> None:
    strategy = _strategy()
    candles = [
        _candle(0, "10", "8", "9"),
        _candle(1, "11", "9", "10"),
        _candle(2, "12", "10", "11"),
        _candle(3, "14", "11", "13"),
    ]

    earlier_atr = atr_at(candles, 3, strategy)
    earlier_candidate = evaluate_candle(candles, 3, strategy)
    future = candles + [_candle(4, "1000", "1", "2")]

    assert atr_at(future, 3, strategy) == earlier_atr
    assert evaluate_candle(future, 3, strategy) == earlier_candidate


def test_equal_close_is_not_a_breakout() -> None:
    candles = [
        _candle(0, "10", "8", "9"),
        _candle(1, "10", "8", "9"),
        _candle(2, "10", "8", "9"),
        _candle(3, "10", "8", "10"),
    ]

    assert evaluate_candle(candles, 3, _strategy()) is None


def test_signal_high_is_excluded_from_breakout_level() -> None:
    prior = [_candle(index, "10", "8", "9") for index in range(3)]
    below_prior_high = prior + [_candle(3, "100", "8", "9")]
    above_prior_high = prior + [_candle(3, "100", "8", "11")]

    assert evaluate_candle(below_prior_high, 3, _strategy()) is None
    candidate = evaluate_candle(above_prior_high, 3, _strategy())
    assert candidate is not None
    assert candidate.breakout_level == Decimal("10")


def test_insufficient_history_returns_none_without_exception() -> None:
    candles = [_candle(index, "10", "8", "9") for index in range(3)]
    strategy = _strategy(atr_period=3, breakout_lookback=3)

    assert atr_at(candles, 0, strategy) is None
    assert atr_at(candles, 2, strategy) is None
    assert evaluate_candle(candles, 2, strategy) is None


def test_idempotency_key_is_stable_when_series_starts_later() -> None:
    strategy = _strategy(atr_period=2, breakout_lookback=3)
    candles = [
        _candle(0, "10", "8", "9"),
        _candle(1, "10", "8", "9"),
        _candle(2, "10", "8", "9"),
        _candle(3, "10", "8", "9"),
        _candle(4, "10", "8", "9"),
        _candle(5, "10", "8", "9"),
        _candle(6, "12", "9", "11"),
    ]

    full_candidate = evaluate_candle(candles, 6, strategy)
    sliced_candidate = evaluate_candle(candles[2:], 4, strategy)

    assert full_candidate is not None
    assert sliced_candidate is not None
    assert sliced_candidate.idempotency_key == full_candidate.idempotency_key


def test_configured_lookback_changes_breakout_behavior() -> None:
    candles = [
        _candle(0, "20", "8", "9"),
        _candle(1, "10", "8", "9"),
        _candle(2, "10", "8", "9"),
        _candle(3, "10", "8", "9"),
        _candle(4, "10", "8", "9"),
        _candle(5, "16", "8", "15"),
    ]

    assert evaluate_candle(candles, 5, _strategy(atr_period=2, breakout_lookback=5)) is None
    assert evaluate_candle(candles, 5, _strategy(atr_period=2, breakout_lookback=3)) is not None
    assert scan_candidates(candles, _strategy(atr_period=2, breakout_lookback=3))
