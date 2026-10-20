"""Point-in-time ATR and breakout candidate rule."""

from collections.abc import Sequence
from decimal import Decimal

from trader.config import StrategySettings
from trader.models import Candidate, Candle


def true_range(candles: Sequence[Candle], index: int) -> Decimal | None:
    """Return max(high-low, abs(high-prior close), abs(low-prior close)); first candle is None."""

    if index <= 0 or index >= len(candles):
        return None
    candle = candles[index]
    previous_close = candles[index - 1].close
    return max(
        candle.high - candle.low,
        abs(candle.high - previous_close),
        abs(candle.low - previous_close),
    )


def atr_at(candles: Sequence[Candle], index: int, strategy: StrategySettings) -> Decimal | None:
    """Return the simple average of the trailing atr_period true ranges through index, or None."""

    first_true_range_index = index - strategy.atr_period + 1
    if first_true_range_index < 1 or index >= len(candles):
        return None
    ranges = [true_range(candles, current) for current in range(first_true_range_index, index + 1)]
    if any(value is None for value in ranges):
        return None
    return sum(ranges, Decimal("0")) / strategy.atr_period


def evaluate_candle(
    candles: Sequence[Candle], index: int, strategy: StrategySettings
) -> Candidate | None:
    """Return a candidate when close is strictly above the prior high and ATR is available."""

    if index < strategy.breakout_lookback or index >= len(candles):
        return None
    candle = candles[index]
    if candle.symbol != strategy.symbol:
        return None
    atr = atr_at(candles, index, strategy)
    if atr is None:
        return None
    breakout_level = max(
        prior.high for prior in candles[index - strategy.breakout_lookback : index]
    )
    if candle.close <= breakout_level:
        return None
    signal_time = candle.open_time
    return Candidate(
        symbol=strategy.symbol,
        bar_index=index,
        signal_time=signal_time,
        reference_price=candle.close,
        atr=atr,
        breakout_level=breakout_level,
        idempotency_key=f"{strategy.symbol}:{strategy.interval}:{signal_time.isoformat()}",
    )


def scan_candidates(candles: Sequence[Candle], strategy: StrategySettings) -> list[Candidate]:
    """Return every point-in-time candidate through the single-candle evaluation rule."""

    return [
        candidate
        for index in range(len(candles))
        if (candidate := evaluate_candle(candles, index, strategy)) is not None
    ]
