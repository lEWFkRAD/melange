"""Fact Graph (Build 3 flagship): facts at paths, derived by formulas.

In the style of the IRS Fact Graph: every value in the return is a fact
at a path (/wages, /agi, /totalTax). Intake facts are set directly and
remember where they came from (a source document and the byte span the
lens extracted them from). Derived facts are formulas over other facts.
Evaluating a fact yields its value AND its provenance: the set of intake
facts — with byte spans — the value ultimately rests on. That walk,
from a headline figure down to exact document bytes, is the layer-3
provenance showcase.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class Fact:
    path: str
    value: Any = None
    formula: Callable[[dict[str, Any]], Any] | None = None
    inputs: list[str] = field(default_factory=list)
    source: str | None = None      # intake facts: source document name
    span: tuple[int, int] | None = None  # intake facts: byte span in source

class FactGraph:
    def __init__(self):
        self.facts: dict[str, Fact] = {}

    def set_intake(self, path: str, value: Any, source: str, span: tuple[int, int]) -> "FactGraph":
        self.facts[path] = Fact(path, value=value, source=source, span=span)
        return self

    def set_fact(self, path: str, value: Any) -> "FactGraph":
        self.facts[path] = Fact(path, value=value)
        return self

    def derive(self, path: str, formula: Callable[[dict[str, Any]], Any], inputs: list[str]) -> "FactGraph":
        self.facts[path] = Fact(path, formula=formula, inputs=inputs)
        return self

    def evaluate(self, path: str, _stack: frozenset[str] = frozenset()) -> Any:
        fact = self.facts[path]
        if fact.formula is None: return fact.value
        if path in _stack: raise ValueError(f"fact cycle at {path}")
        _stack = _stack | {path}
        values = {p: self.evaluate(p, _stack) for p in fact.inputs}
        return fact.formula(values)

    def evaluate_all(self) -> dict[str, Any]:
        return {p: self.evaluate(p) for p in self.facts}

    def provenance(self, path: str) -> dict[str, dict[str, Any]]:
        """Intake provenance of a fact: {intake_path: {source, span, value}}
        for every intake fact the value transitively rests on."""
        out: dict[str, dict[str, Any]] = {}
        def visit(p: str):
            fact = self.facts[p]
            if fact.formula is None:
                if fact.source is not None:
                    out[p] = {"source": fact.source, "span": fact.span, "value": fact.value}
                return
            for dep in fact.inputs: visit(dep)
        visit(path)
        return out

    def dependents_of(self, path: str) -> set[str]:
        """All derived facts that (transitively) read the given fact."""
        out: set[str] = set()
        frontier = {path}
        while frontier:
            nxt = {p for p, f in self.facts.items()
                   if f.formula is not None and (set(f.inputs) & frontier) and p not in out}
            out |= nxt; frontier = nxt
        return out
