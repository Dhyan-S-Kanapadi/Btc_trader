"""Jev tests use only mocked typed gateway responses."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from importlib.resources import files

import httpx
import pytest

from trader.config import JevSettings
from trader.jev.client import JevClient, JevError
from trader.jev.sensor import JevFields, apply_jev_fields, build_state, parse_jev_response
from trader.models import Snapshot
from trader.news.types import SanitizedHeadline


def _snapshot() -> Snapshot:
    return Snapshot(
        idempotency_key="candidate",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 1, 12, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("2"),
        breakout_level=Decimal("99"),
    )


def test_state_is_asof_bounded_and_deterministic() -> None:
    now = _snapshot().signal_time
    old = SanitizedHeadline(
        item_id="old",
        source_id="bls",
        available_at=now - timedelta(hours=4),
        text="old",
        guardrail_version="x",
    )
    current = SanitizedHeadline(
        item_id="now",
        source_id="bls",
        available_at=now,
        text="current",
        flags=("flagged",),
        guardrail_version="x",
    )
    future = SanitizedHeadline(
        item_id="future",
        source_id="bls",
        available_at=now + timedelta(seconds=1),
        text="future",
        guardrail_version="x",
    )
    state, digest, ids = build_state((future, current, old), now, JevSettings(gateway_token="test"))
    assert ids == ("now",)
    assert "future" not in state and "old" not in state
    assert len(digest) == 64


def test_strict_typed_response_and_snapshot_upgrade() -> None:
    fields = parse_jev_response(
        b'{"answers":{"major_event_within_4h":{"value":true,"probability":0.7},"news_tone":{"value":-0.25}}}'
    )
    updated = apply_jev_fields(_snapshot(), fields)
    assert updated.schema_version == 2
    assert updated.jev_event_4h is True
    assert updated.jev_tone_score == Decimal("-0.25")
    assert fields == JevFields(
        event_4h=True, event_prob=Decimal("0.7"), tone_score=Decimal("-0.25"), status="ok"
    )


def test_client_uses_mocked_pinned_gateway_and_rejects_large_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "ai-gateway.vercel.sh"
        assert request.headers["authorization"] == "Bearer test"
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    client = JevClient(
        JevSettings(gateway_token="test"), httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.ask("safe", {}).http_status == 200
    too_large = JevClient(
        JevSettings(gateway_token="test", max_response_bytes=1),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(JevError, match="response_too_large"):
        too_large.ask("safe", {})


def test_versioned_templates_match_the_checked_in_manifest() -> None:
    root = files("trader.jev.templates")
    manifest = json.loads(root.joinpath("manifest.json").read_text(encoding="utf-8"))
    assert {
        name: sha256(root.joinpath(name).read_bytes()).hexdigest() for name in manifest
    } == manifest
