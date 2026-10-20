"""PostgreSQL integration tests; run after `make up` or in CI."""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from trader.cli import main
from trader.db.migrations import downgrade_base, upgrade_head
from trader.db.models import DecisionRow, OrderRow
from trader.db.storage import DecisionWrite, OrderWrite, PostgresStorage
from trader.models import Candidate, Candle

EXPECTED_TABLES = {
    "accounts",
    "candidates",
    "candles",
    "configs",
    "decisions",
    "equity_curve",
    "orders",
    "positions",
    "run_metadata",
    "snapshots",
    "trades",
}


@pytest.fixture
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if value is None:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture
def storage(database_url: str) -> PostgresStorage:
    downgrade_base(database_url)
    upgrade_head(database_url)
    return PostgresStorage(database_url)


def _candidate(storage: PostgresStorage) -> tuple[Candidate, object]:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    candle_id = storage.save_candle(
        Candle(
            symbol="BTCUSDT",
            open_time=now,
            open=Decimal("100"),
            high=Decimal("110"),
            low=Decimal("90"),
            close=Decimal("105"),
            volume=Decimal("1"),
        ),
        "1h",
    )
    candidate = Candidate(
        symbol="BTCUSDT",
        bar_index=1,
        signal_time=now,
        reference_price=Decimal("105"),
        atr=Decimal("5"),
        breakout_level=Decimal("104"),
        idempotency_key="candidate-1",
    )
    return candidate, storage.save_candidate(candidate, candle_id)


def _write(
    account_id: str, candidate_id: object, candidate_key: str
) -> tuple[DecisionWrite, OrderWrite]:
    return (
        DecisionWrite(account_id, candidate_id, candidate_key, "TAKE", "test evidence"),
        OrderWrite(account_id, candidate_id, candidate_key, "BUY", Decimal("0.1"), "PENDING"),
    )


def test_migration_upgrades_and_downgrades_fresh_postgres(
    database_url: str, monkeypatch, capfd
) -> None:
    downgrade_base(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    assert main(["migrate"]) == 0
    _, stderr = capfd.readouterr()
    assert "database migrated" in stderr
    engine = PostgresStorage(database_url)._engine
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())

    downgrade_base(database_url)
    assert not (EXPECTED_TABLES & set(inspect(engine).get_table_names()))


def test_duplicate_decision_is_rejected(storage: PostgresStorage) -> None:
    candidate, candidate_id = _candidate(storage)
    storage.save_account_state("A", Decimal("1000"), Decimal("1000"), Decimal("1000"))
    decision, order = _write("A", candidate_id, candidate.idempotency_key)
    with storage._sessions.begin() as session:
        session.add(DecisionRow(**decision.__dict__))

    with pytest.raises(IntegrityError):
        storage.save_decision_and_order(decision, order)


def test_duplicate_order_rolls_back_the_new_decision(storage: PostgresStorage) -> None:
    candidate, candidate_id = _candidate(storage)
    storage.save_account_state("A", Decimal("1000"), Decimal("1000"), Decimal("1000"))
    decision, order = _write("A", candidate_id, candidate.idempotency_key)
    with storage._sessions.begin() as session:
        session.add(OrderRow(**order.__dict__))

    with pytest.raises(IntegrityError):
        storage.save_decision_and_order(decision, order)

    assert storage.decision_count("A", candidate.idempotency_key) == 0


def test_candidate_is_idempotent_per_account(storage: PostgresStorage) -> None:
    candidate, candidate_id = _candidate(storage)
    for account_id in "ABCD":
        storage.save_account_state(account_id, Decimal("1000"), Decimal("1000"), Decimal("1000"))
        storage.save_decision_and_order(
            *_write(account_id, candidate_id, candidate.idempotency_key)
        )

    for account_id in "ABCD":
        assert storage.decision_count(account_id, candidate.idempotency_key) == 1
