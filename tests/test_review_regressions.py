"""Synthetic review counterexamples for stored secrets and chained edits."""
from pathlib import Path
import tempfile
import unittest

from living_replay import bridge, flagship
from living_replay.capture import PtyCapture
from living_replay.runner import ForkContext, run_fork
from living_replay.store import TimelineStore


class ReviewRegressions(unittest.TestCase):
    def test_chained_clamp_keeps_prior_inputs_and_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = flagship.run_flagship(Path(tmp) / "flag")["store"]
            try:
                first = bridge.clamp(store, "main", "/wages", 48000)
                parent = store.events(first["branch"])
                second = bridge.clamp(store, first["branch"], "/withholding", 6200)
                self.assertEqual(second["values"]["/wages"], 48000)
                self.assertEqual(second["figures"]["/totalTax"], 3088)
                self.assertEqual(second["figures"]["/refund"], 3112)
                self.assertEqual(store.events(first["branch"]), parent)
                explained = bridge.explain(store, second["branch"], "/refund", 3112)
                self.assertEqual(explained["current"], 3112)
                self.assertEqual(explained["candidates"], [])
                self.assertTrue(store.verify(second["branch"]))
            finally:
                store.db.close()

    def test_runner_redacts_tool_model_and_note_payloads_before_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = TimelineStore(tmp)
            try:
                ctx = ForkContext(store, "main", [], None, None, PtyCapture(store))
                ctx.call_tool("demo", b"password=synthetic-secret", "token=synthetic-input")
                ctx.call_model("api_key=synthetic-prompt", "sk_abcdefghijklmnop")
                checkpoint = store.events("main")[-1]["id"]
                run_fork(store, "main", checkpoint, "child", lambda c: c.note,
                         note="password=synthetic-note")
                persisted = b"".join(p.read_bytes() for p in Path(tmp).rglob("*") if p.is_file())
                for marker in (b"synthetic-secret", b"synthetic-input", b"synthetic-prompt",
                               b"sk_abcdefghijklmnop", b"synthetic-note"):
                    self.assertNotIn(marker, persisted)
                self.assertTrue(store.verify("main"))
                self.assertTrue(store.verify("child"))
            finally:
                store.db.close()


if __name__ == "__main__":
    unittest.main()
