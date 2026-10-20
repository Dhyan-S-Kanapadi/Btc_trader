"""Tests for environment-only paper-trading configuration."""

from collections.abc import Iterator
from decimal import Decimal

from pydantic import BaseModel

from trader.config import Settings


def _field_names(model: type[BaseModel]) -> Iterator[str]:
    for name, field in model.model_fields.items():
        yield name
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            yield from _field_names(annotation)


def test_nested_environment_variable_overrides_default(monkeypatch) -> None:
    monkeypatch.setenv("TRADER_RISK__RISK_PER_TRADE", "0.02")

    assert Settings().risk.risk_per_trade == Decimal("0.02")


def test_database_url_uses_the_single_unprefixed_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://paper:paper@localhost/paper_trader")

    assert Settings().database_url == "postgresql+psycopg://paper:paper@localhost/paper_trader"


def test_settings_have_no_exchange_key_or_order_placement_fields() -> None:
    prohibited = ("exchange", "api_key", "secret", "order_", "live_trading")

    assert not any(term in name.lower() for name in _field_names(Settings) for term in prohibited)
