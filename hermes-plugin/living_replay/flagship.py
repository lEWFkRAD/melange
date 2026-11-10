"""The flagship demo (Build 3): one synthetic return, end to end, on
one timeline — intake document -> lens extraction -> Fact Graph ->
terminal session -> an explain edit that forks a ghost branch, rewrites
the intake through the lens, recomputes only dependents, and lands the
amended figure, with the parent branch byte-identical throughout.

Every figure is synthetic. Wages 52,000 -> total tax 3,568 (after the
200 phase-out credit and a 500 child credit); correcting wages to
48,000 -> total tax 3,088.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Any

from .capture import PtyCapture
from .factgraph import FactGraph
from .forking import restore_workspace, snapshot_workspace
from .incremental import Engine
from .lenses import Lens
from .replay import reconstruct
from .store import TimelineStore

INTAKE = (
    "INTAKE SUMMARY — SYNTHETIC\n"
    "Payee: Dana Ruiz\n"
    "W-2 wages (box 1): $52,000\n"
    "Federal withholding: $6,100\n"
    "State wages: $52,000\n"
    "State withholding: $900\n"
    "Dependents: 1\n"
    "Filing status: single\n"
)

_WAGES = re.compile(r"(?P<label>W-2 wages \(box 1\):[ ]*\$?)(?P<value>[\d,]+)")
_WITHHOLDING = re.compile(r"(?P<label>Federal withholding:[ ]*\$?)(?P<value>[\d,]+)")

def _num(m) -> float: return float(m.group("value").replace(",", ""))
def _fmt(v: float) -> str: return f"{int(v):,}" if v == int(v) else f"{v:,.2f}"
def _put(pattern):
    def put(doc: str, value: float) -> str:
        m = pattern.search(doc)
        if not m: raise ValueError("field not found")
        return doc[:m.start("value")] + _fmt(value) + doc[m.end("value"):]
    return put
def _get(pattern):
    def get(doc: str) -> float:
        m = pattern.search(doc)
        if not m: raise ValueError("field not found")
        return _num(m)
    return get

WagesLens = Lens("wages", _get(_WAGES), _put(_WAGES))
WithholdingLens = Lens("withholding", _get(_WITHHOLDING), _put(_WITHHOLDING))

def build_fact_graph(intake_text: str) -> FactGraph:
    """Facts for the synthetic return, with intake provenance spans."""
    g = FactGraph()
    for path, pattern in (("/wages", _WAGES), ("/withholding", _WITHHOLDING)):
        m = pattern.search(intake_text)
        g.set_intake(path, _num(m), "intake.txt", (m.start("value"), m.end("value")))
    g.set_fact("/otherIncome", 0)
    g.set_fact("/standardDeduction", 14600)
    # Parallel sections that do NOT depend on federal wages: a state
    # section driven by its own intake facts, and a child credit driven
    # by the dependents count. They are what makes a wages edit a
    # minority ripple instead of a whole-graph recompute.
    g.set_intake("/stateWages", 52000, "intake.txt", (0, 0))
    g.set_intake("/stateWithholding", 900, "intake.txt", (0, 0))
    g.set_intake("/dependents", 1, "intake.txt", (0, 0))
    g.derive("/agi", lambda v: v["/wages"] + v["/otherIncome"], ["/wages", "/otherIncome"])
    g.derive("/taxableIncome", lambda v: max(0, v["/agi"] - v["/standardDeduction"]),
             ["/agi", "/standardDeduction"])
    g.derive("/taxBeforeCredits",
             lambda v: 0.10 * v["/taxableIncome"] if v["/taxableIncome"] <= 11000
             else 1100 + 0.12 * (v["/taxableIncome"] - 11000), ["/taxableIncome"])
    g.derive("/credit", lambda v: 0 if v["/agi"] > 75000 else 200, ["/agi"])
    g.derive("/childCredit", lambda v: 500 * v["/dependents"], ["/dependents"])
    g.derive("/totalTax", lambda v: max(0, v["/taxBeforeCredits"] - v["/credit"] - v["/childCredit"]),
             ["/taxBeforeCredits", "/credit", "/childCredit"])
    g.derive("/refund", lambda v: v["/withholding"] - v["/totalTax"], ["/withholding", "/totalTax"])
    g.derive("/stateTaxable", lambda v: max(0, v["/stateWages"] - 2000), ["/stateWages"])
    g.derive("/stateTax", lambda v: round(0.03 * v["/stateTaxable"], 2), ["/stateTaxable"])
    g.derive("/stateRefund", lambda v: v["/stateWithholding"] - v["/stateTax"], ["/stateWithholding", "/stateTax"])
    return g

def expected_figures(wages: float, withholding: float = 6100) -> dict[str, float]:
    """Independent recomputation of the same return (no shared code path
    with the Fact Graph formulas beyond the published rules)."""
    agi = wages + 0
    taxable = max(0, agi - 14600)
    tax = 0.10 * taxable if taxable <= 11000 else 1100 + 0.12 * (taxable - 11000)
    credit = 0 if agi > 75000 else 200
    total = max(0, tax - credit - 500)
    state_tax = round(0.03 * max(0, 52000 - 2000), 2)
    return {"/agi": agi, "/taxableIncome": taxable, "/taxBeforeCredits": tax,
            "/credit": credit, "/childCredit": 500, "/totalTax": total,
            "/refund": withholding - total, "/stateTaxable": 50000,
            "/stateTax": state_tax, "/stateRefund": 900 - state_tax}

DERIVED_ORDER = ["/agi", "/taxableIncome", "/taxBeforeCredits", "/credit", "/childCredit", "/totalTax", "/refund", "/stateTaxable", "/stateTax", "/stateRefund"]

def _engine_from_graph(g: FactGraph, inputs: dict[str, float]) -> Engine:
    e = Engine()
    for name, value in inputs.items(): e.add_input(name, value)
    e.add("/agi", lambda v: v["/wages"] + v["/otherIncome"], ["/wages", "/otherIncome"])
    e.add("/taxableIncome", lambda v: max(0, v["/agi"] - v["/standardDeduction"]), ["/agi", "/standardDeduction"])
    e.add("/taxBeforeCredits",
          lambda v: 0.10 * v["/taxableIncome"] if v["/taxableIncome"] <= 11000
          else 1100 + 0.12 * (v["/taxableIncome"] - 11000), ["/taxableIncome"])
    e.add("/credit", lambda v: 0 if v["/agi"] > 75000 else 200, ["/agi"])
    e.add("/childCredit", lambda v: 500 * v["/dependents"], ["/dependents"])
    e.add("/totalTax", lambda v: max(0, v["/taxBeforeCredits"] - v["/credit"] - v["/childCredit"]), ["/taxBeforeCredits", "/credit", "/childCredit"])
    e.add("/refund", lambda v: v["/withholding"] - v["/totalTax"], ["/withholding", "/totalTax"])
    e.add("/stateTaxable", lambda v: max(0, v["/stateWages"] - 2000), ["/stateWages"])
    e.add("/stateTax", lambda v: round(0.03 * v["/stateTaxable"], 2), ["/stateTaxable"])
    e.add("/stateRefund", lambda v: v["/stateWithholding"] - v["/stateTax"], ["/stateWithholding", "/stateTax"])
    return e

def run_flagship(root: Path, *, corrected_wages: float = 48000) -> dict[str, Any]:
    """Run the whole demo against a fresh timeline at `root`; return the
    measured facts the gates assert on."""
    root.mkdir(parents=True, exist_ok=True)
    ws = root / "workspace"; ws.mkdir()
    (ws / "intake.txt").write_text(INTAKE)
    store = TimelineStore(root / "timeline")
    cap = PtyCapture(store, rows=12, cols=60)

    # Session: read the intake, compute through the Fact Graph, print it.
    read = store.append("main", "tool_call",
                        {"name": "read-intake", "input": "intake.txt", "output": INTAKE})
    cap.record_bytes(b"intake read: Dana Ruiz\r\n", read)
    snap = snapshot_workspace(store, "main", ws)
    checkpoint = store.events("main")[-1]["id"]
    g = build_fact_graph(INTAKE)
    figures = {p: g.evaluate(p) for p in DERIVED_ORDER}
    store.append("main", "model_call",
                 {"prompt": "compute return from Fact Graph", "figures": figures, "replayed": True})
    print_tool = store.append("main", "tool_call",
                              {"name": "print-return", "input": "return",
                               "output": f"totalTax={figures['/totalTax']:.0f} refund={figures['/refund']:.0f}"})
    cap.record_bytes(f"AGI {figures['/agi']:,.0f}  TAX {figures['/totalTax']:,.0f}  REFUND {figures['/refund']:,.0f}\r\n".encode(), print_tool)
    parent_events_before = store.events("main")
    parent_screen_before = reconstruct(store, "main", rows=12, cols=60).screen()

    # Explain edit: the W-2 was wrong. Fork a ghost branch, rewrite the
    # intake through the lens, recompute only dependents.
    fork_event = store.fork("main", checkpoint, "ghost-corrected-w2")
    store.append("ghost-corrected-w2", "context_note",
                 {"text": f"explain: corrected W-2 received, wages={corrected_wages:.0f}", "pinned": True},
                 parent_event=fork_event)
    ghost_ws = restore_workspace(store, snap, root / "workspace-ghost")
    amended_text = WagesLens.put((ghost_ws / "intake.txt").read_text(), corrected_wages)
    (ghost_ws / "intake.txt").write_text(amended_text)
    inputs = {"/wages": WagesLens.get(INTAKE), "/withholding": WithholdingLens.get(INTAKE),
              "/otherIncome": 0, "/standardDeduction": 14600,
              "/stateWages": 52000, "/stateWithholding": 900, "/dependents": 1}
    engine = _engine_from_graph(g, inputs)
    engine.build(); full_nodes = engine.executed
    graph_nodes = len(engine.inputs) + len(engine.fns)
    amended = engine.edit("/wages", corrected_wages)
    recomputed = engine.executed
    amended_figures = {p: amended[p] for p in DERIVED_ORDER}
    gcap = PtyCapture(store, "ghost-corrected-w2", rows=12, cols=60)
    tool = store.append("ghost-corrected-w2", "tool_call",
                        {"name": "print-amended-return", "input": "return",
                         "output": f"totalTax={amended_figures['/totalTax']:.0f}"})
    gcap.record_bytes(f"AMENDED  TAX {amended_figures['/totalTax']:,.0f}  REFUND {amended_figures['/refund']:,.0f}\r\n".encode(), tool)

    return {
        "figures": figures, "expected": expected_figures(WagesLens.get(INTAKE)),
        "amended_figures": amended_figures,
        "amended_expected": expected_figures(corrected_wages),
        "provenance_total_tax": g.provenance("/totalTax"),
        "intake_span_text": INTAKE[g.facts["/wages"].span[0]:g.facts["/wages"].span[1]],
        "parent_unchanged": store.events("main") == parent_events_before
                            and reconstruct(store, "main", rows=12, cols=60).screen() == parent_screen_before,
        "full_nodes": full_nodes, "recomputed_nodes": recomputed, "graph_nodes": graph_nodes,
        "ghost_screen": reconstruct(store, "ghost-corrected-w2", rows=12, cols=60).screen(),
        "amended_intake": amended_text, "original_intake": INTAKE,
        "store": store, "checkpoint": checkpoint,
    }
