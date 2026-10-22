import httpx
import pytest

from trader.config import NewsSettings
from trader.news.sources import BlsCalendarSource, NewsFetchError, parse_ics


def test_ics_parser_bounds_and_does_not_guess_timezones() -> None:
    body = b"\r\n".join(
        [
            b"BEGIN:VCALENDAR",
            b"BEGIN:VEVENT",
            b"UID:x",
            b"SUMMARY:Jobs report",
            b"DTSTART:20260101T080000",
            b"END:VEVENT",
            b"END:VCALENDAR",
        ]
    )
    item = parse_ics(body, 1)[0]
    assert item.source_item_id == "x" and item.published_at is None


def test_source_rejects_wrong_content_type() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"x"))
    )
    with pytest.raises(NewsFetchError, match="wrong_content_type"):
        BlsCalendarSource(NewsSettings(), client).fetch()


def test_source_stops_stream_before_oversized_body_is_collected() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/calendar"}, content=b"x" * 11
            )
        )
    )
    settings = NewsSettings(max_response_bytes=10)
    with pytest.raises(NewsFetchError, match="response_too_large"):
        BlsCalendarSource(settings, client).fetch()


def test_source_enforces_total_deadline_while_reading() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/calendar"}, content=b"BEGIN:VCALENDAR"
            )
        )
    )
    ticks = iter((0.0, 2.0))
    with pytest.raises(NewsFetchError, match="deadline_exceeded"):
        BlsCalendarSource(
            NewsSettings(total_deadline_seconds=1), client, lambda: next(ticks)
        ).fetch()
