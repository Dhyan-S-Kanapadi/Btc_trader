"""Pure deterministic guardrail for untrusted, already-sanitized titles."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from trader.guardrail import INJECTION_PATTERNS

# Data tables deliberately share #19's public injection patterns rather than copying them.
HARD_RULES: tuple[tuple[str, str], ...] = (
    ("ai_instruction", r"\b(ignore|override|disregard)\b.{0,40}\b(instruction|system|rule)"),
    ("role_marker", r"\b(system|developer|assistant|user)\s*:"),
    ("tool_syntax", r"\b(tool|function)[ _-]?(call|invoke)\b|<tool"),
    ("embedded_code", r"\{\s*[\"']?(role|tool|function)[\"']?\s*:|```"),
    ("forced_binary", r"\b(answer|output|respond)\s+(yes|no)\b"),
)
SOFT_RULES: tuple[tuple[str, str], ...] = (
    ("padding", r"(.)\1{11,}"),
    ("nonletter_heavy", r"^(?:[^A-Za-z]{1,2}[A-Za-z]){0,3}[^A-Za-z]{12,}$"),
)
GUARDRAIL_VERSION = (
    "news-1-"
    + hashlib.sha256(repr((INJECTION_PATTERNS, HARD_RULES, SOFT_RULES)).encode()).hexdigest()[:12]
)


@dataclass(frozen=True)
class InputGuardrailResult:
    status: str
    flags: tuple[str, ...]
    guardrail_version: str = GUARDRAIL_VERSION


def check_headline(sanitized: str, source: str) -> InputGuardrailResult:
    """Classify only; this function never edits text and never raises."""
    try:
        flags = [
            f"shared_{i}"
            for i, pattern in enumerate(INJECTION_PATTERNS)
            if re.search(pattern, sanitized, re.I)
        ]
        flags += [code for code, pattern in HARD_RULES if re.search(pattern, sanitized, re.I)]
        if flags:
            return InputGuardrailResult("quarantined", tuple(sorted(set(flags))))
        soft = [code for code, pattern in SOFT_RULES if re.search(pattern, sanitized, re.I)]
        return InputGuardrailResult("flagged" if soft else "clean", tuple(soft))
    except Exception:
        return InputGuardrailResult("quarantined", ("guardrail_error",))
