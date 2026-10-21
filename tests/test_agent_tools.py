"""Safety tests for read-only, point-in-time agent evidence tools."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trader.agent_tools import InMemoryCandleSource, ToolError, ToolRegistry
from trader.config import Settings
from trader.models import Candle


def _candles(count: int) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    return [
        Candle(
            symbol="BTCUSDT",
            open_time=start + timedelta(hours=index),
            open=Decimal("100"),
            high=Decimal("102"),
            low=Decimal("99"),
            close=Decimal("101"),
            volume=Decimal(index + 1),
        )
        for index in range(count)
    ]


def _registry(candles: list[Candle], as_of: datetime) -> ToolRegistry:
    settings = Settings().model_copy(
        update={
            "agent_tools": Settings().agent_tools.model_copy(
                update={"volume_long_lookback_bars": 3}
            )
        }
    )
    return ToolRegistry(as_of, InMemoryCandleSource(candles), settings)


def test_boundary_is_inclusive_and_later_candles_do_not_change_result() -> None:
    candles = _candles(6)
    as_of = candles[3].open_time + timedelta(hours=1)
    first = _registry(candles, as_of).call("volume_vs_average", {"lookback_bars": 2})
    second = _registry(candles + _candles(20)[6:], as_of).call(
        "volume_vs_average", {"lookback_bars": 2}
    )
    # Latest=4; prior two=(2+3)/2=2.5; short ratio=1.6.
    assert first == second
    assert first["short_ratio"] == Decimal("1.6")


def test_model_cannot_supply_asof_and_schema_omits_it() -> None:
    registry = _registry(_candles(6), datetime(2026, 1, 1, 6, tzinfo=UTC))
    assert "as_of" not in registry.schemas()["volume_vs_average"]["properties"]
    with pytest.raises(ToolError, match="as_of_override_rejected"):
        registry.call("volume_vs_average", {"as_of": "2027-01-01T00:00:00Z"})


def test_future_leak_is_rejected_loudly() -> None:
    class LeakingSource:
        def candles(self, *_args):
            return _candles(8)

    registry = ToolRegistry(datetime(2026, 1, 1, 3, tzinfo=UTC), LeakingSource(), Settings())
    with pytest.raises(ToolError, match="asof_violation"):
        registry.call("volume_vs_average", {})
