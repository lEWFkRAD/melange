"""Solver rung 4 — lazy byte-level taint (Build 2).

Recording stays cheap: no taint is tracked while work happens. Only when
someone asks "where did THIS value come from?" does the system replay —
and it replays just the slice of recorded steps that fed the queried
value, with byte-level taint switched on for that replay. Each byte of a
value carries the set of (source, offset) labels it flowed from, so the
answer is exact input byte ranges, not a narrative.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

Label = tuple[str, int]  # (source name, byte offset in that source)

@dataclass
class Tainted:
    """A string whose every byte knows its origins."""
    text: str
    labels: list[frozenset[Label]] = field(default_factory=list)

    def __post_init__(self):
        if not self.labels:
            self.labels = [frozenset() for _ in self.text]

    @classmethod
    def source(cls, name: str, text: str) -> "Tainted":
        return cls(text, [frozenset({(name, i)}) for i in range(len(text))])

    @classmethod
    def clean(cls, text: str) -> "Tainted":
        return cls(text)

    def __add__(self, other: "Tainted") -> "Tainted":
        return Tainted(self.text + other.text, self.labels + other.labels)

    def slice(self, start: int, stop: int) -> "Tainted":
        return Tainted(self.text[start:stop], self.labels[start:stop])

    def origins(self) -> set[Label]:
        out: set[Label] = set()
        for s in self.labels: out |= s
        return out

    def origin_ranges(self) -> dict[str, list[tuple[int, int]]]:
        """Contiguous (start, end-exclusive) byte ranges per source."""
        per: dict[str, list[int]] = {}
        for src, off in self.origins():
            per.setdefault(src, []).append(off)
        ranges: dict[str, list[tuple[int, int]]] = {}
        for src, offs in per.items():
            offs.sort(); spans = []
            start = prev = offs[0]
            for o in offs[1:]:
                if o == prev + 1: prev = o; continue
                spans.append((start, prev + 1)); start = prev = o
            spans.append((start, prev + 1))
            ranges[src] = spans
        return ranges

@dataclass
class Step:
    """One recorded pipeline step: named inputs -> one named output."""
    name: str
    inputs: list[str]
    output: str
    fn: Callable[..., Tainted]

class SliceReplay:
    """Replays only the steps a queried value depends on, with taint on.

    `sources` maps source names to their raw text; `steps` is the full
    recorded pipeline in order. dependents_of walks the graph backward
    from the queried output; run() executes just that slice and returns
    the tainted value plus how many steps it touched.
    """
    def __init__(self, sources: dict[str, str], steps: list[Step]):
        self.sources, self.steps = sources, steps
        self._producer = {s.output: s for s in steps}

    def slice_for(self, output: str) -> list[Step]:
        needed: list[Step] = []; seen: set[str] = set()
        def visit(name: str):
            step = self._producer.get(name)
            if step is None or name in seen: return
            seen.add(name)
            for dep in step.inputs: visit(dep)
            needed.append(step)
        visit(output)
        return needed

    def run(self, output: str) -> tuple[Tainted, int, int]:
        slice_steps = self.slice_for(output)
        env: dict[str, Tainted] = {k: Tainted.source(k, v) for k, v in self.sources.items()}
        for step in slice_steps:
            env[step.output] = step.fn(*[env[i] for i in step.inputs])
        return env[output], len(slice_steps), len(self.steps)
