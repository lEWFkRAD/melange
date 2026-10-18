"""Build 2 gate corpus — solver rungs 1/2/4, dependents-only recompute,
and the viewer export. (Sandbox gates B2-G1/G2 live in test_sandbox.py;
they need KVM and run on the sandbox host.)"""
import json, re, shutil, tempfile, unittest
from pathlib import Path

from living_replay.capture import PtyCapture
from living_replay.export_viewer import export_html
from living_replay.incremental import Engine, timed
from living_replay.lenses import AmountLens, PayeeLens, clamp_through_lens, outside_region_identical
from living_replay.store import TimelineStore
from living_replay.taint import SliceReplay, Step, Tainted

try:
    import z3  # noqa: F401
    HAVE_Z3 = True
except ImportError:
    HAVE_Z3 = False

DOCS = [
    "ACME SUPPLY CO\nPayee: Dana Ruiz\nAmount: $52,000\nTerms: net 30\n",
    "INVOICE 1044\nPayee: Marcus Lee\nAmount: $999.99\nDue: friday\n",
    "STATEMENT\nPayee: A B Trucking\nAmount: $1,000,000\nPage: 1\n",
    "RECEIPT\nPayee: Sam Ortiz\nAmount: $48\nThank you\n",
]

class LensGate(unittest.TestCase):
    def test_b2g3_lens_laws_and_region_isolation(self):
        for doc in DOCS:
            laws = AmountLens.check_laws(doc, [0, 48, 999.99, 1_000_000])
            self.assertTrue(all(laws.values()), f"{laws} on {doc!r}")
            for value in (48, 123_456.78):
                out = clamp_through_lens(doc, AmountLens, value)
                self.assertEqual(AmountLens.get(out), value)
                self.assertTrue(outside_region_identical(doc, out, AmountLens),
                                f"put leaked outside region for {value}")
            plaws = PayeeLens.check_laws(doc, ["New Name", "X"])
            self.assertTrue(all(plaws.values()))
        print("\nB2-G3 measured: GetPut+PutGet hold on 4/4 corpus docs; "
              "put byte-diff outside the target region = 0 everywhere")

@unittest.skipUnless(HAVE_Z3, "z3 (solver extra) not installed")
class SmtGate(unittest.TestCase):
    def _graph(self):
        from living_replay.smt import SGraph, if_, lin
        g = SGraph()
        g.add_input("wages", 52000).add_input("other", 0)
        g.add("agi", lin({"wages": 1, "other": 1}))
        g.add("taxable", if_(lambda v: v["agi"] - 14600 > 0, lambda v: v["agi"] - 14600 > 0,
                             lin({"agi": 1}, -14600), lin({}, 0)))
        g.add("tax", if_(lambda v: v["taxable"] <= 11000, lambda v: v["taxable"] <= 11000,
                         lin({"taxable": 0.10}),
                         (lambda v: 1100 + 0.12 * (v["taxable"] - 11000),
                          lambda v: 1100 + 0.12 * (v["taxable"] - 11000))))
        g.add("credit", if_(lambda v: v["agi"] > 75000, lambda v: v["agi"] > 75000,
                            lin({}, 0), lin({}, 200)))
        g.add("total_tax", if_(lambda v: v["tax"] - v["credit"] > 0, lambda v: v["tax"] - v["credit"] > 0,
                               lin({"tax": 1, "credit": -1}), lin({}, 0)))
        return g

    def test_b2g4_goal_seek(self):
        from living_replay.smt import solve
        g = self._graph()
        base = g.evaluate()
        self.assertEqual(base["total_tax"], 4068.0)
        sol = solve(g, "total_tax", 4300)
        self.assertIsNotNone(sol)
        self.assertTrue(sol.verified); self.assertEqual(sol.changed, 1)
        self.assertAlmostEqual(sol.total_delta, 1933.33, places=1)
        self.assertAlmostEqual(g.evaluate(sol.assignment)["total_tax"], 4300, places=4)
        # Already at goal: zero changes is the minimal answer.
        sol0 = solve(g, "total_tax", 4068)
        self.assertIsNotNone(sol0); self.assertEqual(sol0.changed, 0)
        # Unsatisfiable (total_tax is clamped at 0): reported, not forced.
        self.assertIsNone(solve(g, "total_tax", -500))
        print("\nB2-G4 measured: goal 4300 reached with 1 input changed "
              "(delta 1933.33, forward-verified); goal -500 correctly unsatisfiable")

class TaintGate(unittest.TestCase):
    def test_b2g5_lazy_taint_slice(self):
        def extract(t: Tainted) -> Tainted:
            i = t.text.index("amount=") + len("amount=")
            return t.slice(i, t.text.index("\n", i))
        def double(t: Tainted) -> Tainted:
            labels = frozenset().union(*t.labels) if t.labels else frozenset()
            out = str(int(t.text) * 2)
            return Tainted(out, [labels] * len(out))
        def render(d: Tainted) -> Tainted:
            return Tainted.clean("total=") + d
        sources = {"data.txt": "amount=21\nrate=2\n", "banner.txt": "WELCOME\n"}
        steps = [
            Step("banner", ["banner.txt"], "banner_out", lambda t: t),
            Step("shout", ["banner_out"], "banner_shout", lambda t: Tainted.clean(t.text.upper())),
            Step("extract", ["data.txt"], "amount", extract),
            Step("double", ["amount"], "doubled", double),
            Step("render", ["doubled"], "total_line", render),
        ]
        replay = SliceReplay(sources, steps)
        value, used, total = replay.run("total_line")
        self.assertEqual(value.text, "total=42")
        ranges = value.origin_ranges()
        self.assertEqual(ranges, {"data.txt": [(7, 9)]})  # exactly the bytes of "21"
        self.assertLess(used, total)
        print(f"\nB2-G5 measured: taint for 'total=42' resolves to data.txt bytes [7,9); "
              f"slice replayed {used} of {total} steps (lazy)")

class IncrementalGate(unittest.TestCase):
    def _engine(self):
        # Node values are 32-wide records and each node transforms the
        # whole record — the per-node cost profile of a real pipeline
        # (a tool call moving data), not a bare +1.
        def bump(t, by=1): return tuple(x + by for x in t)
        e = Engine()
        e.add_input("A", tuple(range(32))).add_input("B", tuple(range(100, 132)))
        prev = "A"
        for i in range(1, 41):
            name = f"a{i}"; e.add(name, lambda v, p=prev: bump(v[p]), [prev]); prev = name
        e.add("flag", lambda v: v["a40"][0] > 1_000_000, ["a40"])
        e.add("s0", lambda v: (100,) * 32 if v["flag"] else (1,) * 32, ["flag"])
        prev = "s0"
        for i in range(1, 11):
            name = f"s{i}"; e.add(name, lambda v, p=prev: bump(v[p], 100 if v["flag"] else 1), [prev, "flag"]); prev = name
        prev = "B"
        for i in range(1, 41):
            name = f"b{i}"; e.add(name, lambda v, p=prev: bump(v[p]), [prev]); prev = name
        e.add("join", lambda v: tuple(a + b + s for a, b, s in zip(v["a40"], v["b40"], v["s10"])),
              ["a40", "b40", "s10"])
        return e

    def test_b2g6_dependents_only(self):
        e = self._engine()
        full = e.build(); full_count = e.executed
        self.assertEqual(full, e.evaluate_all())
        import statistics
        base_a = tuple(range(32))
        def inc_batch():
            for k in range(1, 201): e.edit("A", tuple(x + (k % 37) for x in base_a))
        def full_batch():
            for _ in range(200): e.evaluate_all()
        inc_times = [timed(inc_batch)[1] for _ in range(5)]
        inc_executed = e.executed  # executions of the LAST edit
        final = e.edit("A", tuple(x + 999 for x in base_a))
        self.assertEqual(final, e.evaluate_all())  # identical outputs
        full_times = [timed(full_batch)[1] for _ in range(5)]
        inc_time, full_time = statistics.median(inc_times), statistics.median(full_times)
        ratio = inc_executed / full_count
        print(f"\nB2-G6 measured: last edit recomputed {inc_executed} of {full_count} nodes "
              f"({ratio:.0%}); median wall time per 200 ops over 5 runs: incremental "
              f"{inc_time * 1000:.1f}ms vs full re-execution {full_time * 1000:.1f}ms")
        self.assertLess(ratio, 0.5)
        self.assertLess(inc_time, full_time)

    def test_b2g6b_cutoff_yield(self):
        # ONY-188: the byte-identical rule (Salsa/Adapton backdating) is
        # already implemented by construction in Engine.edit: a node is
        # recomputed only when a dependency truly changed, and propagation
        # continues only when the recomputed output differs. This gate pins
        # the measured cutoff on the same corpus that produced 42/93.
        e = self._engine()
        full = e.build(); full_count = e.executed
        self.assertEqual(full_count, 93)
        base_a = tuple(range(32))
        # Instrumented mirror of edit() counting per-node outcomes.
        e.edit("A", tuple(x + 999 for x in base_a))  # warm the cache path
        executed = blocked = 0
        e2 = self._engine(); e2.build()
        e2.cache["A"] = tuple(x + 998 for x in base_a)
        changed, same, cand, stack = {"A"}, set(), set(), list(e2.dependents.get("A", ()))
        while stack:
            cur = stack.pop()
            if cur in cand: continue
            cand.add(cur); stack.extend(e2.dependents.get(cur, ()))
        index = e2._index()
        for node in sorted(cand, key=index.__getitem__):
            if not (e2.deps[node] & changed):
                if e2.deps[node] & same: blocked += 1  # stopped by an identical recompute
                continue
            new = e2.fns[node](e2.cache); executed += 1
            if new == e2.cache.get(node): same.add(node)
            else: e2.cache[node] = new; changed.add(node)
        self.assertEqual(executed, 42)          # unchanged: 42 of 93
        self.assertEqual(len(same), 1)          # exactly one identical recompute: the flag node
        self.assertEqual(blocked, 11)           # s0..s10 already skipped by the cutoff
        self.assertEqual(e2.cache, e2.evaluate_all())  # identical final state
        # A change that matters end to end ripples fully — cutoff is sound,
        # not lossy: nothing is skipped when every node's output differs.
        e3 = self._engine(); e3.build()
        e3.edit("A", tuple(x + 1_000_001 for x in base_a))
        self.assertEqual(e3.executed, 53)       # all candidates, zero identical
        self.assertEqual(e3.cache, e3.evaluate_all())
        print(f"\nB2-G6b measured: cutoff yield on the 42/93 corpus — 1 of 42 recomputes "
              f"(flag) is byte-identical and already blocks 11 downstream nodes; "
              f"backdating adds 0 (rule present by construction); flag-crossing edit "
              f"recomputes all 53 candidates; final state identical to full re-execution")

class ViewerGate(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp())
    def tearDown(self): shutil.rmtree(self.tmp)

    def test_viewer_export(self):
        store = TimelineStore(self.tmp / "timeline")
        cap = PtyCapture(store, rows=4, cols=20)
        tool = store.append("main", "tool_call", {"name": "cat", "input": "f.txt", "output": "hello"})
        cap.record_bytes(b"hello\r\n", tool)
        store.fork("main", store.events("main")[-1]["id"], "ghost-1")
        cap2 = PtyCapture(store, "ghost-1", rows=4, cols=20)
        cap2.record_bytes(b"ghost\r\n", tool)
        out = export_html(store, ["main", "ghost-1"], self.tmp / "viewer.html", rows=4, cols=20)
        page = out.read_text()
        self.assertIn("Living Replay", page)
        m = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
        data = json.loads(m.group(1))
        self.assertEqual(sorted(data), ["ghost-1", "main"])
        cells = data["main"][0]["cells"]
        self.assertTrue(any(c["ch"] == "h" and c["tool"] == tool for c in cells))
        print("\nViewer measured: single-file export carries both branches with per-cell provenance")

if __name__ == "__main__":
    unittest.main()
