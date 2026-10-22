"""Pinned Vercel AI Gateway client; response interpretation is deliberately separate."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from trader.config import JevSettings


class JevError(RuntimeError):
    """Stable, non-secret error code at the network boundary."""


@dataclass(frozen=True)
class JevRawResult:
    payload: bytes
    http_status: int
    attempts: int
    latency_ms: int


class JevClient:
    """Send one bounded `POST /v1/evaluate`; never logs request or response content."""

    def __init__(
        self,
        settings: JevSettings,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        parsed = urlparse(settings.base_url)
        if parsed.scheme != "https" or parsed.hostname != "ai-gateway.vercel.sh":
            raise ValueError("Jev base URL must be the pinned HTTPS Vercel AI Gateway host")
        self.settings, self.client = settings, client or httpx.Client(follow_redirects=False)
        self._owns_client, self._monotonic, self._sleep, self._random = (
            client is None,
            monotonic,
            sleep,
            random_value,
        )

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def ask(self, state: str, questions: Mapping[str, object]) -> JevRawResult:
        if not self.settings.gateway_token:
            raise JevError("disabled")
        started = self._monotonic()
        body = {"model": self.settings.model, "state": state, "questions": dict(questions)}
        headers = {
            "Authorization": f"Bearer {self.settings.gateway_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        for attempt in range(1, self.settings.max_retries + 2):
            remaining = self.settings.total_deadline_seconds - (self._monotonic() - started)
            if remaining <= 0:
                raise JevError("timeout")
            try:
                with self.client.stream(
                    "POST",
                    f"{self.settings.base_url}/v1/evaluate",
                    json=body,
                    headers=headers,
                    timeout=httpx.Timeout(
                        remaining, connect=min(remaining, self.settings.connect_timeout_seconds)
                    ),
                ) as response:
                    if response.is_redirect:
                        raise JevError("redirect_refused")
                    if response.status_code == 429:
                        delay = _retry_after(response.headers.get("retry-after"))
                        if delay is not None and self._can_retry(started, delay, attempt):
                            continue
                        raise JevError("rate_limited")
                    if response.status_code in {502, 503, 504}:
                        if self._retry(started, attempt):
                            continue
                        raise JevError("server_error")
                    if response.status_code >= 400:
                        raise JevError(f"http_{response.status_code}")
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise JevError("wrong_content_type")
                    payload = _bounded_body(
                        response,
                        self.settings.max_response_bytes,
                        self._monotonic,
                        started,
                        self.settings.total_deadline_seconds,
                    )
                    return JevRawResult(
                        payload,
                        response.status_code,
                        attempt,
                        int((self._monotonic() - started) * 1000),
                    )
            except httpx.TimeoutException as error:
                if self._retry(started, attempt):
                    continue
                raise JevError("timeout") from error
            except httpx.RequestError as error:
                if self._retry(started, attempt):
                    continue
                raise JevError("transport_error") from error
        raise AssertionError("unreachable")

    def _retry(self, started: float, attempt: int) -> bool:
        return self._can_retry(
            started,
            min(self.settings.max_retry_seconds, 2 ** (attempt - 1) + self._random()),
            attempt,
        )

    def _can_retry(self, started: float, delay: float, attempt: int) -> bool:
        if attempt > self.settings.max_retries:
            return False
        if self._monotonic() + delay - started > self.settings.total_deadline_seconds:
            return False
        self._sleep(delay)
        return True


def _bounded_body(
    response, cap: int, monotonic: Callable[[], float], started: float, deadline: float
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        if monotonic() - started > deadline:
            raise JevError("timeout")
        size += len(chunk)
        if size > cap:
            raise JevError("response_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        try:
            return max(
                0.0,
                (parsedate_to_datetime(value).astimezone(UTC) - datetime.now(UTC)).total_seconds(),
            )
        except (TypeError, ValueError):
            return None
