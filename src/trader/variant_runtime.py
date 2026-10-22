"""Outer evidence composition for paper-account variants.

This module is intentionally outside ``trader.worker``: the worker remains unaware
of Jev, news, and their credentials while the CLI opts into this bounded provider.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from trader.config import Settings
from trader.control import ControlConfig, resolve_evidence_gate
from trader.jev import JevSensor, apply_jev_fields
from trader.jev.client import JevClient
from trader.jev.sensor import JevFields
from trader.news.service import show


class _BlsReader:
    def __init__(self, storage, settings: Settings) -> None:
        self.storage, self.settings = storage, settings

    def read(self, as_of: datetime):
        return show(self.storage, self.settings.news, as_of)


class VariantEvidenceProvider:
    """Provide Account C's opt-in Jev enrichment without exposing it to B or D."""

    def __init__(self, settings: Settings, now: Callable[[], datetime] | None = None) -> None:
        self.settings, self._now, self._client, self._sensor = (
            settings,
            now or (lambda: datetime.now(UTC)),
            None,
            None,
        )

    def enrichers(self, storage, control: ControlConfig, accounts) -> dict[str, object]:
        account = accounts.get("C")
        if account is None:
            return {}
        _state, config = account
        if not resolve_evidence_gate(control, "C", config.variant).jev:
            return {}
        if self._sensor is None:
            self._client = JevClient(self.settings.jev)
            self._sensor = JevSensor(self._client, self.settings.jev, time.monotonic, storage)
        reader = _BlsReader(storage, self.settings)

        def enrich(snapshot):
            try:
                return self._sensor.sense(snapshot, reader, clock=self._now)
            except Exception:
                return apply_jev_fields(snapshot, JevFields(status="error"))

        return {"C": enrich}

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
