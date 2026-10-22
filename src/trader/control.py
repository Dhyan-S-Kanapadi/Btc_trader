"""Fail-closed agent control-plane types and the policy boundary.

This module deliberately has no risk, broker, exit, network, or model imports.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from trader.models import Candidate, FrozenModel, Snapshot

if TYPE_CHECKING:
    from trader.replay.engine import DecisionPolicy, PolicyDecision

DEFAULT_PER_CANDIDATE_CAP = Decimal("0.10")
DEFAULT_PER_DAY_CAP = Decimal("1.00")


class GlobalControl(FrozenModel):
    agent_enabled: bool = False
    kill_switch: bool = False
    jev_enabled: bool = False
    model_version: str | None = None
    prompt_version: str | None = None
    per_candidate_cap: Decimal = Field(default=DEFAULT_PER_CANDIDATE_CAP, ge=0)
    per_day_cap: Decimal = Field(default=DEFAULT_PER_DAY_CAP, ge=0)


class AccountControl(FrozenModel):
    account_id: str = Field(min_length=1)
    agent_enabled: bool = False
    shadow: bool = True
    kill_switch: bool = False
    memory_enabled: bool = False
    jev_enabled: bool = False
    per_candidate_cap: Decimal | None = Field(default=None, ge=0)
    per_day_cap: Decimal | None = Field(default=None, ge=0)
    fallback_policy: Literal["skip_all"] = "skip_all"


class ControlConfig(FrozenModel):
    global_control: GlobalControl = Field(default_factory=GlobalControl)
    accounts: dict[str, AccountControl] = Field(default_factory=dict)
    readable: bool = True


class AgentGate(FrozenModel):
    mode: Literal["off", "shadow", "live"]
    killed: bool = False
    model_version: str | None = None
    prompt_version: str | None = None
    per_candidate_cap: Decimal = DEFAULT_PER_CANDIDATE_CAP
    per_day_cap: Decimal = DEFAULT_PER_DAY_CAP
    fallback_policy: Literal["skip_all"] = "skip_all"


class EvidenceGate(FrozenModel):
    """Separate, fail-closed permission for optional per-variant evidence."""

    jev: bool = False
    memory: bool = False


def resolve_agent_gate(control: ControlConfig | None, account_id: str) -> AgentGate:
    """Resolve an account gate; absent or unreadable input is always non-live."""

    if control is None or not control.readable:
        return AgentGate(mode="off", killed=True)
    global_control = control.global_control
    account = control.accounts.get(account_id)
    if global_control.kill_switch or (account is not None and account.kill_switch):
        return AgentGate(mode="off", killed=True)
    if not global_control.agent_enabled or account is None or not account.agent_enabled:
        return AgentGate(mode="off")
    return AgentGate(
        mode="shadow" if account.shadow else "live",
        model_version=global_control.model_version,
        prompt_version=global_control.prompt_version,
        per_candidate_cap=account.per_candidate_cap or global_control.per_candidate_cap,
        per_day_cap=account.per_day_cap or global_control.per_day_cap,
        fallback_policy=account.fallback_policy,
    )


def resolve_evidence_gate(
    control: ControlConfig | None, account_id: str, variant: str
) -> EvidenceGate:
    """Evidence is spend-capable, so it follows the agent gate and variant exactly."""

    gate = resolve_agent_gate(control, account_id)
    if gate.killed or gate.mode == "off" or control is None or not control.readable:
        return EvidenceGate()
    account = control.accounts.get(account_id)
    if account is None:
        return EvidenceGate()
    return EvidenceGate(
        jev=variant == "jev" and control.global_control.jev_enabled and account.jev_enabled,
        memory=variant == "memory" and account.memory_enabled,
    )


def within_cost_cap(spent: Decimal, cap: Decimal) -> bool:
    """Expose the cap comparison; accounting/spend tracking remains out of scope."""

    return spent <= cap


class GatedPolicy:
    """Restrict an inner decision policy without granting any risk or exit authority."""

    def __init__(self, gate: AgentGate, inner: DecisionPolicy, fallback: DecisionPolicy) -> None:
        self.gate, self.inner, self.fallback = gate, inner, fallback

    def decide(self, snapshot: Snapshot, candidate: Candidate) -> PolicyDecision:
        from trader.replay.engine import PolicyDecision

        if self.gate.killed:
            return PolicyDecision(action="SKIP", reason="agent_killed")
        if self.gate.mode == "off":
            return PolicyDecision(action="SKIP", reason="agent_off")
        try:
            verdict = self.inner.decide(snapshot, candidate)
        except Exception:
            return PolicyDecision(action="SKIP", reason="agent_error")
        if self.gate.mode == "shadow":
            actual = self.fallback.decide(snapshot, candidate)
            return actual.model_copy(
                update={
                    "verdict": {"action": verdict.action, "reason": verdict.reason},
                    "shadow": True,
                    "model_version": self.gate.model_version,
                    "prompt_version": self.gate.prompt_version,
                }
            )
        return verdict
