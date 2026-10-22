"""Small deterministic investigator loop; model/graph adapters stay at the optional edge."""

from __future__ import annotations

import hashlib
import time
from typing import Protocol
from uuid import UUID

from pydantic import Field

from trader.agent.tracing import InvestigationTrace, TraceFactory
from trader.agent_tools import CandleSource, ToolError, ToolRegistry
from trader.config import AgentSettings, AgentTracingSettings, Settings
from trader.guardrail import GuardrailResult, ToolResultRecord, check_verdict
from trader.models import FrozenModel, Snapshot, Verdict


class Model(Protocol):
    def invoke(
        self, prompt: str, snapshot: Snapshot, tools: dict[str, dict[str, object]]
    ) -> object: ...


class InvestigationResult(FrozenModel):
    verdict: Verdict
    status: str
    guardrail: GuardrailResult
    model_id: str | None
    prompt_version: str
    prompt_hash: str
    step_count: int
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float
    tool_calls: list[dict[str, object]] = Field(default_factory=list)
    tool_results: list[ToolResultRecord] = Field(default_factory=list)
    thread_id: str
    trace_enabled: bool = False
    trace_id: str | None = None
    trace_status: str = "disabled"


def _prompt(version: str) -> tuple[str, str] | None:
    from importlib.resources import files

    path = files("trader.agent.prompts").joinpath(f"{version}.md")
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    return text, hashlib.sha256(text.encode()).hexdigest()


def investigate(
    snapshot: Snapshot,
    *,
    config: AgentSettings,
    tool_source: CandleSource,
    model: Model | None = None,
    checkpointer: object | None = None,
    trace_run_id: UUID | None = None,
    trace_source: str = "cli",
    trace_factory: TraceFactory | None = None,
    tracing_config: AgentTracingSettings | None = None,
) -> InvestigationResult:
    """Run the bounded plumbing; any bad model/tool/checkpoint outcome becomes guardrailed SKIP."""
    started = time.monotonic()
    thread_id = hashlib.sha256(snapshot.model_dump_json().encode()).hexdigest()
    prompt = _prompt(config.prompt_version)
    guard_config = Settings().guardrail
    tracing = InvestigationTrace(
        tracing_config or Settings().agent_tracing,
        run_id=trace_run_id,
        inputs={"snapshot": snapshot.model_dump(mode="json")},
        tags=[
            f"candidate:{snapshot.idempotency_key}",
            f"model:{config.model_id or 'unset'}",
            f"prompt:{config.prompt_version}",
            f"source:{trace_source}",
        ],
        metadata={"source": trace_source, "synthetic": snapshot.symbol.startswith("SYNTH-")},
        factory=trace_factory,
    )

    def result(status: str, raw: object, steps: int = 0) -> InvestigationResult:
        guard = check_verdict(raw, snapshot, [], guard_config)
        output = InvestigationResult(
            verdict=guard.verdict,
            status=status,
            guardrail=guard,
            model_id=config.model_id,
            prompt_version=config.prompt_version,
            prompt_hash=prompt[1] if prompt else "",
            step_count=steps,
            latency_ms=(time.monotonic() - started) * 1000,
            thread_id=thread_id,
            trace_enabled=tracing.run_id is not None,
            trace_id=tracing.run_id,
            trace_status=tracing.status,
        )
        tracing.finish(output.model_dump(mode="json"), {"status": status, "step_count": steps})
        return output.model_copy(
            update={"trace_id": tracing.run_id, "trace_status": tracing.status}
        )

    if prompt is None:
        return result("prompt_not_found", {})
    if model is None:
        return result("config_error", {})
    if checkpointer is not None:
        try:
            getattr(checkpointer, "put", lambda *_: None)(
                thread_id, snapshot.model_dump(mode="json")
            )
        except Exception:
            return result("checkpointer_error", {})
    registry = ToolRegistry(snapshot.signal_time, tool_source, Settings())
    try:
        for step in range(1, config.step_cap + 1):
            if time.monotonic() - started > config.wall_clock_seconds:
                return result("deadline", {}, step - 1)
            response = model.invoke(prompt[0], snapshot, registry.schemas())
            if isinstance(response, dict) and "tool" in response:
                registry.call(str(response["tool"]), dict(response.get("args", {})))
                continue
            guard = check_verdict(
                response if isinstance(response, (str, bytes, dict)) else {},
                snapshot,
                [ToolResultRecord.model_validate(record) for record in registry.records],
                guard_config,
            )
            output = InvestigationResult(
                verdict=guard.verdict,
                status="ok" if guard.accepted else "guardrail_rejected",
                guardrail=guard,
                model_id=config.model_id,
                prompt_version=config.prompt_version,
                prompt_hash=prompt[1],
                step_count=step,
                latency_ms=(time.monotonic() - started) * 1000,
                tool_results=[
                    ToolResultRecord.model_validate(record) for record in registry.records
                ],
                thread_id=thread_id,
                trace_enabled=tracing.run_id is not None,
                trace_id=tracing.run_id,
                trace_status=tracing.status,
            )
            tracing.finish(
                output.model_dump(mode="json"),
                {
                    "status": output.status,
                    "guardrail_reason_code": guard.reason_code,
                    "step_count": step,
                    "tool_call_count": len(registry.records),
                },
            )
            return output.model_copy(
                update={"trace_id": tracing.run_id, "trace_status": tracing.status}
            )
        return result("step_cap", {}, config.step_cap)
    except ToolError:
        return result("tool_error", {}, 0)
    except Exception:
        return result("model_error", {}, 0)
