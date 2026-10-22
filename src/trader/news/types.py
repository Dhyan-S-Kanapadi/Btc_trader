"""Typed, bounded objects permitted to leave the news boundary."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from trader.models import FrozenModel


def _utc_or_none(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("datetime must be timezone-aware UTC")
    return value.astimezone(UTC)


class SanitizedHeadline(FrozenModel):
    item_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    published_at: datetime | None = None
    available_at: datetime
    text: str | None = Field(default=None, max_length=200)
    flags: tuple[str, ...] = ()
    guardrail_version: str

    _published = field_validator("published_at")(_utc_or_none)
    _available = field_validator("available_at")(_utc_or_none)


class CoverageSource(FrozenModel):
    source_id: str
    ok: bool
    reason: str | None = None


class NewsCoverage(FrozenModel):
    as_of: datetime
    ok: bool
    sources: tuple[CoverageSource, ...]

    _as_of = field_validator("as_of")(_utc_or_none)


class NewsView(FrozenModel):
    headlines: tuple[SanitizedHeadline, ...]
    coverage: NewsCoverage
    excluded_counts: dict[str, int]


NewsStatus = Literal["clean", "flagged", "quarantined", "duplicate"]
