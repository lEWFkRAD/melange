# Melange service — the bridge as a live service (M3)

`melange_service.py` is a zero-dependency (Python stdlib `http.server`)
HTTP service that wraps the canonical bridge (`living_replay.bridge`)
over a configured set of TimelineStores, and serves the reference
surface (`static/index.html`) at `/`. It replaces the baked players:
the surface holds **no recording data** — everything it shows was
fetched from this service, from the stores on disk, at request time.

Fidelity is enforced server-side by the library's own gates
(`living_replay.ingest.require_branch_op` via the bridge): a refused
operation returns **403** with the library's refusal sentence. The
seal is `store.verify(branch)` computed **at request time**; a store
that does not verify reports `seal: false` in a normal 200 response.

## Run

```sh
service/run.sh            # binds 127.0.0.1:8798
# or:
MELANGE_PORT=9000 PYTHONPATH=src:service python3 service/melange_service.py
```

Environment:

- `MELANGE_PORT` — port (default 8798; 8796/8797 are the SHATNER
  bridge ports, unrelated to this local service).
- `MELANGE_STORES_FILE` — registry JSON (default `service/stores.json`).
- `MELANGE_EXCEL_DIR` — fallback location of the Excel lane's
  `workbook_profile.py` + fixture (workbook clamp path only).

No systemd unit is provided; run it under whatever supervisor you
like, or by hand. It binds 127.0.0.1 only.

## Registry

```json
{"stores": {
  "<id>": {"label": "Human name", "path": "/abs/or/~/store-root",
           "profile_dir": "...", "fixture": "...", "generate": "flagship"}
}}
```

`path` is the TimelineStore root (holds `timeline.sqlite`); relative
paths resolve against the repo root. `generate: "flagship"` runs the
canonical `flagship.run_flagship` into the store's parent directory on
first open if the timeline is absent. `profile_dir`/`fixture` locate
the workbook profile used to evaluate clamp forks on workbook
branches (needs openpyxl; loaded lazily, only for clamp requests).

Preconfigured (`service/stores.json`): `desktop-real` (the real
Hermes desktop capture, screen-only), `workbook` and
`workbook-pinned` (the Excel return; the pinned copy carries the M7
house rules), and `flagship` (generated under `service/stores/`).

Adding another store (e.g. the 153-step live-session store, once it is
copied to this machine) is a registry entry, not a code change.

## Endpoints

Steps are 1-based. A branch's navigable steps depend on its kind:
video → one per kept picture; workbook → one per `cell_frame`;
structure/session → one per event in the branch's replay.

| Route | Returns |
|---|---|
| `GET /api/health` | `{ok, stores}` |
| `GET /api/stores` | `[{id, label, branches: [{name, fidelity, kind, steps, fork, seal}]}]` — seal computed per branch at request time |
| `GET /api/store/<id>/branch/<b>` | `{kind, fidelity, caps, refusals, steps, seal, fork (with split_step), house_rules: [{target, pinned, current, status}], notes}` |
| `GET /api/store/<id>/branch/<b>/step/<n>` | video: the frame bytes (content-type sniffed) — add `?meta=1` for JSON `{event_id, ts}`; workbook: `{label, values}`; session: `{event_kind, screen, payload}`; structure: `{parts}` |
| `GET /api/store/<id>/branch/<b>/wherefrom/<n>?row=&col=` | bridge `where_from`: provenance dict + plain-language `sentence` (403 where fidelity refuses provenance) |
| `POST /api/store/<id>/branch/<b>/note` `{step, text}` | 201 `{event_id, notes}` — a real `annotation` event written into the store via the bridge |
| `POST /api/store/<id>/branch/<b>/fork` `{step?, note?, branch?}` | 201 — bridge `try_differently`: a real What-if branch + context note. 403 with the refusal sentence where fidelity refuses forks |
| `POST .../fork` `{clamp: {cell, value}}` (workbook branches) | `house_rules.checked_fork`: pins pre-checked against the recomputed values; 201 `{accepted, branch, values, pins_inherited}` or **422** `{accepted: false, violations, reason}` with the broken rules named |

Errors: 400 bad input, 403 fidelity refusal, 404 unknown
store/branch/step, 422 house-rule rejection, 500 anything else (with
the exception named — never hidden).

## The surface

`static/index.html` builds its tabs from `GET /api/stores`, draws the
spice volume from the fetched fidelity (v3's `visualParams`, verbatim,
with its legend), opens branches live (seal chip reflects the response
at open time), fetches steps on demand (desktop frames are image URLs
into the step endpoint, not embedded base64), posts notes and forks
back to the service, and — if the API is unreachable — shows an honest
"cannot reach the recordings service" state with no fallback data.
