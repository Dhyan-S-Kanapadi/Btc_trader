"""BLS-only bounded network edge. It returns no response body outside this module."""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from trader.config import NewsSettings

BLS_SOURCE_ID = "bls"
BLS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_HOSTS = frozenset({"www.bls.gov"})


class NewsFetchError(RuntimeError):
    """Stable source-boundary error code; never includes response text or credentials."""


@dataclass(frozen=True)
class RawItem:
    source_item_id: str
    title: str
    published_at: datetime | None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawBatch:
    items: tuple[RawItem, ...]
    etag: str | None
    last_modified: str | None
    not_modified: bool = False


class NewsSource(Protocol):
    source_id: str

    def fetch(self, conditional_state: dict[str, str] | None = None) -> RawBatch: ...


def _checked_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise NewsFetchError("non_https_url")
    if parsed.hostname not in BLS_HOSTS or parsed.username or parsed.password:
        raise NewsFetchError("non_allowlisted_host")


def parse_ics(payload: bytes, max_items: int) -> tuple[RawItem, ...]:
    """Parse only VEVENT identifier/title/timestamp fields; naive times stay unavailable."""
    if b"\x00" in payload:
        raise NewsFetchError("invalid_calendar")
    try:
        lines = payload.decode("utf-8").replace("\r\n ", "").replace("\r\n\t", "").splitlines()
    except UnicodeDecodeError as error:
        raise NewsFetchError("invalid_utf8") from error
    items: list[RawItem] = []
    active: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            active = {}
        elif line == "END:VEVENT" and active is not None:
            title, uid, timestamp = active.get("SUMMARY"), active.get("UID"), active.get("DTSTART")
            if title:
                published_at, flags = None, ()
                if timestamp:
                    try:
                        if timestamp.endswith("Z"):
                            published_at = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(
                                tzinfo=UTC
                            )
                        else:
                            flags = ("timezone_missing",)
                    except ValueError:
                        flags = ("bad_timestamp",)
                item_id = uid or hashlib.sha256((title + (timestamp or "")).encode()).hexdigest()
                items.append(RawItem(item_id, title, published_at, flags))
                if len(items) >= max_items:
                    break
            active = None
        elif active is not None and ":" in line:
            key, value = line.split(":", 1)
            name = key.split(";", 1)[0]
            if name in {"SUMMARY", "UID", "DTSTART"}:
                active[name] = value
    return tuple(items)


class BlsCalendarSource:
    """Official BLS adapter with bounded redirects, retries, rate limiting and a local breaker."""

    source_id = BLS_SOURCE_ID

    def __init__(
        self,
        settings: NewsSettings,
        client: httpx.Client | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        random_value: Callable[[], float] = random.random,
    ) -> None:
        self.settings, self.client, self._monotonic = (
            settings,
            client or httpx.Client(follow_redirects=False),
            monotonic,
        )
        self._owns_client, self._sleep, self._random = client is None, sleep, random_value
        self._last_started = float("-inf")
        self._failures = 0
        self._open_until = float("-inf")
        self._retry_after: float | None = None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def fetch(self, conditional_state: dict[str, str] | None = None) -> RawBatch:
        started = self._monotonic()
        if started < self._open_until:
            raise NewsFetchError("circuit_open")
        wait = self.settings.poll_interval_seconds - (started - self._last_started)
        if self._last_started != float("-inf") and wait > 0:
            self._sleep(wait)
        self._last_started = started
        headers = {"User-Agent": "btc-paper-trader-news/0.1", "Accept": "text/calendar"}
        if conditional_state:
            for key, header in (("etag", "If-None-Match"), ("last_modified", "If-Modified-Since")):
                if conditional_state.get(key):
                    headers[header] = conditional_state[key]
        for attempt in range(self.settings.max_retries + 1):
            try:
                batch = self._fetch_once(BLS_URL, headers, started)
                self._failures = 0
                return batch
            except NewsFetchError as error:
                retryable = str(error) in {
                    "network_error",
                    "deadline_exceeded",
                    "rate_limited",
                    "server_error",
                }
                if (
                    str(error) == "deadline_exceeded"
                    or not retryable
                    or attempt == self.settings.max_retries
                ):
                    self._failures += 1
                    if self._failures >= self.settings.breaker_failure_threshold:
                        self._open_until = (
                            self._monotonic() + self.settings.breaker_cooldown_seconds
                        )
                    raise
                delay = self._retry_after
                self._retry_after = None
                if delay is None:
                    delay = 2**attempt + self._random()
                delay = min(self.settings.max_retry_seconds, delay)
                if self._monotonic() + delay - started > self.settings.total_deadline_seconds:
                    raise NewsFetchError("deadline_exceeded") from error
                self._sleep(delay)
        raise AssertionError("unreachable")

    def _fetch_once(self, url: str, headers: dict[str, str], started: float) -> RawBatch:
        _checked_url(url)
        redirects = 0
        while True:
            if self._monotonic() - started > self.settings.total_deadline_seconds:
                raise NewsFetchError("deadline_exceeded")
            try:
                timeout = max(
                    0.01, self.settings.total_deadline_seconds - (self._monotonic() - started)
                )
                with self.client.stream("GET", url, headers=headers, timeout=timeout) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if redirects >= self.settings.redirect_limit or not location:
                            raise NewsFetchError("redirect_refused")
                        url = urljoin(str(response.url), location)
                        _checked_url(url)
                        redirects += 1
                        continue
                    if response.status_code == 304:
                        return RawBatch(
                            (),
                            response.headers.get("etag"),
                            response.headers.get("last-modified"),
                            True,
                        )
                    if response.status_code == 429:
                        value = response.headers.get("retry-after")
                        try:
                            self._retry_after = max(0.0, float(value)) if value else None
                        except ValueError:
                            try:
                                self._retry_after = max(
                                    0.0,
                                    (
                                        parsedate_to_datetime(value).astimezone(UTC)
                                        - datetime.now(UTC)
                                    ).total_seconds(),
                                )
                            except (TypeError, ValueError):
                                self._retry_after = None
                        raise NewsFetchError("rate_limited")
                    if response.status_code >= 500:
                        raise NewsFetchError("server_error")
                    if response.status_code >= 400:
                        raise NewsFetchError(f"http_{response.status_code}")
                    if "text/calendar" not in response.headers.get("content-type", "").lower():
                        raise NewsFetchError("wrong_content_type")
                    chunks: list[bytes] = []
                    size = 0
                    for chunk in response.iter_bytes():
                        if self._monotonic() - started > self.settings.total_deadline_seconds:
                            raise NewsFetchError("deadline_exceeded")
                        size += len(chunk)
                        if size > self.settings.max_response_bytes:
                            raise NewsFetchError("response_too_large")
                        chunks.append(chunk)
                    return RawBatch(
                        parse_ics(b"".join(chunks), self.settings.max_items_per_poll),
                        response.headers.get("etag"),
                        response.headers.get("last-modified"),
                    )
            except httpx.TimeoutException as error:
                raise NewsFetchError("deadline_exceeded") from error
            except httpx.RequestError as error:
                raise NewsFetchError("network_error") from error
