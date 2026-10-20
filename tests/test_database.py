"""PostgreSQL integration tests; run after `make up` or in CI."""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from trader.cli import main
from trader.config import Settings
from trader.db.migrations import downgrade_base, upgrade_head
from trader.db.models import DecisionRow, OrderRow
from trader.db.storage import DecisionWrite, OrderWrite, PostgresStorage
from trader.models import Candidate, Candle
from trader.replay import (
    TakeAllPolicy,
    generate_candles,
    load_account_state,
    persist_replay,
    persist_routed_candle,
    refuse_nonempty_account,
    run_replay,
    run_routed_replay,
)

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


def test_candle_upsert_is_idempotent(storage: PostgresStorage) -> None:
    candle_time = datetime(2026, 1, 1, tzinfo=UTC)
    candle = Candle(
        symbol="BTCUSDT",
        open_time=candle_time,
        open=Decimal("100"),
        high=Decimal("110"),
        low=Decimal("90"),
        close=Decimal("105"),
        volume=Decimal("1"),
    )
    storage.upsert_candles([candle], "1h")
    storage.upsert_candles([candle], "1h")
    assert storage.candle_times("BTCUSDT", "1h", candle_time, candle_time) == [candle_time]


def test_persisted_synthetic_replay_refuses_account_reuse(storage: PostgresStorage) -> None:
    base = Settings()
    config = base.model_copy(
        update={"strategy": base.strategy.model_copy(update={"symbol": "SYNTH-BTC"})}
    )
    candles = generate_candles(1, 150, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    result = run_replay(candles, TakeAllPolicy(), config)
    persist_replay(
        storage,
        candles,
        "1h",
        result,
        {"source": "synthetic", "seed": 1, "policy": "take_all"},
    )
    assert storage.account_has_replay_rows("A")
    with pytest.raises(ValueError, match="empty scratch-database account"):
        refuse_nonempty_account(storage, "A")


def test_router_persists_each_account_once_and_restores_state(storage: PostgresStorage) -> None:
    config = Settings().model_copy(
        update={"strategy": Settings().strategy.model_copy(update={"symbol": "SYNTH-BTC"})}
    )
    accounts = {}
    for account_id, policy_name in (
        ("A", "take_all"),
        ("B", "skip_all"),
        ("C", "skip_all"),
        ("D", "skip_all"),
    ):
        storage.seed_account(
            account_id,
            Decimal("10000"),
            {
                "account_id": account_id,
                "label": f"Paper {account_id}",
                "policy_name": policy_name,
                "starting_equity": "10000",
                "enabled": True,
            },
        )
    from trader.replay import AccountConfig

    for account_id in "ABCD":
        account = AccountConfig.model_validate(storage.load_account_config(account_id))
        accounts[account_id] = (load_account_state(storage, account), account)
    candles = generate_candles(8, 180, datetime(2026, 1, 1, tzinfo=UTC), "1h")
    results = run_routed_replay(
        candles,
        accounts,
        config,
        lambda candle, routed: persist_routed_candle(storage, "1h", candle, routed),
    )
    for account_id, result in results.items():
        restored = load_account_state(storage, accounts[account_id][1])
        assert restored == result.state
        assert storage.account_has_replay_rows(account_id)
    with storage._sessions() as session:
        assert session.scalar(select(func.count()).select_from(DecisionRow)) == session.scalar(
            select(func.count()).select_from(OrderRow)
        )
    rerun = run_routed_replay(
        candles,
        accounts,
        config,
        lambda candle, routed: persist_routed_candle(storage, "1h", candle, routed),
    )
    assert rerun["B"].state.position is None


def test_seeded_multi_account_cli_persists_to_a_fresh_database(
    storage: PostgresStorage, database_url: str, monkeypatch, tmp_path
) -> None:
    """The public CLI loads seeded JSON config and emits combined plus per-account output."""

    monkeypatch.setenv("DATABASE_URL", database_url)
    assert main(["seed-accounts"]) == 0
    assert (
        main(
            [
                "replay",
                "--source",
                "synthetic",
                "--seed",
                "9",
                "--bars",
                "180",
                "--accounts",
                "A,B,C,D",
                "--persist",
                "--output-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert (tmp_path / "combined_summary.json").is_file()
    assert all(
        (tmp_path / account_id / "SYNTHETIC_run_summary.json").is_file() for account_id in "ABCD"
    )
    assert storage.account_has_replay_rows("A")
    assert storage.account_has_replay_rows("D")
