"""Tests for deterministic candle-only paper fills."""

# ruff: noqa: E501

from datetime import UTC, datetime
from decimal import Decimal

from trader.broker import (
    FillRejection,
    cash_change,
    check_stop,
    fill_entry,
    fill_exit_at_open,
    resolve_stop_or_target,
)
from trader.config import CostSettings
from trader.models import Candle


def _candle(open_: str = "100", low: str = "95", high: str = "110") -> Candle:
    return Candle(
        symbol="BTCUSDT",
        open_time=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(open_),
        volume=Decimal("1"),
    )


def test_entry_fee_cash_and_affordability() -> None:
    # Buy price = 100*(1+.0005)=100.05; fee = 100.05*2*.001=.2001; cash delta=-200.3001.
    fill = fill_entry(Decimal("2"), _candle(), Decimal("1000"), CostSettings())
    assert not isinstance(fill, FillRejection)
    assert fill.price == Decimal("100.05") and fill.fee == Decimal("0.20010")
    assert cash_change(fill) == Decimal("-200.30010")
    partial = fill_entry(Decimal("2"), _candle(), Decimal("100.15005"), CostSettings())
    assert not isinstance(partial, FillRejection) and partial.quantity == Decimal("1")
    assert partial.price * partial.quantity + partial.fee <= Decimal("100.15005")


def test_stop_gap_slippage_fees_and_resolution() -> None:
    normal = check_stop(Decimal("90"), _candle("100", "89", "110"), Decimal("1"), CostSettings())
    gap = check_stop(Decimal("90"), _candle("90", "80", "100"), Decimal("1"), CostSettings())
    assert normal is not None and normal.price == Decimal("89.955") and normal.fee > 0
    assert gap is not None and gap.price == Decimal("89.955")
    assert (
        check_stop(Decimal("90"), _candle("100", "91", "110"), Decimal("1"), CostSettings()) is None
    )
    assert fill_exit_at_open(Decimal("1"), _candle(), CostSettings()).price == Decimal("99.9500")
    assert (
        resolve_stop_or_target(Decimal("90"), Decimal("105"), _candle("100", "89", "106")) == "stop"
    )
    assert (
        resolve_stop_or_target(Decimal("90"), Decimal("105"), _candle("100", "95", "106"))
        == "target"
    )
