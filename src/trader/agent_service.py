"""Internal HTTP wrapper for the investigator; it has no trading-table access."""

from __future__ import annotations

import asyncio
import hmac
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request


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
        if model_allowlist and payload.get("model_id") not in model_allowlist:
            raise HTTPException(status_code=422, detail="model is not allowed")
        if semaphore.locked():
            raise HTTPException(status_code=429, detail="agent service busy")
        async with semaphore:
            try:
                return await asyncio.to_thread(runner, payload)
            except Exception:
                raise HTTPException(status_code=503, detail="investigator unavailable") from None

    return app
