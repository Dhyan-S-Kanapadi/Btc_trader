"""Typed, opt-in Jev sensor. It deliberately has no trading imports."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from typing import Protocol

from pydantic import Field

from trader.config import JevSettings
from trader.models import FrozenModel, Snapshot
from trader.news.types import NewsView, SanitizedHeadline

from .breaker import CircuitBreaker
from .client import JevClient, JevError

QUESTIONS_VERSION = "jev-questions-v1"
TEMPLATE_VERSION = "jev-state-v1"


class JevFields(FrozenModel):
    event_4h: bool | None = None
    event_prob: Decimal | None = Field(default=None, ge=0, le=1)
    tone_score: Decimal | None = Field(default=None, ge=-1, le=1)
    status: str
    questions_version: str = QUESTIONS_VERSION
    input_digest: str | None = None


class NewsReader(Protocol):
    def read(self, as_of: datetime) -> NewsView: ...


class JevAuditStore(Protocol):
    def load_jev_call(self, request_key: str) -> dict[str, object] | None: ...

    def save_jev_call(self, **values: object) -> object: ...

    def jev_daily_usage(self, day: datetime) -> tuple[int, Decimal]: ...


def _template(name: str) -> str:
    return files("trader.jev.templates").joinpath(name).read_text(encoding="utf-8")


def _questions() -> dict[str, object]:
    return json.loads(_template("questions_v1.json"))


def _decimal(value: object, lo: Decimal, hi: Decimal) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("boolean is not numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("invalid numeric response") from error
    if not lo <= parsed <= hi:
        raise ValueError("out of range response")
    return parsed


def parse_jev_response(payload: bytes) -> JevFields:
    """Strictly accept the typed-answer envelope, never generated prose."""
    try:
        data = json.loads(payload)
        answers = data["answers"]
        event, tone = answers["major_event_within_4h"], answers["news_tone"]
        if not isinstance(event, dict) or not isinstance(tone, dict):
            raise ValueError("answers must be objects")
        value = event["value"]
        if not isinstance(value, bool):
            raise ValueError("event value must be boolean")
        return JevFields(
            event_4h=value,
            event_prob=_decimal(event["probability"], Decimal("0"), Decimal("1")),
            tone_score=_decimal(tone["value"], Decimal("-1"), Decimal("1")),
            status="ok",
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("invalid Jev typed response") from error


def build_state(
    items: tuple[SanitizedHeadline, ...], as_of: datetime, settings: JevSettings
) -> tuple[str, str, tuple[str, ...]]:
    """Render only already-visible bounded safe news fields deterministically."""
    lower = as_of - timedelta(hours=settings.window_hours)
    rows = [item for item in items if lower < item.available_at <= as_of and item.text]
    rows.sort(key=lambda item: (item.available_at, item.item_id))
    lines, kept = [_template("state_v1.txt").strip()], []
    for item in rows[: settings.max_headlines]:
        age = int((as_of - item.available_at).total_seconds() // 60)
        line = (
            f"id={item.item_id};age_minutes={age};flags={','.join(item.flags)};headline={item.text}"
        )
        if sum(len(part) + 1 for part in lines) + len(line) > settings.max_state_characters:
            break
        lines.append(line)
        kept.append(item.item_id)
    state = "\n".join(lines)
    digest = hashlib.sha256(
        json.dumps(
            {"template": TEMPLATE_VERSION, "ids": kept, "state": state}, sort_keys=True
        ).encode()
    ).hexdigest()
    return state, digest, tuple(kept)


def apply_jev_fields(snapshot: Snapshot, fields: JevFields) -> Snapshot:
    """Return v2 evidence; original market fields remain untouched."""
    return snapshot.model_copy(
        update={
            "schema_version": 2,
            "jev_event_4h": fields.event_4h,
            "jev_event_prob": fields.event_prob,
            "jev_tone_score": fields.tone_score,
            "jev_status": fields.status,
            "jev_questions_version": fields.questions_version,
            "jev_input_digest": fields.input_digest,
        }
    )


class JevSensor:
    def __init__(
        self,
        client: JevClient,
        settings: JevSettings,
        monotonic: Callable[[], float],
        audit_store: JevAuditStore | None = None,
    ) -> None:
        self.client, self.settings, self._monotonic = client, settings, monotonic
        self.audit_store = audit_store
        self.breaker = CircuitBreaker(
            settings.breaker_failure_threshold, settings.breaker_cooldown_seconds
        )

    def sense(
        self,
        snapshot: Snapshot,
        news_reader: NewsReader,
        *,
        config: JevSettings | None = None,
        clock: Callable[[], datetime],
    ) -> Snapshot:
        settings = config or self.settings
        if not settings.enabled or not settings.gateway_token:
            return apply_jev_fields(snapshot, JevFields(status="disabled"))
        view = news_reader.read(snapshot.signal_time)
        if not view.coverage.ok:
            return apply_jev_fields(snapshot, JevFields(status="coverage_not_ok"))
        state, digest, item_ids = build_state(view.headlines, snapshot.signal_time, settings)
        if not item_ids:
            return apply_jev_fields(snapshot, JevFields(status="no_items", input_digest=digest))
        if not self.breaker.allow(self._monotonic()):
            return apply_jev_fields(snapshot, JevFields(status="circuit_open", input_digest=digest))
        request_key = hashlib.sha256(f"{snapshot.idempotency_key}:{digest}".encode()).hexdigest()
        if self.audit_store is not None:
            cached = self.audit_store.load_jev_call(request_key)
            if cached is not None:
                return apply_jev_fields(snapshot, JevFields.model_validate(cached))
            calls, cost = self.audit_store.jev_daily_usage(clock())
            if calls >= settings.daily_call_cap or (
                settings.daily_cost_cap_usd is not None and cost >= settings.daily_cost_cap_usd
            ):
                return apply_jev_fields(
                    snapshot, JevFields(status="cap_reached", input_digest=digest)
                )
        try:
            raw = self.client.ask(state, _questions())
            fields = parse_jev_response(raw.payload).model_copy(update={"input_digest": digest})
            self._audit(
                request_key,
                snapshot,
                clock(),
                settings,
                digest,
                item_ids,
                fields,
                raw.http_status,
                raw.attempts,
                raw.latency_ms,
                None,
            )
            if self.breaker.record_success():
                logging.getLogger("trader.jev").info(
                    "jev breaker closed", extra={"event": "breaker"}
                )
            return apply_jev_fields(snapshot, fields)
        except (JevError, ValueError) as error:
            opened = self.breaker.record_failure(self._monotonic())
            if opened:
                logging.getLogger("trader.jev").warning(
                    "jev breaker open", extra={"event": "breaker"}
                )
            status = (
                "timeout"
                if str(error) == "timeout"
                else "invalid_response"
                if isinstance(error, ValueError)
                else "error"
            )
            fields = JevFields(status=status, input_digest=digest)
            self._audit(
                request_key,
                snapshot,
                clock(),
                settings,
                digest,
                item_ids,
                fields,
                None,
                0,
                None,
                str(error),
            )
            return apply_jev_fields(snapshot, fields)

    def _audit(
        self,
        request_key: str,
        snapshot: Snapshot,
        now: datetime,
        settings: JevSettings,
        digest: str,
        item_ids: tuple[str, ...],
        fields: JevFields,
        http_status: int | None,
        attempts: int,
        latency_ms: int | None,
        error_code: str | None,
    ) -> None:
        if self.audit_store is None:
            return
        estimate = (
            Decimal(len(item_ids) * 20)
            * (settings.price_per_million_input_usd or Decimal("0"))
            / Decimal("1000000")
        )
        self.audit_store.save_jev_call(
            request_key=request_key,
            candidate_idempotency_key=snapshot.idempotency_key,
            as_of=snapshot.signal_time,
            window_hours=settings.window_hours,
            questions_version=QUESTIONS_VERSION,
            template_version=TEMPLATE_VERSION,
            input_digest=digest,
            item_ids=list(item_ids),
            status=fields.status,
            error_code=error_code,
            http_status=http_status,
            attempts=attempts,
            latency_ms=latency_ms,
            answers=fields.model_dump(mode="json") if fields.status == "ok" else None,
            model=settings.model,
            cost_usd=estimate,
            cost_estimated=True,
            price_table_version="jev-input-0.04-per-million-2026-10-22",
            synthetic=False,
        )
