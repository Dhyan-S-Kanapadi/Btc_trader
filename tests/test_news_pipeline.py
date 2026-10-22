from datetime import UTC, datetime, timedelta

from trader.news.pipeline import prepare_item
from trader.news.sources import RawItem


def test_pipeline_never_uses_source_time_for_availability() -> None:
    fetched = datetime(2026, 1, 2, tzinfo=UTC)
    item = prepare_item(
        "bls",
        RawItem("x", "Employment Situation", fetched - timedelta(days=2)),
        fetched,
        text_cap=200,
        skew=timedelta(minutes=5),
    )
    assert item.available_at == fetched


def test_pipeline_quarantines_future_and_old_timestamps() -> None:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    for value in (now + timedelta(hours=1), now - timedelta(days=2)):
        item = prepare_item(
            "bls",
            RawItem("x", "Employment Situation", value),
            now,
            text_cap=200,
            skew=timedelta(minutes=5),
            max_age=timedelta(days=1),
        )
        assert item.status == "quarantined" and "bad_timestamp" in item.flags


def test_pipeline_marks_missing_timezone_without_inventing_a_zone() -> None:
    item = prepare_item(
        "bls",
        RawItem("x", "Employment Situation", None, ("timezone_missing",)),
        datetime(2026, 1, 2, tzinfo=UTC),
        text_cap=200,
        skew=timedelta(minutes=5),
    )
    assert item.published_at is None and "timezone_missing" in item.flags
