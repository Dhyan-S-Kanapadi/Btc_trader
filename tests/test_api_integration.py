"""PostgreSQL-backed checks for the paper-only read API."""

import os
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from trader.api import create_app
from trader.config import Settings
from trader.db.migrations import upgrade_head
from trader.db.storage import PostgresStorage
from trader.models import Candle


@pytest.fixture
def api_client() -> tuple[TestClient, str]:
    writer = os.environ.get("DATABASE_URL")
    readonly = os.environ.get("DATABASE_URL_READONLY")
    if not writer or not readonly:
        pytest.skip("DATABASE_URL and DATABASE_URL_READONLY are required")
    test_url = make_url(writer).set(database="paper_trader_api_test")
    admin_url = test_url.set(database="postgres")
    with create_engine(admin_url, isolation_level="AUTOCOMMIT").connect() as connection:
        exists = connection.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = 'paper_trader_api_test'")
        )
        if exists is None:
            connection.execute(text("CREATE DATABASE paper_trader_api_test"))
    test_url_text = test_url.render_as_string(hide_password=False)
    readonly_test_url = (
        make_url(readonly)
        .set(database="paper_trader_api_test")
        .render_as_string(hide_password=False)
    )
    upgrade_head(test_url_text)
    with create_engine(test_url).begin() as connection:
        connection.execute(
            text("GRANT CONNECT ON DATABASE paper_trader_api_test TO paper_readonly")
        )
        connection.execute(text("GRANT USAGE ON SCHEMA public TO paper_readonly"))
        connection.execute(text("GRANT SELECT ON ALL TABLES IN SCHEMA public TO paper_readonly"))
    storage = PostgresStorage(test_url_text)
    storage.seed_account(
        "A",
        Decimal("10000"),
        {
            "account_id": "A",
            "label": "Paper A",
            "policy_name": "take_all",
            "starting_equity": "10000",
            "enabled": True,
            "risk": {
                "risk_per_trade": "0.01",
                "daily_loss_cap": "0.03",
                "max_drawdown_halt": "0.10",
                "max_open_positions": 1,
            },
            "private_note": "must not be exposed",
        },
    )
    point_time = datetime(2026, 1, 1, tzinfo=UTC)
    if not storage.equity_exists("A", point_time):
        storage.save_equity_point("A", point_time, Decimal("9900"))
    storage.save_run_metadata("SYNTHETIC_REPLAY", {"source": "synthetic"})
    storage.upsert_candles(
        [
            Candle(
                symbol="BTCUSDT",
                open_time=point_time,
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("2"),
            )
        ],
        "1h",
    )
    settings = Settings().model_copy(
        update={
            "database_url_readonly": readonly_test_url,
            "api": Settings().api.model_copy(
                update={"allowed_origins": "https://dashboard.example"}
            ),
        }
    )
    return TestClient(create_app(settings), raise_server_exceptions=False), readonly_test_url


def test_readonly_role_and_api_contract(api_client: tuple[TestClient, str]) -> None:
    client, readonly = api_client
    with create_engine(readonly).connect() as connection:
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "INSERT INTO accounts (account_id, cash, equity, peak_equity, halted) "
                    "VALUES ('B', 1, 1, 1, false)"
                )
            )
    assert client.get("/health").status_code == 200
    accounts = client.get("/v1/accounts", headers={"Origin": "https://dashboard.example"})
    assert accounts.status_code == 200
    assert accounts.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert "private_note" not in accounts.text
    assert accounts.json()["meta"]["synthetic"] is True
    assert Decimal(client.get("/v1/equity?account=A&limit=1").json()["items"][0]["equity"]) == 9900
    assert client.get("/v1/equity?start=2026-01-01").status_code == 422
    assert client.get("/v1/equity?limit=501").status_code == 422
    candles = client.get("/v1/candles?as_of=2026-01-01T01:00:00Z&limit=1")
    assert candles.status_code == 200
    assert candles.json()["items"][0]["close_time"] == "2026-01-01T01:00:00Z"
    assert client.get("/v1/candles?as_of=2026-01-01T00:00:00&limit=1").status_code == 422
    assert client.get("/v1/candles?as_of=2026-01-01T01:00:00Z&limit=501").status_code == 422
    schema = client.get("/openapi.json").json()
    assert all(set(value) <= {"get"} for value in schema["paths"].values())
