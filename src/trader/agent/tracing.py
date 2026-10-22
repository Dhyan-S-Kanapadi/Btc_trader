"""Optional, fail-open LangSmith observation for the investigator only."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from typing import Any, Protocol
from uuid import UUID

from trader.config import AgentTracingSettings

REDACTED = "[REDACTED]"
TRUNCATED = "[TRUNCATED]"
_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,]+")
_AUTH = re.compile(r"(?i)(authorization\s*[:=]\s*)[^\s,]+")
_KEY = re.compile(r"(?i)\b(?:sk-ant-|lsv2_pt_|AKIA)[A-Za-z0-9_\-]{8,}\b")


class TraceHandle(Protocol):
    def finish(self, output: Mapping[str, object], metadata: Mapping[str, object]) -> None: ...


class TraceFactory(Protocol):
    def start(
        self,
        *,
        run_id: UUID,
        inputs: Mapping[str, object],
        tags: list[str],
        metadata: Mapping[str, object],
    ) -> TraceHandle: ...

    def flush(self, timeout: float) -> None: ...


def _secrets() -> tuple[str, ...]:
    names = (
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AGENT_SERVICE_TOKEN",
        "DATABASE_URL",
        "DATABASE_URL_READONLY",
    )
    return tuple(value for name in names if (value := os.environ.get(name)))


def scrub(value: Any, *, cap: int, secrets: tuple[str, ...] | None = None) -> Any:
    """Deterministically remove credentials and bound payloads; never leak on failure."""

    try:
        known = secrets if secrets is not None else _secrets()
        if isinstance(value, BaseException):
            value = f"{type(value).__name__}: {value}"
        if isinstance(value, str):
            for secret in known:
                value = value.replace(secret, REDACTED)
            value = _BEARER.sub(r"\1" + REDACTED, value)
            value = _AUTH.sub(r"\1" + REDACTED, value)
            value = _KEY.sub(REDACTED, value)
            return value if len(value) <= cap else value[:cap] + TRUNCATED
        if isinstance(value, bytes):
            return scrub(value.decode("utf-8", "replace"), cap=cap, secrets=known)
        if isinstance(value, Mapping):
            return {str(key): scrub(item, cap=cap, secrets=known) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [scrub(item, cap=cap, secrets=known) for item in value]
        return value
    except Exception:
        return "[PAYLOAD_DROPPED]"


class _RunTreeHandle:
    def __init__(self, run: Any, settings: AgentTracingSettings) -> None:
        self._run, self._settings = run, settings

    def finish(self, output: Mapping[str, object], metadata: Mapping[str, object]) -> None:
        self._run.end(
            outputs=scrub(dict(output), cap=self._settings.payload_cap),
            extra={"metadata": scrub(dict(metadata), cap=self._settings.payload_cap)},
        )
        self._run.patch()


class LangSmithTraceFactory:
    """SDK-backed, background-batched trace factory; constructed only when explicitly enabled."""

    def __init__(self, settings: AgentTracingSettings) -> None:
        from langsmith import Client
        from urllib3.util import Retry

        self._settings = settings
        api_key = os.environ.get("LANGSMITH_API_KEY")
        if not api_key:
            raise ValueError("LANGSMITH_API_KEY is required when tracing is enabled")
        self._client = Client(
            api_url=settings.endpoint,
            api_key=api_key,
            timeout_ms=int(settings.timeout_seconds * 1000),
            retry_config=Retry(total=settings.max_retries, backoff_factor=0),
            auto_batch_tracing=True,
            hide_inputs=lambda payload: scrub(payload, cap=settings.payload_cap),
            hide_outputs=lambda payload: scrub(payload, cap=settings.payload_cap),
            hide_metadata=lambda payload: scrub(payload, cap=settings.payload_cap),
            tracing_error_callback=_warn_unavailable,
            # Avoid the SDK's synchronous /info probe on the decision path.
            info={},
        )

    def start(
        self,
        *,
        run_id: UUID,
        inputs: Mapping[str, object],
        tags: list[str],
        metadata: Mapping[str, object],
    ) -> TraceHandle:
        from langsmith.run_trees import RunTree

        run = RunTree(
            id=run_id,
            name="btc-paper-investigate",
            run_type="chain",
            inputs=scrub(dict(inputs), cap=self._settings.payload_cap),
            project_name=self._settings.project_name,
            tags=tags,
            extra={"metadata": scrub(dict(metadata), cap=self._settings.payload_cap)},
            client=self._client,
        )
        run.post()
        return _RunTreeHandle(run, self._settings)

    def flush(self, timeout: float) -> None:
        self._client.flush(timeout=timeout)


_warning_lock = threading.Lock()
_last_warning = 0.0


def _warn_unavailable(_error: Exception) -> None:
    global _last_warning
    with _warning_lock:
        now = time.monotonic()
        if now - _last_warning < 60:
            return
        _last_warning = now
    logging.getLogger("trader.agent.tracing").warning(
        "tracing unavailable", extra={"warn": "tracing_unavailable"}
    )


class InvestigationTrace:
    """A no-op by default wrapper that must never affect investigator output."""

    def __init__(
        self,
        settings: AgentTracingSettings,
        *,
        run_id: UUID | None,
        inputs: Mapping[str, object],
        tags: list[str],
        metadata: Mapping[str, object],
        factory: TraceFactory | None = None,
    ) -> None:
        self.run_id: str | None = None
        self.status = "disabled"
        self._handle: TraceHandle | None = None
        if not settings.enabled or run_id is None:
            return
        try:
            self._handle = (factory or LangSmithTraceFactory(settings)).start(
                run_id=run_id, inputs=inputs, tags=tags, metadata=metadata
            )
            self.run_id, self.status = str(run_id), "started"
        except Exception as error:
            _warn_unavailable(error)
            self.status = "unavailable"

    def finish(self, output: Mapping[str, object], metadata: Mapping[str, object]) -> None:
        if self._handle is None:
            return
        try:
            self._handle.finish(output, metadata)
            self.status = "completed"
        except Exception as error:
            self.run_id, self.status = None, "unavailable"
            _warn_unavailable(error)
