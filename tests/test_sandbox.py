"""Sandbox gates B2-G1/G2 — run only on the KVM sandbox host.

Skipped unless LR_SANDBOX_DIR points at a prepared sandbox (see
sandbox/build_sandbox.sh). Measured on onyx-Linux 2026-10-15 with
Firecracker v1.17.0: boot-to-checkpoint 1.082s, snapshot create 0.43s,
10/10 forks restored and completed, restore-to-work p50 0.007s /
p95 0.012s (bar: <1s), original total=42, fork (note amount=50)
total=100, both verified by host-side replay, shared prefix 3 events.
"""
import json, os, subprocess, sys, unittest
from pathlib import Path

SB = os.environ.get("LR_SANDBOX_DIR")

@unittest.skipUnless(SB, "LR_SANDBOX_DIR not set (sandbox host only)")
class SandboxGate(unittest.TestCase):
    def test_b2g1_g2_firecracker_fork(self):
        repo = Path(__file__).resolve().parent.parent
        env = dict(os.environ, LR_SANDBOX_DIR=SB, LR_FORKS=os.environ.get("LR_FORKS", "10"))
        proc = subprocess.run([sys.executable, str(repo / "sandbox" / "run_experiment.py")],
                              capture_output=True, text=True, env=env, timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stdout[-2000:] + proc.stderr[-2000:])
        results = json.loads(proc.stdout[proc.stdout.index("{"):])
        self.assertEqual(results["forks_measured"], int(env["LR_FORKS"]))
        self.assertLess(results["restore_to_work_p95"], 1.0)
        self.assertIn("verified", results["orig_final"]); self.assertIn("verified", results["fork_final"])
        self.assertGreaterEqual(results["shared_prefix_events"], 3)
        print(f"\nB2-G1/G2 measured: boot {results['boot_to_checkpoint_s']}s, snapshot "
              f"{results['snapshot_create_s']}s, restore-to-work p95 "
              f"{results['restore_to_work_p95']}s over {results['forks_measured']} forks")

if __name__ == "__main__":
    unittest.main()
