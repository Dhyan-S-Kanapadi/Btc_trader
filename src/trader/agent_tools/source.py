"""Read-only candle sources; each source rejects a server-side future-data leak."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

import httpx

from trader.data.binance import interval_delta
from trader.models import Candle


class ToolError(RuntimeError):
    """Typed operational or invariant failure for the future agent layer to map to SKIP."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CandleSource(Protocol):
    def candles(
        self, as_of: datetime, limit: int, symbol: str, interval: str
    ) -> Sequence[Candle]: ...


def enforce_as_of(candles: Sequence[Candle], as_of: datetime, interval: str) -> None:
    """Raise instead of dropping future candles: a source violation must be visible."""

    if any(candle.open_time + interval_delta(interval) > as_of for candle in candles):
        raise ToolError("asof_violation")


class InMemoryCandleSource:
    def __init__(self, candles: Sequence[Candle]) -> None:
        self._candles = tuple(candles)

    def candles(self, as_of: datetime, limit: int, symbol: str, interval: str) -> Sequence[Candle]:
        values = [candle for candle in self._candles if candle.symbol == symbol]
        known = [
            candle for candle in values if candle.open_time + interval_delta(interval) <= as_of
        ]
        return known[-limit:]


class HttpCandleSource:
    def __init__(self, base_url: str, timeout_seconds: float, max_retries: int = 0) -> None:
        self.base_url, self.timeout_seconds, self.max_retries = (
            base_url.rstrip("/"),
            timeout_seconds,
            max_retries,
        )

    def candles(self, as_of: datetime, limit: int, symbol: str, interval: str) -> Sequence[Candle]:
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.get(
                    f"{self.base_url}/v1/candles",
                    params={
                        "as_of": as_of.isoformat(),
                        "limit": limit,
                        "symbol": symbol,
                        "interval": interval,
                    },
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                values = [
                    Candle.model_validate({key: item[key] for key in Candle.model_fields})
                    for item in payload["items"]
                ]
                break
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                if attempt == self.max_retries:
                    raise ToolError("transport_error") from error
        enforce_as_of(values, as_of, interval)
        return values
