"""Variant evidence composition stays outside the worker and uses no network in tests."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from trader.config import Settings
from trader.control import AccountControl, ControlConfig, GlobalControl
from trader.models import Snapshot
from trader.replay import AccountConfig
from trader.variant_runtime import VariantEvidenceProvider


def _snapshot() -> Snapshot:
    return Snapshot(
        idempotency_key="candidate",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("1"),
        breakout_level=Decimal("99"),
    )


def test_c_jev_enrichment_is_opt_in_and_isolated(monkeypatch) -> None:
    calls = []

    class Client:
        def __init__(self, _settings):
            calls.append("client")

        def close(self):
            calls.append("close")

    class Sensor:
        def __init__(self, _client, _settings, _monotonic, _storage):
            calls.append("sensor")

        def sense(self, snapshot, _reader, *, clock):
            calls.append(clock())
            return snapshot.model_copy(
                update={"schema_version": 2, "jev_status": "coverage_not_ok"}
            )

    monkeypatch.setattr("trader.variant_runtime.JevClient", Client)
    monkeypatch.setattr("trader.variant_runtime.JevSensor", Sensor)
    provider = VariantEvidenceProvider(Settings())
    accounts = {
        "C": (
            SimpleNamespace(),
            AccountConfig(
                account_id="C",
                label="C",
                policy_name="agent_veto",
                variant="jev",
                starting_equity=Decimal("1"),
            ),
        )
    }
    off = ControlConfig()
    assert provider.enrichers(object(), off, accounts) == {}
    enabled = ControlConfig(
        global_control=GlobalControl(agent_enabled=True, jev_enabled=True),
        accounts={"C": AccountControl(account_id="C", agent_enabled=True, jev_enabled=True)},
    )
    enriched = provider.enrichers(object(), enabled, accounts)["C"](_snapshot())
    assert enriched.jev_status == "coverage_not_ok"
    assert calls[:2] == ["client", "sensor"]
    provider.close()
    assert calls[-1] == "close"
