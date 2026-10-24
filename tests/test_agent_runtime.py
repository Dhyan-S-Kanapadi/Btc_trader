import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from fastapi.testclient import TestClient

from trader import agent_runtime
from trader.agent.groq import GroqModel
from trader.agent_runtime import create_agentcore_app
from trader.config import Settings
from trader.models import Snapshot


def _snapshot() -> Snapshot:
    return Snapshot(
        idempotency_key="BTCUSDT:1h:2026-01-01T00:00:00+00:00",
        symbol="BTCUSDT",
        signal_time=datetime(2026, 1, 1, tzinfo=UTC),
        reference_price=Decimal("100"),
        atr=Decimal("1"),
        breakout_level=Decimal("99"),
    )


def test_groq_adapter_maps_tool_calls_and_never_exposes_the_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.groq.com"
        assert request.headers["authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "volume_vs_average",
                                        "arguments": '{"lookback_bars":24}',
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    model = GroqModel(
        "test-key",
        "test-model",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    assert model.invoke("prompt", _snapshot(), {"volume_vs_average": {"type": "object"}}) == {
        "tool": "volume_vs_average",
        "args": {"lookback_bars": 24},
    }


def test_agentcore_runtime_contract_returns_guardrailed_verdict() -> None:
    class Model:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def invoke(self, _prompt, snapshot, _tools):
            return json.dumps(
                {
                    "action": "SKIP",
                    "reasons": ["evidence is insufficient"],
                    "cited_evidence": {"snapshot.symbol": snapshot.symbol},
                }
            )

    settings = Settings().model_copy(update={"groq_token": "test-key"})
    client = TestClient(create_agentcore_app(settings, model_factory=Model))
    snapshot = _snapshot()
    payload = {
        "schema_version": 2,
        "request_id": "request",
        "snapshot": snapshot.model_dump(mode="json"),
        "snapshot_digest": "digest",
        "model_id": "test-model",
        "prompt_version": "investigator_v1",
        "variant": "base",
    }
    response = client.post("/invocations", json=payload)
    assert response.status_code == 200
    assert response.json()["verdict"]["action"] == "SKIP"
    assert client.get("/ping").json() == {"status": "ok"}


def test_agentcore_runtime_refuses_bad_contract_without_a_model_call() -> None:
    settings = Settings().model_copy(update={"groq_token": "test-key"})
    client = TestClient(
        create_agentcore_app(settings, model_factory=lambda *_args, **_kwargs: None)
    )
    assert client.post("/invocations", json={"schema_version": 99}).status_code == 422


def test_agentcore_runtime_does_not_import_worker_or_trading_boundaries() -> None:
    source = inspect.getsource(agent_runtime)
    assert all(f"trader.{name}" not in source for name in ("worker", "risk", "broker", "replay"))
