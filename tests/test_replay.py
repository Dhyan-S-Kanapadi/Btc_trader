"""Tests for the deterministic, offline replay core."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trader.config import Settings
from trader.models import Candidate
from trader.replay import (
    AccountConfig,
    TakeAllPolicy,
    VolumeFilterPolicy,
    generate_candles,
    policy_for,
    run_replay,
    run_routed_replay,
    step,
)
from trader.replay.engine import ReplayState
from trader.risk import AccountState


def _config() -> Settings:
    base = Settings()
    return base.model_copy(
        update={"strategy": base.strategy.model_copy(update={"symbol": "SYNTH-BTC"})}
    )


def test_synthetic_candles_are_seeded_valid_and_clearly_labeled() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert generate_candles(1, 20, start, "1h") == generate_candles(1, 20, start, "1h")
    for candle in generate_candles(1, 20, start, "1h"):
        assert candle.symbol == "SYNTH-BTC"
        assert (
            candle.low
            <= min(candle.open, candle.close)
            <= max(candle.open, candle.close)
            <= candle.high
        )


def test_replay_is_deterministic_and_offline() -> None:
    candles = generate_candles(1, 200, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    first = run_replay(candles, TakeAllPolicy(), _config())
    second = run_replay(candles, TakeAllPolicy(), _config())
    assert first.trades == second.trades
    assert first.decisions == second.decisions
    assert first.equity == second.equity


def test_bounded_history_matches_full_history_for_result() -> None:
    candles = generate_candles(2, 200, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    result = run_replay(candles, TakeAllPolicy(), _config())
    assert len(result.equity) == len(candles)


def test_future_candles_cannot_change_prior_events_or_equity() -> None:
    candles = generate_candles(5, 180, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    cutoff = 120
    prefix = run_replay(candles[:cutoff], TakeAllPolicy(), _config())
    full = run_replay(candles, TakeAllPolicy(), _config())
    assert prefix.decisions == tuple(
        decision
        for decision in full.decisions
        if decision.candidate.signal_time < candles[cutoff].open_time
    )
    assert prefix.equity == full.equity[:cutoff]


def test_step_is_pure_for_same_inputs() -> None:
    candles = generate_candles(3, 120, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    config = _config()
    state = ReplayState(
        account_id="A",
        cash=Decimal("10000"),
        risk=AccountState(
            account_id="A",
            equity=Decimal("10000"),
            peak_equity=Decimal("10000"),
            day_start_equity=Decimal("10000"),
            current_day=candles[0].open_time.date(),
            open_position_count=0,
        ),
    )
    history = candles[:100]
    assert step(state, history, history[-1], TakeAllPolicy(), config) == step(
        state, history, history[-1], TakeAllPolicy(), config
    )


def test_volume_filter_baseline_can_skip() -> None:
    candles = generate_candles(4, 150, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    assert (
        run_replay(candles, VolumeFilterPolicy(Decimal("999")), _config()).decisions
        != run_replay(candles, TakeAllPolicy(), _config()).decisions
    )


def test_router_shares_signal_but_keeps_accounts_independent() -> None:
    candles = generate_candles(7, 200, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    config = _config()

    def state(account_id: str) -> ReplayState:
        return ReplayState(
            account_id=account_id,
            cash=Decimal("10000"),
            risk=AccountState(
                account_id=account_id,
                equity=Decimal("10000"),
                peak_equity=Decimal("10000"),
                day_start_equity=Decimal("10000"),
                current_day=candles[0].open_time.date(),
                open_position_count=0,
            ),
        )

    accounts = {
        account_id: (
            state(account_id),
            AccountConfig(
                account_id=account_id,
                label=f"Paper {account_id}",
                policy_name="take_all" if account_id == "A" else "skip_all",
                starting_equity=Decimal("10000"),
            ),
        )
        for account_id in "ABCD"
    }
    results = run_routed_replay(candles, accounts, config)
    decisions = {account_id: result.decisions for account_id, result in results.items()}
    assert decisions["A"]
    assert (
        [item.candidate for item in decisions["B"]]
        == [item.candidate for item in decisions["C"]]
        == [item.candidate for item in decisions["D"]]
    )
    assert all(item.reason == "agent not wired yet (#27)" for item in decisions["B"])
    assert results["B"].state.position is None
    assert results["B"].trades == ()
    assert results["A"].state != results["B"].state


def test_unknown_account_policy_fails_fast() -> None:
    with pytest.raises(ValueError, match="unknown paper-account policy"):
        policy_for("not-a-policy", _config())


def test_router_completes_every_phase_one_before_a_policy_runs(monkeypatch) -> None:
    """The worker can persist all phase-one results before a future agent policy call."""

    from trader.replay import router

    candles = generate_candles(9, 120, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    config = _config()
    events: list[tuple[str, str]] = []
    original = router.phase_one

    def phase(state, history, candle, settings, stale):
        events.append(("phase_one", state.account_id))
        return original(state, history, candle, settings, stale)

    class Policy:
        def decide(self, snapshot, candidate):
            events.append(("policy", candidate.idempotency_key))
            return TakeAllPolicy().decide(snapshot, candidate)

    monkeypatch.setattr(router, "phase_one", phase)
    monkeypatch.setattr(
        router,
        "evaluate_candle",
        lambda *_args: Candidate(
            symbol="SYNTH-BTC",
            bar_index=len(candles) - 1,
            signal_time=candles[-1].open_time,
            reference_price=candles[-1].close,
            atr=Decimal("1"),
            breakout_level=candles[-1].close,
            idempotency_key="phase-order",
        ),
    )
    accounts = {
        account_id: (
            ReplayState(
                account_id=account_id,
                cash=Decimal("10000"),
                risk=AccountState(
                    account_id=account_id,
                    equity=Decimal("10000"),
                    peak_equity=Decimal("10000"),
                    day_start_equity=Decimal("10000"),
                    current_day=candles[0].open_time.date(),
                    open_position_count=0,
                ),
            ),
            AccountConfig(
                account_id=account_id,
                label=account_id,
                policy_name="skip_all",
                starting_equity=Decimal("10000"),
            ),
        )
        for account_id in ("A", "B")
    }
    router.route_candle(
        accounts, candles, candles[-1], config, policies={"A": Policy(), "B": Policy()}
    )
    first_policy = next(index for index, event in enumerate(events) if event[0] == "policy")
    assert {account_id for kind, account_id in events[:first_policy] if kind == "phase_one"} == {
        "A",
        "B",
    }
