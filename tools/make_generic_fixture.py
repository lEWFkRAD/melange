"""Generate tests/generic-build-record.jsonl: a REAL second program's
session, recorded in the generic event format (M10 proof workload).

The program is an ordinary shell session in this repo — git commands
and the repo's own unittest runner — none of it Hermes, none of it
staged. Commands actually execute; their output lines, exit codes and
the session state (branch, dirty-file count, running test tallies
parsed from the runner's own verbose output) are streamed into the
generic JSONL format documented in docs/generic-ingest.md. State
snapshots ride on each command's exit event, which is what earns the
recording structure fidelity at ingest.

Run from anywhere:  python3 tools/make_generic_fixture.py
Re-running regenerates the fixture (timestamps and tallies are the
real ones of that run; tests assert structure, not exact values).
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "tests" / "generic-build-record.jsonl"

COMMANDS = [
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    ["git", "log", "--oneline", "-3"],
    ["git", "status", "--porcelain"],
    [sys.executable, "-m", "unittest", "-v",
     "tests.test_ingest", "tests.test_house_rules"],
]

TEST_LINE = re.compile(r"^(\S+) \(([\w.]+)\) \.\.\. (ok|FAIL|ERROR|skipped)")


def main() -> int:
    env = dict(os.environ, PYTHONPATH="src")
    events = []

    def emit(action, payload, state=None, actor="shell"):
        ev = {"ts": time.time(), "actor": actor, "action": action,
              "payload": payload}
        if state is not None:
            ev["state"] = state
        events.append(ev)

    state = {"cwd": str(REPO), "branch": None, "commands_run": 0,
             "last_exit": None, "tests_run": 0, "tests_failed": 0,
             "tests_errored": 0, "worktree_dirty_files": None}
    emit("session_start", {"program": "shell session (git + unittest)",
                           "repo": REPO.name}, state=dict(state))
    for argv in COMMANDS:
        emit("command", {"argv": argv})
        proc = subprocess.Popen(argv, cwd=REPO, env=env,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True)
        out_lines = []
        for line in proc.stdout:
            line = line.rstrip("\n")
            out_lines.append(line)
            emit("output", {"stream": "stdout", "text": line})
            m = TEST_LINE.match(line)
            if m:
                state["tests_run"] += 1
                if m.group(3) == "FAIL":
                    state["tests_failed"] += 1
                elif m.group(3) == "ERROR":
                    state["tests_errored"] += 1
        code = proc.wait()
        state["commands_run"] += 1
        state["last_exit"] = code
        if argv[:2] == ["git", "rev-parse"] and out_lines:
            state["branch"] = out_lines[0].strip()
        if argv[:2] == ["git", "status"]:
            state["worktree_dirty_files"] = len(
                [l for l in out_lines if l.strip()])
        emit("exit", {"argv": argv, "code": code}, state=dict(state))
        if code != 0:
            print(f"command failed ({code}): {argv}", file=sys.stderr)
            return 1
    emit("session_end", {"commands": state["commands_run"],
                         "tests_run": state["tests_run"]},
         state=dict(state))
    OUT.write_text("".join(json.dumps(e) + "\n" for e in events))
    print(f"wrote {OUT}: {len(events)} events, "
          f"tests_run={state['tests_run']} failed={state['tests_failed']} "
          f"errored={state['tests_errored']} branch={state['branch']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
