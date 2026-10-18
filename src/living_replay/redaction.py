"""Capture-side redaction.  Nothing is handed to the store before this runs."""
from __future__ import annotations
import re

PATTERNS = (
    re.compile(r"\b(?:sk|pk)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:token|api[_-]?key|password)\s*[=:]\s*[^\s]+", re.I),
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
)

def redact_text(value: str) -> str:
    for pattern in PATTERNS:
        value = pattern.sub("[REDACTED]", value)
    return value

def redact_bytes(value: bytes) -> bytes:
    # Terminal text is decoded losslessly enough for UTF-8 fixtures; undecodable
    # bytes remain representable and cannot turn a known secret into stored text.
    return redact_text(value.decode("utf-8", "replace")).encode("utf-8")

def contains_seeded_secret(value: bytes | str) -> bool:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return any(p.search(text) for p in PATTERNS)
