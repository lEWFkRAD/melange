"""Synthetic M9 regressions: recording clock, complete import, exact replay."""
import copy
import json
import tempfile
import unittest

from living_replay import ingest
from living_replay.store import TimelineStore


def tree(name="Demo"):
    return [{"nodeId": "1", "role": {"value": "RootWebArea"},
             "name": {"value": name}, "childIds": []}]


class DesktopIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = TimelineStore(self.temp.name)
        self.addCleanup(self.store.db.close)

    def ingest(self, events):
        return ingest.ingest_desktop_record(
            self.store, "desktop", "\n".join(map(json.dumps, events)))

    def test_elapsed_clock_and_every_reconstructed_frame(self):
        after = ingest.flatten_ax(tree("Changed"))["0"]
        self.ingest([
            {"type": "keyframe", "nodes": tree(), "ts": 0},
            {"type": "delta", "ops": [], "ts": 1.5, "poll": 1},
            {"type": "input", "synthetic": True, "events": [], "ts": 2},
            {"type": "delta", "ops": [{"op": "set", "path": "0", "node": after}],
             "ts": 3.25, "poll": 2},
        ])
        events = self.store.events("desktop")[1:]
        self.assertEqual([e["mono_ns"] for e in events], [0, 1500000000, 2000000000, 3250000000])
        for i, event in enumerate(events):
            expected = tree("Changed" if i == 3 else "Demo")
            self.assertEqual(ingest.tree_state_at(self.store, "desktop", event["id"]),
                             ingest.flatten_ax(expected))
        self.assertTrue(self.store.verify("desktop"))
        for op in ("fork", "clamp", "provenance"):
            with self.assertRaises(ingest.FidelityError):
                ingest.require_branch_op(self.store, "desktop", op)

    def test_spike_millisecond_clock_is_preserved(self):
        self.ingest([{"type": "keyframe", "nodes": tree(), "t": 0},
                     {"type": "delta", "ops": [], "t": 1642}])
        self.assertEqual(self.store.events("desktop")[-1]["mono_ns"], 1642000000)

    def test_untimed_legacy_frames_share_last_known_time(self):
        self.ingest([{"type": "keyframe", "nodes": tree()},
                     {"type": "delta", "ops": []}])
        self.assertEqual([e["mono_ns"] for e in self.store.events("desktop")], [0, 0, 0])

    def test_invalid_record_writes_nothing(self):
        key = {"type": "keyframe", "nodes": tree(), "ts": 1}
        invalid_tails = [
            {"type": "delta", "ops": [], "ts": t}
            for t in (-1, 0, True, "1", float("nan"), float("inf"), 1e308)
        ] + [
            {"type": "delta", "ops": [{"op": "clear", "path": "0"}]},
            {"type": "delta", "ops": [{"op": "set", "path": "0"}]},
            {"type": "delta", "ops": [{"op": "del", "path": "../../file"}]},
            {"type": "mystery"}, {"type": "input", "synthetic": "yes"}, 42,
            {"type": "keyframe", "nodes": [{"nodeId": "1", "childIds": ["missing"]}]},
        ]
        for tail in invalid_tails:
            with self.subTest(tail=tail), self.assertRaises(ValueError):
                self.ingest([key, tail])
            self.assertEqual(self.store.events("desktop"), [])
            self.assertEqual(list(self.store.blobs.iterdir()), [])
        for record in ([], [42], [{"type": "delta", "ops": []}]):
            with self.assertRaises(ValueError):
                self.ingest(record)

    def test_import_cannot_reclassify_existing_branch(self):
        self.store.append("desktop", "context_note", {"text": "original"})
        original = self.store.events("desktop")
        with self.assertRaises(ValueError):
            self.ingest([{"type": "keyframe", "nodes": tree()}])
        self.assertEqual(self.store.events("desktop"), original)

    def test_flatten_handles_deep_trees_without_recursion(self):
        nodes = [{"nodeId": str(i), "childIds": [str(i + 1)] if i < 1099 else []}
                 for i in range(1100)]
        self.assertEqual(len(ingest.flatten_ax(nodes)), 1100)

    def test_invalid_tree_topology_is_rejected(self):
        bad = [[], tree() + tree("Conflict"),
               [{"nodeId": "1", "childIds": ["1"]}],
               [{"nodeId": "1", "childIds": ["2"]}, {"nodeId": "2", "childIds": ["1"]}],
               [{"nodeId": "1", "childIds": ["3"]}, {"nodeId": "2", "childIds": ["3"]},
                {"nodeId": "3"}], [{"nodeId": "1", "childIds": ["2"]}]]
        for nodes in bad:
            with self.subTest(nodes=nodes), self.assertRaises(ValueError):
                ingest.flatten_ax(copy.deepcopy(nodes))

    def test_identical_cdp_node_repeats_are_collapsed(self):
        self.assertEqual(ingest.flatten_ax(tree() * 2), ingest.flatten_ax(tree()))


if __name__ == "__main__":
    unittest.main()
