"""Tests for pure paper exit management."""

# ruff: noqa: E501

from datetime import UTC, datetime
from decimal import Decimal

from trader.config import CostSettings, Settings
from trader.models import Candle, Position
from trader.risk import process_candle


def _position(**updates) -> Position:
    values = dict(
        account_id="A",
        symbol="BTCUSDT",
        qty=Decimal("1"),
        entry_price=Decimal("100"),
        entry_time=datetime(2026, 1, 1, tzinfo=UTC),
        stop_price=Decimal("90"),
        reason="entry",
        entry_fee=Decimal("0"),
    )
    values.update(updates)
    return Position(**values)


def _candle(open_: str, low: str, high: str) -> Candle:
    return Candle(
        symbol="BTCUSDT",
        open_time=datetime(2026, 1, 2, tzinfo=UTC),
        open=Decimal(open_),
        low=Decimal(low),
        high=Decimal(high),
        close=Decimal(open_),
        volume=Decimal("1"),
    )


def test_stop_gap_and_ratchet_next_candle() -> None:
    # Normal stop raw 90, sell slippage 5 bps => 89.955.
    normal = process_candle(
        _position(), _candle("100", "89", "105"), Decimal("2"), Settings(), CostSettings()
    )
    assert normal.exit_fill is not None and normal.exit_fill.price == Decimal("89.955")
    gap = process_candle(
        _position(), _candle("80", "70", "90"), Decimal("2"), Settings(), CostSettings()
    )
    assert gap.exit_fill is not None and gap.exit_fill.price == Decimal("79.960")
    updated = process_candle(
        _position(), _candle("100", "95", "110"), Decimal("5"), Settings(), CostSettings()
    )
    assert updated.exit_fill is None and updated.position.stop_price == Decimal("100")
    assert (
        process_candle(
            updated.position, _candle("99", "98", "101"), Decimal("5"), Settings(), CostSettings()
        ).reason_code
        == "trailing_stop"
    )
