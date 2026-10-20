"""Tests for structured package logging."""

import json

from trader.logging import configure_logging


def test_json_log_line_includes_context(capfd) -> None:
    logger = configure_logging()

    logger.info("candidate evaluated", extra={"candidate_id": "cand-1", "account_id": "A"})
    _, stderr = capfd.readouterr()
    payload = json.loads(stderr)

    assert payload["message"] == "candidate evaluated"
    assert payload["logger"] == "trader"
    assert payload["level"] == "INFO"
    assert payload["candidate_id"] == "cand-1"
    assert payload["account_id"] == "A"
    assert payload["timestamp"].endswith("+00:00")
