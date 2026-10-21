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
        json={"model_id": "safe"},
    )
    assert response.json() == {"ok": "safe"}


def test_service_refuses_start_without_token() -> None:
    with pytest.raises(ValueError, match="AGENT_SERVICE_TOKEN"):
        create_agent_service(token=None, runner=lambda _: {})
