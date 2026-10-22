"""In-memory fail-closed circuit breaker for agent target failures."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 300
    now: Callable[[], float] = __import__("time").monotonic
    failures: int = 0
    opened_at: float | None = None
    probing: bool = False

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self.now() - self.opened_at < self.cooldown_seconds:
            return False
        if self.probing:
            return False
        self.probing = True
        return True

    def record_success(self) -> bool:
        was_open = self.opened_at is not None
        self.failures, self.opened_at, self.probing = 0, None, False
        return was_open

    def record_failure(self) -> bool:
        self.probing = False
        self.failures += 1
        if self.opened_at is None and self.failures >= self.failure_threshold:
            self.opened_at = self.now()
            return True
        if self.opened_at is not None:
            self.opened_at = self.now()
        return False
