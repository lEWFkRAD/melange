"""Synthetic HTTP coverage for desktop and generic ingest navigation."""
import gc
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "service"))

import melange_service as service
from living_replay import ingest
from living_replay.store import TimelineStore


def stream(events):
    return "\n".join(json.dumps(event) for event in events)


class TestIngestService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="melange-ingest-service-")
        cls.root = Path(cls.tmp.name) / "store"
        store = TimelineStore(cls.root)
        cls.before = {"role": "button", "name": "Open synthetic settings",
                      "desc": "", "props": {}}
        cls.after = {**cls.before, "name": "Close synthetic settings"}
        nodes = [{"nodeId": "1", "role": {"value": "button"},
                  "name": {"value": cls.before["name"]}}]
        ingest.ingest_desktop_record(store, "desktop", stream([
            {"type": "keyframe", "ts": 0.0, "nodes": nodes},
            {"type": "delta", "ts": 1.5, "poll": 1,
             "ops": [{"op": "set", "path": "0", "node": cls.after}]},
            {"type": "input", "ts": 2.0, "synthetic": True,
             "events": [{"type": "click"}]},
        ]))
        ingest.ingest_generic_events(store, "structured", stream([
            {"ts": 0.0, "action": "start"},
            {"ts": 1.0, "action": "snapshot", "state": {"count": 1}},
            {"ts": 2.5, "action": "note", "payload": "synthetic update"},
            {"ts": 4.0, "action": "snapshot", "state": {"count": 2}},
        ]))
        for branch in ("transcript", "notes"):
            ingest.ingest_generic_events(store, branch, stream([
                {"ts": 0.0, "action": "start", "payload": "synthetic job"},
                {"ts": 2.5, "action": "finish", "payload": {"rows": 4}},
            ]))
        store.db.close()
        cls.previous_registry = service.REGISTRY
        service.REGISTRY = service.StoreRegistry({"stores": {
            "synthetic": {"path": str(cls.root), "label": "Synthetic"}}})
        cls.server = service.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = (f"http://127.0.0.1:{cls.server.server_port}"
                    "/api/store/synthetic/branch/")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        service.REGISTRY = cls.previous_registry
        gc.collect()
        cls.tmp.cleanup()

    def call(self, branch, suffix="", body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + branch + suffix, data=data,
            headers={"Content-Type": "application/json"})
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            return response.status, json.load(response)

    def test_desktop_opens_on_keyframe_and_replays_every_state(self):
        status, detail = self.call("desktop")
        self.assertEqual(status, 200)
        self.assertEqual(detail["steps"], 3)
        for step, expected, ts, kind in [
                (1, self.before, 0.0, "ax_keyframe"),
                (2, self.after, 1.5, "ax_delta"),
                (3, self.after, 2.0, "input_event")]:
            status, frame = self.call("desktop", f"/step/{step}")
            self.assertEqual(status, 200, frame)
            self.assertEqual(frame["parts"], {"0": expected})
            self.assertTrue(frame["state_available"])
            self.assertEqual(frame["event_kind"], kind)
            self.assertEqual(frame["ts"], ts)

    def test_generic_structure_uses_recorded_snapshots(self):
        status, detail = self.call("structured")
        self.assertEqual(status, 200)
        self.assertEqual(detail["steps"], 4)
        for step, state in [(1, None), (2, {"count": 1}),
                            (3, {"count": 1}), (4, {"count": 2})]:
            status, frame = self.call("structured", f"/step/{step}")
            self.assertEqual(status, 200, frame)
            self.assertEqual(frame["parts"], state)
            self.assertEqual(frame["state_available"], state is not None)

    def test_generic_transcript_retains_navigable_events(self):
        status, detail = self.call("transcript")
        self.assertEqual(status, 200)
        self.assertEqual(detail["kind"], "session")
        self.assertEqual(detail["steps"], 2)
        status, frame = self.call("transcript", "/step/2")
        self.assertEqual(status, 200, frame)
        self.assertEqual(frame["payload"]["action"], "finish")
        self.assertEqual(frame["payload"]["payload"], {"rows": 4})
        self.assertIn("finish", frame["screen"])
        self.assertEqual(frame["ts"], 2.5)

    def test_annotation_roundtrip_and_fidelity_refusals(self):
        status, note = self.call("notes", "/note", {"step": 2, "text": "Synthetic note"})
        self.assertEqual(status, 201, note)
        self.assertEqual(note["notes"][-1]["text"], "Synthetic note")
        for branch in ("desktop", "structured", "transcript"):
            status, refused = self.call(branch, "/fork", {"note": "Synthetic fork"})
            self.assertEqual(status, 403, refused)
            self.assertIn("refused", refused["error"])
            status, refused = self.call(branch, "/wherefrom/1")
            self.assertEqual(status, 403, refused)


if __name__ == "__main__":
    unittest.main()
