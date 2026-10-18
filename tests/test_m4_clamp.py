"""M4 slice 1: surface-issued clamp on session recordings.

The bridge gains the edit the dive was missing: clamp one recorded
input on a native session recording, fork through the house-rules
gate, re-execute only the input's dependents through the incremental
Engine, and report the ripple (recomputed vs reused) with the amended
computation appended to the What-if. The flagship corpus supplies the
ground truth: wages 52,000 -> 48,000 moves total tax 3,568 -> 3,088
and refund 2,532 -> 3,012 (flagship.expected_figures, an independent
code path), and the wages chain has exactly six derived dependents;
the state chain and the child credit must NOT recompute.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "service"))

from living_replay import bridge, flagship, ingest  # noqa: E402
from living_replay.ingest import FidelityError  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402

WAGES_CHAIN = {"/agi", "/taxableIncome", "/taxBeforeCredits", "/credit",
               "/totalTax", "/refund"}
UNTOUCHED = {"/childCredit", "/stateTaxable", "/stateTax", "/stateRefund"}


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestBridgeClampSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.result = flagship.run_flagship(self.tmp / "flag")
        self.store = self.result["store"]

    def test_clamp_reexecutes_dependents_only(self):
        parent_before = self.store.events("main")
        out = bridge.clamp(self.store, "main", "/wages", 48000)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["figures"]["/totalTax"], 3088)
        self.assertEqual(out["figures"]["/refund"], 3012)
        self.assertEqual(out["values"],
                         flagship.expected_figures(48000) |
                         {"/wages": 48000, "/withholding": 6100,
                          "/otherIncome": 0, "/standardDeduction": 14600,
                          "/stateWages": 52000, "/stateWithholding": 900,
                          "/dependents": 1})
        self.assertEqual(set(out["recomputed"]), WAGES_CHAIN)
        self.assertEqual(set(out["reused"]), UNTOUCHED)
        # The parent is untouched; the What-if carries the amendment.
        self.assertEqual(self.store.events("main"), parent_before)
        models = [e for e in self.store.replay_events(out["branch"])
                  if e["kind"] == "model_call"]
        self.assertEqual(models[-1]["payload"]["figures"]["/totalTax"], 3088)
        self.assertEqual(models[-1]["payload"]["clamped"], {"/wages": 48000})
        edits = [e for e in self.store.replay_events(out["branch"])
                 if e["kind"] == "edit"]
        self.assertEqual(edits[-1]["payload"]["edit_kind"], "clamp")
        self.assertTrue(bridge.seal(self.store, out["branch"]))

    def test_clamp_refused_at_screen_only_fidelity(self):
        store = TimelineStore(tempfile.mkdtemp())
        store.append("vid", "ingest_profile", {"fidelity": "screen-only"})
        store.append("vid", "screen_frame", {"frame": 1})
        with self.assertRaises(FidelityError):
            bridge.clamp(store, "vid", "/wages", 48000)

    def test_clamp_rejected_by_named_house_rule(self):
        self.store.typed_edit("main", "pin", "/refund", 2532)
        names_before = {v["name"] for v in bridge.versions(self.store)}
        out = bridge.clamp(self.store, "main", "/wages", 48000)
        self.assertFalse(out["accepted"])
        self.assertEqual(out["violations"], ["/refund"])
        self.assertIn("/refund", out["reason"])
        names_after = {v["name"] for v in bridge.versions(self.store)}
        self.assertEqual(names_before, names_after)

    def test_clamp_without_recorded_computation_refuses_honestly(self):
        store = TimelineStore(tempfile.mkdtemp())
        cap_store_event = store.append("main", "tool_call",
                                       {"name": "noop", "output": "done"})
        self.assertIsNotNone(cap_store_event)
        with self.assertRaises(ValueError):
            bridge.clamp(store, "main", "/wages", 48000)


class TestServiceClampSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        flagship.run_flagship(self.tmp / "gen")
        registry = {"stores": {"flag": {
            "path": str(self.tmp / "gen" / "timeline"),
            "label": "Flagship session"}}}
        cfg = self.tmp / "stores.json"
        cfg.write_text(json.dumps(registry))
        self.port = free_port()
        env = dict(os.environ, MELANGE_STORES_FILE=str(cfg),
                   MELANGE_PORT=str(self.port))
        self.proc = subprocess.Popen(
            [sys.executable, str(REPO / "service" / "melange_service.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(100):
            try:
                self._get("/api/health")
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("service did not come up")

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return json.loads(r.read())

    def _post(self, path, body):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_service_clamp_fork_on_session(self):
        status, out = self._post("/api/store/flag/branch/main/fork",
                                 {"clamp": {"target": "/wages",
                                            "value": 48000}})
        self.assertEqual(status, 201)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["values"]["/totalTax"], 3088)
        self.assertEqual(out["values"]["/refund"], 3012)
        self.assertEqual(set(out["recomputed"]), WAGES_CHAIN)
        self.assertEqual(set(out["reused"]), UNTOUCHED)
        detail = self._get(f"/api/store/flag/branch/{out['branch']}")
        self.assertEqual(detail["branch"], out["branch"])
        self.assertTrue(detail["seal"])


if __name__ == "__main__":
    unittest.main()
