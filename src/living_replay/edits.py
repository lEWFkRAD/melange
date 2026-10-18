"""Build-1 scripted solver: clamps, pins, and CEGIS-style explain candidates."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable

@dataclass
class ExplainResult:
    branch: str | None
    counterexamples: list[str]

def apply_clamp(values: dict[str, object], target: str, value: object, derive: Callable[[dict], dict]) -> dict:
    """Cut target's incoming edge by overlaying its requested frame value."""
    out = derive(dict(values)); out[target] = value
    return derive({**values, **{target: value}, "__clamps__": {target: value}})

def check_pins(values: dict[str, object], pins: dict[str, object]) -> list[str]:
    return [name for name, expected in pins.items() if values.get(name) != expected]

def explain(candidates: list[tuple[str, dict]], target: str, expected: object, derive: Callable[[dict], dict], fork: Callable[[str,dict], str]) -> ExplainResult:
    failures=[]
    for name, proposal in candidates:
        observed=derive(proposal).get(target)
        if observed == expected: return ExplainResult(fork(name,proposal),failures)
        failures.append(f"{name}: forward result {observed!r}, expected {expected!r}")
    return ExplainResult(None,failures)
