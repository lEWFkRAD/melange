"""Solver rung 2 — SMT goal seek over a pipeline graph (Build 2).

The pipeline is a small arithmetic dependency graph: input nodes hold
values, derived nodes hold formulas (including conditionals for
thresholds and phase-outs — the discrete structure spreadsheets hide).
An explain edit ("this output should have been X") becomes a solver
problem: find an assignment to the INPUTS that makes the output X,
minimising first the number of changed inputs, then the total change.
Every candidate assignment is forward-verified through the graph before
it is accepted — the solver proposes, execution disposes.

Nodes are built with helpers (lin, if_) that carry both a numeric
formula and a symbolic Z3 mirror, so the seek is exact, not sampled.
Z3 is an optional dependency (the `solver` extra).
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable

@dataclass
class _Node:
    fn: Callable[[dict[str, float]], float]
    sym: Callable[[dict[str, Any]], Any] | None
    value: float = 0.0

class SGraph:
    def __init__(self):
        self.nodes: dict[str, _Node] = {}
        self._inputs: list[str] = []

    def add_input(self, name: str, value: float) -> "SGraph":
        self.nodes[name] = _Node(lambda v, n=name: v[n], None, value)
        self._inputs.append(name)
        return self

    def add(self, name: str, pair) -> "SGraph":
        fn, sym = pair
        self.nodes[name] = _Node(fn, sym)
        return self

    def input_names(self) -> list[str]:
        return list(self._inputs)

    def evaluate(self, overrides: dict[str, float] | None = None) -> dict[str, float]:
        values = {n: self.nodes[n].value for n in self._inputs}
        if overrides: values.update(overrides)
        pending = {n: s for n, s in self.nodes.items() if n not in self._inputs}
        while pending:
            progressed = False
            for name in list(pending):
                try: values[name] = pending[name].fn(values)
                except KeyError: continue
                del pending[name]; progressed = True
            if not progressed: raise ValueError(f"unresolvable at {sorted(pending)}")
        return values

    def symbolic(self) -> dict[str, Any]:
        import z3
        sym: dict[str, Any] = {n: z3.Real(n) for n in self._inputs}
        pending = {n: s for n, s in self.nodes.items() if n not in self._inputs}
        while pending:
            progressed = False
            for name in list(pending):
                if pending[name].sym is None:
                    raise ValueError(f"node {name} has no symbolic mirror")
                try: sym[name] = pending[name].sym(sym)
                except KeyError: continue
                del pending[name]; progressed = True
            if not progressed: raise ValueError(f"unresolvable at {sorted(pending)}")
        return sym

def lin(coeffs: dict[str, float], const: float = 0.0):
    """fn/sym pair for a linear combination of other nodes."""
    def fn(v): return sum(c * v[k] for k, c in coeffs.items()) + const
    def sym(v):
        import z3
        out = z3.RealVal(const)
        for k, c in coeffs.items(): out = out + c * v[k]
        return out
    return fn, sym

def prod(coeff: float, key: str):
    return lin({key: coeff})

def if_(cond_fn, cond_sym, then_pair, else_pair):
    """fn/sym pair for a conditional (thresholds, phase-outs, brackets)."""
    def fn(v): return then_pair[0](v) if cond_fn(v) else else_pair[0](v)
    def sym(v):
        import z3
        return z3.If(cond_sym(v), then_pair[1](v), else_pair[1](v))
    return fn, sym

@dataclass
class Solution:
    assignment: dict[str, float]     # only the inputs that change
    changed: int
    total_delta: float
    verified: bool

def solve(graph: SGraph, target: str, goal: float, *, timeout_ms: int = 10000) -> Solution | None:
    """Minimal-change assignment making target == goal, forward-verified.
    Returns None when the goal is unsatisfiable — reported, never forced."""
    import z3
    base = graph.evaluate()
    sym = graph.symbolic()
    opt = z3.Optimize(); opt.set(timeout=timeout_ms)
    opt.add(sym[target] == goal)
    flags = {}
    for n in graph.input_names():
        flag = z3.Bool(f"chg_{n}"); flags[n] = flag
        opt.add(flag == (sym[n] != base[n]))
    opt.minimize(z3.Sum([z3.If(f, 1, 0) for f in flags.values()]))
    deltas = {}
    for n in graph.input_names():
        d = z3.Real(f"delta_{n}"); deltas[n] = d
        opt.add(d >= sym[n] - base[n]); opt.add(d >= base[n] - sym[n])
    opt.minimize(z3.Sum(list(deltas.values())))
    if opt.check() != z3.sat:
        return None
    model = opt.model()
    assignment = {}
    for n in graph.input_names():
        val = model[sym[n]]
        f = float(val.as_fraction())
        if abs(f - base[n]) > 1e-9: assignment[n] = round(f, 6)
    if abs(graph.evaluate(assignment)[target] - goal) > 1e-6:
        return None  # solver proposed, forward execution disposed
    return Solution(assignment, len(assignment),
                    sum(abs(v - base[k]) for k, v in assignment.items()), True)
