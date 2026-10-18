"""TUI viewer tests: the Viewer model driven headlessly (no curses).

Same three recording kinds as the bridge tests:
- native (hand-built via PtyCapture): render, stepping, notes, try-
  differently, and where-from all work through the bridge.
- structure (the real desktop record fixture): try-differently is
  refused with the design's outline sentence and makes no version.
- screen-only (ingested frames): where-from and look-inside are refused
  with the video-only sentence; stepping over frames works.
"""
import os
import tempfile
import unittest

from living_replay import bridge, ingest
from living_replay.capture import PtyCapture
from living_replay.store import TimelineStore
from living_replay.tui import Viewer, run_script

HERE = os.path.dirname(os.path.abspath(__file__))
RECORD = os.path.join(HERE, "desktop-record.jsonl")

OUTLINE_REFUSAL = ("Steps cannot be changed in an outline recording: "
                   "the words themselves were not kept.")
VIDEO_REFUSAL = ("This is a video-only recording: only pictures of the "
                 "screen were kept.")


def build_native_store():
    store = TimelineStore(tempfile.mkdtemp())
    cap = PtyCapture(store, rows=4, cols=20)
    tool = store.append("main", "tool_call",
                        {"name": "cat", "input": "synthetic.txt",
                         "output": "hello"})
    chunk = cap.record_bytes(b"hello", tool)
    cap.record_bytes(b" world")
    return store, chunk


class TestNativeTui(unittest.TestCase):
    def setUp(self):
        self.store, self.chunk = build_native_store()
        self.viewer = Viewer(self.store, headless=True)

    def test_initial_render(self):
        out = self.viewer.render()
        self.assertIn(f"step 1/{self.viewer.steps}", out)
        self.assertIn("Original", out)
        self.assertIn("| checked |", out)
        self.assertIn("full recording", out)

    def test_right_advances(self):
        self.viewer.handle_key("right")
        self.assertEqual(self.viewer.pos, 1)
        out = self.viewer.render()
        self.assertIn("step 2/", out)
        self.assertIn("hello", out)

    def test_left_goes_back_and_clamps(self):
        self.viewer.handle_key("right")
        self.viewer.handle_key("left")
        self.assertEqual(self.viewer.pos, 0)
        self.viewer.handle_key("left")
        self.assertEqual(self.viewer.pos, 0)

    def test_note_round_trip(self):
        at = self.viewer.current_event_id
        self.viewer.handle_key("note:check this figure")
        self.assertIn("Note saved at step 1", self.viewer.message)
        notes = bridge.notes(self.store, "main")
        self.assertEqual(notes[-1]["text"], "check this figure")
        self.assertEqual(notes[-1]["at_event"], at)

    def test_try_differently_makes_what_if(self):
        self.viewer.handle_key("try:use the corrected figure")
        self.assertNotEqual(self.viewer.branch, "main")
        self.assertIn("What-if", self.viewer.bar_line())
        self.assertIn("Saved as the first step of the What-if",
                      self.viewer.message)
        names = [v["name"] for v in bridge.versions(self.store)]
        self.assertIn(self.viewer.branch, names)

    def test_try_keeps_screen_at_split_step(self):
        # Regression: on a What-if, steps before the split were recorded
        # by the Original; the screen at the split step must still show
        # what the Original showed there.
        ids = [e["id"] for e in self.viewer.events]
        self.viewer.pos = ids.index(self.chunk)
        self.viewer.handle_key("try:use the corrected figure")
        self.assertIn("hello", self.viewer.render())
        self.viewer.handle_key(f"where:0,1")
        self.assertTrue(self.viewer.message.startswith(
            f"This came from step {self.chunk},"))

    def test_where_from_chunk_cell(self):
        ids = [e["id"] for e in self.viewer.events]
        self.viewer.pos = ids.index(self.chunk)
        self.viewer.handle_key("where:0,1")
        self.assertEqual(
            self.viewer.message,
            f"This came from step {self.chunk}, 1 characters into that "
            "step's output.")

    def test_script_mode_play_and_quit(self):
        out = run_script(self.viewer, "play,quit")
        # play in script mode advances 5 steps, clamped at the end.
        self.assertEqual(self.viewer.pos, self.viewer.steps - 1)
        self.assertTrue(self.viewer.done)
        self.assertIn("step", out)


class TestStructureTui(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        with open(RECORD) as f:
            ingest.ingest_desktop_record(self.store, "desk", f.read())
        self.viewer = Viewer(self.store, branch="desk", headless=True)

    def test_bar_says_outline_and_checked(self):
        bar = self.viewer.bar_line()
        self.assertIn("outline recording", bar)
        self.assertIn("| checked |", bar)

    def test_try_differently_refused_no_branch_made(self):
        before = [v["name"] for v in bridge.versions(self.store)]
        self.viewer.handle_key("try:another way")
        self.assertEqual(self.viewer.message, OUTLINE_REFUSAL)
        self.assertEqual(self.viewer.branch, "desk")
        self.assertEqual([v["name"] for v in bridge.versions(self.store)],
                         before)

    def test_where_from_refused(self):
        self.viewer.handle_key("where:0,0")
        self.assertEqual(self.viewer.message, OUTLINE_REFUSAL)


class TestScreenOnlyTui(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        frames = [(b"\x89PNG-fake-1", 0.0), (b"\x89PNG-fake-2", 1.0)]
        ingest.ingest_screen_frames(self.store, "vid", frames)
        self.viewer = Viewer(self.store, branch="vid", headless=True)

    def test_frames_render_and_step(self):
        self.assertIn("Frame 1 of 2 - video-only recording",
                      self.viewer.render())
        self.viewer.handle_key("right")
        self.assertIn("Frame 2 of 2 - video-only recording",
                      self.viewer.render())
        self.viewer.handle_key("right")  # clamps at the last frame
        self.assertIn("Frame 2 of 2", self.viewer.render())

    def test_bar_says_video_only(self):
        self.assertIn("video-only recording", self.viewer.bar_line())

    def test_where_from_refused(self):
        self.viewer.handle_key("where:0,0")
        self.assertEqual(self.viewer.message, VIDEO_REFUSAL)

    def test_look_inside_refused(self):
        self.viewer.look_inside()
        self.assertEqual(self.viewer.message, VIDEO_REFUSAL)

    def test_note_allowed(self):
        self.viewer.handle_key("note:frame note")
        self.assertEqual(bridge.notes(self.store, "vid")[-1]["text"],
                         "frame note")


if __name__ == "__main__":
    unittest.main()
