"""Small fail-closed adapter around an untrusted investigator target."""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Mapping
from typing import Protocol

from trader.config import GuardrailSettings
from trader.control import AgentGate
from trader.guardrail import GUARDRAIL_VERSION, ToolResultRecord, check_verdict
from trader.models import FrozenModel, Snapshot, Verdict

from .breaker import CircuitBreaker
from .cache import ResultCache


class AgentUnavailable(RuntimeError):
    """Raised only by a target; AgentClient converts it to a safe result."""


class AgentTarget(Protocol):
    name: str

    def investigate(
        self, request: Mapping[str, object], timeout_seconds: float
    ) -> Mapping[str, object]: ...


class AgentCallResult(FrozenModel):
    """Worker-owned result; every non-ok outcome has a fail-closed SKIP verdict."""

    verdict: Verdict
    status: str
    attempts: int
    latency_ms: float
    target: str
    model_id: str | None
    prompt_version: str | None
    prompt_hash: str | None = None
    guardrail_version: str
    guardrail_reason_code: str
    call_id: str
    cache_hit: bool = False
    circuit_open: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    trace_id: str | None = None
    trace_status: str = "disabled"


def _skip(
    code: str, *, target: str, started: float, gate: AgentGate, call_id: str
) -> AgentCallResult:
    return AgentCallResult(
        verdict=Verdict(action="SKIP", reasons=[code], cited_evidence={}),
        status=code,
        attempts=0,
        latency_ms=(time.monotonic() - started) * 1000,
        target=target,
        model_id=gate.model_version,
        prompt_version=gate.prompt_version,
        guardrail_version=GUARDRAIL_VERSION,
        guardrail_reason_code=code,
        call_id=call_id,
    )


class AgentClient:
    """Invoke one target and independently guardrail its returned verdict.

    The caller remains responsible for durable cache, cost accounting and cycle
    budget. This boundary never grants execution authority.
    """

    def __init__(
        self,
        target: AgentTarget,
        *,
        deadline_seconds: float = 10.0,
        breaker: CircuitBreaker | None = None,
        cache: ResultCache | None = None,
    ) -> None:
        self.target = target
        self.deadline_seconds = deadline_seconds
        self.breaker = breaker
        self.cache = cache

    def investigate(
        self,
        snapshot: Snapshot,
        *,
        gate: AgentGate,
        variant: str,
        account_context: Mapping[str, object],
    ) -> AgentCallResult:
        started, call_id = time.monotonic(), str(uuid.uuid4())
        trace_run_id = str(uuid.uuid4())
        if gate.killed:
            return _skip(
                "agent_killed", target=self.target.name, started=started, gate=gate, call_id=call_id
            )
        if gate.mode == "off":
            return _skip(
                "agent_off", target=self.target.name, started=started, gate=gate, call_id=call_id
            )
        if self.breaker is not None and not self.breaker.allow():
            return _skip(
                "agent_circuit_open",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            ).model_copy(update={"circuit_open": True})
        digest = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
        request_key = hashlib.sha256(
            f"{digest}:{variant}:{gate.model_version}:{gate.prompt_version}".encode()
        ).hexdigest()
        if self.cache is not None and (cached := self.cache.get(request_key)) is not None:
            return cached.model_copy(update={"cache_hit": True})
        request = {
            "schema_version": 2,
            "request_id": call_id,
            "candidate_key": snapshot.idempotency_key,
            "snapshot": snapshot.model_dump(mode="json"),
            "snapshot_digest": digest,
            "variant": variant,
            "model_id": gate.model_version,
            "prompt_version": gate.prompt_version,
            "account_context": dict(account_context),
            "trace_run_id": trace_run_id,
        }
        try:
            response = self.target.investigate(request, self.deadline_seconds)
        except AgentUnavailable:
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_unavailable",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        except TimeoutError:
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_timeout",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        except Exception:
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_transport_error",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        if not isinstance(response, Mapping):
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_response_invalid",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        if response.get("request_id") != call_id or response.get("snapshot_digest") != digest:
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_response_mismatch",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        if (
            response.get("model_id") != gate.model_version
            or response.get("prompt_version") != gate.prompt_version
        ):
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_response_mismatch",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        try:
            raw_tools = response.get("tool_results", [])
            if not isinstance(raw_tools, list):
                raise ValueError("tool results must be a list")
            tool_results = [ToolResultRecord.model_validate(item) for item in raw_tools]
        except Exception:
            if self.breaker is not None:
                self.breaker.record_failure()
            return _skip(
                "agent_response_invalid",
                target=self.target.name,
                started=started,
                gate=gate,
                call_id=call_id,
            )
        guard = check_verdict(
            response.get("verdict", {}), snapshot, tool_results, GuardrailSettings()
        )
        status = str(response.get("status", "ok")) if guard.accepted else "agent_guardrail_rejected"
        if self.breaker is not None:
            self.breaker.record_success()
        trace = response.get("trace")
        trace_id = None
        trace_status = "disabled"
        if isinstance(trace, Mapping):
            trace_status = str(trace.get("status", "disabled"))
            candidate_trace_id = trace.get("run_id")
            if trace.get("enabled") is True and candidate_trace_id == trace_run_id:
                try:
                    uuid.UUID(str(candidate_trace_id), version=4)
                    trace_id = str(candidate_trace_id)
                except (TypeError, ValueError):
                    trace_status = "invalid"
        result = AgentCallResult(
            verdict=guard.verdict,
            status=status,
            attempts=1,
            latency_ms=(time.monotonic() - started) * 1000,
            target=self.target.name,
            model_id=gate.model_version,
            prompt_version=gate.prompt_version,
            prompt_hash=response.get("prompt_hash")
            if isinstance(response.get("prompt_hash"), str)
            else None,
            guardrail_version=guard.guardrail_version,
            guardrail_reason_code=guard.reason_code,
            call_id=call_id,
            trace_id=trace_id,
            trace_status=trace_status,
        )
        if self.cache is not None and result.status not in {
            "agent_timeout",
            "agent_transport_error",
            "agent_circuit_open",
        }:
            self.cache.put(request_key, result)
        return result
