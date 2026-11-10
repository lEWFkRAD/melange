from __future__ import annotations
from dataclasses import dataclass
import json, unicodedata

@dataclass
class Cell:
    char: str = " "; offset: int | None = None; chunk_id: int | None = None; tool_event: int | None = None

def _char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

class Grid:
    """Deterministic ANSI/VT terminal grid with per-cell provenance.

    Implements the control surface real TUI programs use: cursor motion,
    erase/insert/delete lines and chars, scroll regions, scrolling, the
    alternate screen, saved cursor, tabs, and deferred wrap — the semantics
    a reference emulator (pyte) implements, which the gate corpus checks
    against. SGR/colour sequences are parsed and ignored (chars only).
    Unsupported sequences are consumed, never fatal: a cell the grid cannot
    account for simply keeps whatever provenance it already had.
    """
    def __init__(self, rows=24, cols=80):
        self.rows, self.cols = rows, cols
        self.x, self.y = 0, 0
        self.cells = [[Cell() for _ in range(cols)] for _ in range(rows)]
        self._alt_saved = None      # saved main-buffer cells while alt screen active
        self._in_alt = False
        self._saved = (0, 0)        # saved cursor (x, y)
        self._top, self._bottom = 0, rows - 1   # scroll region (inclusive)
        self._wrap_pending = False  # xterm-style deferred wrap
        self._insert = False
        self._pending = b""         # incomplete UTF-8 tail between feeds

    # -- buffer helpers -------------------------------------------------
    def _blank_row(self):
        return [Cell() for _ in range(self.cols)]

    def _scroll_up(self, region_top, region_bottom, n):
        for _ in range(min(n, region_bottom - region_top + 1)):
            del self.cells[region_top]
            self.cells.insert(region_bottom, self._blank_row())

    def _scroll_down(self, region_top, region_bottom, n):
        for _ in range(min(n, region_bottom - region_top + 1)):
            del self.cells[region_bottom]
            self.cells.insert(region_top, self._blank_row())

    def _index(self):
        """LF: move down, scrolling the region when at its bottom margin."""
        if self.y == self._bottom:
            self._scroll_up(self._top, self._bottom, 1)
        elif self.y < self.rows - 1:
            self.y += 1

    def _reverse_index(self):
        if self.y == self._top:
            self._scroll_down(self._top, self._bottom, 1)
        elif self.y > 0:
            self.y -= 1

    def _put(self, ch, offset, chunk_id, tool_event):
        width = _char_width(ch)
        if width == 0:  # combining char: attach to previous cell's char
            if self.x > 0:
                self.cells[self.y][self.x - 1].char += ch
            return
        if self._wrap_pending:
            self._wrap_pending = False
            self.x = 0
            self._index()
        if self._insert:
            row = self.cells[self.y]
            for _ in range(width):
                row.insert(self.x, Cell())
                row.pop()
        self.cells[self.y][self.x] = Cell(ch, offset, chunk_id, tool_event)
        if width == 2 and self.x + 1 < self.cols:
            self.cells[self.y][self.x + 1] = Cell("", offset, chunk_id, tool_event)
        last = self.cols - 1
        nxt = self.x + width
        if nxt > last:
            self.x = last
            self._wrap_pending = True
        else:
            self.x = nxt
            if self.x == self.cols:
                self.x = last
                self._wrap_pending = True

    # -- escape dispatch --------------------------------------------------
    def _csi(self, priv, params, final, chunk_id, tool_event):
        def p(i, default=0):
            if i < len(params) and params[i] not in ("", None):
                try: return int(params[i])
                except ValueError: return default
            return default
        n = p(0, 1) or 1
        if priv == "?":
            if final in ("h", "l"):
                on = final == "h"
                for raw in params:
                    mode = int(raw or 0)
                    if mode == 1049:
                        if on and not self._in_alt:
                            # xterm semantics: save cursor, save the main
                            # buffer, switch to a blank alternate buffer.
                            self._saved = (self.x, self.y)
                            self._alt_saved = self.cells
                            self.cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
                            self._in_alt = True
                        elif not on and self._in_alt:
                            self.cells = self._alt_saved
                            self._alt_saved = None
                            self._in_alt = False
                            self.x, self.y = self._saved
                    elif mode in (47, 1047):
                        if on and not self._in_alt:
                            self._alt_saved = self.cells
                            self.cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
                            self._in_alt = True
                        elif not on and self._in_alt:
                            self.cells = self._alt_saved
                            self._alt_saved = None
                            self._in_alt = False
            return
        if final in ("H", "f"):
            self.y = max(0, min(self.rows - 1, (p(0, 1) or 1) - 1))
            self.x = max(0, min(self.cols - 1, (p(1, 1) or 1) - 1))
            self._wrap_pending = False
        elif final == "A": self.y = max(0, self.y - n); self._wrap_pending = False
        elif final in ("B", "e"): self.y = min(self.rows - 1, self.y + n); self._wrap_pending = False
        elif final in ("C", "a"): self.x = min(self.cols - 1, self.x + n); self._wrap_pending = False
        elif final == "D": self.x = max(0, self.x - n); self._wrap_pending = False
        elif final == "E": self.y = min(self.rows - 1, self.y + n); self.x = 0; self._wrap_pending = False
        elif final == "F": self.y = max(0, self.y - n); self.x = 0; self._wrap_pending = False
        elif final == "G": self.x = max(0, min(self.cols - 1, (p(0, 1) or 1) - 1)); self._wrap_pending = False
        elif final == "d": self.y = max(0, min(self.rows - 1, (p(0, 1) or 1) - 1)); self._wrap_pending = False
        elif final == "J":
            mode = p(0, 0)
            if mode == 0:
                self._erase_line_range(self.y, self.x, self.cols)
                for yy in range(self.y + 1, self.rows): self.cells[yy] = self._blank_row()
            elif mode == 1:
                for yy in range(0, self.y): self.cells[yy] = self._blank_row()
                self._erase_line_range(self.y, 0, self.x + 1)
            elif mode in (2, 3):
                self.cells = [[Cell() for _ in range(self.cols)] for _ in range(self.rows)]
        elif final == "K":
            mode = p(0, 0)
            if mode == 0: self._erase_line_range(self.y, self.x, self.cols)
            elif mode == 1: self._erase_line_range(self.y, 0, self.x + 1)
            elif mode == 2: self.cells[self.y] = self._blank_row()
        elif final == "L":
            if self._top <= self.y <= self._bottom:
                self._scroll_down(self.y, self._bottom, n)
        elif final == "M":
            if self._top <= self.y <= self._bottom:
                self._scroll_up(self.y, self._bottom, n)
        elif final == "P":
            row = self.cells[self.y]
            for _ in range(min(n, self.cols - self.x)):
                del row[self.x]; row.append(Cell())
        elif final == "@":
            row = self.cells[self.y]
            for _ in range(min(n, self.cols - self.x)):
                row.insert(self.x, Cell()); row.pop()
        elif final == "X":
            self._erase_line_range(self.y, self.x, min(self.cols, self.x + n))
        elif final == "S": self._scroll_up(self._top, self._bottom, n)
        elif final == "T": self._scroll_down(self._top, self._bottom, n)
        elif final == "r":
            top = (p(0, 1) or 1) - 1; bottom = (p(1, self.rows) or self.rows) - 1
            if 0 <= top < bottom < self.rows:
                self._top, self._bottom = top, bottom
            self.x, self.y = 0, 0; self._wrap_pending = False
        elif final == "s": self._saved = (self.x, self.y)
        elif final == "u": self.x, self.y = self._saved; self._wrap_pending = False
        elif final == "h" and p(0) == 4: self._insert = True
        elif final == "l" and p(0) == 4: self._insert = False
        # m (SGR) and everything else: parsed, ignored.

    def _erase_line_range(self, row, start, end):
        for xx in range(max(0, start), min(self.cols, end)):
            self.cells[row][xx] = Cell()

    # -- main feed --------------------------------------------------------
    def feed(self, data: bytes, chunk_id: int, tool_event: int | None = None, offset_base: int = 0) -> None:
        data = self._pending + data
        self._pending = b""
        utf8_tail = b""
        # Hold back an incomplete UTF-8 tail so a char split across chunks
        # is still written whole, with the offset of its first byte.
        if data:
            cut = len(data)
            for k in range(1, 4):
                if cut - k < 0: break
                b = data[cut - k]
                if b >= 0xC2:
                    need = 4 if b >= 0xF0 else 3 if b >= 0xE0 else 2
                    if k < need:
                        utf8_tail = data[cut - k:]; data = data[:cut - k]
                    break
                if not (0x80 <= b <= 0xBF): break
        self._pending = utf8_tail
        text = data.decode("utf-8", "replace")
        # Byte offset of a char: exact for the ASCII/control span; for
        # multibyte text compute by re-encoding char by char.
        i = 0; boff = offset_base
        raw = data
        bi = 0  # byte index into raw walking with text
        while i < len(text):
            ch = text[i]
            chlen = len(ch.encode("utf-8", "replace"))
            if ch == "\x1b" and i + 1 >= len(text):
                # Lone ESC at the end of a chunk: the sequence continues in
                # the next chunk — stash it instead of dropping it.
                self._pending = raw[bi:] + utf8_tail; return
            if ch == "\x1b" and i + 1 < len(text):
                nxt = text[i + 1]
                if nxt in "()#%" and i + 2 >= len(text):
                    self._pending = raw[bi:] + utf8_tail; return
                if nxt == "[":  # CSI
                    j = i + 2; priv = ""
                    if j < len(text) and text[j] == "?": priv = "?"; j += 1
                    start = j
                    while j < len(text) and not ("@" <= text[j] <= "~"): j += 1
                    if j >= len(text):  # CSI split across chunks: stash and resume next feed
                        self._pending = raw[bi:] + utf8_tail; return
                    params = text[start:j].split(";") if text[start:j] else []
                    self._csi(priv, params, text[j], chunk_id, tool_event)
                    adv = len(text[i:j + 1].encode("utf-8", "replace"))
                    i = j + 1; bi += adv; continue
                if nxt == "]":  # OSC: skip to BEL or ST
                    j = i + 2
                    while j < len(text) and text[j] != "\x07" and not (text[j] == "\x1b" and j + 1 < len(text) and text[j + 1] == "\\"): j += 1
                    if j >= len(text):
                        self._pending = raw[bi:] + utf8_tail; return
                    j = j + 1 if text[j] == "\x07" else j + 2
                    adv = len(text[i:j].encode("utf-8", "replace")); i = j; bi += adv; continue
                if nxt in "P_^":  # DCS/APC/SOS: skip to ST
                    j = i + 2
                    while j + 1 < len(text) and not (text[j] == "\x1b" and text[j + 1] == "\\"): j += 1
                    if j + 1 >= len(text):
                        self._pending = raw[bi:] + utf8_tail; return
                    j += 2; adv = len(text[i:j].encode("utf-8", "replace")); i = j; bi += adv; continue
                if nxt == "7": self._saved = (self.x, self.y)
                elif nxt == "8": self.x, self.y = self._saved; self._wrap_pending = False
                elif nxt == "M": self._reverse_index()
                elif nxt == "D": self._index(); self.x = 0 if False else self.x
                elif nxt == "E": self._index(); self.x = 0
                elif nxt == "c":  # RIS: full reset
                    self.__init__(self.rows, self.cols)
                # ESC ( X / ) X charset selects and other two-byte forms: skip the pair.
                step = 3 if nxt in "()#%" and i + 2 < len(text) else 2
                adv = len(text[i:i + step].encode("utf-8", "replace")); i += step; bi += adv; continue
            if ch == "\n":
                self._index(); self._wrap_pending = False
            elif ch == "\r":
                self.x = 0; self._wrap_pending = False
            elif ch == "\b":
                self.x = max(0, self.x - 1); self._wrap_pending = False
            elif ch == "\t":
                self.x = min(self.cols - 1, (self.x // 8 + 1) * 8); self._wrap_pending = False
            elif ch == "\x07" or ch == "\x00":
                pass
            elif ch >= " ":
                self._put(ch, offset_base + bi, chunk_id, tool_event)
            i += 1; bi += chlen

    def screen(self) -> str:
        return "\n".join("".join(c.char for c in row) for row in self.cells)

    def snapshot(self) -> bytes:
        state = {"v": 2, "x": self.x, "y": self.y, "saved": list(self._saved),
                 "pending": self._pending.decode("utf-8", "replace"),
                 "top": self._top, "bottom": self._bottom, "wrap": self._wrap_pending,
                 "cells": [[c.__dict__ for c in row] for row in self.cells],
                 "in_alt": self._in_alt,
                 "alt": [[c.__dict__ for c in row] for row in self._alt_saved] if self._alt_saved is not None else None}
        return json.dumps(state, separators=(",", ":")).encode()

    @classmethod
    def from_snapshot(cls, value: bytes):
        saved = json.loads(value)
        if isinstance(saved, list):  # earliest shape: bare cell rows
            g = cls(len(saved), len(saved[0])); g.cells = [[Cell(**c) for c in row] for row in saved]; return g
        rows = saved["cells"]
        g = cls(len(rows), len(rows[0]))
        g.cells = [[Cell(**c) for c in row] for row in rows]
        g.x, g.y = saved.get("x", 0), saved.get("y", 0)
        if saved.get("v") == 2:
            g._pending = saved.get("pending", "").encode("utf-8", "replace")
            g._saved = tuple(saved.get("saved", (0, 0)))
            g._top, g._bottom = saved.get("top", 0), saved.get("bottom", g.rows - 1)
            g._wrap_pending = bool(saved.get("wrap", False))
            g._in_alt = bool(saved.get("in_alt", False))
            if saved.get("alt") is not None:
                g._alt_saved = [[Cell(**c) for c in row] for row in saved["alt"]]
        return g
