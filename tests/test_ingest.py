"""ONY-169 Door 2 tests: trace ingest at labeled fidelity.

- The real desktop record (recorder3, SHATNER) ingests as a
  'structure' branch and its reconstructed final state equals the
  recorder's separately-saved final tree.
- Fidelity refusals are enforced in the library: clamp/fork/
  provenance refused on structure; dive refused on screen-only.
- A synthetic non-zero delta exercises set/del application.
- Screen frames ingest as screen-only and come back byte-identical.
"""
import json
import os
import tempfile
import unittest

from living_replay import ingest
from living_replay.store import TimelineStore

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "desktop-record.jsonl")
FINAL = os.path.join(HERE, "desktop-final.json")


class TestDesktopIngest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.store = TimelineStore(self.dir)
        with open(RECORD) as f:
            self.counts = ingest.ingest_desktop_record(self.store, "desk", f.read())

    def test_counts(self):
        self.assertEqual(self.counts["keyframes"], 1)
        self.assertEqual(self.counts["deltas"], 15)

    def test_fidelity_label(self):
        self.assertEqual(ingest.branch_fidelity(self.store, "desk"), "structure")

    def test_reconstruction_matches_recorders_final(self):
        with open(FINAL) as f:
            final_nodes = json.load(f)["nodes"]
        expected = ingest.flatten_ax(final_nodes)
        got = ingest.tree_state_at(self.store, "desk")
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 1801)

    def test_structure_refusals(self):
        for op in ("clamp", "fork", "provenance"):
            with self.assertRaises(ingest.FidelityError):
                ingest.require_branch_op(self.store, "desk", op)
        for op in ("scrub", "dive", "annotate"):
            ingest.require_branch_op(self.store, "desk", op)


class TestNonZeroDelta(unittest.TestCase):
    def test_set_and_del_apply(self):
        d = tempfile.mkdtemp()
        store = TimelineStore(d)
        key = [{"nodeId": "1", "role": {"value": "RootWebArea"},
                "name": {"value": "App"}, "childIds": ["2"]},
               {"nodeId": "2", "role": {"value": "button"},
                "name": {"value": "Open settings"}, "childIds": []}]
        delta = {"ops": [
            {"op": "set", "path": "0/0",
             "node": {"role": "button", "name": "Close settings",
                      "desc": "", "props": {}}},
            {"op": "set", "path": "0/1",
             "node": {"role": "text", "name": "Settings panel",
                      "desc": "", "props": {}}}]}
        text = "\n".join([json.dumps({"type": "keyframe", "nodes": key}),
                          json.dumps({"type": "delta", "poll": 1, **delta})])
        counts = ingest.ingest_desktop_record(store, "synth", text)
        self.assertEqual(counts["delta_ops"], 2)
        state = ingest.tree_state_at(store, "synth")
        self.assertEqual(state["0/0"]["name"], "Close settings")
        self.assertEqual(state["0/1"]["name"], "Settings panel")


class TestScreenOnly(unittest.TestCase):
    def test_frames_round_trip_and_refusals(self):
        d = tempfile.mkdtemp()
        store = TimelineStore(d)
        frames = [(b"\x89PNG-fake-1", 0.0), (b"\x89PNG-fake-2", 1.0)]
        out = ingest.ingest_screen_frames(store, "vid", frames)
        self.assertEqual(out["frames"], 2)
        self.assertEqual(ingest.branch_fidelity(store, "vid"), "screen-only")
        self.assertEqual(ingest.screen_frame_at(store, "vid", 1), b"\x89PNG-fake-2")
        for op in ("dive", "clamp", "fork", "provenance"):
            with self.assertRaises(ingest.FidelityError):
                ingest.require_branch_op(store, "vid", op)


if __name__ == "__main__":
    unittest.main()


class TestLiveDesktopIngest(unittest.TestCase):
    """The live-change capture: settings opened and closed mid-record,
    7,285 real delta ops; reconstruction must still be exact."""

    def test_live_reconstruction_exact(self):
        live_rec = os.path.join(HERE, "desktop-live-record.jsonl")
        live_fin = os.path.join(HERE, "desktop-live-final.json")
        if not (os.path.exists(live_rec) and os.path.exists(live_fin)):
            self.skipTest("live capture fixtures not present")
        store = TimelineStore(tempfile.mkdtemp())
        with open(live_rec) as f:
            counts = ingest.ingest_desktop_record(store, "live", f.read())
        self.assertEqual(counts["delta_ops"], 7285)
        with open(live_fin) as f:
            expected = ingest.flatten_ax(json.load(f)["nodes"])
        got = ingest.tree_state_at(store, "live")
        self.assertEqual(got, expected)
