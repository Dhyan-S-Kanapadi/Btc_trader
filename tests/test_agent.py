"""Synthetic bounded-investigator plumbing tests; no model or network calls."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trader.agent import investigate
from trader.agent_tools import InMemoryCandleSource
from trader.config import Settings
from trader.models import Candle, Snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        idempotency_key="synthetic",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 2, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("2"),
        breakout_level=Decimal("99"),
        volume_ratio=Decimal("1.8"),
    )


class _Model:
    def invoke(self, prompt, snapshot, tools):
        return {
            "action": "SKIP",
            "reasons": ["evidence is insufficient"],
            "cited_evidence": {"snapshot.volume_ratio": 1.80},
        }


def test_investigator_returns_guardrailed_synthetic_verdict() -> None:
    candles = [
        Candle(
            symbol="BTCUSDT",
            open_time=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=i),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for i in range(24)
    ]
    result = investigate(
        _snapshot(),
        config=Settings().agent,
        tool_source=InMemoryCandleSource(candles),
        model=_Model(),
    )
    assert result.status == "ok" and result.verdict.action == "SKIP"


def test_step_cap_fails_closed() -> None:
    class Loop:
        def invoke(self, prompt, snapshot, tools):
            return {"tool": "volume_vs_average", "args": {}}

    settings = Settings().model_copy(
        update={"agent": Settings().agent.model_copy(update={"step_cap": 1})}
    )
    result = investigate(
        _snapshot(), config=settings.agent, tool_source=InMemoryCandleSource([]), model=Loop()
    )
    assert result.status == "step_cap" and result.verdict.action == "SKIP"
