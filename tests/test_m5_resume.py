"""M5: fork resumption planning and verification (guest-independent).

The live half (a guest booting and continuing a branch) is proven by
sandbox/run_resume_guest.py on the sandbox host; what can be proven
anywhere is the logic that decides WHERE a resume anchors, WHAT state
goes into the guest, and WHETHER a finished resume kept its three
promises: pre-resume prefix byte-identical, continuation chained onto
the branch tip, parent untouched. These tests build small stores,
fork them, simulate a continuation by appending directly to the
branch (exactly what the guest agent does through the store), and
check the verifier accepts the honest case and refuses the tampered
ones.
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from living_replay import resume  # noqa: E402
from living_replay.forking import snapshot_workspace  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402


def build_store(tmp: Path, key_provider=None) -> tuple[TimelineStore, int, int]:
    """A small 'session': turns around a mid checkpoint, one workspace
    snapshot before it. Returns (store, checkpoint_id, snapshot_id)."""
    store = TimelineStore(tmp / "timeline", key_provider=key_provider)
    store.append("main", "context_note", {"text": "session start", "pinned": False})
    store.append("main", "model_call", {"request": {"messages": []}, "response": {}})
    ws = tmp / "ws-src"; ws.mkdir(exist_ok=True)
    (ws / "brief.md").write_text("brief at checkpoint\n")
    snap = snapshot_workspace(store, "main", ws)
    store.append("main", "tool_call", {"name": "write-brief"})
    ckpt = store.append("main", "context_note", {"text": "checkpoint", "pinned": True})
    store.append("main", "model_call", {"request": {"messages": [1]}, "response": {}})
    store.append("main", "context_note", {"text": "session end", "pinned": False})
    return store, ckpt, snap


def simulate_continuation(store: TimelineStore, branch: str, turns: int = 2) -> None:
    """What the guest agent does: notes and model calls onto the branch."""
    store.append(branch, "context_note",
                 {"text": "session resumed live", "pinned": False, "resume": True})
    for i in range(turns):
        store.append(branch, "context_note",
                     {"text": f"USER TURN {i + 1}: continue", "pinned": False})
        store.append(branch, "model_call",
                     {"request": {"messages": [i]}, "response": {"ok": True}})


class TestPlanResume(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.ckpt, self.snap = build_store(self.tmp)

    def test_plan_on_forked_branch(self):
        fork_id = self.store.fork("main", self.ckpt, "reopen",
                                  edit={"intent": "reopen in a live session"})
        plan = resume.plan_resume(self.store, "reopen", self.ckpt)
        self.assertEqual(plan.parent_branch, "main")
        self.assertEqual(plan.fork_event, fork_id)
        # Logical prefix: main's events through the checkpoint + the fork.
        prefix = self.store.replay_events("main", through=self.ckpt)
        self.assertEqual(plan.prefix_ids,
                         [e["id"] for e in prefix] + [fork_id])
        self.assertEqual(plan.checkpoint_hash,
                         self.store.event(self.ckpt)["hash"])
        self.assertEqual(plan.tip_event, fork_id)
        # The snapshot taken on main before the checkpoint is inherited.
        self.assertEqual(plan.workspace_snapshot_event, self.snap)

    def test_plan_on_root_branch_has_no_parent(self):
        plan = resume.plan_resume(self.store, "main", self.ckpt)
        self.assertIsNone(plan.fork_event)
        self.assertIsNone(plan.parent_branch)
        self.assertEqual(plan.prefix_ids,
                         [e["id"] for e in self.store.events("main")])

    def test_branch_local_snapshot_wins_over_inherited(self):
        self.store.fork("main", self.ckpt, "reopen")
        ws = self.tmp / "ws-later"; ws.mkdir()
        (ws / "brief.md").write_text("brief amended on the branch\n")
        local_snap = snapshot_workspace(self.store, "reopen", ws)
        plan = resume.plan_resume(self.store, "reopen", self.ckpt)
        self.assertEqual(plan.workspace_snapshot_event, local_snap)

    def test_prepare_workspace_restores_snapshot_bytes(self):
        self.store.fork("main", self.ckpt, "reopen")
        plan = resume.plan_resume(self.store, "reopen", self.ckpt)
        dest = resume.prepare_workspace(self.store, plan, self.tmp / "restored")
        self.assertIsNotNone(dest)
        self.assertEqual((Path(dest) / "brief.md").read_text(),
                         "brief at checkpoint\n")

    def test_prepare_workspace_none_without_snapshot(self):
        store = TimelineStore(self.tmp / "bare")
        a = store.append("main", "context_note", {"text": "x", "pinned": False})
        plan = resume.plan_resume(store, "main", a)
        self.assertIsNone(plan.workspace_snapshot_event)
        self.assertIsNone(resume.prepare_workspace(store, plan, self.tmp / "nowhere"))


class TestResolveCheckpoint(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.ckpt, self.snap = build_store(self.tmp)

    def test_checkpoint_above_fork_point_refused(self):
        self.store.fork("main", self.ckpt, "reopen")
        after = self.store.events("main")[-1]["id"]  # on main, past the fork
        with self.assertRaises(ValueError):
            resume.plan_resume(self.store, "reopen", after)

    def test_checkpoint_from_sibling_branch_refused(self):
        self.store.fork("main", self.ckpt, "fork-a")
        fork_b_event = self.store.fork("main", self.ckpt, "fork-b")
        with self.assertRaises(ValueError):
            resume.plan_resume(self.store, "fork-a", fork_b_event)

    def test_nonexistent_checkpoint_refused(self):
        with self.assertRaises(ValueError):
            resume.plan_resume(self.store, "main", 999999)

    def test_empty_branch_refused(self):
        with self.assertRaises(ValueError):
            resume.plan_resume(self.store, "never-written", self.ckpt)

    def test_nested_fork_checkpoint_in_grandparent_prefix(self):
        self.store.fork("main", self.ckpt, "fork-a")
        local = self.store.append("fork-a", "context_note",
                                  {"text": "fork-a continues", "pinned": False})
        self.store.fork("fork-a", local, "fork-b")
        plan = resume.plan_resume(self.store, "fork-b", self.ckpt)
        self.assertEqual(plan.parent_branch, "fork-a")
        self.assertIn(self.ckpt, plan.prefix_ids)
        self.assertIn(local, plan.prefix_ids)


class TestVerifyResume(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.ckpt, self.snap = build_store(self.tmp)
        self.store.fork("main", self.ckpt, "reopen")
        self.plan = resume.plan_resume(self.store, "reopen", self.ckpt)
        self.parent_state = resume.capture_branch_state(self.store, "main")

    def test_honest_continuation_verifies(self):
        simulate_continuation(self.store, "reopen")
        report = resume.verify_resume(self.store, self.plan,
                                      parents={"main": self.parent_state})
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["prefix_ok"])
        self.assertTrue(report["chain_ok"])
        self.assertTrue(report["parents_ok"])
        self.assertEqual(report["new_model_calls"], 2)
        self.assertGreater(report["new_events"], 0)
        # The continuation's first local event chains onto the fork event.
        first_new_local = self.store.events("reopen")[1]
        fork_event = self.store.event(self.plan.fork_event)
        self.assertEqual(first_new_local["prev_hash"], fork_event["hash"])

    def test_empty_continuation_fails(self):
        report = resume.verify_resume(self.store, self.plan,
                                      parents={"main": self.parent_state})
        self.assertFalse(report["ok"])
        self.assertFalse(report["continuation_ok"])
        report2 = resume.verify_resume(self.store, self.plan,
                                       parents={"main": self.parent_state},
                                       require_new=False)
        self.assertTrue(report2["ok"], report2)

    def test_parent_append_after_baseline_detected(self):
        simulate_continuation(self.store, "reopen")
        self.store.append("main", "context_note",
                          {"text": "parent moved", "pinned": False})
        report = resume.verify_resume(self.store, self.plan,
                                      parents={"main": self.parent_state})
        self.assertFalse(report["ok"])
        self.assertFalse(report["parents_ok"])
        self.assertFalse(report["parents"]["main"]["unchanged"])
        # The prefix itself is still intact — only the parent check trips.
        self.assertTrue(report["prefix_ok"])

    def test_rewritten_history_detected(self):
        simulate_continuation(self.store, "reopen")
        db = sqlite3.connect(self.store.root / "timeline.sqlite")
        db.execute("UPDATE events SET payload=? WHERE id=?",
                   ('{"tampered":true}', self.ckpt))
        db.commit(); db.close()
        # Verify from a fresh open, as the host runner does — a second
        # connection's write is not visible inside the writer's snapshot.
        reopened = TimelineStore(self.store.root)
        report = resume.verify_resume(reopened, self.plan,
                                      parents={"main": self.parent_state})
        self.assertFalse(report["ok"])
        # A payload-only edit leaves the stored hash sequence standing
        # (prefix_ok) but breaks hash recomputation (chain_ok); a full
        # chain rewrite would instead break prefix_ok against the plan.
        self.assertTrue(report["prefix_ok"])
        self.assertFalse(report["chain_ok"])

    def test_assert_resume_raises_on_failure(self):
        with self.assertRaises(AssertionError):
            resume.assert_resume(self.store, self.plan,
                                 parents={"main": self.parent_state})
        simulate_continuation(self.store, "reopen")
        report = resume.assert_resume(self.store, self.plan,
                                      parents={"main": self.parent_state})
        self.assertTrue(report["ok"])


class TestEncryptedStoreResume(unittest.TestCase):
    def test_plan_and_verify_under_encryption(self):
        try:
            from living_replay.crypto import LocalKeyProvider
        except ImportError:
            self.skipTest("cryptography extra not installed")
        tmp = Path(tempfile.mkdtemp())
        provider = LocalKeyProvider(LocalKeyProvider.generate())
        store, ckpt, _snap = build_store(tmp, key_provider=provider)
        store.fork("main", ckpt, "reopen")
        plan = resume.plan_resume(store, "reopen", ckpt)
        parent_state = resume.capture_branch_state(store, "main")
        simulate_continuation(store, "reopen")
        report = resume.verify_resume(store, plan, parents={"main": parent_state})
        self.assertTrue(report["ok"], report)
        dest = resume.prepare_workspace(store, plan, tmp / "restored")
        self.assertEqual((Path(dest) / "brief.md").read_text(),
                         "brief at checkpoint\n")


if __name__ == "__main__":
    unittest.main()
