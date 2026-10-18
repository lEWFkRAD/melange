"""Melange TUI viewer: watch a recording, step through it, ask where a
word on the screen came from, pin notes, and try it differently.

This is the terminal surface from the Melange UX design (section 4):
the same transport bar, the same office words, and the same honesty
rules as the desktop bar. The screen at the current step fills the top;
below it sit the bar, one hint line, and a message line where answers
appear (where-from sentences, refusal sentences, note confirmations).

Every store operation goes through living_replay.bridge, the one
UI-facing API: screens, parts, frames, where-from, notes, try-
differently, the seal, versions and caps. The single exception is step
enumeration: the bridge takes event ids as inputs (screen_at's
`through`, where_from's `event_id`) but offers no way to list them, so
the viewer reads replay_events metadata (ids and mono_ns timestamps)
to know which steps exist and how far apart they were recorded. No
replay, reconstruction, or fidelity decision is made here.

Fidelity refusals are the design's plain sentences, never the raw
FidelityError text:

- outline recording: "Steps cannot be changed in an outline recording:
  the words themselves were not kept."
- video-only recording: "This is a video-only recording: only pictures
  of the screen were kept."

Headless mode (--script "right,note:check this,quit") drives the same
Viewer model without curses and prints the final rendered screen; it
exists for tests and demos. Script keys: right, left, play (advances
5 steps), pause, note:<text>, try:<instruction>, where:<row>,<col>,
version, quit. Note and instruction texts may not contain commas (the
script is comma-separated).
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import bridge, ingest
from .crypto import LocalKeyProvider
from .store import TimelineStore

try:
    import curses
except ImportError:  # pragma: no cover - curses is stdlib on Linux
    curses = None

REFUSALS = {
    "structure": ("Steps cannot be changed in an outline recording: "
                  "the words themselves were not kept."),
    "screen-only": ("This is a video-only recording: only pictures of "
                    "the screen were kept."),
}

KIND_WORDS = {
    "native": "full recording",
    "structure": "outline recording",
    "screen-only": "video-only recording",
}

HINT = ("keys: space play/pause | arrows step | shift+arrows jump 10 | "
        "i try differently | n note | w where-from | b version | q quit")

TRACK_WIDTH = 20
MIN_GAP_S = 0.1
MAX_GAP_S = 2.0


def open_store(path):
    """Open a timeline directory, encrypted or plain.

    Follows sandbox/export_render.py's pattern: when the store carries
    a wrapped key (key.json), the master key comes from the
    LIVING_REPLAY_KEY env var or a master.b64 beside/inside the tree.
    """
    root = Path(path)
    provider = None
    if (root / "key.json").exists():
        if os.environ.get("LIVING_REPLAY_KEY"):
            provider = LocalKeyProvider.from_env()
        else:
            for cand in (root / "master.b64", root.parent / "master.b64"):
                if cand.exists():
                    provider = LocalKeyProvider.from_file(cand)
                    break
    return TimelineStore(root, key_provider=provider)


class Viewer:
    """The viewer model: one recording, one current version and step.

    Both the curses shell and the headless script mode drive this
    class through handle_key(); rendering is plain text lines.
    """

    def __init__(self, store, branch=None, rows=24, cols=80, headless=False):
        self.store = store
        self.rows = rows
        self.cols = cols
        self.headless = headless
        self.playing = False
        self.done = False
        self.picking = False
        self.cursor = (0, 0)
        self.show_parts = False
        self.message = ""
        self.branch = None
        self.fidelity = "native"
        self._versions = bridge.versions(store)
        if branch is None:
            branch = self._default_branch()
        if branch is not None:
            self._load_branch(branch, pos=0)

    # ---------- version / step bookkeeping ----------

    def _default_branch(self):
        names = [v["name"] for v in self._versions]
        if not names:
            return None
        if "main" in names:
            return "main"
        for v in self._versions:
            if v["fork"] is None:
                return v["name"]
        return names[0]

    def _version_info(self, name):
        for v in self._versions:
            if v["name"] == name:
                return v
        return None

    def _owner_map(self, name):
        """Map each step's event id to the version that recorded it.

        A What-if's history is composed: the split step and everything
        before it were recorded by the parent version. This matters
        because the backend composes a fork's prefix only when the
        `through` step is the fork step or later, so a prefix step's
        screen and where-from must be asked of the version that
        recorded it (through the bridge, like everything else).
        """
        owners = {}
        seen = set()
        branch = name
        while branch is not None and branch not in seen:
            seen.add(branch)
            for e in self.store.events(branch):
                owners.setdefault(e["id"], branch)
            info = self._version_info(branch)
            branch = (info["fork"]["parent_branch"]
                      if info is not None and info["fork"] else None)
        return owners

    def _owner_of(self, event_id):
        return self._owners.get(event_id, self.branch)

    def _load_branch(self, name, pos=0):
        info = self._version_info(name)
        if info is None:
            raise KeyError(f"no version named {name!r}")
        self.branch = name
        self.fidelity = info["fidelity"]
        self.show_parts = False
        self.picking = False
        self._owners = self._owner_map(name)
        events = self.store.replay_events(name)
        if self.fidelity == "screen-only":
            # Steps are the kept pictures; scrub is frame_at checks.
            events = [e for e in events if e["kind"] == "screen_frame"]
        self.events = events
        self.pos = max(0, min(pos, len(events) - 1)) if events else 0
        self._note_steps = self._note_step_indexes()

    def refresh_versions(self):
        self._versions = bridge.versions(self.store)

    @property
    def steps(self):
        return len(self.events) if self.branch else 0

    @property
    def current_event_id(self):
        if not self.branch or not self.events:
            return None
        return self.events[self.pos]["id"]

    def display_name(self):
        """The version's office word: Original, or the What-if's name."""
        if self.branch is None:
            return "Original"
        info = self._version_info(self.branch)
        if info is not None and info["fork"] is None:
            first_root = next(
                (v["name"] for v in self._versions if v["fork"] is None), None)
            if self.branch == first_root:
                return "Original"
            return self.branch
        name = self.branch
        return name[:1].upper() + name[1:]

    def kind_word(self):
        return KIND_WORDS[self.fidelity]

    def seal_word(self):
        if self.branch is None:
            return "NOT CHECKED"
        return "checked" if bridge.seal(self.store, self.branch) else "NOT CHECKED"

    def _note_step_indexes(self):
        if self.branch is None:
            return set()
        by_id = {e["id"]: i for i, e in enumerate(self.events)}
        return {by_id[n["at_event"]] for n in bridge.notes(self.store, self.branch)
                if n["at_event"] in by_id}

    # ---------- movement ----------

    def _after_move(self):
        if self.pos in self._note_steps:
            text = next(n["text"] for n in bridge.notes(self.store, self.branch)
                        if n["at_event"] == self.current_event_id)
            self.message = f"Note at this step: {text}"
        else:
            self.message = ""

    def step_forward(self):
        """Advance one step; False when already at the last step."""
        if self.pos < self.steps - 1:
            self.pos += 1
            self._after_move()
            return True
        return False

    def step_back(self):
        if self.pos > 0:
            self.pos -= 1
            self._after_move()
            return True
        return False

    def advance(self, n):
        moved = False
        for _ in range(n):
            if not self.step_forward():
                break
            moved = True
        return moved

    def next_gap_s(self):
        """Seconds before the next step when playing: the recorded gap
        between this step and the next, clamped to 0.1s..2s."""
        if self.pos >= self.steps - 1:
            return MIN_GAP_S
        cur, nxt = self.events[self.pos], self.events[self.pos + 1]
        ts_cur, ts_nxt = cur["payload"].get("ts"), nxt["payload"].get("ts")
        if isinstance(ts_cur, (int, float)) and isinstance(ts_nxt, (int, float)):
            dt = ts_nxt - ts_cur
        else:
            dt = (nxt["mono_ns"] - cur["mono_ns"]) / 1e9
        return min(max(dt, MIN_GAP_S), MAX_GAP_S)

    # ---------- operations (all through the bridge) ----------

    def refusal(self, exc=None):
        return REFUSALS.get(self.fidelity,
                            str(exc) if exc else "That is not allowed here.")

    def add_note(self, text):
        if self.branch is None or not text:
            return
        try:
            bridge.add_note(self.store, self.branch, self.current_event_id, text)
        except ingest.FidelityError as exc:
            self.message = self.refusal(exc)
            return
        self._note_steps = self._note_step_indexes()
        self.message = f"Note saved at step {self.pos + 1}: {text}"

    def try_differently(self, instruction):
        if self.branch is None or not instruction:
            return
        existing = {v["name"] for v in self._versions}
        name, n = "what-if", 2
        while name in existing:
            name = f"what-if-{n}"
            n += 1
        checkpoint = self.current_event_id
        split_step = self.pos + 1
        try:
            out = bridge.try_differently(
                self.store, self.branch, checkpoint, name, instruction)
        except ingest.FidelityError as exc:
            self.message = self.refusal(exc)
            return
        self.refresh_versions()
        self._load_branch(out["branch"], pos=0)
        ids = [e["id"] for e in self.events]
        if checkpoint in ids:
            self.pos = ids.index(checkpoint)
        self.message = (
            f"Made the What-if from step {split_step}. Saved as the first "
            "step of the What-if. It runs when this recording is reopened "
            "in a live session.")

    def ask_where(self, row, col):
        if self.branch is None:
            return
        try:
            result = bridge.where_from(
                self.store, self._owner_of(self.current_event_id),
                self.current_event_id, row, col)
        except ingest.FidelityError as exc:
            self.message = self.refusal(exc)
            return
        self.message = result["sentence"]

    def look_inside(self):
        """Ask the bridge for the parts list; refused kinds answer with
        the design's sentence for their recording kind."""
        if self.branch is None:
            return
        try:
            bridge.parts_at(self.store, self._owner_of(self.current_event_id),
                            self.current_event_id)
        except ingest.FidelityError as exc:
            self.message = self.refusal(exc)
            return
        except ValueError:
            self.message = "This recording does not keep a parts list."
            return
        self.show_parts = True
        self.message = "Looking inside: the parts this screen is made of."

    def switch_version(self):
        names = [v["name"] for v in self._versions]
        if len(names) < 2 or self.branch is None:
            return
        nxt = names[(names.index(self.branch) + 1) % len(names)]
        pos = self.pos
        self._load_branch(nxt, pos=pos)
        self._after_move()

    # ---------- key handling (shared by curses and script modes) ----------

    def handle_key(self, token):
        if token == "quit":
            self.done = True
        elif token == "space":
            self.playing = not self.playing
        elif token == "play":
            if self.headless:
                self.advance(5)
            else:
                self.playing = True
        elif token == "pause":
            self.playing = False
        elif token == "left":
            if self.picking:
                self._move_cursor(0, -1)
            else:
                self.step_back()
        elif token == "right":
            if self.picking:
                self._move_cursor(0, 1)
            else:
                self.step_forward()
        elif token == "jump-left":
            for _ in range(10):
                if not self.step_back():
                    break
        elif token == "jump-right":
            for _ in range(10):
                if not self.step_forward():
                    break
        elif token == "up":
            if self.picking:
                self._move_cursor(-1, 0)
        elif token == "down":
            if self.picking:
                self._move_cursor(1, 0)
        elif token == "pick":
            if self.fidelity == "screen-only":
                self.ask_where(0, 0)  # the bridge refuses; shows the sentence
            else:
                self.picking = True
                self.cursor = (0, 0)
                self.message = ("Pick a word or number on the screen: arrows "
                                "move, Enter asks where it came from, Esc "
                                "goes back.")
        elif token == "enter":
            if self.picking:
                self.ask_where(*self.cursor)
        elif token == "escape":
            self.picking = False
        elif token == "version":
            self.switch_version()
        elif token == "parts":
            self.look_inside()
        elif token.startswith("note:"):
            self.add_note(token[len("note:"):].strip())
        elif token.startswith("try:"):
            self.try_differently(token[len("try:"):].strip())
        elif token.startswith("where:"):
            row, _, col = token[len("where:"):].partition(",")
            self.ask_where(int(row), int(col))

    def _move_cursor(self, dr, dc):
        r, c = self.cursor
        self.cursor = (min(max(r + dr, 0), max(self.rows - 4, 0)),
                       min(max(c + dc, 0), max(self.cols - 1, 0)))

    # ---------- rendering ----------

    def screen_lines(self):
        limit = max(self.rows - 3, 1)
        if self.branch is None or self.steps == 0:
            return ["This recording has no steps yet."]
        if self.fidelity == "screen-only":
            return self._frame_lines()
        if self.fidelity == "structure" or self.show_parts:
            return self._parts_lines(limit)
        text = bridge.screen_at(self.store,
                                self._owner_of(self.current_event_id),
                                self.current_event_id)
        lines = [ln.rstrip() for ln in text.split("\n")]
        while lines and not lines[-1]:
            lines.pop()
        return [ln[:self.cols] for ln in lines[:limit]] or [""]

    def _frame_lines(self):
        index = self.pos
        try:
            bridge.frame_at(self.store, self.branch, index)  # existence only
        except Exception:
            return ["That picture is missing from the recording."]
        return [
            f"Frame {index + 1} of {self.steps} - video-only recording",
            f"step {self.pos + 1} of {self.steps} | {self.display_name()}",
            "Only pictures of the screen were kept; there is no text "
            "to look inside.",
        ]

    def _parts_lines(self, limit):
        try:
            parts = bridge.parts_at(self.store,
                                    self._owner_of(self.current_event_id),
                                    self.current_event_id)
        except ingest.FidelityError as exc:
            return [self.refusal(exc)]
        except ValueError:
            return ["No parts recorded yet at this step."]
        lines = [f"The screen at this step is made of {len(parts)} parts:"]
        for node in parts.values():
            role = node.get("role") or "part"
            name = node.get("name")
            lines.append(f"{role}: {name}" if name else role)
            if len(lines) >= limit:
                break
        return lines[:limit]

    def _track(self, width):
        if self.steps <= 1:
            return "*" + "-" * (width - 1) if self.steps else "-" * width
        star = round(self.pos / (self.steps - 1) * (width - 1))
        chars = []
        for i in range(width):
            step_idx = round(i / (width - 1) * (self.steps - 1))
            if i == star:
                chars.append("*")
            elif step_idx in self._note_steps:
                chars.append("o")
            elif i < star:
                chars.append("=")
            else:
                chars.append("-")
        return "".join(chars)

    def bar_line(self):
        btn = "[|| pause]" if self.playing else "[> play]"
        step = self.pos + 1 if self.steps else 0
        prefix = f"[<<] {btn} [>>]  step {step}/{self.steps}  "
        suffix = (f"  {self.display_name()} | {self.seal_word()} | "
                  f"{self.kind_word()}")
        # The words on the bar are the contract; the slider track is
        # what shrinks on a narrow terminal, never the words.
        width = min(TRACK_WIDTH,
                    max(self.cols - len(prefix) - len(suffix), 3))
        return (prefix + self._track(width) + suffix)[:self.cols]

    def hint_line(self):
        return HINT[:self.cols]

    def render(self):
        """The full text screen: screen, bar, hint, message."""
        return "\n".join(self.screen_lines() +
                         [self.bar_line(), self.hint_line(), self.message])

    def set_size(self, rows, cols):
        self.rows, self.cols = rows, cols


# ---------- headless script mode ----------

def parse_script(script):
    """Split a --script string into model tokens.

    where:<row>,<col> itself contains a comma, so its two halves are
    rejoined here.
    """
    raw = [t.strip() for t in script.split(",")]
    tokens, i = [], 0
    while i < len(raw):
        tok = raw[i]
        if tok.startswith("where:") and i + 1 < len(raw):
            tokens.append(f"{tok},{raw[i + 1]}")
            i += 2
        else:
            tokens.append(tok)
            i += 1
    return [t for t in tokens if t]


def run_script(viewer, script):
    for token in parse_script(script):
        viewer.handle_key(token)
        if viewer.done:
            break
    return viewer.render()


# ---------- interactive curses shell (thin, over the same model) ----------

def _curses_prompt(stdscr, label, width):
    import curses as _c
    height, _ = stdscr.getmaxyx()
    y = height - 1
    stdscr.move(y, 0)
    stdscr.clrtoeol()
    stdscr.addnstr(y, 0, label, max(width - 1, 1))
    _c.echo()
    _c.curs_set(1)
    try:
        raw = stdscr.getstr(y, len(label), max(width - len(label) - 1, 10))
    finally:
        _c.noecho()
        _c.curs_set(0)
    return raw.decode("utf-8", "replace").strip()


def _curses_main(stdscr, viewer):
    import curses as _c
    stdscr.keypad(True)
    _c.curs_set(0)
    while not viewer.done:
        height, width = stdscr.getmaxyx()
        viewer.set_size(height, width)
        stdscr.erase()
        for i, line in enumerate(viewer.screen_lines()[:max(height - 3, 0)]):
            stdscr.addnstr(i, 0, line, max(width - 1, 1))
        stdscr.addnstr(height - 3, 0, viewer.bar_line(), max(width - 1, 1))
        stdscr.addnstr(height - 2, 0, viewer.hint_line(), max(width - 1, 1))
        msg = viewer.message
        if viewer.picking:
            msg = (f"row {viewer.cursor[0]}, col {viewer.cursor[1]} | " + msg)
        stdscr.addnstr(height - 1, 0, msg, max(width - 1, 1))
        if viewer.picking:
            _c.curs_set(1)
            stdscr.move(min(viewer.cursor[0], max(height - 4, 0)),
                        min(viewer.cursor[1], max(width - 1, 0)))
        else:
            _c.curs_set(0)
        stdscr.refresh()
        stdscr.timeout(int(viewer.next_gap_s() * 1000) if viewer.playing else -1)
        key = stdscr.getch()
        if key == -1:  # play timer fired
            if not viewer.step_forward():
                viewer.playing = False
            continue
        if viewer.picking:
            if key in (_c.KEY_LEFT,):
                viewer.handle_key("left")
            elif key in (_c.KEY_RIGHT,):
                viewer.handle_key("right")
            elif key in (_c.KEY_UP,):
                viewer.handle_key("up")
            elif key in (_c.KEY_DOWN,):
                viewer.handle_key("down")
            elif key in (10, 13, _c.KEY_ENTER):
                viewer.handle_key("enter")
            elif key == 27:
                viewer.handle_key("escape")
            continue
        if key == ord("q"):
            viewer.handle_key("quit")
        elif key == ord(" "):
            viewer.handle_key("space")
        elif key == _c.KEY_LEFT:
            viewer.handle_key("left")
        elif key == _c.KEY_RIGHT:
            viewer.handle_key("right")
        elif key in (_c.KEY_SLEFT, _c.KEY_PPAGE):
            viewer.handle_key("jump-left")
        elif key in (_c.KEY_SRIGHT, _c.KEY_NPAGE):
            viewer.handle_key("jump-right")
        elif key == ord("b"):
            viewer.handle_key("version")
        elif key == ord("w"):
            viewer.handle_key("pick")
        elif key == ord("i"):
            text = _curses_prompt(stdscr, "New instruction at this step: ", width)
            if text:
                viewer.handle_key("try:" + text)
        elif key == ord("n"):
            text = _curses_prompt(stdscr, "Note for this step: ", width)
            if text:
                viewer.handle_key("note:" + text)


# ---------- entry point ----------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="living-replay-tui",
        description="Watch a Melange recording in the terminal.")
    parser.add_argument("timeline", help="timeline directory")
    parser.add_argument("--branch", default=None,
                        help="version to open (default: the Original)")
    parser.add_argument("--script", default=None,
                        help="comma-separated keys, run headlessly and print")
    parser.add_argument("--rows", type=int, default=24)
    parser.add_argument("--cols", type=int, default=80)
    args = parser.parse_args(argv)

    store = open_store(args.timeline)
    if args.branch is not None and args.branch not in [
            v["name"] for v in bridge.versions(store)]:
        parser.error(f"no version named {args.branch!r} in this recording")
    viewer = Viewer(store, branch=args.branch, rows=args.rows, cols=args.cols,
                    headless=args.script is not None)
    if args.script is not None:
        print(run_script(viewer, args.script))
        return 0
    if curses is None:
        parser.error("curses is not available; use --script for headless mode")
    curses.wrapper(_curses_main, viewer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
