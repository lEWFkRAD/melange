"""M2 regression test: replay_events(through) on a forked branch, pre-split.

Defect (Melange intent audit M2): TimelineStore.replay_events filtered the
branch's local events by `through` BEFORE looking for the fork event. A
fork's first local event is the fork event itself, whose global id is
always greater than the parent's checkpoint — so for any
through <= checkpoint, the filtered local list was empty, no fork event
was found, and replay_events returned [] instead of the inherited prefix.
That broke every "context at checkpoint" / "replay up to the split" read
on a forked branch (runner.context_at, replay.provenance, gui keyframes).

This test pins the correct behavior:
- replay_events(fork, through <= checkpoint) returns the parent's events
  up to `through`;
- replay_events(fork, through = fork event id) returns prefix + fork event;
- replay_events(fork, through >= last local id) and through=None return
  prefix + the full local tail;
- the non-forked path and nested forks behave the same way.

Run: PYTHONPATH=<tree>/src python3 -m unittest test_replay_events_prefix -v
"""
import tempfile
import unittest

from living_replay.store import TimelineStore


class ReplayEventsPrefixTest(unittest.TestCase):
    def setUp(self):
        self.store = TimelineStore(tempfile.mkdtemp())
        # Parent branch: 6 events, ids 1..6. Split (checkpoint) at event 4.
        self.parent_ids = [
            self.store.append("main", kind, {"seq": i})
            for i, kind in enumerate(
                ["context_note", "tool_call", "model_call",
                 "tool_call", "model_call", "context_note"], start=1)
        ]
        self.split = self.parent_ids[3]  # id 4
        self.fork_event_id = self.store.fork("main", self.split, "whatif")
        self.local_ids = [
            self.store.append("whatif", kind, {"seq": i})
            for i, kind in enumerate(["context_note", "model_call", "tool_call"], start=1)
        ]

    def ids(self, events):
        return [e["id"] for e in events]

    def test_prefix_at_split(self):
        got = self.store.replay_events("whatif", through=self.split)
        self.assertEqual(self.ids(got), self.parent_ids[:4])

    def test_prefix_before_split(self):
        got = self.store.replay_events("whatif", through=self.parent_ids[1])
        self.assertEqual(self.ids(got), self.parent_ids[:2])

    def test_prefix_at_first_event(self):
        got = self.store.replay_events("whatif", through=self.parent_ids[0])
        self.assertEqual(self.ids(got), self.parent_ids[:1])

    def test_at_fork_event(self):
        got = self.store.replay_events("whatif", through=self.fork_event_id)
        self.assertEqual(self.ids(got), self.parent_ids[:4] + [self.fork_event_id])

    def test_full_tail_with_through(self):
        got = self.store.replay_events("whatif", through=self.local_ids[-1])
        self.assertEqual(
            self.ids(got),
            self.parent_ids[:4] + [self.fork_event_id] + self.local_ids)

    def test_full_tail_no_through(self):
        got = self.store.replay_events("whatif")
        self.assertEqual(
            self.ids(got),
            self.parent_ids[:4] + [self.fork_event_id] + self.local_ids)

    def test_parent_branch_unchanged(self):
        got = self.store.replay_events("main", through=self.split)
        self.assertEqual(self.ids(got), self.parent_ids[:4])
        got_all = self.store.replay_events("main")
        self.assertEqual(self.ids(got_all), self.parent_ids)

    def test_nested_fork_prefix(self):
        # Fork the fork at its first local event; a pre-split read on the
        # nested branch must walk both levels of inheritance.
        nested_fork_id = self.store.fork("whatif", self.local_ids[0], "nested")
        self.store.append("nested", "model_call", {"seq": 99})
        got = self.store.replay_events("nested", through=self.parent_ids[2])
        self.assertEqual(self.ids(got), self.parent_ids[:3])
        got_split = self.store.replay_events("nested", through=self.local_ids[0])
        self.assertEqual(
            self.ids(got_split),
            self.parent_ids[:4] + [self.fork_event_id, self.local_ids[0]])


if __name__ == "__main__":
    unittest.main()
