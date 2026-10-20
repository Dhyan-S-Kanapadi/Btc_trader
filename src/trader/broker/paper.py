"""Pure, deterministic fills against recorded candles for paper trading only."""

# ruff: noqa: E501

from decimal import Decimal
from typing import Literal

from pydantic import Field

from trader.config import CostSettings
from trader.models import Candle, FrozenModel


class Fill(FrozenModel):
    """One simulated fill with adverse slippage and a per-side fee."""

    price: Decimal = Field(gt=0)
    quantity: Decimal = Field(gt=0)
    fee: Decimal = Field(ge=0)
    fill_time: object
    side: Literal["BUY", "SELL"]


class FillRejection(FrozenModel):
    """A deterministic unfilled entry reason."""

    reason_code: str = Field(min_length=1)


def fill_entry(
    quantity: Decimal, next_candle: Candle, cash: Decimal, costs: CostSettings
) -> Fill | FillRejection:
    """Buy at next open plus slippage, reducing quantity to what cash including fee can afford."""

    price = next_candle.open * (Decimal("1") + costs.slippage_bps / Decimal("10000"))
    affordable = cash / (price * (Decimal("1") + costs.fee_bps / Decimal("10000")))
    filled_quantity = min(quantity, affordable)
    if filled_quantity <= 0:
        return FillRejection(reason_code="INSUFFICIENT_CASH")
    return _fill("BUY", next_candle.open, filled_quantity, next_candle, costs)


def check_stop(
    position_stop: Decimal, candle: Candle, quantity: Decimal, costs: CostSettings
) -> Fill | None:
    """Sell at adverse open on a gap, otherwise adverse stop price when the low reaches the stop."""

    if candle.open <= position_stop:
        return _fill("SELL", candle.open, quantity, candle, costs)
    if candle.low <= position_stop:
        return _fill("SELL", position_stop, quantity, candle, costs)
    return None


def fill_exit_at_open(quantity: Decimal, candle: Candle, costs: CostSettings) -> Fill:
    """Sell at candle open less adverse slippage with the sell-side fee."""

    return _fill("SELL", candle.open, quantity, candle, costs)


def resolve_stop_or_target(
    stop: Decimal, target: Decimal, candle: Candle
) -> Literal["stop", "target"] | None:
    """Resolve a touched stop or target, conservatively selecting stop when both occur in one candle."""

    stop_hit = candle.low <= stop
    target_hit = candle.high >= target
    if stop_hit:
        return "stop"
    if target_hit:
        return "target"
    return None


def cash_change(fill: Fill) -> Decimal:
    """Return cash delta: buy costs notional plus fee; sell credits notional less fee."""

    notional = fill.price * fill.quantity
    return -notional - fill.fee if fill.side == "BUY" else notional - fill.fee


def _fill(
    side: Literal["BUY", "SELL"],
    raw_price: Decimal,
    quantity: Decimal,
    candle: Candle,
    costs: CostSettings,
) -> Fill:
    slippage = costs.slippage_bps / Decimal("10000")
    price = raw_price * (Decimal("1") + slippage if side == "BUY" else Decimal("1") - slippage)
    fee = price * quantity * costs.fee_bps / Decimal("10000")
    return Fill(price=price, quantity=quantity, fee=fee, fill_time=candle.open_time, side=side)
