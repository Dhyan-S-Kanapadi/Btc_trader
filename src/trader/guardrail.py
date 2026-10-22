"""Pure, fail-closed validation of untrusted model verdict JSON."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import Field

from trader.config import GuardrailSettings
from trader.models import FrozenModel, Snapshot, Verdict

DENY_TERMS = {
    "stop": "execution stop control",
    "target": "execution target control",
    "size": "position sizing",
    "qty": "position sizing",
    "quantity": "position sizing",
    "notional": "position sizing",
    "leverage": "risk control",
    "risk": "risk control",
    "position": "position control",
    "limit": "risk control",
    "cap": "risk control",
    "drawdown": "risk control",
    "halt": "risk control",
    "entry": "execution control",
    "exit": "execution control",
}
INJECTION_PATTERNS = (
    r"ignore .*instructions",
    r"(system|developer|assistant)\s*:",
    r"override .*rules",
    r"(tool|function)[ _-]?call",
    r"approve anyway",
)
GUARDRAIL_VERSION = (
    "1.0.0-" + hashlib.sha256(repr((DENY_TERMS, INJECTION_PATTERNS)).encode()).hexdigest()[:8]
)


class ToolResultRecord(FrozenModel):
    tool_name: str = Field(min_length=1)
    as_of: datetime
    args: dict[str, Any]
    output: dict[str, Any]


class Violation(FrozenModel):
    code: str
    detail: str


class GuardrailResult(FrozenModel):
    accepted: bool
    verdict: Verdict
    reason_code: str
    violations: list[Violation]
    guardrail_version: str = GUARDRAIL_VERSION
    evidence_digest: str
    raw_digest: str


def verdict_json_schema() -> dict[str, Any]:
    """The three-field model-facing contract, intentionally excluding all execution controls."""

    return Verdict.model_json_schema()


def _skip(code: str, raw: object, violations: list[Violation]) -> GuardrailResult:
    digest = hashlib.sha256(repr(raw).encode("utf-8", "replace")).hexdigest()
    return GuardrailResult(
        accepted=False,
        verdict=Verdict(action="SKIP", reasons=[f"guardrail_rejected: {code}"], cited_evidence={}),
        reason_code=code,
        violations=violations or [Violation(code=code, detail=code)],
        evidence_digest=hashlib.sha256(b"{}").hexdigest(),
        raw_digest=digest,
    )


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def _index(value: Any, path: str, result: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _index(item, f"{path}.{key}", result)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _index(item, f"{path}[{index}]", result)
    else:
        result[path] = value


def check_verdict(
    raw: str | bytes | dict[str, Any],
    snapshot: Snapshot,
    tool_results: list[ToolResultRecord],
    config: GuardrailSettings,
) -> GuardrailResult:
    """Validate form and citation faithfulness only; never raises and never repairs input."""
    violations: list[Violation] = []
    try:
        if isinstance(raw, bytes):
            if len(raw) > config.max_raw_bytes:
                return _skip("raw_too_large", raw, violations)
            if raw.startswith(b"\xef\xbb\xbf"):
                return _skip("bom_rejected", raw, violations)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return _skip("invalid_utf8", raw, violations)
        elif isinstance(raw, str):
            if len(raw.encode()) > config.max_raw_bytes:
                return _skip("raw_too_large", raw, violations)
            text = raw
        elif isinstance(raw, dict):
            text = None
            parsed = raw
        else:
            return _skip("invalid_raw_type", raw, violations)
        if text is not None:
            if not text.strip():
                return _skip("empty_body", raw, violations)
            try:
                parsed = json.loads(
                    text,
                    parse_float=Decimal,
                    parse_int=Decimal,
                    object_pairs_hook=_pairs,
                    parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
                )
            except ValueError as error:
                return _skip(
                    "duplicate_key" if str(error) == "duplicate_key" else "invalid_json",
                    raw,
                    violations,
                )
        if not isinstance(parsed, dict):
            return _skip("top_level_not_object", raw, violations)
        try:
            verdict = Verdict.model_validate(parsed)
        except Exception:
            return _skip("schema_invalid", raw, violations)
        for key in _walk_keys(parsed):
            normalized = re.sub(r"[^a-z]", "", key.lower())
            if any(term in normalized for term in DENY_TERMS):
                return _skip(
                    "risk_key_rejected", raw, [Violation(code="risk_key_rejected", detail=key)]
                )
        if not verdict.reasons or len(verdict.reasons) > config.max_reasons:
            return _skip("reasons_invalid", raw, violations)
        if len(set(verdict.reasons)) != len(verdict.reasons):
            return _skip("duplicate_reason", raw, violations)
        if sum(len(item) for item in verdict.reasons) > config.max_reason_total:
            return _skip("reasons_invalid", raw, violations)
        for reason in verdict.reasons:
            normalized = unicodedata.normalize("NFKC", reason)
            if (
                len(normalized) > config.max_reason_length
                or any(unicodedata.category(c) in {"Cc", "Cf"} for c in normalized)
                or "\n" in normalized
                or re.search(r"<[^>]+>|```|https?://|\S+@\S+", normalized, re.I)
                or any(re.search(p, normalized, re.I) for p in INJECTION_PATTERNS)
            ):
                return _skip("unsafe_reason", raw, violations)
        index: dict[str, Any] = {}
        _index(snapshot.model_dump(), "snapshot", index)
        for number, record in enumerate(tool_results):
            if record.as_of != snapshot.signal_time:
                return _skip("evidence_asof_mismatch", raw, violations)
            _index(record.output, f"tool.{record.tool_name}[{number}]", index)
        citations = verdict.cited_evidence
        minimum = config.min_citations_take if verdict.action == "TAKE" else config.min_citations
        if not minimum <= len(citations) <= config.max_citations:
            return _skip("citation_count_invalid", raw, violations)
        for path, cited in citations.items():
            if path not in index:
                return _skip("citation_unknown_path", raw, violations)
            if not _matches(index[path], cited):
                return _skip("citation_mismatch", raw, violations)
        evidence = hashlib.sha256(
            json.dumps(index, default=str, sort_keys=True).encode()
        ).hexdigest()
        return GuardrailResult(
            accepted=True,
            verdict=verdict,
            reason_code="ok",
            violations=[],
            evidence_digest=evidence,
            raw_digest=hashlib.sha256(repr(raw).encode()).hexdigest(),
        )
    except Exception:
        logging.getLogger("trader.guardrail").exception(
            "guardrail internal error", extra={"alarm": "guardrail_internal_error"}
        )
        return _skip("guardrail_internal_error", raw, violations)


def _walk_keys(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_keys(item)


def _matches(actual: Any, cited: Any) -> bool:
    if actual is None or cited is None:
        return actual is None and cited is None
    if isinstance(actual, (int, float, Decimal)) and isinstance(cited, (int, float, Decimal)):
        try:
            value = Decimal(str(cited))
            source = Decimal(str(actual))
            places = max(2, -value.as_tuple().exponent)
            return source.quantize(Decimal(1).scaleb(-places)) == value
        except (InvalidOperation, ValueError):
            return False
    return type(actual) is type(cited) and actual == cited
