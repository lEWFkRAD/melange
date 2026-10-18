"""Bridge tests: the single UI-facing API over the library.

Covers the three recording kinds the surfaces can open:
- native (hand-built via PtyCapture): every operation works; where-from
  speaks in plain sentences, including the honest caveat when the
  recording kept the step but not the action inside the step, and the
  blank/redraw answer when no step made the cell.
- structure (the real desktop record fixture): dive works, fork and
  provenance are refused by the bridge gate, notes are allowed.
- screen-only (ingested frames): frames come back byte-identical,
  dive is refused, notes are allowed.
"""
import os
import tempfile
import unittest

from living_replay import bridge, ingest
from living_replay.capture import PtyCapture
from living_replay.store import TimelineStore

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "desktop-record.jsonl")


class TestNativeBridge(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        cap = PtyCapture(self.store, rows=4, cols=20)
        self.tool = self.store.append(
            "main", "tool_call",
            {"name": "cat", "input": "synthetic.txt", "output": "hello"})
        self.chunk = cap.record_bytes(b"hello", self.tool)
        self.bare = cap.record_bytes(b" world")  # no tool linkage

    def test_versions_and_caps(self):
        vs = {v["name"]: v for v in bridge.versions(self.store)}
        self.assertEqual(vs["main"]["fidelity"], "native")
        self.assertEqual(vs["main"]["steps"],
                         len(self.store.replay_events("main")))
        self.assertIsNone(vs["main"]["fork"])
        self.assertEqual(bridge.caps(self.store, "main"),
                         ["annotate", "clamp", "dive", "fork",
                          "provenance", "scrub"])

    def test_screen_at(self):
        self.assertIn("hello world", bridge.screen_at(self.store, "main"))
        self.assertIn("hello", bridge.screen_at(self.store, "main",
                                                through=self.chunk))
        self.assertNotIn("world", bridge.screen_at(self.store, "main",
                                                   through=self.chunk))

    def test_where_from_chunk_sentence(self):
        got = bridge.where_from(self.store, "main", self.chunk, 0, 1)
        self.assertTrue(got["attributed"])
        self.assertEqual(got["chunk"], self.chunk)
        self.assertEqual(
            got["sentence"],
            f"This came from step {self.chunk}, 1 characters into that "
            "step's output.")

    def test_where_from_unlinked_chunk_carries_caveat(self):
        got = bridge.where_from(self.store, "main", self.bare, 0, 6)
        self.assertFalse(got["attributed"])
        self.assertEqual(got["chunk"], self.bare)
        self.assertTrue(got["sentence"].startswith(
            f"This came from step {self.bare},"))
        self.assertIn("did not keep which action inside the step made it",
                      got["sentence"])

    def test_where_from_blank_spot(self):
        got = bridge.where_from(self.store, "main", self.chunk, 3, 10)
        self.assertFalse(got["attributed"])
        self.assertNotIn("chunk", got)
        self.assertIn("blank", got["sentence"])
        self.assertIn("no step", got["sentence"])

    def test_notes_round_trip(self):
        nid = bridge.add_note(self.store, "main", self.chunk,
                              "check this figure")
        self.assertEqual(bridge.notes(self.store, "main"),
                         [{"event_id": nid, "at_event": self.chunk,
                           "text": "check this figure"}])

    def test_try_differently(self):
        out = bridge.try_differently(self.store, "main", self.chunk,
                                     "what-if", "use the corrected figure")
        self.assertEqual(out["branch"], "what-if")
        fork_ev = self.store.event(out["fork_event"])
        self.assertEqual(fork_ev["kind"], "fork")
        self.assertEqual(fork_ev["payload"]["parent_branch"], "main")
        self.assertEqual(fork_ev["payload"]["checkpoint"], self.chunk)
        self.assertEqual(fork_ev["payload"]["edit"],
                         {"instruction": "use the corrected figure"})
        note_ev = self.store.event(out["note_event"])
        self.assertEqual(note_ev["kind"], "context_note")
        self.assertEqual(note_ev["payload"],
                         {"text": "use the corrected figure", "pinned": False})
        vs = {v["name"]: v for v in bridge.versions(self.store)}
        self.assertEqual(vs["what-if"]["fork"],
                         {"parent_branch": "main", "checkpoint": self.chunk})
        # The What-if sees the recording up to the split step, no further.
        self.assertIn("hello", bridge.screen_at(self.store, "what-if"))
        self.assertNotIn("world", bridge.screen_at(self.store, "what-if"))
        # Notes work on the What-if too.
        nid = bridge.add_note(self.store, "what-if", self.chunk, "on the copy")
        self.assertEqual(bridge.notes(self.store, "what-if"),
                         [{"event_id": nid, "at_event": self.chunk,
                           "text": "on the copy"}])

    def test_seal(self):
        self.assertTrue(bridge.seal(self.store, "main"))


class TestStructureBridge(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        with open(RECORD) as f:
            ingest.ingest_desktop_record(self.store, "desk", f.read())

    def test_versions_and_caps(self):
        vs = {v["name"]: v for v in bridge.versions(self.store)}
        self.assertEqual(vs["desk"]["fidelity"], "structure")
        self.assertIsNone(vs["desk"]["fork"])
        self.assertEqual(bridge.caps(self.store, "desk"),
                         ["annotate", "dive", "scrub"])

    def test_parts_at_works(self):
        state = bridge.parts_at(self.store, "desk")
        self.assertEqual(len(state), 1801)

    def test_fork_refused(self):
        with self.assertRaises(ingest.FidelityError):
            bridge.try_differently(self.store, "desk", 1, "desk-whatif",
                                   "try it another way")
        self.assertEqual([v["name"] for v in bridge.versions(self.store)],
                         ["desk"])

    def test_where_from_refused(self):
        with self.assertRaises(ingest.FidelityError):
            bridge.where_from(self.store, "desk", 1, 0, 0)

    def test_notes_allowed(self):
        nid = bridge.add_note(self.store, "desk", 2, "look here")
        self.assertIn({"event_id": nid, "at_event": 2, "text": "look here"},
                      bridge.notes(self.store, "desk"))


class TestScreenOnlyBridge(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        self.frames = [(b"\x89PNG-fake-1", 0.0), (b"\x89PNG-fake-2", 1.0)]
        ingest.ingest_screen_frames(self.store, "vid", self.frames)

    def test_versions_and_caps(self):
        vs = {v["name"]: v for v in bridge.versions(self.store)}
        self.assertEqual(vs["vid"]["fidelity"], "screen-only")
        self.assertEqual(bridge.caps(self.store, "vid"),
                         ["annotate", "scrub"])

    def test_frame_at_round_trip(self):
        self.assertEqual(bridge.frame_at(self.store, "vid", 0), b"\x89PNG-fake-1")
        self.assertEqual(bridge.frame_at(self.store, "vid", 1), b"\x89PNG-fake-2")

    def test_parts_at_refused(self):
        with self.assertRaises(ingest.FidelityError):
            bridge.parts_at(self.store, "vid")

    def test_notes_allowed(self):
        nid = bridge.add_note(self.store, "vid", 1, "frame note")
        self.assertEqual(bridge.notes(self.store, "vid"),
                         [{"event_id": nid, "at_event": 1,
                           "text": "frame note"}])


if __name__ == "__main__":
    unittest.main()
