"""Pure as-of reads.  Publication time is never used as availability time."""

from __future__ import annotations

from datetime import datetime, timedelta

from trader.news.types import CoverageSource, NewsCoverage, NewsView, SanitizedHeadline


def news_coverage(
    as_of: datetime,
    configured_sources: tuple[str, ...],
    successful_polls: dict[str, datetime],
    max_staleness: timedelta,
) -> NewsCoverage:
    states = tuple(
        CoverageSource(
            source_id=source,
            ok=(at := successful_polls.get(source)) is not None
            and as_of - max_staleness <= at <= as_of,
            reason=None
            if (at := successful_polls.get(source)) is not None
            and as_of - max_staleness <= at <= as_of
            else "no_recent_successful_poll",
        )
        for source in configured_sources
    )
    return NewsCoverage(as_of=as_of, ok=all(state.ok for state in states), sources=states)


def visible(
    items: tuple[SanitizedHeadline, ...],
    *,
    as_of: datetime,
    allowlisted_sources: tuple[str, ...],
    coverage: NewsCoverage,
    excluded_counts: dict[str, int],
) -> NewsView:
    """Return caller-selected records visible at inclusive as-of; persistence filters statuses."""
    return NewsView(
        headlines=tuple(
            item
            for item in sorted(items, key=lambda value: (value.available_at, value.item_id))
            if item.source_id in allowlisted_sources and item.available_at <= as_of
        ),
        coverage=coverage,
        excluded_counts=excluded_counts,
    )
