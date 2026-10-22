"""Storage-free contracts for time-gated episodic-memory evidence."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol


class MemorySource(Protocol):
    def search(
        self,
        *,
        as_of: datetime,
        candidate_key: str,
        namespace: str,
        embedding: list[float],
        embedding_version: str,
        k: int,
        max_distance: float,
    ) -> Sequence[dict[str, object]]: ...
