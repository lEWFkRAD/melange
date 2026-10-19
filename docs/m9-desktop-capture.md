# M9: capture a real application's structure

The reusable recorder is `living_replay.desktop`. It attaches to an
explicitly selected local Chromium/Electron CDP target, reads its real
accessibility tree, and records a keyframe followed by structural deltas.
The application does not need Melange instrumentation.

This is **structure fidelity**: scrub, inspect and annotate work. The
recording does not contain executable application state, so clamp, fork
and causal provenance remain refused. Replaying changed inputs into an
existing vendor application requires a separate checkpoint/input adapter.

## Capture

Install the optional transport dependency:

```sh
pip install -e '.[desktop]'
```

Start an isolated Chromium/Electron instance with a local debugging
endpoint and synthetic content. For example, with Chromium:

```sh
chromium --user-data-dir=/tmp/melange-demo-profile --remote-debugging-port=9222
curl http://127.0.0.1:9222/json/list
```

Copy the intended page's exact `id` from the response. The recorder
requires a target id and never silently selects an open page:

```sh
PYTHONPATH=src python -m living_replay.desktop \
  --endpoint http://127.0.0.1:9222 --target-id PAGE_ID \
  --output desktop-demo.jsonl --samples 20 --interval 1.5
```

An explicit local `--websocket ws://127.0.0.1:9222/devtools/page/PAGE_ID`
can be used instead. Output creation is exclusive: an existing recording
is never overwritten. A disconnected target fails the capture instead of
reporting an invented successful frame.

Each line has an elapsed monotonic timestamp `ts` in seconds. The first
line is a semantic AX keyframe; subsequent lines are deterministic `set`
and `del` operations. Still frames produce empty deltas, preserving the
poll timeline. The driver observes structure only and does not claim to
capture keyboard/mouse input or prove what caused a change.

Known secret patterns are redacted from semantic text before it reaches
the JSONL file. Unneeded CDP source and DOM metadata is omitted.
This is pattern redaction, not a guarantee that arbitrary private text is
removed. Capture synthetic content for tests and demonstrations. JSONL is
plain text; storing it later in an encrypted timeline does not encrypt the
original recording file.

## Import and serve

Import into a fresh branch. The importer validates the full record before
writing any events or objects, preserves elapsed timestamps, and also
accepts the spike recorder's legacy `t` timestamps in milliseconds.

```sh
PYTHONPATH=src python - <<'PY'
from pathlib import Path
from living_replay.ingest import ingest_desktop_record, tree_state_at
from living_replay.store import TimelineStore

store = TimelineStore('desktop-demo-store')
try:
    print(ingest_desktop_record(store, 'desktop',
                              Path('desktop-demo.jsonl').read_text()))
    print('checked:', store.verify('desktop'))
    print('parts:', len(tree_state_at(store, 'desktop')))
finally:
    store.db.close()
PY
```

Use an absolute path to that store in a separate registry file:

```json
{"stores": {"desktop-demo": {"path": "/absolute/path/desktop-demo-store", "label": "Synthetic desktop demo"}}}
```

Then run `MELANGE_STORES_FILE=/absolute/path/registry.json service/run.sh`
and open `http://127.0.0.1:8798`. Desktop navigation starts at the first
captured tree, never the internal import metadata event.

## Forward verification

`tools/verify_desktop_capture.py` launches a fresh headless Chromium/Edge
profile with a synthetic page. The harness sends two synthetic mouse
inputs to open and close a details panel; the recorder only reads CDP.
It compares every reconstructed frame to the actual AX tree returned by
the browser at that poll, verifies a still poll has no delta, and checks
the ledger and fidelity refusals:

```sh
PYTHONPATH=src python tools/verify_desktop_capture.py --browser /path/to/chromium
```

On Windows, set `PYTHONPATH=src` and pass the installed `msedge.exe` path.
This checks a real browser accessibility engine with synthetic content.
It does not certify QuickBooks, Sage, cross-origin iframe capture, full
Windows UI Automation, or execution forks for third-party applications.

Measured 2026-10-19 with Edge on Windows, Python 3.14: four frames verified,
zero differing paths, 18 delta operations, zero operations on the still
poll, seal true and all three forbidden operations refused. The full
Linux suite ran 215 tests: 199 passed and 16 environment-gated skips.
