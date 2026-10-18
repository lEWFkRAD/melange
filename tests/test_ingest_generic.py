"""M10 Door 2 generality: profile-less ingest of arbitrary event streams.

- A real second program's session (tests/generic-build-record.jsonl:
  a shell session running git + this repo's unittest runner, recorded
  by tools/make_generic_fixture.py) ingests at structure fidelity:
  seal verifies, state reconstructs at any point, every event traces
  back to its exact source line, and the stream round-trips whole.
- Fidelity is derived from content, never declared: no snapshots ->
  screen-only caps; snapshots -> structure; a recorded computation
  passes the bridge's own rebuildability test -> native, and only
  then does bridge.clamp actually re-execute on the recording.
- A computation claim that does not check out is recorded unverified
  and buys nothing (no silent fidelity upgrade, ever).
- Malformed streams fail loud, naming the line, and store nothing.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from living_replay import bridge, flagship, ingest  # noqa: E402
from living_replay.ingest import FidelityError  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "generic-build-record.jsonl")


def stream(events):
    return "".join(json.dumps(e) + "\n" for e in events)


class TestGenericBuildFixture(unittest.TestCase):
    """The proof workload: a shell/build session from a program that
    is not Hermes and has no Melange profile."""

    def setUp(self):
        self.text = Path(FIXTURE).read_text()
        self.source_events = [json.loads(l) for l in
                              self.text.splitlines() if l.strip()]
        self.store = TimelineStore(tempfile.mkdtemp())
        self.counts = ingest.ingest_generic_events(
            self.store, "build", self.text, source="shell-session")

    def test_counts_and_fidelity(self):
        self.assertEqual(self.counts["events"], len(self.source_events))
        self.assertEqual(self.counts["fidelity"], "structure")
        self.assertEqual(self.counts["computation"], "absent")
        self.assertGreaterEqual(self.counts["snapshots"], 3)
        self.assertEqual(ingest.branch_fidelity(self.store, "build"),
                         "structure")

    def test_seal_verifies(self):
        self.assertTrue(self.store.verify("build"))
        self.assertTrue(bridge.seal(self.store, "build"))

    def test_state_at_end_is_the_sessions_final_state(self):
        final = ingest.generic_state_at(self.store, "build")
        self.assertEqual(final, self.source_events[-1]["state"])
        self.assertEqual(final["tests_failed"], 0)
        self.assertEqual(final["tests_errored"], 0)
        self.assertGreater(final["tests_run"], 0)
        self.assertEqual(final["commands_run"],
                         len([e for e in self.source_events
                              if e["action"] == "command"]))

    def test_state_at_early_point_is_the_early_snapshot(self):
        events = self.store.events("build")
        first_snapshot = next(
            ev for ev in events if "state_blob" in (ev["payload"] or {}))
        state = ingest.generic_state_at(self.store, "build",
                                        through=first_snapshot["id"])
        self.assertEqual(state, self.source_events[0]["state"])
        self.assertEqual(state["commands_run"], 0)

    def test_roundtrip_reconstructs_the_source_stream(self):
        got = ingest.reconstruct_generic_stream(self.store, "build")
        self.assertEqual(got, self.source_events)

    def test_every_event_traces_to_its_source_line(self):
        events = [ev for ev in self.store.events("build")
                  if ev["kind"] != "ingest_profile"]
        self.assertEqual(len(events), len(self.source_events))
        for ev in events:
            trace = ingest.source_trace(self.store, "build", ev["id"])
            self.assertEqual(trace["source"], "shell-session")
            self.assertTrue(ingest.verify_source_line(
                self.store, "build", ev["id"], self.text))
        mid = events[len(events) // 2]
        trace = ingest.source_trace(self.store, "build", mid["id"])
        claimed = json.loads(self.text.splitlines()[trace["line"]])
        rebuilt = ingest.reconstruct_generic_stream(
            self.store, "build")[len(events) // 2]
        self.assertEqual(claimed["action"], rebuilt["action"])

    def test_tampered_stream_fails_verification(self):
        events = [ev for ev in self.store.events("build")
                  if ev["kind"] != "ingest_profile"]
        mid = events[len(events) // 2]
        trace = ingest.source_trace(self.store, "build", mid["id"])
        lines = self.text.splitlines()
        lines[trace["line"]] = lines[trace["line"]].replace(
            '"action"', '"actionx"', 1)
        self.assertFalse(ingest.verify_source_line(
            self.store, "build", mid["id"], "\n".join(lines)))

    def test_structure_refusals_hold(self):
        for op in ("clamp", "fork", "provenance"):
            with self.assertRaises(FidelityError):
                ingest.require_branch_op(self.store, "build", op)
        for op in ("scrub", "dive", "annotate"):
            ingest.require_branch_op(self.store, "build", op)
        with self.assertRaises(FidelityError):
            bridge.clamp(self.store, "build", "/wages", 48000)


class TestGenericScreenOnly(unittest.TestCase):
    def test_event_log_without_state_is_screen_only(self):
        text = stream([
            {"ts": 10.0, "actor": "cron", "action": "start",
             "payload": {"job": "nightly"}},
            {"ts": 11.5, "actor": "cron", "action": "log",
             "payload": {"text": "wrote 42 rows"}},
            {"ts": 12.0, "actor": "cron", "action": "end",
             "payload": {"code": 0}},
        ])
        store = TimelineStore(tempfile.mkdtemp())
        counts = ingest.ingest_generic_events(store, "log", text)
        self.assertEqual(counts["fidelity"], "screen-only")
        self.assertEqual(counts["snapshots"], 0)
        for op in ("scrub", "annotate"):
            ingest.require_branch_op(store, "log", op)
        for op in ("dive", "clamp", "fork", "provenance"):
            with self.assertRaises(FidelityError):
                ingest.require_branch_op(store, "log", op)
        with self.assertRaises(FidelityError):
            ingest.generic_state_at(store, "log")
        got = ingest.reconstruct_generic_stream(store, "log")
        self.assertEqual([e["action"] for e in got],
                         ["start", "log", "end"])
        self.assertTrue(store.verify("log"))


class TestGenericNativeComputation(unittest.TestCase):
    """A generic stream that genuinely carries a recorded computation
    (rebuildable intake + a model_call with figures) earns native,
    and the M4 clamp re-executes on it for real."""

    def _native_stream(self):
        graph = flagship.build_fact_graph(flagship.INTAKE)
        figures = {p: graph.evaluate(p) for p in flagship.DERIVED_ORDER}
        return stream([
            {"ts": 1.0, "actor": "importer", "action": "tool_call",
             "payload": {"name": "read-intake", "input": "intake.txt",
                         "output": flagship.INTAKE}},
            {"ts": 2.0, "actor": "importer", "action": "model_call",
             "payload": {"prompt": "compute return from Fact Graph",
                         "figures": figures, "replayed": True}},
        ])

    def test_verified_computation_earns_native_and_clamps(self):
        store = TimelineStore(tempfile.mkdtemp())
        counts = ingest.ingest_generic_events(store, "gen", 
                                              self._native_stream())
        self.assertEqual(counts["computation"], "verified")
        self.assertEqual(counts["fidelity"], "native")
        out = bridge.clamp(store, "gen", "/wages", 48000)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["figures"]["/totalTax"], 3088)
        self.assertEqual(out["figures"]["/refund"], 3012)

    def test_unverified_computation_claim_buys_nothing(self):
        text = stream([
            {"ts": 1.0, "actor": "importer", "action": "model_call",
             "payload": {"figures": {"/totalTax": 3568}},
             "state": {"phase": "done"}},
            {"ts": 2.0, "actor": "importer", "action": "note",
             "payload": {"text": "trust me"}},
        ])
        store = TimelineStore(tempfile.mkdtemp())
        counts = ingest.ingest_generic_events(store, "gen", text)
        self.assertEqual(counts["computation"], "unverified")
        self.assertEqual(counts["fidelity"], "structure")
        with self.assertRaises(FidelityError):
            bridge.clamp(store, "gen", "/wages", 48000)

    def test_unverified_claim_without_state_is_screen_only(self):
        text = stream([
            {"ts": 1.0, "actor": "importer", "action": "model_call",
             "payload": {"figures": {"/totalTax": 3568}}},
        ])
        store = TimelineStore(tempfile.mkdtemp())
        counts = ingest.ingest_generic_events(store, "gen", text)
        self.assertEqual(counts["computation"], "unverified")
        self.assertEqual(counts["fidelity"], "screen-only")


class TestGenericMalformed(unittest.TestCase):
    def assert_rejected(self, text, line_no):
        store = TimelineStore(tempfile.mkdtemp())
        with self.assertRaises(ValueError) as ctx:
            ingest.ingest_generic_events(store, "bad", text)
        self.assertIn(f"line {line_no}", str(ctx.exception))
        self.assertEqual(store.events("bad"), [])

    def test_not_json(self):
        self.assert_rejected('{"ts": 1.0, "action": "x"}\nnope\n', 1)

    def test_missing_ts(self):
        self.assert_rejected('{"action": "x"}\n', 0)

    def test_missing_action(self):
        self.assert_rejected('{"ts": 1.0}\n', 0)

    def test_state_must_be_an_object(self):
        self.assert_rejected(
            '{"ts": 1.0, "action": "x", "state": [1, 2]}\n', 0)

    def test_empty_stream(self):
        store = TimelineStore(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            ingest.ingest_generic_events(store, "bad", "\n\n")


if __name__ == "__main__":
    unittest.main()
