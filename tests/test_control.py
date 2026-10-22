"""Fail-closed control-plane behavior without model, broker, or network code."""

from datetime import UTC, datetime
from decimal import Decimal

from trader.control import (
    AccountControl,
    ControlConfig,
    GatedPolicy,
    GlobalControl,
    resolve_agent_gate,
    resolve_evidence_gate,
)
from trader.models import Candidate, Snapshot
from trader.replay import PolicyDecision, TakeAllPolicy


def _inputs() -> tuple[Snapshot, Candidate]:
    candidate = Candidate(
        symbol="BTCUSDT",
        bar_index=1,
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("1"),
        breakout_level=Decimal("99"),
        idempotency_key="candidate",
    )
    return Snapshot(**candidate.model_dump(exclude={"bar_index"})), candidate


def test_resolver_is_fail_closed_and_kill_precedes_enablement() -> None:
    assert resolve_agent_gate(None, "B").killed
    control = ControlConfig(
        global_control=GlobalControl(agent_enabled=True),
        accounts={"B": AccountControl(account_id="B", agent_enabled=True, kill_switch=True)},
    )
    assert resolve_agent_gate(control, "B").killed
    assert resolve_agent_gate(control, "C").mode == "off"


def test_evidence_switches_default_off() -> None:
    control = ControlConfig()
    assert not control.global_control.jev_enabled
    assert not AccountControl(account_id="D").memory_enabled


def test_evidence_requires_a_live_or_shadow_agent_and_the_matching_variant() -> None:
    control = ControlConfig(
        global_control=GlobalControl(agent_enabled=True, jev_enabled=True),
        accounts={
            "C": AccountControl(account_id="C", agent_enabled=True, jev_enabled=True),
            "D": AccountControl(account_id="D", agent_enabled=True, memory_enabled=True),
        },
    )
    assert resolve_evidence_gate(control, "C", "jev").jev
    assert not resolve_evidence_gate(control, "C", "base").jev
    assert resolve_evidence_gate(control, "D", "memory").memory
    assert not resolve_evidence_gate(ControlConfig(), "C", "jev").jev


def test_shadow_records_inner_verdict_but_uses_skip_fallback() -> None:
    snapshot, candidate = _inputs()
    control = ControlConfig(
        global_control=GlobalControl(agent_enabled=True, model_version="m1"),
        accounts={"B": AccountControl(account_id="B", agent_enabled=True, shadow=True)},
    )
    decision = GatedPolicy(resolve_agent_gate(control, "B"), TakeAllPolicy(), _Skip()).decide(
        snapshot, candidate
    )
    assert (decision.action, decision.reason, decision.shadow) == ("SKIP", "fallback", True)
    assert decision.verdict == {"action": "TAKE", "reason": "take_all"}


class _Skip:
    def decide(self, snapshot, candidate) -> PolicyDecision:
        return PolicyDecision(action="SKIP", reason="fallback")
