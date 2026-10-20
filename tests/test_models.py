"""Tests for validated frozen core types."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trader.models import Candle, Snapshot, Verdict


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware UTC"):
        Candle.model_validate(
            {
                "symbol": "BTCUSDT",
                "open_time": datetime(2026, 1, 1),
                "open": "1",
                "high": "2",
                "low": "1",
                "close": "2",
                "volume": "3",
            }
        )


def test_verdict_rejects_extra_fields_and_invalid_actions() -> None:
    valid = {"action": "TAKE", "reasons": ["evidence"], "cited_evidence": {}}

    with pytest.raises(ValidationError):
        Verdict.model_validate({**valid, "stop_price": "10"})
    with pytest.raises(ValidationError):
        Verdict.model_validate({**valid, "action": "BUY"})


def test_snapshot_json_round_trip_is_lossless() -> None:
    snapshot = Snapshot(
        idempotency_key="BTCUSDT:1h:2026-01-01T00:00:00+00:00",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("2"),
        breakout_level=Decimal("99"),
        volume_ratio=Decimal("1.25"),
        trend_vs_sma=Decimal("0.03"),
    )

    assert Snapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
