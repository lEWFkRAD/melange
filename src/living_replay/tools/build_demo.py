"""Build a demo Melange recording on any platform (no PTY needed).

Writes a native-fidelity timeline: a sequence of terminal_chunk events
that paint a small "quarterly report" session, with recorded gaps
between steps so playback has a real pace. Used by the TUI widget's
evidence runs and by anyone who wants a recording to point the bar at
without a live capture.

Usage:  python -m living_replay.tools.build_demo <dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..grid import Grid
from ..store import TimelineStore

# (text, gap_seconds_before_this_step). The first chunk paints a prompt;
# later chunks type a report and its numbers, so where-from has real
# answers to give and the slider has notes to mark.
SCRIPT = [
    ("$ report --quarter Q3\n", 0.0),
    ("Loading ledger...\n", 1.2),
    ("Revenue:   1,204,500.00\n", 0.8),
    ("Expenses:    887,310.55\n", 0.6),
    ("Margin:        317,189.45\n", 2.5),
    ("Headcount:            14\n", 0.4),
    ("\nQ3 closed. Draft due Friday.\n", 1.0),
    ("$ \x1b[K", 0.3),
]


def build(root: str | Path) -> Path:
    root = Path(root)
    store = TimelineStore(root)
    grid = Grid(rows=10, cols=60)
    stamp_ns = 0
    for text, gap in SCRIPT:
        stamp_ns += int(gap * 1e9)
        eid = store.append("main", "terminal_chunk",
                           {"blob": store.put_blob(text.encode()),
                            "offset": 0, "length": len(text),
                            "tool_event": None},
                           mono_ns=stamp_ns)
        grid.feed(text.encode(), eid, None, 0)
        store.append("main", "grid_keyframe",
                     {"blob": store.put_blob(grid.snapshot()), "through": eid},
                     mono_ns=stamp_ns)
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m living_replay.tools.build_demo <dir>")
    print(build(sys.argv[1]))
