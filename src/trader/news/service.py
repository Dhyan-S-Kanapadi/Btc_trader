"""Standalone forward-test poller; it is deliberately not part of ``trader.worker``."""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from trader.config import NewsSettings
from trader.db.storage import PostgresStorage
from trader.news.pipeline import prepare_item
from trader.news.sources import BlsCalendarSource, NewsFetchError
from trader.news.types import SanitizedHeadline
from trader.news.view import news_coverage, visible


class NewsLock:
    """Dedicated lock; the polling process never shares the worker's connection or key."""

    def __init__(self, storage: PostgresStorage, key: int) -> None:
        self.connection, self.key = storage._engine.connect(), key

    def acquire(self) -> bool:
        return bool(
            self.connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
        )

    def close(self) -> None:
        try:
            if not self.connection.closed:
                self.connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})
        finally:
            self.connection.close()


def poll_once(
    storage: PostgresStorage,
    settings: NewsSettings,
    source: BlsCalendarSource,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> dict[str, int | str | bool]:
    """Fetch then persist bounded, sanitized metadata. Errors are durable stable codes only."""
    started = now()
    logger = logging.getLogger("trader.news")
    try:
        batch = source.fetch(storage.news_conditional_state(source.source_id))
        poll_id = storage.save_news_poll(
            source_id=source.source_id,
            started_at=started,
            finished_at=now(),
            status="ok",
            error_code=None,
            http_status=None,
            items_seen=len(batch.items),
            items_new=0,
            duplicates=0,
            quarantined=0,
            revisions=0,
            latency_ms=int((now() - started).total_seconds() * 1000),
            not_modified=batch.not_modified,
            retry_after_seen=False,
            etag=batch.etag,
            last_modified=batch.last_modified,
        )
        counts = {"new": 0, "duplicates": 0, "quarantined": 0, "revisions": 0}
        for raw in batch.items:
            item = prepare_item(
                source.source_id,
                raw,
                now(),
                text_cap=settings.text_cap,
                skew=timedelta(seconds=settings.skew_seconds),
                max_age=timedelta(seconds=settings.max_timestamp_age_seconds),
            )
            duplicate = storage.find_news_duplicate(
                item.source_id,
                item.text_digest,
                item.fetched_at,
                settings.near_duplicate_window_seconds,
            )
            values = {
                **item.__dict__,
                "flags": list(item.flags),
                "poll_id": poll_id,
                "synthetic": False,
                "revision_count": 0,
            }
            if duplicate is not None:
                values.update(
                    status="duplicate",
                    duplicate_of=duplicate.id,
                    flags=sorted(set([*item.flags, "cross_source_duplicate"])),
                )
                counts["duplicates"] += 1
            _id, inserted, revision = storage.save_news_item(**values)
            counts["new"] += int(inserted)
            counts["revisions"] += int(revision)
            counts["quarantined"] += int(item.status == "quarantined")
        logger.info(
            "news poll",
            extra={
                "source": source.source_id,
                "event": "poll",
                "items_seen": len(batch.items),
                "not_modified": batch.not_modified,
                **counts,
            },
        )
        return {"status": "ok", "not_modified": batch.not_modified, **counts}
    except NewsFetchError as error:
        storage.save_news_poll(
            source_id=source.source_id,
            started_at=started,
            finished_at=now(),
            status="failed",
            error_code=str(error),
            http_status=None,
            items_seen=0,
            items_new=0,
            duplicates=0,
            quarantined=0,
            revisions=0,
            latency_ms=int((now() - started).total_seconds() * 1000),
            not_modified=False,
            retry_after_seen=str(error) == "rate_limited",
            etag=None,
            last_modified=None,
        )
        logger.error(
            "news poll failed",
            extra={"source": source.source_id, "event": "error", "error_code": str(error)},
        )
        return {"status": "failed", "error_code": str(error)}


def show(storage: PostgresStorage, settings: NewsSettings, as_of: datetime):
    sources = tuple(part.strip() for part in settings.sources.split(",") if part.strip() == "bls")
    if sources != ("bls",):
        raise ValueError("only the BLS source is allowlisted")
    if as_of.tzinfo is None:
        raise ValueError("--as-of must be timezone-aware UTC")
    polls = storage.recent_news_polls(
        sources, as_of, as_of - timedelta(seconds=settings.max_poll_staleness_seconds)
    )
    latest = {
        source: max((row.finished_at for row in polls if row.source_id == source), default=None)
        for source in sources
    }
    coverage = news_coverage(
        as_of, sources, latest, timedelta(seconds=settings.max_poll_staleness_seconds)
    )
    rows = storage.read_news_items(as_of, sources, synthetic=False)
    headlines = tuple(
        SanitizedHeadline(
            item_id=str(row.id),
            source_id=row.source_id,
            published_at=row.published_at,
            available_at=row.available_at,
            text=row.text,
            flags=tuple(row.flags),
            guardrail_version=row.guardrail_version,
        )
        for row in rows
    )
    return visible(
        headlines,
        as_of=as_of,
        allowlisted_sources=sources,
        coverage=coverage,
        excluded_counts={"quarantined_or_duplicate": 0},
    )


def run(storage: PostgresStorage, settings: NewsSettings) -> int:
    """Gracefully finish at most the current persistence operation after SIGTERM."""
    logger, stopping = logging.getLogger("trader.news"), False
    lock = NewsLock(storage, settings.lock_key)
    if not lock.acquire():
        logger.error(
            "news lock unavailable", extra={"event": "error", "error_code": "lock_unavailable"}
        )
        lock.close()
        return 1

    def stop(_signum, _frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    source = BlsCalendarSource(settings)
    try:
        while not stopping:
            result = poll_once(storage, settings, source)
            logger.info("news heartbeat", extra={"event": "heartbeat", "status": result["status"]})
            for _ in range(settings.poll_interval_seconds):
                if stopping:
                    break
                time.sleep(1)
        return 0
    finally:
        source.close()
        lock.close()
