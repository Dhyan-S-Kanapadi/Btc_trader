"""Pure deterministic headline normalization; it never interprets or repairs instructions."""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass

_TAG_CONTENT = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]*>")
_URL = re.compile(r"(?:https?|data):[^\s<>()]+|www\.[^\s<>()]+", re.I)
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_MARKUP = re.compile(r"[`*_#>{}\[\]|]+")
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class SanitizeResult:
    text: str | None
    flags: tuple[str, ...]


def sanitize_headline(raw_title: object, cap: int = 200) -> SanitizeResult:
    """Return one plain line or None.  Fixed order is part of the input contract."""
    try:
        value = (
            raw_title.decode("utf-8", "replace") if isinstance(raw_title, bytes) else str(raw_title)
        )
        for _ in range(3):
            decoded = html.unescape(value)
            if decoded == value:
                break
            value = decoded
        value = _TAG_CONTENT.sub(" ", value)
        value = _TAG.sub(" ", value)
        value = unicodedata.normalize("NFKC", value)
        value = "".join(c for c in value if unicodedata.category(c) not in {"Cc", "Cf"})
        value = _URL.sub(" ", value)
        value = _EMAIL.sub(" ", value)
        value = _MARKUP.sub(" ", value)
        value = _SPACE.sub(" ", value).strip()
        if not value:
            return SanitizeResult(None, ("empty_after_sanitize",))
        flags: list[str] = []
        if len(value) > cap:
            cut = value[: cap - 1].rsplit(" ", 1)[0] or value[: cap - 1]
            value = cut.rstrip() + "…"
            flags.append("truncated")
        return SanitizeResult(value, tuple(flags))
    except Exception:
        return SanitizeResult(None, ("empty_after_sanitize",))
