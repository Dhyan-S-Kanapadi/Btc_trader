"""Concrete agent targets; optional SDKs are imported only inside invocation methods."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping

import httpx

from .client import AgentUnavailable


class LocalTarget:
    """Development/test target. A timed-out Python thread cannot be force-killed."""

    name = "local"

    def __init__(
        self, run: Callable[[Mapping[str, object]], Mapping[str, object]] | None = None
    ) -> None:
        self._run = run

    def investigate(
        self, request: Mapping[str, object], timeout_seconds: float
    ) -> Mapping[str, object]:
        if self._run is not None:
            return self._run(request)
        try:
            # Lazy by design: importing the worker must never import investigator dependencies.
            from trader import agent
        except ImportError as error:
            raise AgentUnavailable("local investigator is unavailable") from error
        if not callable(getattr(agent, "investigate", None)):
            raise AgentUnavailable("local investigator is unavailable")
        raise AgentUnavailable(
            "LocalTarget needs an explicit development adapter for investigator dependencies"
        )


class HttpTarget:
    """Internal authenticated HTTP target with no model-client dependency."""

    name = "http"

    def __init__(self, url: str, token: str | None, connect_timeout_seconds: float = 2) -> None:
        self.url, self.token, self.connect_timeout_seconds = (
            url.rstrip("/"),
            token,
            connect_timeout_seconds,
        )

    def investigate(
        self, request: Mapping[str, object], timeout_seconds: float
    ) -> Mapping[str, object]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = httpx.Timeout(
            timeout_seconds, connect=min(timeout_seconds, self.connect_timeout_seconds)
        )
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    f"{self.url}/v1/investigate", json=dict(request), headers=headers
                )
        except httpx.TimeoutException as error:
            raise TimeoutError from error
        except httpx.HTTPError as error:
            raise AgentUnavailable("agent transport failed") from error
        if response.status_code >= 500:
            raise AgentUnavailable("agent service unavailable")
        if response.status_code >= 400:
            raise ValueError(f"agent service returned {response.status_code}")
        try:
            parsed = response.json()
        except json.JSONDecodeError as error:
            raise ValueError("agent service returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise ValueError("agent service returned non-object JSON")
        return parsed


class AgentCoreTarget:
    """Optional AgentCore Runtime target; boto3 is never imported at module load."""

    name = "agentcore"

    def __init__(self, runtime_arn: str, client: object | None = None) -> None:
        self.runtime_arn, self._client = runtime_arn, client

    def investigate(
        self, request: Mapping[str, object], timeout_seconds: float
    ) -> Mapping[str, object]:
        try:
            client = self._client
            if client is None:
                import boto3
                from botocore.config import Config

                client = boto3.client(
                    "bedrock-agentcore",
                    config=Config(
                        connect_timeout=min(timeout_seconds, 2),
                        read_timeout=timeout_seconds,
                        retries={"max_attempts": 0},
                    ),
                )
            response = client.invoke_agent_runtime(
                agentRuntimeArn=self.runtime_arn,
                runtimeSessionId=str(uuid.uuid4()),
                payload=json.dumps(dict(request)).encode(),
            )
            stream = response["response"]
            raw = stream.read() if hasattr(stream, "read") else b"".join(stream)
            parsed = json.loads(raw)
        except ImportError as error:
            raise AgentUnavailable("AgentCore optional dependency is unavailable") from error
        except Exception as error:
            raise AgentUnavailable("AgentCore invocation failed") from error
        if not isinstance(parsed, dict):
            raise ValueError("AgentCore returned non-object JSON")
        return parsed
