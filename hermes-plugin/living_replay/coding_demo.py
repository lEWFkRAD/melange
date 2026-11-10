"""Synthetic retry repair using a real, bounded Python test process.

Only the bundled program executes; recorded source is display evidence.
"""
from __future__ import annotations
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

PROFILE = "coding-retry-v1"
TARGET = "/retryBudget"
PROGRAM = '''def retry(operation, retries):
    for attempt in range(retries + 1):
        try:
            return operation()
        except ConnectionError:
            if attempt == retries:
                raise
'''
TESTS = '''
import io
import json
import unittest

def flaky(count):
    calls = 0
    def operation():
        nonlocal calls
        calls += 1
        if calls <= count:
            raise ConnectionError("transient failure")
        return "signal delivered"
    return operation

class RetryTests(unittest.TestCase):
    def test_01_immediate_success(self):
        self.assertEqual(retry(flaky(0), RETRY_BUDGET), "signal delivered")
    def test_02_one_transient_failure(self):
        self.assertEqual(retry(flaky(1), RETRY_BUDGET), "signal delivered")
    def test_03_two_transient_failures(self):
        self.assertEqual(retry(flaky(2), RETRY_BUDGET), "signal delivered")
    def test_04_three_transient_failures(self):
        self.assertEqual(retry(flaky(3), RETRY_BUDGET), "signal delivered")
    def test_05_exhaustion_raises(self):
        with self.assertRaises(ConnectionError):
            retry(flaky(20), RETRY_BUDGET)
    def test_06_preserves_result(self):
        marker = {"status": "delivered"}
        self.assertIs(retry(lambda: marker, RETRY_BUDGET), marker)

stream = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromTestCase(RetryTests)
result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
failed = len(result.failures) + len(result.errors)
print(json.dumps({"tests_run": result.testsRun, "passed": result.testsRun-failed,
                  "failed": failed, "output": stream.getvalue()}))
raise SystemExit(0 if result.wasSuccessful() else 1)
'''
PROGRAM_SHA256 = hashlib.sha256((PROGRAM + TESTS).encode()).hexdigest()


def budget(value) -> int:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value != int(value) or not 0 <= value <= 8):
        raise ValueError("Retry budget must be a whole number from 0 to 8")
    return int(value)


def source_for(value) -> str:
    return f"RETRY_BUDGET = {budget(value)}\n\n" + PROGRAM


def run_suite(value) -> dict:
    value = budget(value)
    source = source_for(value)
    try:
        proc = subprocess.run([sys.executable, "-I", "-B", "-c", source + TESTS],
                              text=True, capture_output=True, timeout=5)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("The retry test process did not finish") from exc
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("The retry test process returned no valid result") from exc
    if (proc.returncode not in (0, 1) or result.get("tests_run") != 6
            or result.get("passed", -1) + result.get("failed", -1) != 6
            or (proc.returncode == 0) != (result.get("failed") == 0)):
        raise ValueError("The retry test process returned an inconsistent result")
    return {"inputs": {TARGET: value},
            "figures": {"/testsPassed": result["passed"], "/testsFailed": result["failed"],
                        "/testsRun": result["tests_run"]},
            "execution": {"command": "python -I -B -c <bundled retry program and tests>",
                          "source": source, "output": result["output"], "exit_code": proc.returncode}}


def _latest(store, branch):
    return next((ev for ev in reversed(store.replay_events(branch))
                 if ev["kind"] == "model_call" and "figures" in (ev["payload"] or {})), None)


def is_recording(store, branch) -> bool:
    ev = _latest(store, branch)
    return bool(ev and ev["payload"].get("profile") == PROFILE)


def _recorded(store, branch):
    ev = _latest(store, branch)
    if not ev or ev["payload"].get("profile") != PROFILE:
        raise ValueError("This recording has no supported retry program")
    if ev["payload"].get("program_sha256") != PROGRAM_SHA256:
        raise ValueError("This recording needs its original retry program version")
    return ev, budget(ev["payload"].get("inputs", {}).get(TARGET))


def computation(store, branch) -> dict:
    ev, value = _recorded(store, branch)
    return {"profile": PROFILE, "inputs": {TARGET: value}, "figures": dict(ev["payload"]["figures"])}


def _payload(report, clamped=None) -> dict:
    out = {"profile": PROFILE, "program_sha256": PROGRAM_SHA256,
           "prompt": "Run the bundled retry test suite", **report, "replayed": False}
    if clamped is not None:
        out.update({"clamped": clamped, "recomputed": list(report["figures"]), "reused": []})
    return out


def run_demo(root: Path) -> dict:
    from .forking import snapshot_workspace
    from .store import TimelineStore
    root = Path(root)
    ws = root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "retry.py").write_text(source_for(2), encoding="utf-8")
    (ws / "test_retry.py").write_text("from retry import retry, RETRY_BUDGET\n" + TESTS, encoding="utf-8")
    store = TimelineStore(root / "timeline")
    store.append("main", "tool_call", {"name": "Read coding task", "output":
        "SYNTHETIC CODING TASK\nThe delivery client must recover from three transient failures.\n"
        "Inspect retry.py, run its six tests, and repair the retry budget."})
    store.append("main", "tool_call", {"name": "Read retry.py", "output": source_for(2)})
    snapshot_workspace(store, "main", ws)
    report = run_suite(2)
    store.append("main", "tool_call", {"name": "Run Python tests",
        "output": report["execution"]["output"], "exit_code": report["execution"]["exit_code"]})
    store.append("main", "model_call", _payload(report))
    return {"store": store, **report}


def clamp(store, parent_branch, target, value, new_branch=None, instruction="") -> dict:
    from . import bridge, house_rules, ingest
    ingest.require_branch_op(store, parent_branch, "clamp")
    if not store.verify(parent_branch):
        raise ValueError("The recording does not check out")
    comp, current = _recorded(store, parent_branch)
    if target != TARGET:
        raise ValueError("Only the recorded Retry budget can be changed")
    value = budget(value)
    names = {v["name"] for v in bridge.versions(store)}
    if new_branch is None:
        base = "whatif-clamp-retryBudget"
        new_branch = base
        i = 2
        while new_branch in names:
            new_branch = f"{base}-{i}"
            i += 1
    if new_branch in names:
        raise ValueError("That What-if already exists")
    reports = {}

    def evaluate(overrides):
        candidate = budget(overrides.get(TARGET, current))
        if candidate not in reports:
            reports[candidate] = run_suite(candidate)
        report = reports[candidate]
        return {**report["inputs"], **report["figures"]}

    result = house_rules.checked_fork(store, parent_branch, comp["id"], new_branch,
        instruction or f"Change Retry budget from {current} to {value}", {TARGET: value}, evaluate)
    if not result["accepted"]:
        return {"accepted": False, "branch": None, "violations": result["violations"], "reason": result["reason"]}
    report = reports[value]
    store.append(new_branch, "model_call", _payload(report, {TARGET: value}), parent_event=result["fork_event"])
    return {"accepted": True, "branch": new_branch, "fork_event": result["fork_event"],
            "target": target, "value": value, "values": result["candidate"], "figures": report["figures"],
            "recomputed": list(report["figures"]), "reused": [], "violations": result["violations"],
            "pins_inherited": result["pins_inherited"]}
