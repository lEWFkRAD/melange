"""Viewer export (Build 2): one timeline -> one self-contained HTML file.

Frames are pre-rendered host-side (screen text per chunk boundary, from
the same reconstruct() the scrubber uses), and every non-blank cell
carries its provenance (chunk id, tool event, byte offset). The page is
a scrubber: a slider walks frames, clicking a cell shows its provenance
in the side panel, and the branch list switches between the main line,
forks, and ghost branches. No server, no external assets.
"""
from __future__ import annotations
import json
from pathlib import Path

from .replay import reconstruct
from .store import TimelineStore

def timeline_frames(store: TimelineStore, branch: str, rows: int = 24, cols: int = 80) -> list[dict]:
    frames = []
    for e in store.replay_events(branch):
        if e["kind"] != "terminal_chunk": continue
        grid = reconstruct(store, branch, e["id"], rows, cols)
        cells = []
        for y, row in enumerate(grid.cells):
            for x, cell in enumerate(row):
                if cell.char not in (" ", ""):
                    cells.append({"x": x, "y": y, "ch": cell.char, "chunk": cell.chunk_id,
                                  "tool": cell.tool_event, "offset": cell.offset})
        frames.append({"event": e["id"], "screen": grid.screen(), "cells": cells})
    return frames

def export_html(store: TimelineStore, branches: list[str], out: str | Path, rows: int = 24, cols: int = 80) -> Path:
    data = {b: timeline_frames(store, b, rows, cols) for b in branches}
    payload = json.dumps(data)
    page = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Living Replay — timeline viewer</title>
<style>
body{font-family:ui-monospace,Menlo,Consolas,monospace;background:#101418;color:#d7dee6;margin:2rem}
#screen{background:#0a0d10;border:1px solid #2a323b;padding:1rem;white-space:pre;line-height:1.25;cursor:pointer}
#screen span:hover{background:#274b73}
#panel{margin-top:1rem;color:#9fd1ff;min-height:1.5em}
button{background:#1c232b;color:#d7dee6;border:1px solid #2a323b;padding:.3rem .7rem;margin-right:.4rem;cursor:pointer}
input[type=range]{width:60%%}
</style></head><body>
<h1>Living Replay — timeline viewer</h1>
<div id="branches"></div>
<input type="range" id="scrub" min="0" value="0"> <span id="pos"></span>
<pre id="screen"></pre>
<div id="panel">Click a character to see what caused it.</div>
<script>
const DATA = %s;
let branch = Object.keys(DATA)[0], idx = 0;
const screenEl = document.getElementById('screen'), panel = document.getElementById('panel'),
      scrub = document.getElementById('scrub'), pos = document.getElementById('pos'),
      bdiv = document.getElementById('branches');
Object.keys(DATA).forEach(b => { const btn = document.createElement('button');
  btn.textContent = b; btn.onclick = () => { branch = b; idx = 0; draw(); }; bdiv.appendChild(btn); });
function draw(){
  const frames = DATA[branch]; scrub.max = Math.max(0, frames.length - 1); scrub.value = idx;
  const f = frames[idx]; pos.textContent = frames.length ? `frame ${idx + 1}/${frames.length} (event ${f.event})` : 'no frames';
  screenEl.innerHTML = '';
  if(!f) return;
  const byPos = {}; f.cells.forEach(c => byPos[c.y + ',' + c.x] = c);
  f.screen.split('\\n').forEach((line, y) => {
    [...line].forEach((ch, x) => {
      const s = document.createElement('span'); s.textContent = ch;
      const c = byPos[y + ',' + x];
      if(c) s.onclick = () => { panel.textContent =
        `'${c.ch}' at (${y},${x}) — chunk ${c.chunk}, tool event ${c.tool}, byte offset ${c.offset}`; };
      screenEl.appendChild(s);
    });
    screenEl.appendChild(document.createTextNode('\\n'));
  });
}
scrub.oninput = () => { idx = +scrub.value; draw(); };
draw();
</script></body></html>"""
    # HTML parses script end tags case-insensitively, including end tags
    # with whitespace. Escape every '<' in the embedded JSON so recorded
    # output and branch names can never become HTML/script markup.
    out = Path(out); out.write_text(page % payload.replace("<", "\\u003c"), encoding="utf-8")
    return out
