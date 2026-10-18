"""Build 1 gate corpus — the measured gates from the brief (G1-G6).

Every gate asserts the brief's threshold AND prints its measured number.
G1's ground truth is pyte, a real reference emulator, fed the same stored
(post-redaction) bytes the timeline replays — never the grid's own output.
"""
import os, shutil, sys, tempfile, unittest
from pathlib import Path

from living_replay.capture import PtyCapture
from living_replay.edits import apply_clamp, check_pins, explain
from living_replay.forking import snapshot_workspace
from living_replay.replay import provenance, reconstruct
from living_replay.runner import context_at, demo_task, run_fork
from living_replay.store import TimelineStore

try:
    import pyte
except ImportError:  # reference emulator is a test-only dependency
    pyte = None

ROWS, COLS = 10, 40
PY = sys.executable

HOSTILE = {
    "plain-scroll": "for i in range(30): print(f'line-{i:02d}')",
    "crlf-progress": "import sys\nfor i in range(0,101,10):\n sys.stdout.write(f'\\rprogress {i}%'); sys.stdout.flush()\nprint('\\ndone')",
    "curses-box-edit": ("import curses, time\ndef main(s):\n s.addstr(0,0,'HEADER')\n"
        " win = curses.newwin(6, 30, 2, 3); win.box(); win.addstr(1,1,'inside box'); win.refresh()\n"
        " s.move(9,0); s.addstr('status: ok'); s.refresh(); time.sleep(0.1)\n"
        " win.addstr(3,1,'edited!'); win.refresh(); time.sleep(0.1)\ncurses.wrapper(main)"),
    "alt-screen": "import sys; sys.stdout.write('main-screen\\r\\n'); sys.stdout.write('\\x1b[?1049h'); sys.stdout.write('\\x1b[HALT CONTENT'); sys.stdout.write('\\x1b[?1049l'); sys.stdout.write('back-to-main'); sys.stdout.flush()",
    "scroll-region-insert": ("import curses, time\ndef main(s):\n s.scrollok(True)\n"
        " for i in range(10): s.addstr(i, 0, f'row{i}')\n"
        " s.setscrreg(2, 7); s.move(7,0); s.scroll(3); s.refresh(); time.sleep(0.1)\n"
        " s.move(0,0); s.insertln(); s.addstr(0,0,'INSERTED'); s.refresh(); time.sleep(0.1)\ncurses.wrapper(main)"),
    "colors-attrs-erase": "import sys; w=sys.stdout.write; w('\\x1b[31mred\\x1b[0m plain\\r\\n'); w('\\x1b[2;5HBOLD\\x1b[1mX\\x1b[22m'); w('\\x1b[3;1Habcdefghij\\x1b[3;4H\\x1b[1K'); w('\\x1b[4;1Hxyz\\x1b[1J'); sys.stdout.flush()",
    "tabs-backspace": "import sys; w=sys.stdout.write; w('a\\tb\\tc\\r\\n'); w('abc\\b\\bXY\\r\\n'); w('tail'); sys.stdout.flush()",
    "deletelines-chars": "import sys; w=sys.stdout.write; [w(f'L{i}\\r\\n') for i in range(6)]; w('\\x1b[2;1H\\x1b[2M'); w('\\x1b[1;3H\\x1b[2P'); sys.stdout.flush()",
    "dashboard-redraw": ("import time\nfor t in range(12):\n"
        " print('\\x1b[H\\x1b[2J' + f'tick {t}\\r\\n' + 'x' * t + '\\r\\n' + f'val={t*t}')\n time.sleep(0.02)"),
}

PYTE_SCENARIOS = [k for k in HOSTILE if k not in ("curses-box-edit", "alt-screen", "scroll-region-insert")]
TMUX_SCENARIOS = ["curses-box-edit", "alt-screen", "scroll-region-insert"]

def tmux_final_screen(code: str) -> list[str] | None:
    """Final pane contents of a REAL terminal (tmux) running the same
    program — the ground truth for alternate-screen restore semantics,
    which pyte deliberately does not implement."""
    import subprocess, time as _time
    name = f"lr-g1-{os.getpid()}"
    script = Path(tempfile.mkdtemp()) / "prog.py"; script.write_text(code)
    try:
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
        r = subprocess.run(["tmux", "new-session", "-d", "-s", name, "-x", str(COLS), "-y", str(ROWS),
                            f"{PY} {script}; sleep 30"], capture_output=True, text=True)
        if r.returncode != 0: return None
        _time.sleep(2.5)
        out = subprocess.run(["tmux", "capture-pane", "-p", "-t", name], capture_output=True, text=True)
        if out.returncode != 0: return None
        lines = out.stdout.split("\n")
        return [(lines[i] if i < len(lines) else "") for i in range(ROWS)]
    finally:
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        if os.environ.get("TERM", "dumb") == "dumb": os.environ["TERM"] = "xterm-256color"
    def tearDown(self): shutil.rmtree(self.tmp)
    _n = 0
    def store(self):
        GateTests._n += 1
        return TimelineStore(self.tmp / f"timeline-{GateTests._n}")

    # ---- G1: replay fidelity vs a reference emulator -------------------
    @unittest.skipIf(pyte is None, "pyte (test extra) not installed")
    def test_g1_hostile_corpus_vs_reference(self):
        samples = cells = matched = 0
        per = {}
        for name, code in ((k, HOSTILE[k]) for k in PYTE_SCENARIOS):
            store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
            env = dict(os.environ, TERM="xterm-256color")
            self.assertEqual(cap.run([PY, "-c", code], timeout=15), 0, name)
            chunks = [e for e in store.events("main") if e["kind"] == "terminal_chunk"]
            ref = pyte.Screen(COLS, ROWS); stream = pyte.ByteStream(ref)
            s_cells = s_matched = 0
            for e in chunks:
                stream.feed(store.get_blob(e["payload"]["blob"]))
                mine = reconstruct(store, "main", e["id"], ROWS, COLS).screen().split("\n")
                for y in range(ROWS):
                    r = (ref.display[y] if y < len(ref.display) else "").ljust(COLS)
                    m = (mine[y] if y < len(mine) else "").ljust(COLS)
                    s_matched += sum(1 for a, b in zip(r, m) if a == b); s_cells += COLS
                samples += 1
            per[name] = s_matched / s_cells if s_cells else 1.0
            cells += s_cells; matched += s_matched
        # Sub-chunk leg: step the two richest streams through pyte and a
        # fresh Grid in rotating slice sizes, sampling every slice. This
        # stresses sequences split at arbitrary byte boundaries, which is
        # where chunked replay usually breaks.
        from living_replay.grid import Grid as _Grid
        sub_samples = 0
        for name in ("dashboard-redraw", "deletelines-chars", "plain-scroll", "crlf-progress"):
            store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
            self.assertEqual(cap.run([PY, "-c", HOSTILE[name]], timeout=15), 0, name)
            blob = b"".join(store.get_blob(e["payload"]["blob"])
                            for e in store.events("main") if e["kind"] == "terminal_chunk")
            ref = pyte.Screen(COLS, ROWS); stream = pyte.ByteStream(ref)
            mine = _Grid(ROWS, COLS)
            pos = 0; sizes = (1, 3, 7, 16); k = 0
            while pos < len(blob):
                step = sizes[k % len(sizes)]; k += 1
                part = blob[pos:pos + step]; pos += len(part)
                stream.feed(part); mine.feed(part, 1, None, pos)
                mm = mine.screen().split("\n")
                for y in range(ROWS):
                    r = (ref.display[y] if y < len(ref.display) else "").ljust(COLS)
                    m = (mm[y] if y < len(mm) else "").ljust(COLS)
                    matched += sum(1 for a, b in zip(r, m) if a == b); cells += COLS
                samples += 1; sub_samples += 1
        rate = matched / cells
        print(f"\nG1 measured: {rate:.4%} cell agreement over {samples} sampled frames "
              f"({sub_samples} sub-chunk); per-scenario: "
              + ", ".join(f"{k}={v:.2%}" for k, v in per.items()))
        self.assertGreaterEqual(samples, 100)
        self.assertGreaterEqual(rate, 0.995, f"G1 fidelity {rate:.4%}")

    def test_g1_alt_screen_vs_real_terminal(self):
        """Alt-screen resolution (Build 3): pyte treats 1049 set/reset as
        no-ops, but real terminals restore the main buffer — and real
        workloads (curses teardown) depend on it. The grid implements
        xterm semantics; this leg proves it against tmux, a real
        terminal, on the final screen of the alt-screen scenarios."""
        import shutil as _sh
        if not _sh.which("tmux"):
            self.skipTest("tmux not available")
        cells = matched = 0; per = {}
        for name in TMUX_SCENARIOS:
            truth = tmux_final_screen(HOSTILE[name])
            self.assertIsNotNone(truth, f"tmux run failed for {name}")
            store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
            self.assertEqual(cap.run([PY, "-c", HOSTILE[name]], timeout=15), 0, name)
            mine = reconstruct(store, "main", rows=ROWS, cols=COLS).screen().split("\n")
            s = 0
            for y in range(ROWS):
                t = (truth[y] if y < len(truth) else "").ljust(COLS)
                m = (mine[y] if y < len(mine) else "").ljust(COLS)
                s += sum(1 for a, b in zip(t, m) if a == b)
            per[name] = s / (ROWS * COLS); cells += ROWS * COLS; matched += s
        rate = matched / cells
        print(f"\nG1-tmux measured: {rate:.4%} final-screen agreement vs tmux on alt-screen scenarios; "
              + ", ".join(f"{k}={v:.2%}" for k, v in per.items()))
        self.assertGreaterEqual(rate, 0.995, f"tmux fidelity {rate:.4%}")

    # ---- G2: pixel-to-cause over a multi-tool workload ------------------
    def test_g2_pixel_to_cause_corpus(self):
        store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
        shell = store.append("main", "tool_call", {"name": "shell", "input": "", "output": "prompt"})
        cap.record_bytes(b"$ ", shell)
        jobs = [("cat report.txt", b"revenue 52000\r\nexpenses 31000\r\n"),
                ("ls work/", b"a.txt b.txt c.txt\r\n"),
                ("grep total out.txt", b"total=21000\r\n")]
        last = None
        for name, out in jobs:
            tool = store.append("main", "tool_call", {"name": name, "input": name, "output": out.decode()})
            last = cap.record_bytes(out, tool)
        banner = cap.record_bytes(b"~", None)  # one unattributed control cell
        grid = reconstruct(store, "main", rows=ROWS, cols=COLS)
        total = attributed = 0; misses = {}
        for y in range(ROWS):
            for x in range(COLS):
                if grid.cells[y][x].char in (" ", ""): continue
                total += 1
                cell = grid.cells[y][x]
                if cell.tool_event is not None: attributed += 1
                else: misses[cell.char] = misses.get(cell.char, 0) + 1
        rate = attributed / total
        print(f"\nG2 measured: {rate:.2%} of {total} content cells resolve to a tool call; unattributed: {misses}")
        self.assertGreaterEqual(rate, 0.95, f"G2 attribution {rate:.2%}")
        self.assertEqual(misses, {"~": 1})  # failures are reported, never hidden

    # ---- G3: fork finishes the task on a new branch ---------------------
    def test_g3_fork_runner_completes_with_note(self):
        store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
        ws = self.tmp / "ws"; ws.mkdir(); (ws / "data.txt").write_text("amount=21")
        read = store.append("main", "tool_call", {"name": "read-amount", "input": "data.txt", "amount": 21, "output": "21"})
        cap.record_bytes(b"amount=21\r\n", read)
        snap = snapshot_workspace(store, "main", ws)
        checkpoint = store.events("main")[-1]["id"]
        store.append("main", "model_call", {"prompt": "late", "tokens": "after-checkpoint"})
        before = store.events("main"); before_screen = reconstruct(store, "main", rows=ROWS, cols=COLS).screen()
        out = run_fork(store, "main", checkpoint, "fork-fix", demo_task(),
                       note="correction: amount=50", workspace_snapshot=snap,
                       workspace_dest=self.tmp / "ws-fork", rows=ROWS, cols=COLS)
        self.assertEqual(out["result"], {"amount": 50, "total": 100})
        self.assertIn("total=100", out["screen"])
        self.assertEqual(store.events("main"), before)  # parent branch untouched
        self.assertEqual(reconstruct(store, "main", rows=ROWS, cols=COLS).screen(), before_screen)
        ctx_kinds = [c["payload"].get("tokens") for c in context_at(store, "fork-fix")]
        self.assertNotIn("after-checkpoint", ctx_kinds)  # context truncated at checkpoint
        self.assertTrue(any(c["kind"] == "context_note" for c in context_at(store, "fork-fix")))
        self.assertEqual((self.tmp / "ws-fork" / "data.txt").read_text(), "amount=21")  # snapshot restored

    # ---- G4: zero seeded secrets at rest --------------------------------
    def test_g4_seeded_secret_corpus(self):
        seeds = [b"sk_live_4eC39HqLyjWDarjtT1zdp7dc", b"AKIAIOSFODNN7EXAMPLE",
                 b"hunter2-correct-horse", b"123-45-6789", b"ghp_abcdefghij0123456789",
                 b"split-secret-77889900"]
        store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
        cap.record_bytes(b"key=" + seeds[0] + b"\r\naws " + seeds[1] + b"\r\n")
        cap.record_bytes(b"password=" + seeds[2] + b" ssn " + seeds[3] + b"\r\n")
        cap.record_bytes(b"token: " + seeds[4] + b"\r\n")
        # Secret printed by a live child in two writes with a pause, so PTY
        # reads split it; the capture tail buffer must reassemble it before
        # redaction. token= prefix makes it pattern-visible once whole.
        code = ("import sys, time; sys.stdout.write('token=' + '" + seeds[5][:10].decode() + "'); "
                "sys.stdout.flush(); time.sleep(0.4); sys.stdout.write('" + seeds[5][10:].decode() + "'); sys.stdout.flush()")
        self.assertEqual(cap.run([PY, "-c", code], timeout=10), 0)
        persisted = (store.root / "timeline.sqlite").read_bytes() + \
            b"".join(p.read_bytes() for p in store.blobs.iterdir())
        for seed in seeds:
            self.assertNotIn(seed, persisted, f"seed leaked: {seed[:12]}...")
        self.assertIn(b"[REDACTED]", persisted)
        print(f"\nG4 measured: 0 of {len(seeds)} seeded secrets present in persisted timeline")

    # ---- G5: replay-by-record, zero live model calls ---------------------
    def test_g5_replay_by_record_zero_live_calls(self):
        class FakeModel:
            def __init__(self): self.calls = 0
            def double(self, n): self.calls += 1; return str(n * 2)
        model = FakeModel()
        store = self.store(); cap = PtyCapture(store, rows=ROWS, cols=COLS)
        live_screens = []
        read = store.append("main", "tool_call", {"name": "read-amount", "amount": 21, "input": "", "output": "21"})
        cap.record_bytes(b"amount=21\r\n", read); live_screens.append(cap.grid.screen())
        tokens = model.double(21)
        store.append("main", "model_call", {"prompt": "double", "tokens": tokens, "replayed": True})
        tool = store.append("main", "tool_call", {"name": "print-total", "input": "", "output": f"total={tokens}"})
        cap.record_bytes(f"total={tokens}\r\n".encode(), tool); live_screens.append(cap.grid.screen())
        self.assertEqual(model.calls, 1)
        ids = [e["id"] for e in store.events("main")]
        replayed = [reconstruct(store, "main", i, ROWS, COLS).screen() for i in ids]
        self.assertIn(live_screens[0], replayed); self.assertEqual(replayed[-1], live_screens[-1])
        self.assertEqual(model.calls, 1, "replay made a live model call")
        print("\nG5 measured: full transcript reproduced from record; live model calls during replay = 0")

    # ---- G6: typed edits — clamp / explain / pin -------------------------
    def test_g6_typed_edits_on_event_graph(self):
        store = self.store()
        store.append("main", "tool_call", {"name": "read-amount", "amount": 21, "input": "", "output": "21"})
        store.append("main", "model_call", {"prompt": "double", "tokens": "42", "replayed": True})
        def values(branch):
            v = {}
            for e in store.replay_events(branch):
                if e["kind"] == "tool_call" and e["payload"].get("name") == "read-amount": v["amount"] = e["payload"]["amount"]
                if e["kind"] == "model_call": v["total"] = int(e["payload"]["tokens"])
            return v
        def derive(v):
            out = {"amount": v.get("amount", 0)}; out["total"] = out["amount"] * 2
            out["tax"] = round(out["total"] * 0.1, 2); out.update(v.get("__clamps__", {}))
            if "__clamps__" in v and "total" in v["__clamps__"]: out["tax"] = round(out["total"] * 0.1, 2)
            return out
        base = values("main"); self.assertEqual(derive(base)["total"], 42)
        # CLAMP: cut total's incoming edge; downstream recomputes consistently.
        store.typed_edit("main", "clamp", "total", 48)
        clamped = apply_clamp(base, "total", 48, derive)
        self.assertEqual((clamped["total"], clamped["tax"]), (48, 4.8))
        # EXPLAIN: only the candidate that forward-verifies becomes a ghost branch.
        def fork(name, proposal):
            b = f"ghost-{name}"; store.fork("main", store.events('main')[-1]["id"], b); return b
        result = explain([("duplicate-1099", {"amount": 30}), ("wrong-basis", {"amount": 24})],
                         "total", 48, derive, fork)
        self.assertEqual(result.branch, "ghost-wrong-basis")
        self.assertEqual(len(result.counterexamples), 1); self.assertIn("duplicate-1099", result.counterexamples[0])
        unresolved = explain([("nope", {"amount": 1})], "total", 48, derive, fork)
        self.assertIsNone(unresolved.branch); self.assertEqual(len(unresolved.counterexamples), 1)
        # PIN: a pinned value violated by a fork is reported by name.
        store.typed_edit("main", "pin", "total", 48)
        cp = store.events("main")[-1]["id"]
        out = run_fork(store, "main", cp, "fork-pin-break", demo_task(), note="amount=30",
                       rows=ROWS, cols=COLS)
        self.assertEqual(out["result"]["total"], 60)
        self.assertEqual(check_pins({"total": out["result"]["total"]}, out["pins"]), ["total"])
        print("\nG6 measured: clamp recomputes downstream (48 -> tax 4.8); explain verified 1 of 2 "
              "candidates into a ghost branch, 1 counterexample kept; pin violation reported by name")

if __name__ == "__main__":
    unittest.main()
