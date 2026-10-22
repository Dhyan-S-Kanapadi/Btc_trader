"""Internal HTTP wrapper for the investigator; it has no trading-table access."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request

from trader.agent import investigate
from trader.agent.investigator import Model
from trader.agent_tools import CandleSource, MemorySource
from trader.config import Settings
from trader.models import Snapshot


def make_investigator_runner(
    settings: Settings,
    tool_source: CandleSource,
    model: Model,
    memory_source: MemorySource | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Bind D's reader-only memory source inside the agent service, never the worker."""

    def runner(payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = Snapshot.model_validate(payload["snapshot"])
        variant = str(payload.get("variant", "base"))
        if variant not in {"base", "jev", "memory"}:
            raise ValueError("unknown variant")
        trace_run_id = UUID(str(payload["trace_run_id"])) if payload.get("trace_run_id") else None
        result = investigate(
            snapshot,
            config=settings.agent.model_copy(
                update={
                    "model_id": payload.get("model_id"),
                    "prompt_version": payload.get("prompt_version", settings.agent.prompt_version),
                }
            ),
            tool_source=tool_source,
            model=model,
            trace_run_id=trace_run_id,
            memory_source=(
                memory_source if variant == "memory" and settings.agent_memory.enabled else None
            ),
            variant=variant,
            runtime_settings=settings,
        )
        return {
            "request_id": payload["request_id"],
            "snapshot_digest": payload["snapshot_digest"],
            "model_id": payload.get("model_id"),
            "prompt_version": payload.get("prompt_version", settings.agent.prompt_version),
            "prompt_hash": result.prompt_hash,
            "status": result.status,
            "verdict": result.verdict.model_dump(mode="json"),
            "tool_results": [item.model_dump(mode="json") for item in result.tool_results],
            "trace": {
                "enabled": result.trace_enabled,
                "run_id": str(result.trace_id) if result.trace_id else None,
                "status": result.trace_status,
            },
        }

    return runner


def create_agent_service(
    *,
    token: str | None,
    runner: Callable[[dict[str, Any]], dict[str, Any]],
    model_allowlist: set[str] | None = None,
    max_body_bytes: int = 16_384,
    max_concurrency: int = 2,
) -> FastAPI:
    """Create a bounded internal service. Missing token is a startup error."""

    if not token:
        raise ValueError("AGENT_SERVICE_TOKEN is required")
    app = FastAPI(title="paper-trader-agent", docs_url=None, redoc_url=None)
    semaphore = asyncio.Semaphore(max_concurrency)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/investigate")
    async def investigate(request: Request) -> dict[str, Any]:
        authorization = request.headers.get("authorization", "")
        supplied = authorization.removeprefix("Bearer ")
        if not authorization.startswith("Bearer ") or not hmac.compare_digest(supplied, token):
            raise HTTPException(status_code=401, detail="unauthorized")
        length = request.headers.get("content-length")
        if length is not None and int(length) > max_body_bytes:
            raise HTTPException(status_code=413, detail="request too large")
        body = await request.body()
        if len(body) > max_body_bytes:
            raise HTTPException(status_code=413, detail="request too large")
        try:
            payload = await request.json()
        except Exception as error:
            raise HTTPException(status_code=422, detail="invalid JSON") from error
        if not isinstance(payload, dict):
            raise HTTPException(status_code=422, detail="request must be an object")
        if payload.get("schema_version", 1) != 2:
            raise HTTPException(status_code=422, detail="unsupported agent request schema_version")
        trace_run_id = payload.get("trace_run_id")
        if trace_run_id is not None:
            try:
                UUID(str(trace_run_id), version=4)
            except (TypeError, ValueError):
                payload.pop("trace_run_id", None)
        if model_allowlist and payload.get("model_id") not in model_allowlist:
            raise HTTPException(status_code=422, detail="model is not allowed")
        if semaphore.locked():
            raise HTTPException(status_code=429, detail="agent service busy")
        async with semaphore:
            try:
                response = await asyncio.to_thread(runner, payload)
                if not isinstance(response, dict):
                    raise ValueError("investigator response must be an object")
                response.setdefault("schema_version", 2)
                response.setdefault(
                    "trace", {"enabled": False, "run_id": None, "status": "disabled"}
                )
                return response
            except Exception:
                raise HTTPException(status_code=503, detail="investigator unavailable") from None

    return app
