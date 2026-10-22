"""Small cache seam; storage owns durable implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .client import AgentCallResult


class ResultCache(Protocol):
    def get(self, key: str) -> AgentCallResult | None: ...

    def put(self, key: str, result: AgentCallResult) -> None: ...


class InMemoryResultCache:
    """Test/development cache; production callers provide durable storage-backed cache."""

    def __init__(self) -> None:
        self._results: dict[str, AgentCallResult] = {}

    def get(self, key: str) -> AgentCallResult | None:
        return self._results.get(key)

    def put(self, key: str, result: AgentCallResult) -> None:
        self._results[key] = result
