#!/usr/bin/env python3
"""Build the static surface export (flagship example only).

Runs the real Melange service against a scratch registry containing
ONLY the flagship store (the synthetic Dana Ruiz return), captures the
exact API responses the surface page consumes, and bakes them into
surface-export/:

  index.html    service/static/index.html with the export patches:
                static labeling in the header/shelf copy, a fetch
                shim installed before the page script, and a small
                locking script after it.
  baked-data.js window.MELANGE_BAKED = {stores, shelf, details, map,
                steps, wherefrom grids} — the service's own responses,
                captured, not re-derived.
  README.md     what the export is and how to view it.

Write controls (note, fork, clamp, explain, promote, demote,
narration) cannot work in a baked copy. The export locks them two
ways, both in the surface's own style: the baked branch details carry
the live-service sentence in their refusals (the page's fidelity-lock
mechanism disables note/fork/clamp/explain and shows the sentence),
and the locking script disables promote/demote/narrate and writes
the same sentence into their panels. As a backstop the fetch shim
answers every POST with HTTP 403 and that sentence.

"Where did this come from?" is a read, so it is baked for real: the
wherefrom grids are computed with the bridge's own where_from over
the generated flagship store, deduplicated into a table + index grids.

No other store is ever opened by this script: the scratch registry
names the flagship alone, so no real recording (desktop, live
session) and no key material can enter the export.

Run with the project venv interpreter:
  ~/workspace/living-replay/venv/bin/python tools/build_surface_export.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVICE = REPO / "service"
EXPORT_DIR = REPO / "surface-export"
PORT = 8891
BASE = f"http://127.0.0.1:{PORT}"

LIVE_WORDING = (
    "This needs the live Melange service. This page is a baked copy "
    "of the flagship example, and a baked copy cannot change the "
    "recording."
)

SHIM_JS = r"""
// Static export fetch shim: answers the surface's /api reads from
// the baked responses in baked-data.js, and refuses every write with
// the live-service sentence. Installed before the page script runs.
(function () {
  const B = window.MELANGE_BAKED;
  const LIVE = __LIVE_WORDING__;
  const jr = (obj, status) => new Response(JSON.stringify(obj), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json' } });
  const nativeFetch = window.fetch.bind(window);
  window.fetch = function (input, opts) {
    const raw = typeof input === 'string' ? input : input.url;
    const method = ((opts && opts.method) ||
      (typeof input !== 'string' && input.method) || 'GET').toUpperCase();
    if (!raw.startsWith('/api/')) return nativeFetch(input, opts);
    if (method !== 'GET')
      return Promise.resolve(jr({ error: LIVE }, 403));
    const q = raw.indexOf('?');
    const path = q < 0 ? raw : raw.slice(0, q);
    const query = new URLSearchParams(q < 0 ? '' : raw.slice(q + 1));
    const seg = path.split('/').filter(Boolean)
      .map(decodeURIComponent);
    try {
      if (path === '/api/health') return Promise.resolve(
        jr({ ok: true, stores: B.stores.length, static_export: true }));
      if (path === '/api/stores') return Promise.resolve(jr(B.stores));
      if (path === '/api/shelf') return Promise.resolve(jr(B.shelf));
      if (seg[0] === 'api' && seg[1] === 'store' && seg[3] === 'branch') {
        if (!B.stores.some(s => s.id === seg[2]))
          throw new Error('not in this static export');
        const detail = B.details[seg[4]];
        if (!detail) throw new Error('not in this static export');
        if (seg.length === 5) return Promise.resolve(jr(detail));
        if (seg.length === 6 && seg[5] === 'map')
          return Promise.resolve(jr(B.map));
        if (seg.length === 7 && seg[5] === 'step') {
          const step = (B.steps[seg[4]] || {})[seg[6]];
          if (!step) throw new Error('not in this static export');
          return Promise.resolve(jr(step));
        }
        if (seg.length === 7 && seg[5] === 'wherefrom') {
          const n = seg[6];
          const row = +(query.get('row') || 0);
          const col = +(query.get('col') || 0);
          const g = (B.wherefrom[seg[4]] || {})[n];
          let entry = B.wherefrom_blank;
          if (g && g.grid[row] && g.grid[row][col] !== undefined)
            entry = g.table[g.grid[row][col]];
          const step = (B.steps[seg[4]] || {})[n] || {};
          return Promise.resolve(jr(Object.assign(
            { step: +n, event_id: step.event_id }, entry)));
        }
      }
      throw new Error('not in this static export');
    } catch (e) {
      return Promise.resolve(jr({ error: e.message }, 404));
    }
  };
})();
"""

LOCKS_JS = r"""
<script>
'use strict';
// Static export locks: keeping a What-if on the shelf and telling
// its story both write into the recording, so in a baked copy their
// buttons render disabled with the reason written in their panels.
// (Note/fork/clamp/explain are locked by the refusals baked into the
// branch details, through the page's own fidelity-lock mechanism;
// the fetch shim refuses the writes themselves as a backstop.)
(function () {
  const LIVE = __LIVE_WORDING__;
  const wrap = (name, after) => {
    const orig = window[name];
    if (typeof orig !== 'function') return;
    window[name] = function () {
      const r = orig.apply(this, arguments); after(); return r;
    };
  };
  wrap('renderShelfPanel', () => {
    for (const id of ['btn-promote', 'btn-demote']) {
      const b = document.querySelector('#' + id);
      if (b) b.disabled = true;
    }
    const note = document.querySelector('#shelf-note');
    if (note) note.textContent =
      (note.textContent ? note.textContent + ' ' : '') + LIVE;
  });
  wrap('renderNarration', () => {
    const b = document.querySelector('#btn-narrate');
    if (b) b.disabled = true;
    const note = document.querySelector('#narr-note');
    if (note && !note.textContent) note.textContent = LIVE;
  });
})();
</script>
"""

# (exact text in service/static/index.html, replacement for the export)
PATCHES = [
    ("<title>Melange — recordings, live from the store</title>",
     "<title>Melange: the flagship example (static export)</title>"),
    ('<span class="sub">Every recording below is read live from its '
     'store — nothing on this page was baked in.</span>',
     '<span class="sub">Static export: the flagship example recording '
     '(the synthetic Dana Ruiz return), baked from the live surface. '
     'Looking, scrubbing and the map work from the baked copy. '
     'Anything that would change the recording needs the live '
     'service.</span>'),
    ("how it was made stays written on it. Nothing here was baked in: the\n"
     "  shelf is read from the stores when you look at it.",
     "how it was made stays written on it. This shelf was baked in\n"
     "  when the export was made: it shows the flagship example exactly\n"
     "  as the live surface read it then."),
    ("  <b>Cannot reach the recordings service.</b><br>\n"
     "  This page keeps no copy of any recording — when the service is not\n"
     "  answering, there is honestly nothing to show. Start the service\n"
     "  (service/run.sh) and reload.",
     "  <b>The baked example did not load.</b><br>\n"
     "  This static export carries one recording, the flagship example,\n"
     "  baked into the page's own data file. If you can see this, that\n"
     "  data did not load. The live service (service/run.sh) shows every\n"
     "  recording on the shelf."),
]

README_TEXT = """# Melange: the flagship example (static export)

A self-contained, static copy of the Melange surface showing one
recording: the flagship example, a synthetic tax return for a made-up
person (Dana Ruiz). Every figure in it is fixture data. There is no
real recording in this folder: no desktop capture, no live session,
nothing from anyone's real work.

## What works here

Looking. The shelf card, both versions of the recording (the Original
and the What-if made from it), playback and scrubbing through every
step, the spatial map, house rules, and "Where did this come from?"
all run from data baked into `baked-data.js` when the export was
made, using the live service's own responses.

## What does not, on purpose

Anything that would change the recording: notes, What-ifs, clamping
a step, working backward ("What went wrong?"), keeping a What-if on
the shelf, and generating the spoken story. Those buttons render
locked, with the reason written next to them: they need the live
service (`service/run.sh` in the repository), which reads and writes
the real store. A baked copy that pretended to save changes would be
lying about where they went.

## How to view it

Open `index.html` in a browser. It runs from `file://` and from any
static host; there is no server and nothing to install.

For GitHub Pages: point Pages at this folder on a branch (repo
Settings, Pages, "Deploy from a branch", choose the branch and the
`/surface-export` folder). Note that the Melange repository is
private, and whether Pages can serve a private repository at all
depends on the owner's GitHub plan and visibility choices. Making
the repository public to publish this page would publish the whole
repository, not just this folder. That is the owner's call, not
something this export decides.

## How it was made

`tools/build_surface_export.py` runs the real service against a
registry containing only the flagship store, captures its responses,
and bakes them. The flagship data itself is generated by the
repository's flagship demo (`living_replay.flagship`), so the export
can be regenerated at any time and never drifts from the surface it
was baked from.
"""


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def main() -> int:
    scratch = Path(tempfile.mkdtemp(prefix="melange-export-"))
    registry = {"stores": {"flagship": {
        "path": str(scratch / "flagship" / "timeline"),
        "label": "Flagship demo — Dana Ruiz return",
        "generate": "flagship"}}}
    registry_file = scratch / "stores.json"
    registry_file.write_text(json.dumps(registry))

    env = dict(os.environ, MELANGE_STORES_FILE=str(registry_file),
               MELANGE_PORT=str(PORT))
    proc = subprocess.Popen(
        [sys.executable, str(SERVICE / "melange_service.py")],
        cwd=REPO, env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    try:
        for _ in range(150):
            try:
                get("/api/health")
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise RuntimeError("scratch service did not come up")

        stores = get("/api/stores")
        assert [s["id"] for s in stores] == ["flagship"], stores
        shelf = get("/api/shelf")
        branches = [b["name"] for b in stores[0]["branches"]]
        enc = lambda s: urllib.request.quote(s, safe="")
        details, steps, the_map = {}, {}, None
        for b in branches:
            detail = get(f"/api/store/flagship/branch/{enc(b)}")
            # Lock the write operations in the baked detail itself:
            # the page's fidelity-lock mechanism disables the note,
            # fork, clamp and explain buttons and shows this sentence
            # as the reason, exactly as it shows fidelity refusals.
            detail["refusals"] = {
                **detail.get("refusals", {}),
                "annotate": LIVE_WORDING,
                "fork": LIVE_WORDING,
                "clamp": LIVE_WORDING,
            }
            details[b] = detail
            if the_map is None:
                the_map = get(f"/api/store/flagship/branch/{enc(b)}/map")
            steps[b] = {str(n): get(
                f"/api/store/flagship/branch/{enc(b)}/step/{n}")
                for n in range(1, detail["steps"] + 1)}
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    # Wherefrom grids, computed with the bridge's own function over
    # the generated store (the service's endpoint does exactly this).
    sys.path.insert(0, str(SERVICE))
    sys.path.insert(0, str(REPO / "src"))
    import melange_service as svc
    from living_replay import bridge
    from living_replay.store import TimelineStore

    store = TimelineStore(scratch / "flagship" / "timeline")
    # The coordinate space is per step: a step's reconstruction grid
    # is the default 24x80 until the recording's first screen snapshot
    # replaces it with its own size (12x60 in the flagship). Bake each
    # step's grid at that step's own size, from its own screen text.
    wherefrom, blank = {}, None
    for b in branches:
        _, step_events = svc.step_events(store, b)
        wherefrom[b] = {}
        for n, ev in enumerate(step_events, start=1):
            lines = (steps[b][str(n)].get("screen") or "").split("\n")
            nrows = len(lines)
            ncols = max(len(line) for line in lines)
            table, index, grid = [], {}, []
            for row in range(nrows):
                line = []
                for col in range(ncols):
                    result = bridge.where_from(store, b, ev["id"],
                                                row, col)
                    if "chunk" not in result and blank is None:
                        blank = result
                    key = json.dumps(result, sort_keys=True)
                    if key not in index:
                        index[key] = len(table)
                        table.append(result)
                    line.append(index[key])
                grid.append(line)
            wherefrom[b][str(n)] = {"table": table, "grid": grid}
    assert blank is not None

    baked = {"stores": stores, "shelf": shelf, "details": details,
             "map": the_map, "steps": steps, "wherefrom": wherefrom,
             "wherefrom_blank": blank}

    page = (SERVICE / "static" / "index.html").read_text()
    for old, new in PATCHES:
        assert old in page, f"export patch anchor missing: {old[:60]!r}"
        page = page.replace(old, new, 1)
    shim = ('<script src="baked-data.js"></script>\n<script>'
            + SHIM_JS.replace("__LIVE_WORDING__",
                              json.dumps(LIVE_WORDING))
            + "</script>\n")
    anchor = "<script>\n'use strict';"
    assert anchor in page
    page = page.replace(anchor, shim + anchor, 1)
    tail = "</script>\n</body>"
    assert page.rstrip().endswith("</html>") and tail in page
    locks = LOCKS_JS.replace("__LIVE_WORDING__",
                             json.dumps(LIVE_WORDING))
    page = page.replace(tail, "</script>\n" + locks + "</body>", 1)

    EXPORT_DIR.mkdir(exist_ok=True)
    (EXPORT_DIR / "baked-data.js").write_text(
        "// Generated by tools/build_surface_export.py from the live\n"
        "// service's own responses for the flagship example store\n"
        "// (synthetic Dana Ruiz return). Do not edit by hand.\n"
        "window.MELANGE_BAKED = " + json.dumps(baked) + ";\n")
    (EXPORT_DIR / "index.html").write_text(page)
    (EXPORT_DIR / "README.md").write_text(README_TEXT)
    print(f"baked {len(branches)} branches {branches}, "
          f"steps per branch "
          f"{ {b: len(steps[b]) for b in branches} }, "
          f"wherefrom grids per step; export in {EXPORT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
