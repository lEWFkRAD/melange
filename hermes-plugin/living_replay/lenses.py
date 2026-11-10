"""Solver rung 1 — bidirectional lenses (Build 2).

A lens is a forward `get` and a backward `put` over the same source:
get(source) -> view, put(source, view') -> source'. A well-behaved lens
obeys the round-trip laws (Foster et al.):
  GetPut: put(s, get(s)) == s            (reading then writing back is a no-op)
  PutGet: get(put(s, v)) == v            (what you wrote is what you read)
Frame edits on lens-sourced values compile to put(): the change flows
back into the exact document region the value was extracted from, and
nowhere else — the gate suite checks the byte-diff outside the region.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class Lens:
    name: str
    get: Callable[[str], Any]
    put: Callable[[str, Any], str]

    def check_laws(self, source: str, views: list[Any]) -> dict[str, bool]:
        out = {"GetPut": self.put(source, self.get(source)) == source}
        out["PutGet"] = all(self.get(self.put(source, v)) == v for v in views)
        return out

# A synthetic source document: a form-like text with labelled fields.
# The amount field lives at a precise region; extraction is a lens over it.
_AMOUNT = re.compile(r"(?P<label>Amount:[ ]*\$?)(?P<value>\d[\d,]*(?:\.\d{2})?)(?P<tail>[ ]*\r?$)", re.M)

def _amount_get(doc: str) -> float:
    m = _AMOUNT.search(doc)
    if not m: raise ValueError("no Amount field in document")
    return float(m.group("value").replace(",", ""))

def _amount_put(doc: str, value: float) -> str:
    m = _AMOUNT.search(doc)
    if not m: raise ValueError("no Amount field in document")
    text = f"{value:,.2f}" if value != int(value) else f"{int(value):,}"
    return doc[:m.start("value")] + text + doc[m.end("value"):]

AmountLens = Lens("amount", _amount_get, _amount_put)

_NAME = re.compile(r"(?P<label>Payee:[ ]*)(?P<value>[^\r\n]+?)(?P<tail>[ ]*\r?$)", re.M)

def _name_get(doc: str) -> str:
    m = _NAME.search(doc)
    if not m: raise ValueError("no Payee field in document")
    return m.group("value")

def _name_put(doc: str, value: str) -> str:
    m = _NAME.search(doc)
    if not m: raise ValueError("no Payee field in document")
    return doc[:m.start("value")] + value + doc[m.end("value"):]

PayeeLens = Lens("payee", _name_get, _name_put)

def region_span(doc: str, lens: Lens) -> tuple[int, int]:
    """Byte span a lens writes to — for the outside-region diff check."""
    pattern = {"amount": _AMOUNT, "payee": _NAME}[lens.name]
    m = pattern.search(doc)
    if not m: raise ValueError(f"lens {lens.name} does not apply")
    return m.start("value"), m.end("value")

def outside_region_identical(before: str, after: str, lens: Lens) -> bool:
    """True iff put() changed nothing outside the target region. Region
    lengths can shift (1,000 -> 999), so compare prefix and suffix."""
    start, end = region_span(before, lens)
    if after[:start] != before[:start]: return False
    suffix_before = before[end:]
    return after[len(after) - len(suffix_before):] == suffix_before if suffix_before else True

def clamp_through_lens(doc: str, lens: Lens, value: Any) -> str:
    """A frame clamp on a lens-sourced value, compiled to a put()."""
    return lens.put(doc, value)
