"""Policy adapter that can only veto an already-proposed paper entry."""

from __future__ import annotations

from collections.abc import Callable

from trader.control import AgentGate
from trader.models import Candidate, Snapshot
from trader.replay.engine import PolicyDecision

from .client import AgentClient


class AgentVetoPolicy:
    """Translate a guardrailed agent verdict into the existing policy seam."""

    def __init__(
        self,
        client: AgentClient,
        gate: AgentGate,
        variant: str = "base",
        enrich: Callable[[Snapshot], Snapshot] | None = None,
    ) -> None:
        self.client, self.gate, self.variant, self.enrich = client, gate, variant, enrich

    def decide(self, snapshot: Snapshot, candidate: Candidate) -> PolicyDecision:
        if self.enrich is not None:
            try:
                snapshot = self.enrich(snapshot)
            except Exception:
                # Evidence failures cannot block the base-veto path.
                pass
        result = self.client.investigate(
            snapshot,
            gate=self.gate,
            variant=self.variant,
            account_context={"candidate_key": candidate.idempotency_key},
        )
        if result.verdict.action == "TAKE":
            return PolicyDecision(action="TAKE", reason="agent_no_veto")
        return PolicyDecision(
            action="SKIP",
            reason=result.status,
            verdict={"action": result.verdict.action, "status": result.status},
            model_version=result.model_id,
            prompt_version=result.prompt_version,
        )
