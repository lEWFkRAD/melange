"""Real subprocess tests, branch preservation, and execution boundaries."""
import tempfile
import unittest
import json
import subprocess
import sys
from pathlib import Path
from living_replay import bridge, coding_demo


class CodingDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = coding_demo.run_demo(Path(self.tmp.name))["store"]
        self.addCleanup(self.store.db.close)

    def test_real_failure_then_real_success(self):
        self.assertEqual(bridge.computation(self.store, "main")["figures"]["/testsFailed"], 1)
        before = self.store.events("main")
        fixed = bridge.clamp(self.store, "main", "/retryBudget", 3)
        self.assertTrue(fixed["accepted"])
        self.assertEqual(fixed["figures"], {"/testsPassed": 6, "/testsFailed": 0, "/testsRun": 6})
        event = self.store.replay_events(fixed["branch"])[-1]
        self.assertEqual(event["payload"]["execution"]["exit_code"], 0)
        self.assertIn("OK", event["payload"]["execution"]["output"])
        self.assertEqual(self.store.events("main"), before)
        self.assertTrue(self.store.verify("main"))
        self.assertTrue(self.store.verify(fixed["branch"]))

    def test_saved_workspace_reproduces_the_recorded_failure(self):
        workspace = Path(self.tmp.name) / "workspace"
        process = subprocess.run([sys.executable, "-B", "test_retry.py"],
                                 cwd=workspace, capture_output=True, text=True, timeout=5)
        self.assertEqual(process.returncode, 1)
        result = json.loads(process.stdout)
        self.assertEqual((result["passed"], result["failed"]), (5, 1))
        self.assertIn("ConnectionError", result["output"])
        self.assertNotIn("NameError", result["output"])

    def test_chained_change_uses_selected_version(self):
        fixed = bridge.clamp(self.store, "main", "/retryBudget", 3)
        self.assertEqual(bridge.computation(self.store, fixed["branch"])["inputs"], {"/retryBudget": 3})
        again = bridge.clamp(self.store, fixed["branch"], "/retryBudget", 2)
        self.assertEqual(again["figures"]["/testsFailed"], 1)

    def test_invalid_changes_create_nothing(self):
        before = bridge.versions(self.store)
        for value in [-1, 9, 2.5, True, float("nan"), "3"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                bridge.clamp(self.store, "main", "/retryBudget", value)
        with self.assertRaises(ValueError):
            bridge.clamp(self.store, "main", "/arbitraryCode", 3)
        self.assertEqual(bridge.versions(self.store), before)

    def test_house_rule_blocks_fork(self):
        self.store.typed_edit("main", "pin", "/testsPassed", 5)
        before = bridge.versions(self.store)
        result = bridge.clamp(self.store, "main", "/retryBudget", 3)
        self.assertFalse(result["accepted"])
        self.assertIn("/testsPassed", result["violations"])
        self.assertEqual(bridge.versions(self.store), before)

    def test_recorded_source_is_never_execution_authority(self):
        payload = dict(self.store.replay_events("main")[-1]["payload"])
        payload["execution"] = {"source": "raise RuntimeError('untrusted recording')"}
        self.store.append("main", "model_call", payload)
        fixed = bridge.clamp(self.store, "main", "/retryBudget", 3)
        self.assertEqual(fixed["figures"]["/testsFailed"], 0)

    def test_version_mismatch_cannot_execute(self):
        payload = dict(self.store.replay_events("main")[-1]["payload"])
        payload["program_sha256"] = "unsupported-version"
        self.store.append("main", "model_call", payload)
        self.assertIsNone(bridge.computation(self.store, "main"))
        with self.assertRaisesRegex(ValueError, "original retry program"):
            bridge.clamp(self.store, "main", "/retryBudget", 3)
