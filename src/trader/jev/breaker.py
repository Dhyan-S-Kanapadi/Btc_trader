"""Small in-process breaker for the isolated Jev boundary."""

from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    failure_threshold: int
    cooldown_seconds: float
    failures: int = 0
    opened_at: float | None = None

    def allow(self, now: float) -> bool:
        return self.opened_at is None or now - self.opened_at >= self.cooldown_seconds

    def record_success(self) -> bool:
        was_open = self.opened_at is not None
        self.failures, self.opened_at = 0, None
        return was_open

    def record_failure(self, now: float) -> bool:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = now
            return True
        return False
