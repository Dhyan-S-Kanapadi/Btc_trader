"""Pure point-in-time evidence snapshot builder."""

from collections.abc import Sequence
from decimal import Decimal

from trader.config import StrategySettings
from trader.models import Candidate, Candle, Snapshot


def build_snapshot(
    candles: Sequence[Candle], candidate: Candidate, config: StrategySettings
) -> Snapshot:
    """Build v1 evidence through signal time, with null fields when history is insufficient.

    Volume ratio is signal volume/prior-lookback mean volume; breakout strength is
    (reference-breakout)/ATR; atr_pct is ATR/reference; range_24h_pct is the inclusive
    lookback high-low/reference; and trend_vs_sma is reference/inclusive SMA minus one.
    """

    signal_index = next(
        (
            index
            for index, candle in enumerate(candles)
            if candle.symbol == candidate.symbol and candle.open_time == candidate.signal_time
        ),
        None,
    )
    history = candles[: signal_index + 1] if signal_index is not None else ()
    signal = history[-1] if history else None

    volume_ratio = _volume_ratio(history, signal, config.breakout_lookback)
    range_24h_pct = _range_fraction(history, candidate.reference_price, config.breakout_lookback)
    trend_vs_sma = _trend_fraction(history, candidate.reference_price, config.trend_sma_period)
    return Snapshot(
        idempotency_key=candidate.idempotency_key,
        symbol=candidate.symbol,
        signal_time=candidate.signal_time,
        reference_price=candidate.reference_price,
        atr=candidate.atr,
        breakout_level=candidate.breakout_level,
        volume_ratio=volume_ratio,
        breakout_strength_atr=(candidate.reference_price - candidate.breakout_level)
        / candidate.atr,
        atr_pct=candidate.atr / candidate.reference_price,
        range_24h_pct=range_24h_pct,
        trend_vs_sma=trend_vs_sma,
    )


def snapshot_to_json(snapshot: Snapshot) -> str:
    """Serialize a snapshot as lossless JSON with UTC ISO-8601 timestamps for HTTP transport."""

    return snapshot.model_dump_json()


def snapshot_from_json(payload: str) -> Snapshot:
    """Deserialize a lossless JSON snapshot payload and validate its version-1 field set."""

    return Snapshot.model_validate_json(payload)


def _volume_ratio(
    history: Sequence[Candle], signal: Candle | None, lookback: int
) -> Decimal | None:
    if signal is None or len(history) <= lookback:
        return None
    mean_volume = (
        sum((candle.volume for candle in history[-lookback - 1 : -1]), Decimal("0")) / lookback
    )
    return None if mean_volume == 0 else signal.volume / mean_volume


def _range_fraction(
    history: Sequence[Candle], reference_price: Decimal, lookback: int
) -> Decimal | None:
    if len(history) < lookback:
        return None
    window = history[-lookback:]
    return (
        max(candle.high for candle in window) - min(candle.low for candle in window)
    ) / reference_price


def _trend_fraction(
    history: Sequence[Candle], reference_price: Decimal, period: int
) -> Decimal | None:
    if len(history) < period:
        return None
    sma = sum((candle.close for candle in history[-period:]), Decimal("0")) / period
    return reference_price / sma - Decimal("1")
