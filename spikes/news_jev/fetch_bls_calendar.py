"""Throwaway Issue #24 sampler; not production news ingestion."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

SOURCE_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
OUTPUT_PATH = Path("tests/fixtures/news/bls_calendar_sample.json")


def _unfold(lines: list[str]) -> list[str]:
    """Join RFC 5545 continuation lines without depending on an ICS package."""
    result: list[str] = []
    for line in lines:
        if line.startswith((" ", "\t")) and result:
            result[-1] += line[1:]
        else:
            result.append(line)
    return result


def sample_calendar(document: str, retrieved_at: datetime) -> dict[str, object]:
    """Keep up to five schedule-only events; do not retain descriptions or bodies."""
    events: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in _unfold(document.splitlines()):
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current and {"DTSTART", "SUMMARY"} <= current.keys():
            events.append({"scheduled_at": current["DTSTART"], "headline": current["SUMMARY"]})
            current = None
        elif current is not None:
            key, separator, value = line.partition(":")
            if separator and key.split(";", 1)[0] in {"DTSTART", "SUMMARY"}:
                current[key.split(";", 1)[0]] = value

    today = retrieved_at.strftime("%Y%m%d")
    upcoming = [event for event in events if event["scheduled_at"][:8] >= today]
    selected = upcoming[:5] or events[-5:]
    return {
        "source": "U.S. Bureau of Labor Statistics release calendar",
        "source_url": SOURCE_URL,
        "retrieved_at": retrieved_at.isoformat(),
        "timezone_note": (
            "BLS web calendar publishes schedule times in Eastern Time; DTSTART is retained "
            "exactly as supplied."
        ),
        "items": selected,
        "scrub_note": (
            "Selected public schedule fields only; no credentials, account identifiers, "
            "descriptions, or article bodies."
        ),
    }


def main() -> None:
    retrieved_at = datetime.now(UTC)
    response = httpx.get(
        SOURCE_URL,
        headers={"User-Agent": "btc-paper-trader-issue-24-spike/0.1"},
        timeout=10.0,
    )
    response.raise_for_status()
    sample = sample_calendar(response.text, retrieved_at)
    if not sample["items"]:
        raise RuntimeError("BLS calendar response had no parseable scheduled events")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(sample, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(sample['items'])} scrubbed BLS events to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
