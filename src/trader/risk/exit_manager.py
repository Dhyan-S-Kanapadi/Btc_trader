"""Pure candle-by-candle management for paper-trading exits."""

# ruff: noqa: E501

from decimal import Decimal

from trader.broker import Fill, check_stop, fill_exit_at_open
from trader.config import CostSettings, Settings
from trader.models import Candle, FrozenModel, Position, Trade


class ExitResult(FrozenModel):
    """Updated position plus an optional paper exit fill and stable reason code."""

    position: Position
    exit_fill: Fill | None = None
    reason_code: str | None = None


def process_candle(
    position: Position, candle: Candle, atr: Decimal | None, config: Settings, costs: CostSettings
) -> ExitResult:
    """Process one closed candle: due time exit, old stop, ratchet for next candle, then bar count."""

    if position.time_stop_exit_due:
        fill = fill_exit_at_open(position.qty, candle, costs)
        reason = "stop" if candle.open <= position.stop_price else "time_stop"
        return ExitResult(position=position, exit_fill=fill, reason_code=reason)
    fill = check_stop(position.stop_price, candle, position.qty, costs)
    if fill is not None:
        reason = "trailing_stop" if position.highest_high_since_entry is not None else "stop"
        return ExitResult(position=position, exit_fill=fill, reason_code=reason)
    highest = max(position.highest_high_since_entry or position.entry_price, candle.high)
    stop = position.stop_price
    if atr is not None:
        stop = max(stop, highest - config.strategy.trailing_stop_atr_mult * atr)
    bars = position.bars_held + 1
    return ExitResult(
        position=position.model_copy(
            update={
                "highest_high_since_entry": highest,
                "stop_price": stop,
                "bars_held": bars,
                "time_stop_exit_due": bars >= config.strategy.time_stop_bars,
            }
        )
    )


def trade_from_exit(position: Position, fill: Fill, reason: str) -> Trade:
    """Build a completed trade with net fees retained for later P&L reporting."""

    return Trade(
        account_id=position.account_id,
        symbol=position.symbol,
        qty=position.qty,
        entry_price=position.entry_price,
        entry_time=position.entry_time,
        stop_price=position.stop_price,
        initial_stop_price=position.initial_stop_price,
        exit_price=fill.price,
        exit_time=fill.fill_time,
        fees=position.entry_fee + fill.fee,
        reason=reason,
    )
