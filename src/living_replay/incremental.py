"""Dependents-only recomputation (Build 2) — the CAD-timeline ripple.

The pipeline graph is evaluated through a memoizing engine in the style
of self-adjusting computation / Salsa: dependencies are declared per
node; an edit marks only the edited input's transitive dependents as
candidates; a candidate is actually recomputed only if one of its
dependencies changed value (early cutoff — the ripple dies where the
change stops mattering). The gate measures executed nodes and wall time
against a full re-execution of the same graph, and requires identical
outputs.
"""
from __future__ import annotations
import time
from typing import Any, Callable

class Engine:
    def __init__(self):
        self.fns: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self.deps: dict[str, set[str]] = {}
        self.dependents: dict[str, set[str]] = {}
        self.inputs: list[str] = []
        self.cache: dict[str, Any] = {}
        self.executed = 0
        self.last_executed_nodes: list[str] = []

    def add_input(self, name: str, value: Any) -> "Engine":
        self.inputs.append(name); self.cache[name] = value
        self._cached_order = None; self._cached_index = None
        return self

    def add(self, name: str, fn: Callable[[dict[str, Any]], Any], deps: list[str]) -> "Engine":
        self.fns[name] = fn; self.deps[name] = set(deps)
        for d in deps: self.dependents.setdefault(d, set()).add(name)
        self._cached_order = None; self._cached_index = None
        return self

    _cached_order: list[str] | None = None
    _cached_index: dict[str, int] | None = None

    def _order(self) -> list[str]:
        if self._cached_order is not None: return self._cached_order
        order, seen = [], set()
        def visit(n: str):
            if n in seen: return
            seen.add(n)
            for d in self.deps.get(n, ()): visit(d)
            order.append(n)
        for n in list(self.fns) + list(self.inputs): visit(n)
        self._cached_order = order
        self._cached_index = {n: i for i, n in enumerate(order)}
        return order

    def _index(self) -> dict[str, int]:
        self._order()
        return self._cached_index

    def build(self) -> dict[str, Any]:
        """Full first build through the cache; counts every execution.
        Node functions receive the live value dict and must treat it as
        read-only."""
        self.executed = 0
        self.last_executed_nodes = []
        for name in self._order():
            if name in self.inputs: continue
            self.cache[name] = self.fns[name](self.cache)
            self.executed += 1
            self.last_executed_nodes.append(name)
        return dict(self.cache)

    def evaluate_all(self) -> dict[str, Any]:
        """Naive full re-execution from current input values (baseline)."""
        out = {n: self.cache[n] for n in self.inputs}
        count = 0
        for name in self._order():
            if name in self.inputs: continue
            out[name] = self.fns[name](out); count += 1
        self.last_full_executed = count
        return out

    def edit(self, name: str, value: Any) -> dict[str, Any]:
        """Change one input; recompute only true dependents, with cutoff."""
        self.executed = 0
        self.last_executed_nodes = []
        if self.cache.get(name) == value:
            return dict(self.cache)
        self.cache[name] = value
        changed = {name}
        candidates: set[str] = set()
        stack = list(self.dependents.get(name, ()))
        while stack:
            cur = stack.pop()
            if cur in candidates: continue
            candidates.add(cur); stack.extend(self.dependents.get(cur, ()))
        index = self._index()
        for node in sorted(candidates, key=index.__getitem__):
            if not (self.deps[node] & changed): continue  # early cutoff
            new = self.fns[node](self.cache)
            self.executed += 1
            self.last_executed_nodes.append(node)
            if new != self.cache.get(node):
                self.cache[node] = new; changed.add(node)
        return dict(self.cache)

def timed(fn) -> tuple[Any, float]:
    start = time.perf_counter(); out = fn(); return out, time.perf_counter() - start
