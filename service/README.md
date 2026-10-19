# Melange service — the bridge as a live service (M3)

`melange_service.py` is a zero-dependency (Python stdlib `http.server`)
HTTP service that wraps the canonical bridge (`living_replay.bridge`)
over a configured set of TimelineStores, and serves the reference
surface (`static/index.html`) at `/`. It replaces the baked players:
the surface holds **no recording data** — everything it shows was
fetched from this service, from the stores on disk, at request time.

M11 adds the rest of the volume doctrine to the same pattern: the
surface lands on **the shelf** (every recording, its versions, their
seals and Golden Path standings, and the kept What-ifs with their
provenance), each open recording carries a **spatial map** of its
lanes and steps that dives on click, and a version can **tell its
story** — a narration composed from the record, spoken by the
machine's speech engine where one exists and attached to the branch
in the store. The library side is `living_replay/shelf.py`.

Fidelity is enforced server-side by the library's own gates
(`living_replay.ingest.require_branch_op` via the bridge): a refused
operation returns **403** with the library's refusal sentence. The
seal is `store.verify(branch)` computed **at request time**; a store
that does not verify reports `seal: false` in a normal 200 response.

## Run

On Windows with WSL and Python 3.11+ installed, run `./start-melange.ps1`
from the repository root, then open http://localhost:8798. Pass `-Port 8799`
to use another port. Keep the terminal open while using the player.

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

The default registry (`service/stores.json`) contains one synthetic return,
generated under `service/stores/` on first open. It needs no external fixture
files. Add your recording paths to a separate registry and set
`MELANGE_STORES_FILE` to use them; workbook entries also need their profile
and fixture. Paths from another machine are not included in the default.

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
| `GET /api/shelf` | The shelf as a place (M11): `[{id, label, branch_count, branches: [{name, fidelity, kind, steps, seal, fork, pins, pin_status, kept, provenance, narration}]}]` — `pin_status` is `Holding`/`Broken` where the branch's values are computable in this service, `Not checked` where they are not, and null where the branch carries no house rules |
| `GET /api/store/<id>/branch/<b>` | also carries `kept` (shelf standing), `provenance` (how this version was made) and `narration` (latest story: script, engine, has_audio) |
| `GET /api/store/<id>/branch/<b>/map` | The spatial map: `{store, lanes: [{branch, kind, fidelity, original, parent_branch, split_step, kept, steps: [{n, event_id, kind, markers}]}]}` — markers (`pin`, `note`, `checkpoint`, `split`) read off real events |
| `POST /api/store/<id>/branch/<b>/promote` `{name}` | Keep a What-if on the shelf under a name (201). A `shelf` event on the What-if branch only — the Original is never touched, and the standing survives restarts because it lives in the store. 400 for the Original itself, a blank name, or a name already on the shelf |
| `POST /api/store/<id>/branch/<b>/demote` | Take a kept What-if back off the shelf (200); the branch and its record stay |
| `POST /api/store/<id>/branch/<b>/narration` | Compose the version's story from its record and speak it where a speech engine exists (ffmpeg's flite filter): the audio is attached to the branch as a store blob and a `narration` event records script + engine. 201 `{script, engine, has_audio, audio_note}` — with no engine, `has_audio` is false and `audio_note` says the story is words only |
| `GET /api/store/<id>/branch/<b>/narration/audio` | The spoken story (WAV), or 404 saying plainly that this version's story is words only here |

Errors: 400 bad input, 403 fidelity refusal, 404 unknown
store/branch/step, 422 house-rule rejection, 500 anything else (with
the exception named — never hidden).

## The surface

`static/index.html` is the default player: recording picker, version selector,
screen, playback bar, and an optional side panel. All content comes from the
live service. `player.js` ignores stale step responses, preserves the step
when switching versions, plays at recorded pace (pauses bounded to 0.25–3
seconds), and marks notes on the slider. The branch response includes a
`timeline` of step numbers, event IDs, kinds and timestamps, plus the latest
`computation_step`; neither requires downloading every frame first.

Try the synthetic example: **Go to calculation → select Wages → enter
48000 → Make the What-if**. The new calculation opens immediately with tax
3,088 and refund 3,012. **Compare Original** returns to the unchanged tax
3,568 and refund 2,532. Notes are saved through the bridge and survive reload.

The simple player's numeric edits apply to session recordings with a recorded
calculation. Desktop outlines and pictures retain playback and notes; their
locked actions explain the limitation. Instruction What-ifs explicitly record
intent and do not claim to have run. A broken seal permits watching but locks
changes in the player. Empty and unreachable recordings have explicit states.

**Advanced view** preserves the previous surface at `/static/advanced.html`,
including the volume, map, workbook controls, explanations, house rules,
narration and shelf management.
