"""Worker-side agent boundary tests; no model, network, or SDK calls."""

from datetime import UTC, datetime
from decimal import Decimal

from trader.agent_client import AgentClient, CircuitBreaker
from trader.control import AgentGate
from trader.models import Snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        idempotency_key="BTCUSDT:1h:2026-01-01T00:00:00+00:00",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("1"),
        breakout_level=Decimal("99"),
    )


class _Target:
    name = "test"

    def __init__(self) -> None:
        self.calls = 0

    def investigate(self, request, timeout_seconds):
        self.calls += 1
        return {
            "request_id": request["request_id"],
            "snapshot_digest": request["snapshot_digest"],
            "model_id": request["model_id"],
            "prompt_version": request["prompt_version"],
            "status": "ok",
            "verdict": {
                "action": "SKIP",
                "reasons": ["evidence is insufficient"],
                "cited_evidence": {"snapshot.symbol": "BTCUSDT"},
            },
        }


def test_off_gate_makes_no_target_call() -> None:
    target = _Target()
    result = AgentClient(target).investigate(
        _snapshot(), gate=AgentGate(mode="off"), variant="base", account_context={}
    )
    assert result.status == "agent_off"
    assert target.calls == 0


def test_client_requires_echoes_and_rechecks_verdict() -> None:
    target = _Target()
    result = AgentClient(target).investigate(
        _snapshot(),
        gate=AgentGate(mode="live", model_version="test", prompt_version="v1"),
        variant="base",
        account_context={},
    )
    assert (result.status, result.verdict.action, target.calls) == ("ok", "SKIP", 1)


def test_circuit_open_prevents_a_second_target_call() -> None:
    class FailingTarget(_Target):
        def investigate(self, request, timeout_seconds):
            self.calls += 1
            raise TimeoutError

    target = FailingTarget()
    client = AgentClient(target, breaker=CircuitBreaker(failure_threshold=1))
    gate = AgentGate(mode="live", model_version="test", prompt_version="v1")
    assert (
        client.investigate(_snapshot(), gate=gate, variant="base", account_context={}).status
        == "agent_timeout"
    )
    second = client.investigate(_snapshot(), gate=gate, variant="base", account_context={})
    assert (second.status, second.circuit_open, target.calls) == ("agent_circuit_open", True, 1)
