"""Read-only API surface tests that do not require credentials or a writer connection."""

import pytest
from fastapi.testclient import TestClient

from trader.api import create_app
from trader.config import Settings


def _settings(url: str = "postgresql+psycopg://paper_readonly:paper@localhost:1/paper") -> Settings:
    base = Settings()
    return base.model_copy(update={"database_url_readonly": url})


def test_api_refuses_missing_readonly_url(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL_READONLY", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL_READONLY"):
        create_app(Settings())


def test_api_exposes_only_get_operations_and_health_is_unavailable_without_db() -> None:
    app = create_app(_settings())
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/health").status_code == 503
    schema = client.get("/openapi.json").json()
    assert all(set(item) <= {"get"} for item in schema["paths"].values())
    for path in schema["paths"]:
        assert client.post(path).status_code in {404, 405}


def test_api_module_has_no_agent_or_market_intelligence_imports() -> None:
    imports = [
        line.lower()
        for line in open("src/trader/api.py", encoding="utf-8").read().splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not any(term in "\n".join(imports) for term in ("jev", "news", "agent", "model_client"))
