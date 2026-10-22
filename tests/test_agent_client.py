"""Worker-side agent boundary tests; no model, network, or SDK calls."""

from datetime import UTC, datetime
from decimal import Decimal

from trader.agent_client import AgentClient, AgentVetoPolicy, CircuitBreaker, InMemoryResultCache
from trader.control import AgentGate
from trader.models import Candidate, Snapshot


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
        self.last_request = None

    def investigate(self, request, timeout_seconds):
        self.calls += 1
        self.last_request = request
        response = {
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
        if "trace_run_id" in request:
            response["trace"] = {
                "enabled": True,
                "run_id": request["trace_run_id"],
                "status": "completed",
            }
        return response


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


def test_completed_result_is_reused_for_the_same_request_key() -> None:
    target = _Target()
    client = AgentClient(target, cache=InMemoryResultCache())
    gate = AgentGate(mode="live", model_version="test", prompt_version="v1")
    first = client.investigate(_snapshot(), gate=gate, variant="base", account_context={})
    second = client.investigate(_snapshot(), gate=gate, variant="base", account_context={})
    assert (first.cache_hit, second.cache_hit, target.calls) == (False, True, 1)
    assert first.trace_id is not None and second.trace_id == first.trace_id


def test_jev_variant_enriches_only_its_own_request_snapshot() -> None:
    target = _Target()
    policy = AgentVetoPolicy(
        AgentClient(target),
        AgentGate(mode="live", model_version="test", prompt_version="v1"),
        "jev",
        lambda snapshot: snapshot.model_copy(
            update={"schema_version": 2, "jev_status": "coverage_not_ok"}
        ),
    )
    snapshot = _snapshot()
    policy.decide(
        snapshot,
        Candidate(
            symbol="BTCUSDT",
            bar_index=1,
            signal_time=snapshot.signal_time,
            reference_price=Decimal("100"),
            atr=Decimal("1"),
            breakout_level=Decimal("99"),
            idempotency_key="x",
        ),
    )
    assert target.calls == 1
    assert target.last_request["snapshot"]["jev_status"] == "coverage_not_ok"
