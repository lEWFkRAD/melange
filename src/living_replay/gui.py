"""GUI surface (Build 3): a second Surface beside the terminal.

A synthetic GUI app runs under Xvfb inside the boundary. The surface
records two event kinds into the same hash-chained timeline:
`gui_input` (a driven input: typed text, a click — each bound to a tool
event) and `gui_keyframe` (the app's widget tree plus a framebuffer
grab as a content-addressed blob, taken after the input lands). Every
node in a keyframe carries the id of the input event that produced the
frame — node-to-cause provenance, honestly scoped: this is the app's
own widget tree (an instrumented citizen), not a scraped guess.

Scrubbing reconstructs the tree at any event. A fork restarts the app
with the checkpoint's serialised state plus an optional note override,
exactly the terminal fork's restart semantics on a second surface.
"""
from __future__ import annotations
import json, os, subprocess, sys, time
from pathlib import Path
from typing import Any

from .store import TimelineStore

class Xvfb:
    def __init__(self, display: int = 99, size: str = "400x300x24"):
        self.display = display
        self.proc = subprocess.Popen(["Xvfb", f":{display}", "-screen", "0", size],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            if Path(f"/tmp/.X11-unix/X{display}").exists(): break
            time.sleep(0.1)
    def env(self) -> dict[str, str]:
        return {**os.environ, "DISPLAY": f":{self.display}"}
    def stop(self):
        self.proc.terminate()

def _ppm_from_ximage(img, w: int, h: int) -> bytes:
    """Encode an X GetImage reply (ZPixmap, depth 24) as a binary PPM."""
    data = img.data
    out = bytearray(w * h * 3)
    for i in range(w * h):
        b, g, r = data[i * 4], data[i * 4 + 1], data[i * 4 + 2]
        out[i * 3:i * 3 + 3] = bytes((r, g, b))
    return f"P6\n{w} {h}\n255\n".encode() + bytes(out)

class GuiSession:
    def __init__(self, store: TimelineStore, branch: str, xvfb: Xvfb, ctrl: Path,
                 app_path: str | Path, state_file: str | Path | None = None):
        self.store, self.branch, self.xvfb = store, branch, xvfb
        self.ctrl = Path(ctrl); self.ctrl.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, str(app_path), str(self.ctrl)]
        if state_file: args.append(str(state_file))
        self.app = subprocess.Popen(args, env=xvfb.env(),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._last_n = 0
        self._wait_dump()

    def _read_dump(self):
        try:
            return json.loads((self.ctrl / "tree.json").read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _wait_dump(self, timeout: float = 10.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self._read_dump()
            if d and d["n"] > self._last_n:
                self._last_n = d["n"]; return d
            time.sleep(0.05)
        raise TimeoutError("GUI app did not produce a new tree dump")

    def _x(self):
        from Xlib import display as xdisplay
        return xdisplay.Display(f":{self.xvfb.display}")

    def _find_window(self, d, title: str = "LR Form"):
        root = d.screen().root
        for win in root.query_tree().children:
            try:
                if win.get_wm_name() == title: return win
            except Exception: pass
        raise RuntimeError("app window not found")

    def screenshot_blob(self) -> str:
        d = self._x(); win = self._find_window(d)
        geom = win.get_geometry()
        img = win.get_image(0, 0, geom.width, geom.height, 2, 0xFFFFFFFF)  # ZPixmap
        return self.store.put_blob(_ppm_from_ximage(img, geom.width, geom.height))

    def keyframe(self, after_input: int | None, fresh: bool = False) -> int:
        # After a driven input we wait for the app's next dump; an explicit
        # keyframe uses the latest dump as-is.
        dump = self._wait_dump() if fresh else (self._read_dump() or self._wait_dump())
        return self._record_keyframe(dump, after_input)

    def _record_keyframe(self, dump: dict, after_input: int | None) -> int:
        self._last_n = max(self._last_n, dump["n"])
        blob = self.screenshot_blob()
        return self.store.append(self.branch, "gui_keyframe",
                                 {"tree": dump["tree"], "screenshot": blob, "after_input": after_input})

    def _wait_state(self, predicate, timeout: float = 15.0) -> dict:
        """Poll the app's latest tree dump until predicate(dump) holds.

        A driven input is only real once the app's own state shows it:
        dumps lag inputs on a loaded machine, and an early dump can
        predate the input it is supposed to frame. Waiting for the state
        itself, not just a newer dump counter, is what keeps a keyframe
        honest about the input that caused it."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = self._read_dump()
            if d and predicate(d):
                return d
            time.sleep(0.05)
        raise TimeoutError("GUI app state did not reach the expected state")

    def _focus_and_type(self, field_xy: tuple[int, int], text: str):
        from Xlib import X
        from Xlib.ext import xtest
        d = self._x(); win = self._find_window(d)
        geom = win.get_geometry()
        x, y = geom.x + field_xy[0], geom.y + field_xy[1]
        xtest.fake_input(d, X.MotionNotify, x=x, y=y)
        xtest.fake_input(d, X.ButtonPress, 1); xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()
        # Settle so the entry has input focus before the keys arrive; on a
        # loaded machine an immediate burst can land before the focus does
        # and the text goes nowhere.
        time.sleep(0.15)
        for ch in text:
            self._type_char(d, ch)
            time.sleep(0.01)
        d.sync()

    def _type_char(self, d, ch: str):
        """One XTest keystroke for a character. keysym_to_keycode alone
        loses shifted characters on many keymaps (it finds the keycode
        that carries the keysym, but a bare press yields the unshifted
        keysym, so 'D' arrives as 'd'); hold Shift when the character
        lives on the shifted level of its keycode."""
        from Xlib import X, XK
        from Xlib.ext import xtest
        ks = ord(ch)
        kc = d.keysym_to_keycode(ks)
        shift = False
        if kc:
            try:
                levels = d.get_keyboard_mapping(kc, 1)[0]
                shift = len(levels) > 1 and levels[1] == ks and levels[0] != ks
            except Exception:
                shift = ch.isupper()
        shift_kc = d.keysym_to_keycode(XK.XK_Shift_L) if shift else 0
        if shift_kc: xtest.fake_input(d, X.KeyPress, shift_kc)
        xtest.fake_input(d, X.KeyPress, kc); xtest.fake_input(d, X.KeyRelease, kc)
        if shift_kc: xtest.fake_input(d, X.KeyRelease, shift_kc)

    def _clear_field(self, field_xy: tuple[int, int]):
        """Empty an entry: triple-click selects its contents in Tk, then
        BackSpace deletes the selection; an End + BackSpace sweep covers
        builds where the selection binding differs."""
        from Xlib import X, XK
        from Xlib.ext import xtest
        d = self._x(); win = self._find_window(d)
        geom = win.get_geometry()
        x, y = geom.x + field_xy[0], geom.y + field_xy[1]
        xtest.fake_input(d, X.MotionNotify, x=x, y=y)
        for _ in range(3):
            xtest.fake_input(d, X.ButtonPress, 1); xtest.fake_input(d, X.ButtonRelease, 1)
            time.sleep(0.03)
        d.sync(); time.sleep(0.1)
        bs = d.keysym_to_keycode(XK.XK_BackSpace)
        end = d.keysym_to_keycode(XK.XK_End)
        xtest.fake_input(d, X.KeyPress, bs); xtest.fake_input(d, X.KeyRelease, bs)
        xtest.fake_input(d, X.KeyPress, end); xtest.fake_input(d, X.KeyRelease, end)
        for _ in range(32):
            xtest.fake_input(d, X.KeyPress, bs); xtest.fake_input(d, X.KeyRelease, bs)
        d.sync()

    def _tree_points(self, dump) -> dict:
        """Click points from the app's own latest tree dump (widget centers,
        window-relative): entries in order, plus the Compute button. The
        dump is the surface's source of truth, so the driver follows the
        real layout even when fonts or metrics shift it."""
        points: dict[str, tuple[int, int]] = {}
        if not dump: return points
        entries: list[tuple[int, int]] = []
        def walk(node):
            cx = node.get("x", 0) + node.get("w", 0) // 2
            cy = node.get("y", 0) + node.get("h", 0) // 2
            if node.get("class") == "Entry": entries.append((cx, cy))
            if node.get("class") == "Button" and node.get("text") == "Compute":
                points["compute"] = (cx, cy)
            for c in node.get("children", []): walk(c)
        walk(dump["tree"])
        if entries: points["payee"] = entries[0]
        if len(entries) > 1: points["amount"] = entries[1]
        return points

    def _point_for(self, what: str) -> tuple[int, int]:
        pts = self._tree_points(self._read_dump())
        if what in pts: return pts[what]
        return {"payee": self.PAYEE_FIELD, "amount": self.AMOUNT_FIELD,
                "compute": self.COMPUTE_BTN}[what]

    def _entry_values(self, dump) -> list[str]:
        values: list[str] = []
        def walk(node):
            if node.get("class") == "Entry": values.append(node.get("value", ""))
            for c in node.get("children", []): walk(c)
        if dump: walk(dump["tree"])
        return values

    def _result_text(self, dump) -> str:
        """The form's result label: the Label that is neither field caption."""
        texts: list[str] = []
        def walk(node):
            if node.get("class") == "Label": texts.append(node.get("text", ""))
            for c in node.get("children", []): walk(c)
        if dump: walk(dump["tree"])
        for t in texts:
            if t not in ("Payee", "Amount"): return t
        return ""

    def _click(self, xy: tuple[int, int]):
        from Xlib import X
        from Xlib.ext import xtest
        d = self._x(); win = self._find_window(d)
        geom = win.get_geometry()
        xtest.fake_input(d, X.MotionNotify, x=geom.x + xy[0], y=geom.y + xy[1])
        xtest.fake_input(d, X.ButtonPress, 1); xtest.fake_input(d, X.ButtonRelease, 1)
        d.sync()

    # Widget geometry inside the 320x200 form (title bar excluded):
    PAYEE_FIELD = (160, 45); AMOUNT_FIELD = (160, 95); COMPUTE_BTN = (160, 130)

    def _set_field_once(self, idx: int, text: str):
        field = "payee" if idx == 0 else "amount"
        self._clear_field(self._point_for(field))
        if text: self._focus_and_type(self._point_for(field), text)

    def type_field(self, field: str, text: str) -> int:
        tool = self.store.append(self.branch, "tool_call",
                                 {"name": f"gui-type-{field}", "input": text, "output": ""})
        event = self.store.append(self.branch, "gui_input",
                                  {"action": "type", "field": field, "text": text, "tool": tool})
        idx = 0 if field == "payee" else 1
        other = 1 - idx
        base = self._entry_values(self._read_dump())
        base_other = base[other] if len(base) > other else ""

        def landed(dump) -> bool:
            v = self._entry_values(dump)
            return len(v) > idx and v[idx] == text and \
                (len(v) <= other or v[other] == base_other)

        # Drive, then verify against the app's own state before framing:
        # on a loaded machine a click may not move focus and keystrokes
        # land in the wrong entry, so an attempt that polluted the other
        # field restores it and retries. Three attempts, then fail loudly
        # rather than record a keyframe that misstates the input.
        dump = None
        for attempt in range(3):
            vals = self._entry_values(self._read_dump())
            if len(vals) > other and vals[other] != base_other:
                self._set_field_once(other, base_other)
            cur = self._entry_values(self._read_dump())
            if not (len(cur) > idx and cur[idx] == text):
                self._focus_and_type(self._point_for(field), text) \
                    if attempt == 0 else self._set_field_once(idx, text)
            try:
                dump = self._wait_state(landed, timeout=6.0)
                break
            except TimeoutError:
                if attempt == 2: raise
        self._record_keyframe(dump, after_input=event)
        return event

    def click_compute(self) -> int:
        tool = self.store.append(self.branch, "tool_call",
                                 {"name": "gui-click-compute", "input": "Compute", "output": ""})
        event = self.store.append(self.branch, "gui_input",
                                  {"action": "click", "target": "Compute", "tool": tool})
        # Click, then verify: the keyframe is recorded only from a dump
        # whose result label shows the computation actually ran. A missed
        # click produces no such dump, so re-aim and click again.
        dump = None
        for attempt in range(3):
            self._click(self._point_for("compute"))
            try:
                dump = self._wait_state(
                    lambda d: self._result_text(d).startswith("total="),
                    timeout=6.0)
                break
            except TimeoutError:
                if attempt == 2: raise
        self._record_keyframe(dump, after_input=event)
        return event

    def state(self) -> dict:
        return json.loads((self.ctrl / "state.json").read_text())

    def stop(self):
        self.app.terminate()

def gui_reconstruct(store: TimelineStore, branch: str, through: int | None = None) -> dict[str, Any] | None:
    """Latest GUI keyframe tree at or before `through`, with the causing
    input event attached as provenance on the frame."""
    frames = [e for e in store.replay_events(branch, through) if e["kind"] == "gui_keyframe"]
    if not frames: return None
    last = frames[-1]
    return {"tree": last["payload"]["tree"], "after_input": last["payload"]["after_input"],
            "screenshot": last["payload"]["screenshot"], "event": last["id"]}

def flatten_tree(tree: dict, prefix: str = "") -> dict[str, dict]:
    out = {}
    path = f"{prefix}/{tree['name']}[{tree['class']}]"
    out[path] = {k: tree.get(k) for k in ("class", "value", "text", "x", "y", "w", "h")}
    for i, child in enumerate(tree.get("children", [])):
        out.update(flatten_tree(child, f"{path}.{i}"))
    return out
