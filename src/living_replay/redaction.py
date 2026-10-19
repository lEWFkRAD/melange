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
    return redact_text(value.decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape")


_LAST_TOKEN = re.compile(r"\S+\s*$")
_ASSIGNMENT_PREFIX = re.compile(r"\b(?:token|api[_-]?key|password)\s*(?:[=:]\s*)?$", re.I)


def split_redaction_buffer(value: bytes, *, final: bool = False) -> tuple[bytes, bytes]:
    """Retain a possible credential suffix, rather than a fixed byte tail.

    Assignment values have no maximum length. The released prefix still
    needs redact_bytes before persistence. Hold the last token and any
    preceding credential assignment until another token or EOF arrives.
    """
    if final:
        return value, b""
    text = value.decode("utf-8", "surrogateescape")
    last = _LAST_TOKEN.search(text)
    cut = last.start() if last else len(text)
    assignment = _ASSIGNMENT_PREFIX.search(text[:cut])
    if assignment:
        cut = assignment.start()
    boundary = len(text[:cut].encode("utf-8", "surrogateescape"))
    return value[:boundary], value[boundary:]

def contains_seeded_secret(value: bytes | str) -> bool:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
    return any(p.search(text) for p in PATTERNS)
