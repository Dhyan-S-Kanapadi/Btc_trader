"""Time-gated episodic-memory tests: future evidence must raise, never disappear."""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from trader.agent_tools import InMemoryCandleSource, ToolError, ToolRegistry
from trader.config import Settings
from trader.memory import (
    Episode,
    InMemoryMemorySource,
    embed_snapshot,
    embedding_version,
    record_episode,
)
from trader.models import Candidate, Snapshot, Trade


def _snapshot(at: datetime, key: str = "current") -> Snapshot:
    return Snapshot(
        idempotency_key=key,
        symbol="BTCUSDT",
        signal_time=at,
        reference_price=Decimal("100"),
        atr=Decimal("2"),
        breakout_level=Decimal("99"),
        volume_ratio=Decimal("2"),
        breakout_strength_atr=Decimal("1"),
        atr_pct=Decimal("0.02"),
        range_24h_pct=Decimal("0.1"),
        trend_vs_sma=Decimal("0.01"),
    )


def _settings() -> Settings:
    return Settings().model_copy(
        update={"agent_memory": Settings().agent_memory.model_copy(update={"enabled": True})}
    )


def _episode(
    at: datetime, known_at: datetime, key: str = "past", namespace: str = "live"
) -> Episode:
    settings, snapshot = _settings(), _snapshot(at, key)
    vector = embed_snapshot(snapshot, settings.agent_memory)
    assert vector is not None
    return Episode(
        episode_id=f"{namespace}:{key}",
        namespace=namespace,
        symbol="BTCUSDT",
        interval="1h",
        candidate_key=key,
        candidate_time=at,
        snapshot_digest="digest",
        features=tuple(vector),
        embedding=tuple(vector),
        embedding_version=embedding_version(settings.agent_memory),
        net_r=Decimal("1"),
        exit_reason="stop",
        bars_held=2,
        known_at=known_at,
        synthetic=False,
    )


def test_memory_tool_is_gated_and_inclusive_at_known_at() -> None:
    as_of = datetime(2026, 1, 2, tzinfo=UTC)
    source = InMemoryMemorySource(
        [
            _episode(as_of - timedelta(days=1), as_of),
            _episode(as_of - timedelta(days=2), as_of + timedelta(seconds=1), "future"),
        ]
    )
    registry = ToolRegistry(
        as_of,
        InMemoryCandleSource([]),
        _settings(),
        snapshot=_snapshot(as_of),
        variant="memory",
        memory_source=source,
    )
    assert registry.call("similar_past_setups", {"k": 5})["found"] == 1
    assert "similar_past_setups" in registry.schemas()


def test_memory_is_not_exposed_or_retrieved_when_disabled() -> None:
    as_of = datetime(2026, 1, 2, tzinfo=UTC)
    registry = ToolRegistry(as_of, InMemoryCandleSource([]), Settings())
    assert "similar_past_setups" not in registry.schemas()
    assert registry.call("similar_past_setups", {})["reason"] == "memory_off"


def test_memory_tool_rejects_a_leaking_source_loudly() -> None:
    as_of = datetime(2026, 1, 2, tzinfo=UTC)

    class Leaking:
        def search(self, **_kwargs):
            return [{"episode_id": "bad", "candidate_time": as_of, "known_at": as_of, "net_r": 1}]

    registry = ToolRegistry(
        as_of,
        InMemoryCandleSource([]),
        _settings(),
        snapshot=_snapshot(as_of),
        variant="memory",
        memory_source=Leaking(),
    )
    with pytest.raises(ToolError, match="asof_violation"):
        registry.call("similar_past_setups", {"k": 1})


def test_embedding_is_fixed_and_nulls_are_not_embeddable() -> None:
    settings, snapshot = _settings(), _snapshot(datetime(2026, 1, 2, tzinfo=UTC))
    assert embed_snapshot(snapshot, settings.agent_memory) == embed_snapshot(
        snapshot, settings.agent_memory
    )
    assert (
        embed_snapshot(snapshot.model_copy(update={"atr_pct": None}), settings.agent_memory) is None
    )
    changed = settings.agent_memory.model_copy(update={"atr_pct_hi": 0.3})
    assert embedding_version(settings.agent_memory) != embedding_version(changed)


def test_direct_agent_memory_url_environment_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MEMORY_DATABASE_URL", "postgresql+psycopg://memory")
    monkeypatch.setenv("AGENT_MEMORY_WRITE_DATABASE_URL", "postgresql+psycopg://memory-write")
    assert Settings().agent_memory.database_url == "postgresql+psycopg://memory"
    assert Settings().agent_memory.write_database_url == "postgresql+psycopg://memory-write"


def test_record_episode_uses_net_r_after_fees_and_known_exit_close() -> None:
    at = datetime(2026, 1, 2, tzinfo=UTC)
    candidate = Candidate(
        symbol="BTCUSDT",
        bar_index=1,
        signal_time=at,
        reference_price=100,
        atr=2,
        breakout_level=99,
        idempotency_key="candidate",
    )
    trade = Trade(
        account_id="A",
        symbol="BTCUSDT",
        qty=2,
        entry_price=100,
        entry_time=at,
        stop_price=95,
        initial_stop_price=95,
        exit_price=110,
        exit_time=at + timedelta(hours=1),
        fees=2,
        reason="time_stop",
    )
    episode = record_episode(
        candidate,
        _snapshot(at, "candidate"),
        trade,
        at + timedelta(hours=2),
        namespace="synthetic:test",
        synthetic=True,
        config=_settings().agent_memory,
    )
    assert episode is not None and episode.net_r == Decimal("1.8")


def test_postgres_memory_is_time_gated_and_idempotent() -> None:
    """Exercise pgvector exact search when a Postgres test URL is available."""

    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL memory integration tests")
    import psycopg

    from trader.memory.postgres import PostgresMemorySource, PostgresMemoryWriter

    with psycopg.connect(database_url.replace("postgresql+psycopg://", "postgresql://", 1)) as con:
        con.execute(Path("sql/agent_memory_init.sql").read_text(encoding="utf-8"))
    as_of = datetime(2026, 1, 3, tzinfo=UTC)
    namespace = f"test-{uuid4()}"
    past = _episode(as_of - timedelta(days=1), as_of, "past", namespace)
    future = _episode(as_of - timedelta(days=2), as_of + timedelta(seconds=1), "future", namespace)
    source = PostgresMemorySource(database_url)
    writer = PostgresMemoryWriter(database_url)
    assert writer.insert([past, future]) == 2
    assert writer.insert([past]) == 0
    rows = source.search(
        as_of=as_of,
        candidate_key="future",
        namespace=namespace,
        embedding=list(past.embedding),
        embedding_version=past.embedding_version,
        k=5,
        max_distance=2.0,
    )
    assert [row["candidate_key"] for row in rows] == ["past"]
    raw_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    with psycopg.connect(raw_url) as con:
        con.execute("SET LOCAL ROLE agent_memory_reader")
        assert con.execute("SELECT count(*) FROM agent_memory.episodes").fetchone() is not None
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            con.execute("INSERT INTO agent_memory.episodes DEFAULT VALUES")
