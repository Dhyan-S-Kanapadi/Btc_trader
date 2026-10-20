"""Public, paper-trading-only Binance kline ingestion."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol

import httpx

from trader.config import DataSettings
from trader.logging import configure_logging
from trader.models import Candle

MAX_KLINES = 1_000


class BinanceError(RuntimeError):
    """A public market-data request or payload failed."""


class BinanceBanError(BinanceError):
    """Binance returned 418; stop requests until the operator intervenes."""


class CandleStore(Protocol):
    """The narrow candle operations required by the ingestor."""

    def upsert_candles(self, candles: list[Candle], interval: str) -> int: ...

    def candle_times(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[datetime]: ...

    def latest_candle_time(self, symbol: str, interval: str) -> datetime | None: ...


@dataclass(frozen=True)
class Freshness:
    """Latest candle freshness without importing risk policy."""

    latest_open_time: datetime | None
    stale: bool


def interval_delta(interval: str) -> timedelta:
    """Return the fixed duration for supported Binance kline intervals."""

    values = {
        "1m": timedelta(minutes=1),
        "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1),
    }
    try:
        return values[interval]
    except KeyError as error:
        raise ValueError(f"unsupported interval: {interval}") from error


def find_gaps(candle_times: list[datetime], interval: str) -> list[tuple[datetime, datetime]]:
    """Return missing inclusive open-time ranges between ordered candle timestamps."""

    step = interval_delta(interval)
    result: list[tuple[datetime, datetime]] = []
    for earlier, later in zip(candle_times, candle_times[1:], strict=False):
        expected = earlier + step
        if later > expected:
            result.append((expected, later - step))
    return result


def _utc_millis(value: datetime) -> int:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return int(value.astimezone(UTC).timestamp() * 1_000)


def _parse_row(row: object, symbol: str) -> tuple[Candle, datetime]:
    """Parse Binance's documented 12-item kline response into validated Decimal data."""

    if not isinstance(row, list) or len(row) != 12:
        raise BinanceError("malformed kline: expected a 12-item array")
    try:
        open_time = datetime.fromtimestamp(int(row[0]) / 1_000, tz=UTC)
        close_time = datetime.fromtimestamp(int(row[6]) / 1_000, tz=UTC)
        candle = Candle(
            symbol=symbol,
            open_time=open_time,
            open=Decimal(str(row[1])),
            high=Decimal(str(row[2])),
            low=Decimal(str(row[3])),
            close=Decimal(str(row[4])),
            volume=Decimal(str(row[5])),
        )
    except (InvalidOperation, TypeError, ValueError, OverflowError) as error:
        raise BinanceError("malformed kline values") from error
    return candle, close_time


class BinanceIngestor:
    """Fetch public spot klines, retain only closed bars, and persist them idempotently."""

    def __init__(
        self,
        settings: DataSettings,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.base_url, timeout=settings.timeout_seconds
        )
        self._owns_client = client is None
        self._sleep = sleep
        self._random_value = random_value
        configure_logging()
        self._logger = logging.getLogger(__name__)

    def close(self) -> None:
        """Close the owned HTTP client."""

        if self._owns_client:
            self.client.close()

    def _get(self, params: dict[str, int | str]) -> list[object]:
        for attempt in range(self.settings.max_retries + 1):
            delay: float | None = None
            try:
                response = self.client.get("/api/v3/klines", params=params)
            except httpx.RequestError as error:
                failure: Exception = error
            else:
                if response.status_code == 418:
                    raise BinanceBanError(
                        "Binance returned 418; public-data requests are temporarily banned"
                    )
                if response.status_code == 429:
                    failure = BinanceError("Binance returned 429 rate limit")
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after is not None else None
                elif 500 <= response.status_code < 600:
                    failure = BinanceError(f"Binance server error: {response.status_code}")
                    delay = None
                else:
                    try:
                        response.raise_for_status()
                        payload = response.json()
                    except (httpx.HTTPStatusError, ValueError) as error:
                        raise BinanceError("Binance returned an invalid kline response") from error
                    if not isinstance(payload, list):
                        raise BinanceError("Binance kline response is not an array")
                    return payload
            if attempt == self.settings.max_retries:
                raise BinanceError("Binance retries exhausted") from failure
            if delay is None:
                delay = min(
                    self.settings.max_retry_seconds,
                    (2**attempt) + self._random_value(),
                )
            self._sleep(min(delay, self.settings.max_retry_seconds))
        raise AssertionError("unreachable")

    def fetch(
        self, symbol: str, interval: str, start: datetime, end: datetime, now: datetime
    ) -> list[Candle]:
        """Fetch [start, end] chronologically and return only candles closed at passed `now`."""

        interval_delta(interval)
        cursor = _utc_millis(start)
        end_millis = _utc_millis(end)
        closed: list[Candle] = []
        while cursor <= end_millis:
            rows = self._get(
                {
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_millis,
                    "limit": MAX_KLINES,
                }
            )
            if not rows:
                break
            parsed = [_parse_row(row, symbol) for row in rows]
            if parsed[-1][0].open_time.timestamp() * 1_000 < cursor:
                raise BinanceError("Binance response did not advance pagination")
            closed.extend(candle for candle, close_time in parsed if close_time <= now)
            cursor = _utc_millis(parsed[-1][0].open_time) + int(
                interval_delta(interval).total_seconds() * 1_000
            )
            if len(rows) < MAX_KLINES:
                break
        self._logger.info(
            "klines fetched", extra={"symbol": symbol, "interval": interval, "count": len(closed)}
        )
        return closed

    def backfill(
        self,
        storage: CandleStore,
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime,
        now: datetime,
    ) -> int:
        """Fetch and upsert a requested range, then fill gaps found in persisted timestamps."""

        candles = self.fetch(symbol, interval, start, end, now)
        written = storage.upsert_candles(candles, interval)
        gaps = find_gaps(storage.candle_times(symbol, interval, start, end), interval)
        for gap_start, gap_end in gaps:
            written += storage.upsert_candles(
                self.fetch(symbol, interval, gap_start, gap_end, now), interval
            )
        remaining = find_gaps(storage.candle_times(symbol, interval, start, end), interval)
        self._logger.info(
            "klines backfill complete",
            extra={
                "symbol": symbol,
                "interval": interval,
                "written": written,
                "gaps_found": len(gaps),
                "gaps_remaining": len(remaining),
            },
        )
        return written


def latest_freshness(storage: CandleStore, symbol: str, interval: str, now: datetime) -> Freshness:
    """Mark data stale only when its newest open time is older than two intervals."""

    latest = storage.latest_candle_time(symbol, interval)
    return Freshness(latest, latest is None or now - latest > 2 * interval_delta(interval))
