"""Tests for deterministic new-entry risk gates."""

from datetime import UTC, date, datetime
from decimal import Decimal
from inspect import signature

from trader.config import Settings
from trader.models import Candidate
from trader.risk import AccountState, evaluate_entry, mark_equity


def _candidate(atr: str = "10") -> Candidate:
    values = dict(
        symbol="BTCUSDT",
        bar_index=1,
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal(atr),
        breakout_level=Decimal("90"),
        idempotency_key="key",
    )
    return Candidate.model_construct(**values) if Decimal(atr) <= 0 else Candidate(**values)


def _state(**changes) -> AccountState:
    values = dict(
        account_id="A",
        equity=Decimal("1000"),
        peak_equity=Decimal("1000"),
        day_start_equity=Decimal("1000"),
        current_day=date(2026, 1, 1),
        open_position_count=0,
    )
    values.update(changes)
    return AccountState(**values)


def _evaluate(state: AccountState | None = None, **changes):
    return evaluate_entry(
        _candidate(changes.pop("atr", "10")),
        Decimal(changes.pop("entry", "100")),
        state or _state(),
        datetime(2026, 1, 1, tzinfo=UTC),
        changes.pop("stale", False),
        Settings(),
    )


def test_sizing_stop_and_notional_cap() -> None:
    # Stop = 100 - 1.5*10 = 85; risk budget = 1000*0.01 = 10; qty = 10/15 = 2/3; notional = 200/3.
    decision = _evaluate()
    assert decision.approved and decision.stop_price == Decimal("85")
    assert decision.quantity == Decimal("2") / Decimal("3")
    assert decision.notional == Decimal("200") / Decimal("3")
    tight = _evaluate(atr="0.01")
    assert tight.quantity == Decimal("10") and tight.notional == Decimal("1000")


def test_rejections_and_boundaries() -> None:
    assert _evaluate(stale=True).reason.code == "STALE_DATA"
    assert _evaluate(_state(halted=True, halt_reason="x")).reason.code == "HALTED"
    assert _evaluate(_state(equity=Decimal("900"))).reason.code == "DRAWDOWN_HALT"
    assert _evaluate(_state(equity=Decimal("901"), day_start_equity=Decimal("900"))).approved
    assert (
        _evaluate(_state(equity=Decimal("970"), peak_equity=Decimal("1000"))).reason.code
        == "DAILY_LOSS_CAP"
    )
    assert _evaluate(_state(open_position_count=1)).reason.code == "MAX_OPEN_POSITIONS"
    assert not _evaluate(_state(equity=Decimal("0"))).approved
    for state, entry, atr in [
        (_state(), "0", "10"),
        (_state(), "100", "0"),
    ]:
        assert _evaluate(state, entry=entry, atr=atr).reason.code == "INVALID_INPUT"


def test_halt_rollover_determinism_and_no_override_parameters() -> None:
    halted = _evaluate(_state(equity=Decimal("900")))
    assert _evaluate(halted.updated_state).reason.code == "HALTED"
    next_day = _evaluate(
        _state(equity=Decimal("970"), peak_equity=Decimal("1000")),
    )
    assert next_day.reason.code == "DAILY_LOSS_CAP"
    rolled = evaluate_entry(
        _candidate(),
        Decimal("100"),
        _state(equity=Decimal("970"), peak_equity=Decimal("1000")),
        datetime(2026, 1, 2, tzinfo=UTC),
        False,
        Settings(),
    )
    assert rolled.updated_state.day_start_equity == Decimal("970")
    assert rolled.approved and _evaluate() == _evaluate()
    assert {
        "risk_per_trade",
        "daily_loss_cap",
        "max_drawdown_halt",
        "max_open_positions",
    }.isdisjoint(signature(evaluate_entry).parameters)
    assert mark_equity(_state(peak_equity=Decimal("1100")), Decimal("1000")).peak_equity == Decimal(
        "1100"
    )
