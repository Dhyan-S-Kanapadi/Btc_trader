"""Internal agent HTTP service tests with an injected no-model runner."""

import pytest
from fastapi.testclient import TestClient

from trader.agent_service import create_agent_service


def _app():
    return create_agent_service(token="secret", runner=lambda payload: {"ok": payload["model_id"]})


def test_service_requires_bearer_token_and_bounds_body() -> None:
    client = TestClient(_app())
    assert client.post("/v1/investigate", json={}).status_code == 401
    assert (
        client.post(
            "/v1/investigate", headers={"Authorization": "Bearer secret"}, json={"x": "x" * 20_000}
        ).status_code
        == 413
    )
    response = client.post(
        "/v1/investigate",
        headers={"Authorization": "Bearer secret"},
        json={"schema_version": 2, "model_id": "safe"},
    )
    assert response.json() == {
        "ok": "safe",
        "schema_version": 2,
        "trace": {"enabled": False, "run_id": None, "status": "disabled"},
    }


def test_service_refuses_start_without_token() -> None:
    with pytest.raises(ValueError, match="AGENT_SERVICE_TOKEN"):
        create_agent_service(token=None, runner=lambda _: {})


def test_service_rejects_unknown_contract_version_and_ignores_bad_trace_id() -> None:
    client = TestClient(_app())
    headers = {"Authorization": "Bearer secret"}
    assert (
        client.post(
            "/v1/investigate", headers=headers, json={"schema_version": 99, "model_id": "safe"}
        ).status_code
        == 422
    )
    response = client.post(
        "/v1/investigate",
        headers=headers,
        json={"schema_version": 2, "model_id": "safe", "trace_run_id": "not-a-uuid"},
    )
    assert response.json()["trace"] == {"enabled": False, "run_id": None, "status": "disabled"}
