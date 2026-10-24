"""AgentCore Runtime edge: read-only evidence in, guardrailed verdict out."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from trader.agent.groq import GroqModel
from trader.agent_service import make_investigator_runner
from trader.agent_tools import HttpCandleSource
from trader.config import Settings
from trader.memory.postgres import PostgresMemorySource


def _groq_key(settings: Settings) -> str:
    if settings.groq_token:
        return settings.groq_token
    secret_arn = os.environ.get("GROQ_SECRET_ARN")
    if not secret_arn:
        raise ValueError("GROQ_API_KEY or GROQ_SECRET_ARN is required")
    try:
        import boto3

        value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
        key = value.get("SecretString")
    except Exception as error:
        raise ValueError("Groq secret is unavailable") from error
    if not isinstance(key, str) or not key:
        raise ValueError("Groq secret is invalid")
    return key


def create_agentcore_app(settings: Settings | None = None, *, model_factory=GroqModel) -> FastAPI:
    """Create the AgentCore HTTP contract without importing worker or trading code."""

    settings = settings or Settings()
    source = HttpCandleSource(
        settings.agent_tools.api_base_url,
        settings.agent_tools.timeout_seconds,
        settings.agent_tools.max_retries,
    )
    memory = (
        PostgresMemorySource(settings.agent_memory.database_url)
        if settings.agent_memory.enabled and settings.agent_memory.database_url
        else None
    )
    key = _groq_key(settings)

    def runner(payload: dict[str, Any]) -> dict[str, Any]:
        model_id = payload.get("model_id") or settings.agent.groq_model
        if not isinstance(model_id, str) or not model_id:
            raise ValueError("model_id is required")
        model = model_factory(key, model_id, timeout_seconds=settings.agent.groq_timeout_seconds)
        return make_investigator_runner(settings, source, model, memory)(payload)

    app = FastAPI(docs_url=None, redoc_url=None)

    @app.get("/ping")
    def ping() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/invocations")
    async def invoke(request: Request) -> dict[str, Any]:
        if (
            request.headers.get("content-length")
            and int(request.headers["content-length"]) > 16_384
        ):
            raise HTTPException(status_code=413, detail="request too large")
        try:
            body = await request.body()
            if len(body) > 16_384:
                raise HTTPException(status_code=413, detail="request too large")
            payload = await request.json()
        except Exception as error:
            raise HTTPException(status_code=422, detail="invalid JSON") from error
        if not isinstance(payload, dict) or payload.get("schema_version", 1) != 2:
            raise HTTPException(status_code=422, detail="unsupported agent request")
        try:
            result = runner(payload)
        except Exception:
            raise HTTPException(status_code=503, detail="investigator unavailable") from None
        result.setdefault("schema_version", 2)
        result.setdefault("trace", {"enabled": False, "run_id": None, "status": "disabled"})
        return result

    return app
