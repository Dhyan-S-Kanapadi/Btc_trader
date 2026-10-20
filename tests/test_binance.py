"""Deterministic tests for public Binance candle ingestion."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from trader.config import DataSettings, Settings
from trader.data.binance import (
    BinanceBanError,
    BinanceError,
    BinanceIngestor,
    find_gaps,
    latest_freshness,
)
from trader.models import Candle


def _row(open_ms: int, close_ms: int | None = None) -> list[object]:
    return [
        open_ms,
        "10",
        "12",
        "9",
        "11",
        "2",
        close_ms or open_ms + 3_599_999,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[datetime, Candle] = {}

    def upsert_candles(self, candles: list[Candle], interval: str) -> int:
        self.rows.update({candle.open_time: candle for candle in candles})
        return len(candles)

    def candle_times(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> list[datetime]:
        return sorted(time for time in self.rows if start <= time <= end)

    def latest_candle_time(self, symbol: str, interval: str) -> datetime | None:
        return max(self.rows, default=None)


def _client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://test.invalid", transport=httpx.MockTransport(handler))


def test_fetch_pages_forward_and_keeps_only_closed_rows() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(int(request.url.params["startTime"]))
        if len(seen) == 1:
            return httpx.Response(200, json=[_row(1_767_225_600_000), _row(1_767_229_200_000)])
        return httpx.Response(200, json=[])

    ingestor = BinanceIngestor(DataSettings(), _client(handler))
    assert (
        len(
            ingestor.fetch(
                "BTCUSDT", "1h", start, start + timedelta(hours=3), start + timedelta(hours=2)
            )
        )
        == 2
    )
    assert seen == [1_767_225_600_000]


def test_fetch_paginates_after_documented_page_limit() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    first_page = [_row(1_767_225_600_000 + index * 3_600_000) for index in range(1_000)]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=first_page if calls == 1 else [])

    ingestor = BinanceIngestor(DataSettings(), _client(handler))
    candles = ingestor.fetch(
        "BTCUSDT", "1h", start, start + timedelta(days=50), start + timedelta(days=60)
    )
    assert len(candles) == 1_000
    assert calls == 2


def test_429_retries_using_retry_after_and_418_stops() -> None:
    responses = [httpx.Response(429, headers={"Retry-After": "2"}), httpx.Response(200, json=[])]
    waits: list[float] = []
    ingestor = BinanceIngestor(
        DataSettings(), _client(lambda request: responses.pop(0)), waits.append
    )
    assert (
        ingestor.fetch(
            "BTCUSDT",
            "1h",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
        == []
    )
    assert waits == [2]
    banned = BinanceIngestor(DataSettings(), _client(lambda request: httpx.Response(418)))
    with pytest.raises(BinanceBanError):
        banned.fetch(
            "BTCUSDT",
            "1h",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )


def test_server_errors_retry_then_raise_a_typed_error() -> None:
    waits: list[float] = []
    ingestor = BinanceIngestor(
        DataSettings(max_retries=1),
        _client(lambda request: httpx.Response(503)),
        waits.append,
        lambda: 0,
    )
    with pytest.raises(BinanceError, match="retries exhausted"):
        ingestor.fetch(
            "BTCUSDT",
            "1h",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
        )
    assert waits == [1]


def test_malformed_batch_writes_nothing() -> None:
    store = MemoryStore()
    ingestor = BinanceIngestor(
        DataSettings(), _client(lambda request: httpx.Response(200, json=[[1]]))
    )
    with pytest.raises(BinanceError):
        ingestor.backfill(
            store,
            "BTCUSDT",
            "1h",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 2, tzinfo=UTC),
            datetime(2026, 1, 3, tzinfo=UTC),
        )
    assert store.rows == {}


def test_gaps_backfill_and_freshness_boundary() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    assert find_gaps([start, start + timedelta(hours=2)], "1h") == [
        (start + timedelta(hours=1), start + timedelta(hours=1))
    ]
    store = MemoryStore()
    store.rows[start] = Candle(
        symbol="BTCUSDT", open_time=start, open=10, high=12, low=9, close=11, volume=2
    )
    assert not latest_freshness(store, "BTCUSDT", "1h", start + timedelta(hours=2)).stale
    assert latest_freshness(store, "BTCUSDT", "1h", start + timedelta(hours=2, seconds=1)).stale


def test_settings_has_only_public_data_settings(monkeypatch) -> None:
    monkeypatch.setenv("TRADER_DATA__BASE_URL", "https://example.invalid")
    assert Settings().data.base_url == "https://example.invalid"
