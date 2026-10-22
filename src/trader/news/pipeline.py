"""Pure conversion from a source item to a bounded durable news record."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from trader.news.guardrail import check_headline
from trader.news.sanitize import sanitize_headline
from trader.news.sources import RawItem


@dataclass(frozen=True)
class PreparedNewsItem:
    source_id: str
    source_item_id: str
    published_at: datetime | None
    fetched_at: datetime
    available_at: datetime
    text: str | None
    text_digest: str
    status: str
    flags: tuple[str, ...]
    guardrail_version: str


def prepare_item(
    source_id: str,
    raw: RawItem,
    fetched_at: datetime,
    *,
    text_cap: int,
    skew: timedelta,
    max_age: timedelta = timedelta(days=365),
) -> PreparedNewsItem:
    """Apply all deterministic input gates; `available_at` is always local receipt time."""
    sanitized = sanitize_headline(raw.title, text_cap)
    flags = [*sanitized.flags, *raw.flags]
    published_at = raw.published_at
    status = "clean"
    if published_at is not None and (
        published_at.tzinfo is None or published_at.utcoffset() is None
    ):
        status, flags, published_at = "quarantined", [*flags, "timezone_missing"], None
    elif published_at is not None and (
        published_at > fetched_at + skew or published_at < fetched_at - max_age
    ):
        status, flags, published_at = "quarantined", [*flags, "bad_timestamp"], None
    if sanitized.text is None:
        status = "quarantined"
    elif status == "clean":
        guarded = check_headline(sanitized.text, source_id)
        status = guarded.status
        flags.extend(guarded.flags)
        version = guarded.guardrail_version
    else:
        version = check_headline("", source_id).guardrail_version
    text = sanitized.text
    return PreparedNewsItem(
        source_id,
        raw.source_item_id,
        published_at,
        fetched_at,
        fetched_at,
        text,
        hashlib.sha256((text or "").encode()).hexdigest(),
        status,
        tuple(sorted(set(flags))),
        version,
    )
