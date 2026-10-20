"""Pure deterministic gates for new paper-trading entries."""

from datetime import UTC, date, datetime
from decimal import Decimal

from pydantic import Field

from trader.config import Settings
from trader.models import Candidate, FrozenModel


class AccountState(FrozenModel):
    """Persistable account mark; daily loss uses marked equity against day-start equity."""

    account_id: str = Field(min_length=1)
    equity: Decimal
    peak_equity: Decimal
    day_start_equity: Decimal
    current_day: date
    open_position_count: int = Field(ge=0)
    halted: bool = False
    halt_reason: str | None = None


class RiskReason(FrozenModel):
    """Stable machine-readable reason code and concise human message."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class RiskDecision(FrozenModel):
    """Approval or rejection for a new entry; exits are intentionally outside this gate."""

    approved: bool
    reason: RiskReason
    stop_price: Decimal | None = None
    quantity: Decimal | None = None
    notional: Decimal | None = None
    updated_state: AccountState


def mark_equity(state: AccountState, equity: Decimal) -> AccountState:
    """Return a mark with equity updated and a peak that never decreases."""

    return state.model_copy(
        update={"equity": equity, "peak_equity": max(state.peak_equity, equity)}
    )


def evaluate_entry(
    candidate: Candidate,
    entry_price: Decimal,
    state: AccountState,
    now: datetime,
    data_is_stale: bool,
    config: Settings,
) -> RiskDecision:
    """Gate a new long entry in fixed order; later fill handling re-sizes the estimate."""

    def reject(code: str, message: str, updated: AccountState = state) -> RiskDecision:
        return RiskDecision(
            approved=False, reason=RiskReason(code=code, message=message), updated_state=updated
        )

    if state.halted:
        return reject("HALTED", "Account remains halted.")
    if data_is_stale:
        return reject("STALE_DATA", "Market data is stale.")
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError("now must be timezone-aware UTC")
    today = now.date()
    updated = state
    if today != state.current_day:
        updated = state.model_copy(update={"current_day": today, "day_start_equity": state.equity})
    risk = config.risk
    if updated.equity <= updated.peak_equity * (Decimal("1") - risk.max_drawdown_halt):
        halted = updated.model_copy(update={"halted": True, "halt_reason": "DRAWDOWN_HALT"})
        return reject("DRAWDOWN_HALT", "Drawdown limit reached.", halted)
    if updated.equity <= updated.day_start_equity * (Decimal("1") - risk.daily_loss_cap):
        return reject("DAILY_LOSS_CAP", "Daily equity-loss cap reached.", updated)
    if updated.open_position_count >= risk.max_open_positions:
        return reject("MAX_OPEN_POSITIONS", "Maximum open positions reached.", updated)
    if updated.equity <= 0 or entry_price <= 0 or candidate.atr <= 0:
        return reject("INVALID_INPUT", "Equity, entry price, and ATR must be positive.", updated)
    stop_price = entry_price - config.strategy.initial_stop_atr_mult * candidate.atr
    stop_distance = entry_price - stop_price
    if stop_distance <= 0 or stop_price >= entry_price:
        return reject("INVALID_STOP", "Initial long stop must be below entry.", updated)
    risk_quantity = (updated.equity * risk.risk_per_trade) / stop_distance
    quantity = min(risk_quantity, updated.equity / entry_price)
    notional = quantity * entry_price
    if quantity <= 0:
        return reject("INVALID_QUANTITY", "Calculated quantity is not positive.", updated)
    return RiskDecision(
        approved=True,
        reason=RiskReason(code="APPROVED", message="Entry satisfies configured risk limits."),
        stop_price=stop_price,
        quantity=quantity,
        notional=notional,
        updated_state=updated,
    )
