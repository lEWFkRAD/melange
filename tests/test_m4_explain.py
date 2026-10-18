"""M4 remainder: surface-issued explain on session recordings.

The bridge gains the second half of the dive: work backward from a
figure that came out wrong to the recorded inputs that could have
caused it. Doctrine (UX design section 2, audit P4/P6): explain
presents candidate ghost branches, one per verified explanation,
and NEVER chooses; every candidate is forward-executed through the
same incremental Engine path clamp uses before it exists. The
flagship corpus supplies the ground truth: refund 2,532 should have
been 3,012, and the wages correction 52,000 -> 48,000 is one way to
get there (refund 3,012, total tax 3,088 per the independent
flagship.expected_figures path) — but not the only way, and the
bridge must say so.
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

from living_replay import bridge, flagship  # noqa: E402
from living_replay.ingest import FidelityError  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def by_input(out):
    return {c["input"]: c for c in out["candidates"]}


class TestBridgeExplainSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.result = flagship.run_flagship(self.tmp / "flag")
        self.store = self.result["store"]

    def test_refund_solved_back_to_wages(self):
        parent_before = self.store.events("main")
        out = bridge.explain(self.store, "main", "/refund", 3012)
        self.assertEqual(out["current"], 2532)
        self.assertFalse(out["unresolved"])
        wages = by_input(out)["/wages"]
        self.assertTrue(wages["accepted"])
        self.assertEqual(wages["from"], 52000)
        self.assertEqual(wages["to"], 48000)
        self.assertEqual(wages["figures"], flagship.expected_figures(48000))
        self.assertEqual(wages["figures"]["/totalTax"], 3088)
        self.assertEqual(wages["figures"]["/refund"], 3012)
        # The parent is untouched; the ghost carries the explanation.
        self.assertEqual(self.store.events("main"), parent_before)
        models = [e for e in self.store.replay_events(wages["branch"])
                  if e["kind"] == "model_call"]
        self.assertEqual(models[-1]["payload"]["explained"],
                         {"target": "/refund", "desired": 3012})
        self.assertEqual(models[-1]["payload"]["clamped"],
                         {"/wages": 48000})
        self.assertTrue(bridge.seal(self.store, wages["branch"]))

    def test_tax_solved_back_to_wages(self):
        out = bridge.explain(self.store, "main", "/totalTax", 3088)
        wages = by_input(out)["/wages"]
        self.assertTrue(wages["accepted"])
        self.assertEqual(wages["to"], 48000)
        self.assertEqual(wages["figures"]["/totalTax"], 3088)
        self.assertEqual(wages["figures"]["/refund"], 3012)

    def test_every_candidate_forward_verified(self):
        out = bridge.explain(self.store, "main", "/refund", 3012)
        accepted = [c for c in out["candidates"] if c["accepted"]]
        self.assertTrue(accepted)
        for c in accepted:
            # The candidate's own re-execution lands the figure exactly.
            self.assertEqual(c["figures"]["/refund"], 3012)
            self.assertTrue(bridge.seal(self.store, c["branch"]))
        # The two candidates with an independent ground-truth path
        # match it figure for figure.
        self.assertEqual(by_input(out)["/withholding"]["to"], 6580)
        self.assertEqual(by_input(out)["/withholding"]["figures"],
                         flagship.expected_figures(52000, 6580))

    def test_explain_presents_and_never_chooses(self):
        out = bridge.explain(self.store, "main", "/refund", 3012)
        accepted = [c for c in out["candidates"] if c["accepted"]]
        # Wages is one honest way; withholding is another. The bridge
        # returns them all and marks none as the answer.
        self.assertGreaterEqual(len(accepted), 2)
        branches = {c["branch"] for c in accepted}
        self.assertEqual(len(branches), len(accepted))
        self.assertNotIn("chosen", out)

    def test_explain_blocked_by_named_house_rule(self):
        self.store.typed_edit("main", "pin", "/refund", 2532)
        names_before = {v["name"] for v in bridge.versions(self.store)}
        out = bridge.explain(self.store, "main", "/refund", 3012)
        self.assertTrue(out["unresolved"])
        self.assertTrue(out["candidates"])
        for c in out["candidates"]:
            self.assertFalse(c["accepted"])
            self.assertIsNone(c["branch"])
            self.assertEqual(c["violations"], ["/refund"])
            self.assertIn("/refund", c["reason"])
        names_after = {v["name"] for v in bridge.versions(self.store)}
        self.assertEqual(names_before, names_after)

    def test_explain_unreachable_desired_is_honest(self):
        out = bridge.explain(self.store, "main", "/refund", 10 ** 9)
        self.assertEqual(out["candidates"], [])
        self.assertTrue(out["unresolved"])

    def test_explain_input_target_is_a_clamp_not_an_explain(self):
        with self.assertRaises(ValueError):
            bridge.explain(self.store, "main", "/wages", 48000)

    def test_explain_refused_at_screen_only_fidelity(self):
        store = TimelineStore(tempfile.mkdtemp())
        store.append("vid", "ingest_profile", {"fidelity": "screen-only"})
        store.append("vid", "screen_frame", {"frame": 1})
        with self.assertRaises(FidelityError):
            bridge.explain(store, "vid", "/refund", 3012)

    def test_explain_without_recorded_computation_refuses_honestly(self):
        store = TimelineStore(tempfile.mkdtemp())
        store.append("main", "tool_call", {"name": "noop", "output": "done"})
        with self.assertRaises(ValueError):
            bridge.explain(store, "main", "/refund", 3012)


class TestServiceExplainSession(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        flagship.run_flagship(self.tmp / "gen")
        vid = TimelineStore(self.tmp / "vidstore")
        vid.append("vid", "ingest_profile", {"fidelity": "screen-only"})
        vid.append("vid", "screen_frame", {"frame": 1})
        registry = {"stores": {
            "flag": {"path": str(self.tmp / "gen" / "timeline"),
                     "label": "Flagship session"},
            "vid": {"path": str(self.tmp / "vidstore"),
                    "label": "Video only"}}}
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

    def test_service_explain_on_session(self):
        status, out = self._post("/api/store/flag/branch/main/explain",
                                 {"target": "/refund", "desired": 3012})
        self.assertEqual(status, 200, out)
        self.assertFalse(out["unresolved"])
        wages = {c["input"]: c for c in out["candidates"]}["/wages"]
        self.assertTrue(wages["accepted"])
        self.assertEqual(wages["to"], 48000)
        self.assertEqual(wages["figures"]["/totalTax"], 3088)
        self.assertEqual(wages["figures"]["/refund"], 3012)
        detail = self._get(f"/api/store/flag/branch/{wages['branch']}")
        self.assertTrue(detail["seal"])
        # The branch detail carries the computation the surface's
        # Change-this-step and What-went-wrong panels are built from.
        main = self._get("/api/store/flag/branch/main")
        self.assertEqual(main["computation"]["inputs"]["/wages"], 52000)
        self.assertEqual(main["computation"]["figures"]["/refund"], 2532)

    def test_service_explain_refused_at_screen_only(self):
        status, out = self._post("/api/store/vid/branch/vid/explain",
                                 {"target": "/refund", "desired": 3012})
        self.assertEqual(status, 403, out)
        self.assertIn("screen-only", out["error"])


if __name__ == "__main__":
    unittest.main()
