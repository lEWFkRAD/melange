"""JSON-lines driver: the Viewer model behind a pipe.

This is the seam the Hermes TUI widget (tui-widgets/melange.mjs) uses to
drive the reference viewer without reimplementing any of it. Every store
operation still goes through living_replay.bridge exactly as in tui.py;
this module only speaks a line protocol and reports what the model says.

Protocol (one JSON object per line, both directions):

  in:  {"cmd": "key",    "token": "right"}   -> Viewer.handle_key(token)
       {"cmd": "tick"}                        -> play timer fired: step
                                                 forward, stop at the end
                                                 (the curses shell's rule)
       {"cmd": "size",   "rows": 24, "cols": 80}
       {"cmd": "quit"}                         -> final reply, then exit

  out: {"ok": true, "screen": [...], "bar": "...", "hint": "...",
        "message": "...", "playing": bool, "next_gap_s": float,
        "steps": int, "pos": int, "picking": bool, "done": bool}

Every command is answered with one full snapshot, so the widget never has
to guess what changed. Errors come back as {"ok": false, "error": "..."}
and never kill the driver — a bad token is the widget's bug, not a reason
to lose the recording.
"""
from __future__ import annotations

import json
import sys

from . import tui
from .tui import Viewer, open_store


def snapshot(viewer: Viewer) -> dict:
    """Everything the widget renders, straight from the model."""
    empty = viewer.branch is None
    return {
        "ok": True,
        "screen": viewer.screen_lines(),
        "bar": viewer.bar_line() if not empty else "",
        "hint": viewer.hint_line(),
        "message": viewer.message,
        "playing": viewer.playing,
        "next_gap_s": viewer.next_gap_s() if not empty else 0.1,
        "steps": viewer.steps,
        "pos": 0 if empty else viewer.pos,
        "picking": viewer.picking,
        "done": viewer.done,
    }


def apply(viewer: Viewer, req: dict) -> dict:
    cmd = req.get("cmd")
    if cmd == "key":
        viewer.handle_key(str(req.get("token", "")))
    elif cmd == "tick":
        # The play timer fired: same rule as _curses_main's getch timeout.
        if not viewer.step_forward():
            viewer.playing = False
    elif cmd == "size":
        viewer.set_size(int(req.get("rows", 24)), int(req.get("cols", 80)))
    elif cmd == "quit":
        viewer.done = True
    else:
        return {"ok": False, "error": f"unknown cmd: {cmd!r}"}
    return snapshot(viewer)


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="living-replay-tui-driver")
    parser.add_argument("timeline", help="timeline directory")
    parser.add_argument("--branch", default=None)
    parser.add_argument("--rows", type=int, default=24)
    parser.add_argument("--cols", type=int, default=80)
    args = parser.parse_args(argv)

    store = open_store(args.timeline)
    viewer = Viewer(store, branch=args.branch, rows=args.rows, cols=args.cols,
                    headless=True)

    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            out.write(json.dumps({"ok": False, "error": f"bad json: {exc}"}) + "\n")
            out.flush()
            continue
        try:
            reply = apply(viewer, req)
        except Exception as exc:  # noqa: BLE001 - the pipe must survive
            reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            reply.update(snapshot(viewer))
        out.write(json.dumps(reply, ensure_ascii=False) + "\n")
        out.flush()
        if viewer.done:
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
