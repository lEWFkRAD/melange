# Melange (Living Replay) backend API map

Read-only recon, 2026-10-16. Source: `/home/kip/lr-repo/src/living_replay/` (21 modules, ~1,990 lines) plus `sandbox/` scripts and the Build 2 live stores under `/home/kip/lr-sandbox/live-1792176400`. Package exports only three names (`living_replay/__init__.py`): `TimelineStore`, `Grid`, `PtyCapture`. Everything else is imported by submodule path. There is no server, no HTTP API, and no UI-facing facade: every consumer so far is a Python script importing the library directly.

## 1. Core store: `store.py` — `TimelineStore`

Append-only, hash-chained SQLite ledger (`timeline.sqlite`, table `events`) plus content-addressed blobs (`objects/` dir). One store = one timeline directory. Optional encryption at rest (Build 3): with `key_provider` set, a per-timeline DEK wrapped in `key.json` seals every blob and event payload with AES-256-GCM; opening with the wrong key raises `crypto.TimelineKeyError` (fails closed). The Build 2 live stores ARE encrypted; readers need `LocalKeyProvider` + the tree's `master.b64`.

Constructor: `TimelineStore(root: str | Path, key_provider=None)`.

| Method | Signature | What it does |
|---|---|---|
| `put_blob` | `(data: bytes) -> str` | Store bytes content-addressed (sha256; ciphertext hash when encrypted), return digest. |
| `get_blob` | `(digest: str) -> bytes` | Fetch (and decrypt) a blob. |
| `append` | `(branch, kind, payload: dict, *, parent_event=None, mono_ns=None) -> int` | Append one event, return its global event id. Thread-safe (serialized; hash chain is read-modify-write). Defaults `mono_ns` to `time.monotonic_ns()`. |
| `event` | `(event_id: int) -> dict` | One event by id, payload parsed/decrypted. `KeyError` if absent. |
| `events` | `(branch, through=None) -> list[dict]` | The branch's LOCAL events in id order (optionally only `id <= through`). Does not include any inherited prefix. |
| `replay_events` | `(branch, through=None) -> list[dict]` | The branch's full logical history: inherited prefix (recursively, parent's history through the fork checkpoint) followed by local events. This is what replay consumes. |
| `verify` | `(branch) -> bool` | Recompute the branch's hash chain; True iff intact. |
| `fork` | `(parent_branch, checkpoint, new_branch, edit=None) -> int` | Create a branch: appends a `fork` event on the NEW branch with payload `{parent_branch, checkpoint, edit}` and `parent_event=checkpoint`. Copies nothing; raises `ValueError` if the branch already exists. |
| `typed_edit` | `(branch, kind, target, value, **extra) -> int` | Append an `edit` event `{edit_kind, target, value, **extra}`; `kind` must be `clamp`, `explain`, or `pin`. Records the edit only; it does not recompute anything by itself. |

There is no `create` branch method (branches are implicit on first append), no delete, no annotation method, no branch-listing method (branch names are discovered by querying the events table), and no search/query API beyond the methods above.

### Event shape

Every event dict: `id` (int, global autoincrement across branches), `branch` (str), `parent_event` (int | None), `kind` (str), `mono_ns` (int), `payload` (dict), `prev_hash`, `hash` (sha256 of canonical JSON of branch+parent_event+kind+mono_ns+stored payload+prev_hash). Each branch has its OWN hash chain rooted at `GENESIS = "0"*64`; a forked branch links to its parent only through its `fork` event.

Event kinds that exist across the builds, and their payloads:

| Kind | Payload | Written by |
|---|---|---|
| `terminal_chunk` | `{blob, offset, length, raw_length, tool_event}` | `capture.PtyCapture.record_bytes` |
| `grid_keyframe` | `{blob, through}` (blob = serialized Grid snapshot) | `PtyCapture` (every Nth chunk; N=1 in practice) |
| `tool_call` | `{name, input, output}` | `runner.ForkContext.call_tool`, flagship |
| `model_call` | `{prompt, tokens, replayed: True}` (flagship variant adds `figures`) | `ForkContext.call_model`, guest agents |
| `context_note` | `{text, pinned}` | `runner.run_fork` (the injected note), guest agents |
| `fork` | `{parent_branch, checkpoint, edit}` | `store.fork` |
| `edit` | `{edit_kind: clamp|explain|pin, target, value, ...}` | `store.typed_edit` |
| `workspace_snapshot` | `{blob, format: "tar.gz"}` | `forking.snapshot_workspace` |
| `gui_keyframe` | `{tree, after_input, screenshot}` | `gui.GuiSession.keyframe` (Build 1 GUI spike) |
| `ingest_profile` | `{source, fidelity}` | `ingest.*` (first event of an ingested branch) |
| `ax_keyframe` | `{blob}` (blob = raw CDP AX node list JSON) | `ingest.ingest_desktop_record` |
| `ax_delta` | `{ops, poll}` | `ingest.ingest_desktop_record` |
| `input_event` | `{synthetic, events}` | `ingest.ingest_desktop_record` |
| `screen_frame` | `{blob, ts}` | `ingest.ingest_screen_frames` |

Build 2 live stores contain ONLY: `context_note` (5), `model_call` (16 orig / 15 fork), `terminal_chunk` (66 / 81), `grid_keyframe` (66 / 81). No `tool_call`, no `fork`, no `edit` events.

### Branches, fork point, shared prefix: three different things in the data

1. **Single-store fork (Build 1 / library model).** The fork point is data: the child branch's `fork` event payload `{parent_branch, checkpoint}`. The "shared prefix" is never stored twice and never computed as a comparison; `replay_events()` composes it structurally (parent history through `checkpoint`, then local events).
2. **Build 2 live run (what the player shows).** Original and fork are TWO SEPARATE single-branch stores (both branch name `main`), produced by Firecracker snapshot restore, not by `store.fork()`. Neither store contains a `fork` event. The 108-event shared prefix is a host-side observation: because both stores use branch `main` and identical stored payloads, event hashes 1..108 are identical across the two stores and diverge at 109. No library function computes this; the surface build computed it during extraction and baked the number in.
3. **`runner.prefix_offset(store, branch, checkpoint) -> int`** sounds related but is not: it is the total recorded terminal BYTES in a prefix, used so byte offsets stay monotonic across a fork.

## 2. Replay, frames, provenance: `replay.py`, `grid.py`

A "frame" is not a stored object. It is the reconstructed terminal screen after replaying a branch's events through a given event id.

- `reconstruct(store, branch, through=None, rows=24, cols=80) -> Grid`: replays `replay_events(branch, through)`; `grid_keyframe` events reset the grid from their snapshot blob, `terminal_chunk` events feed their blob bytes into the grid. Default geometry 24x80; the live run / Door 1 export used 24x100.
- `Grid` (`grid.py`): deterministic ANSI/VT emulator (cursor, erase/insert/delete, scroll regions, alt screen; SGR parsed and ignored, chars only). `feed(data, chunk_id, tool_event=None, offset_base=0)`, `screen() -> str`, `snapshot() -> bytes`, `Grid.from_snapshot(bytes)`. Each `Cell` carries provenance: `{char, offset, chunk_id, tool_event}`.
- `provenance(store, branch, event_id, row, col) -> dict` (row/col 0-based): reconstructs through `event_id` and reports the cell's origin: `{"attributed": bool, "chunk": chunk_id, "tool_event": ..., "offset": ...}`, or `{"attributed": False, "reason": "control/redraw/empty"}` for cells no chunk produced. `attributed` is True only when the cell's `tool_event` is not None. Caveat for Build 2 data: live chunks were recorded without tool linkage (`tool_event` is None on the chunks; `model_call`s are separate events), so per-cell provenance on live data yields chunk id + byte offset but `attributed: False` under this formula. Chunk-level attribution exists; tool-level attribution does not, for the live run.

## 3. Door 2 ingest and the fidelity contract: `ingest.py`

```python
FIDELITY_CAPS = {
    "native":      {"scrub", "dive", "annotate", "provenance", "clamp", "fork"},
    "structure":   {"scrub", "dive", "annotate"},
    "screen-only": {"scrub", "annotate"},
}
```

Six operations total: **scrub, dive, annotate, provenance, clamp, fork**. That is the entire allowed-op table; there are no other gated ops.

- `FidelityError(Exception)`: raised on any refusal.
- `require_op(fidelity, op) -> None`: raises `FidelityError` for an unknown fidelity string, or `f"operation {op!r} refused at fidelity {fidelity!r}: this capture depth supports {sorted(caps)}"` when the op is not in the set.
- `branch_fidelity(store, branch) -> str`: fidelity from the branch's first `ingest_profile` event; **`"native"` when the branch has no ingest profile** (all hand-built and Build 2 branches are native by default).
- `require_branch_op(store, branch, op) -> None`: `require_op(branch_fidelity(...), op)`. This is the enforcement entry point; it is called inside `tree_state_at` (dive) and `screen_frame_at` (scrub). Note the asymmetry: enforcement exists where ingest functions call it. `store.fork` / `typed_edit` do NOT call it, so clamp/fork refusal on ingested branches is enforced by callers using `require_branch_op`, not by the store itself.
- `ingest_desktop_record(store, branch, jsonl_text, source="cdp-ax") -> {keyframes, deltas, delta_ops, inputs}`: imports a recorder JSONL (`keyframe` / `delta` / `input` lines) as `ingest_profile` (structure) + `ax_keyframe` / `ax_delta` / `input_event` events.
- `flatten_ax(nodes) -> {path: slim_node}`: flattens a CDP accessibility tree by childIds linkage; paths are `rootIdx/childIdx/...`; slim node = `{role, name, desc, props}` (props sorted by name). This path keying must match the recorder's exactly.
- `tree_state_at(store, branch, through=None) -> {path: slim_node}`: reconstructs the flattened tree at any point: latest keyframe at or before `through`, then deltas in order. Delta ops: `{"op": "set", "path", "node"}` / `{"op": "del", "path"}`. Requires `dive`. Raises if a delta precedes any keyframe.
- `ingest_screen_frames(store, branch, frames: list[(png_bytes, ts)], source="video") -> {"frames": n}`: imports frames as `screen_frame` events at screen-only fidelity.
- `screen_frame_at(store, branch, index) -> bytes`: the index-th screen frame's PNG bytes. Requires `scrub`.

Important gap: **annotate is in every fidelity's capability set, but no function in the library implements annotations.** There is no annotation event writer or reader anywhere. The capability is a declared contract only.

## 4. Forking, clamping, explaining: where the real semantics live

- `forking.snapshot_workspace(store, branch, source) -> int`: tar.gz the workspace dir into a blob + `workspace_snapshot` event. `restore_workspace(store, snapshot_event, dest) -> Path`: unpack it. This is the workspace half of a fork.
- `runner.run_fork(store, parent_branch, checkpoint, new_branch, task, *, note=None, workspace_snapshot=None, workspace_dest=None, rows=24, cols=80) -> dict`: the only end-to-end "fork and continue" implementation. It calls `store.fork`, appends the pinned `context_note` if `note` given, restores the workspace snapshot, rebuilds the grid at the checkpoint, seeds a `PtyCapture` at `prefix_offset`, and runs `task(ctx)` LIVE on the new branch. Returns `{branch, fork_event, result, screen, pins}` where `pins` is collected from `pin` edit events visible in the fork's history. The task is a Python callable (`ForkContext` with `call_tool(name, output, tool_input="")` and `call_model(prompt, tokens)`), not data: **there is no serializable "inject" operation a UI can call.** Build 2's fork was not made this way either (it was a VM snapshot restore driven by `sandbox/` scripts).
- `runner.context_at(store, branch, checkpoint=None) -> [{kind, payload}]`: the restart context: `tool_call` / `model_call` / `context_note` events from `replay_events`, in order, nothing after the checkpoint.
- `edits.apply_clamp(values, target, value, derive) -> dict`: pure value-pipeline clamp: overlay the target, re-derive; the clamped input is passed to `derive` via a `__clamps__` marker so downstream recomputes from the clamped value.
- `edits.check_pins(values, pins) -> list[str]`: names of pins whose expected value does not hold.
- `edits.explain(candidates, target, expected, derive, fork) -> ExplainResult{branch, counterexamples}`: CEGIS-style explain over candidate input sets; first candidate whose forward derivation matches wins and is forked; failures are reported as strings, never silently dropped.
- `smt.solve(graph, target, goal, timeout_ms=10000) -> Solution | None`: EXPLAIN rung 2 for numeric pipelines (Z3 over `SGraph`, which evaluates both numerically and symbolically; builders `lin`, `prod`, `if_`).
- `lenses.clamp_through_lens(doc, lens, value) -> str`: CLAMP on a document through a bidirectional lens; `outside_region_identical(before, after, lens)` verifies nothing outside the lens region changed; `Lens.check_laws` checks get/put round-trips.
- `incremental.Engine`: dependency graph with `add_input` / `add(name, fn, deps)` / `build()` / `evaluate_all()` / `edit(name, value) -> dict` recomputing ONLY dependents (tracks `executed` count; this is the "42 of 93" machinery).
- `factgraph.FactGraph`: document-fact graph. `set_intake(path, value, source, span)`, `set_fact`, `derive(path, formula, inputs)`, `evaluate`, `evaluate_all`, `provenance(path)` (per-fact: source document, character span, formula inputs: the numeric-pipeline provenance), `dependents_of(path)`.
- `taint.SliceReplay`: lazy taint. `Tainted` text carries per-range origin labels; `slice_for(output) -> list[Step]` gives the minimal recorded steps an output depends on (EXPLAIN rung 4, computed only on demand).

## 5. Remaining modules, one line each

- `capture.py` — `PtyCapture(store, branch="main", rows, cols, keyframe_every=1, grid=None, offset=0)`: owns a PTY, redacts, stores chunks+keyframes; `record_bytes(raw, tool_event=None) -> event_id`, `run(argv, timeout=10.0, tool_event=None) -> exit code`. Holds back a 64-byte tail so secrets split across reads are still redacted whole.
- `crypto.py` — `TimelineKeyError`; `KeyProvider` protocol (`wrap`/`unwrap`); `LocalKeyProvider` (raw 32-byte master; `from_env("LIVING_REPLAY_KEY")`, `from_file`, `generate()`); `TimelineCrypto` (`encrypt`/`decrypt(data, aad)`, `encrypt_payload`/`decrypt_payload(payload, branch, kind)`).
- `export_viewer.py` — `timeline_frames(store, branch, rows, cols) -> [{event, screen, cells: [{x, y, ch, chunk, tool, offset}]}]`: one frame per `terminal_chunk` event, every non-blank cell with its provenance. `export_html(store, branches, out, rows, cols) -> Path`: the library's own self-contained scrubber page (slider + click-a-cell provenance + branch buttons). This is the player's direct ancestor.
- `gui.py` — Build 1 GUI spike: `Xvfb`, `GuiSession` (drives an X11 app, appends `gui_keyframe` events), `gui_reconstruct(store, branch, through=None) -> {tree, after_input, screenshot, event} | None` (latest keyframe; `after_input` is the frame's provenance), `flatten_tree(tree, prefix="") -> {path: {class, value, text, x, y, w, h}}`.
- `redaction.py` — `redact_text`, `redact_bytes`, `contains_seeded_secret` (capture-time secret scrubbing; gate G4).
- `flagship.py` — Build 3 end-to-end demo on one timeline: `build_fact_graph(intake_text)`, `expected_figures(wages, withholding=6100)` (independent oracle), `run_flagship(root, *, corrected_wages=48000) -> dict` (figures, amended figures, provenance, recomputed vs full node counts, parent-unchanged proof, screens). All figures synthetic by design.
- `sandbox.py` — Firecracker driver (Build 2 machinery, not UI surface): `api(sock, method, path, body)`, `SerialLog`, `MicroVM` (`configure`, `start_process`, `action`, `pause`/`resume`, `snapshot`, `load_snapshot`, `vsock_send`, `wait_exit`, `stop`), `fresh_data_drive`, `write_file_into_image`, `extract_dir_from_image`.
- `cli.py` — `main()`: minimal terminal scrubber: `living-replay <timeline> <branch> [--event N] [--cell ROW COL]`, prints the reconstructed screen and optionally one cell's provenance.
- `sandbox/export_render.py` — Door 1: timeline to mp4. Reconstructs the screen at each `terminal_chunk`/`grid_keyframe` event, dedupes consecutive identical screens, frame durations from `mono_ns` deltas clamped to 0.2–4.0s, renders with PIL, encodes with ffmpeg. (Script, not library; hardcodes branch `main` and the encrypted-store open.)

## 6. Player vs backend: gaps in both directions

Player = `~/workspace/your_files/melange-player/melange-player.html`, assembled by `~/workspace/lr-live/build_surface.py` from data extracted ONCE from the stores (baked JSON). The player never opens a store, never calls the library, and cannot see any branch, event, or trace that was not baked in at build time.

### Things the player presents that the backend does not actually do (or does differently)

1. **The CLAMP button is not a clamp.** It switches to the pre-recorded fork branch and jumps to event 108. No `typed_edit`, no `apply_clamp`, no recompute, no new fork is created, and the clamped value (99.85) is fixed. The backend's real clamp paths (value pipelines, lens rewrite + incremental recompute, `run_fork` with a pinned note) all require Python callables and none is reachable from a UI today. In particular there is NO backend "inject" operation: ONY-191's Inject button has nothing to call yet; the closest mechanisms are `store.fork` + `context_note` append (records intent) and `run_fork` / VM snapshot restore (executes, host-side only).
2. **Branch switching is not the backend's branch model.** The player's two "branches" are two separate encrypted stores unified at extraction time. The backend model (one store, `fork` event, `replay_events` composition) is not what is on screen, and a third branch cannot appear without rebuilding the page.
3. **The shared-prefix shading is a baked constant** (`meta.shared_prefix_events = 108`, computed at extraction by cross-store hash comparison). No backend function computes or verifies it at runtime; `store.verify()` (per-branch chain check) is never surfaced anywhere in the player.
4. **Provenance is one hardcoded card, not the provenance API.** The player shows a precomputed narrative for a single fact (99.9 first at event 25, row 13 col 67 1-based, capture chunk 25; fork's 99.85 at event 141). The backend offers per-cell provenance for EVERY cell (`replay.provenance`, and `export_viewer` exports it for all non-blank cells); the player exposes none of that generality: no click-a-cell, no other fact lookup. And per section 2, on live data the backend's own `attributed` flag would read False (no tool linkage on chunks), which the card's confident wording ("produced by capture chunk 25") quietly sidesteps: chunk attribution is real, tool attribution is absent.
5. **Annotations are localStorage only.** The backend declares `annotate` a capability at all three fidelities but implements no annotation storage at all. Player notes vanish with the browser profile and are invisible to every other client (desktop, TUI). Neither side has real annotations today.
6. **Playback timing is invented presentation.** The player advances events on baked `mono_ns` gaps scaled by 0.6 with a 60ms floor. The backend has no playback concept; the only timing semantics anywhere are Door 1's (real-time deltas clamped 0.2–4.0s). Harmless, but it is a player choice, not a backend behavior.
7. **Disabled buttons overstate enforcement location.** On structure/screen-only panes the player disables clamp/fork/provenance because the library refuses them. Accurate in effect, but the refusal lives in `require_branch_op`, which only the ingest functions call internally; a UI calling `store.fork` directly would NOT be refused by the store. Any future UI must call `require_branch_op` itself before offering an op.

### Backend capabilities the player does not expose

1. **Structure-fidelity scrub and dive at any point.** `tree_state_at(through)` reconstructs the desktop tree at ANY event, and the branch's `ax_delta`/`input_event` events form a real timeline. The player's structure pane has no transport at all: static stats, a per-poll ops bar chart, and a baked sample of the first 40 named nodes of the FINAL tree only.
2. **Screen-only scrub against the store.** `screen_frame_at(index)` serves any ingested frame; the player instead steps through 6 stills extracted from the Door 1 mp4 at build time (equivalent for those 6 frames, but disconnected from any ingested branch, and its video pane lacks the annotate UI that screen-only fidelity explicitly allows; annotations exist only on the native pane).
3. **Live fork execution and context inspection.** `run_fork` + `context_at` (what a forked agent is re-primed with) have no surface anywhere. The player can show a fork that already happened; nothing can make a new one.
4. **Typed edits and pins.** `typed_edit` (clamp/explain/pin), pin collection and violation reporting in `run_fork`, `check_pins`: unexposed. Pins (Golden Path invariants) have no UI representation at all.
5. **Explain machinery.** `edits.explain` (ghost-branch candidates with counterexamples), `smt.solve`, `taint.SliceReplay.slice_for`, `factgraph.provenance` / `dependents_of`, lens law checks: none reachable. The only explain-shaped thing in the player is the static provenance card.
6. **Fact-level provenance for derived numbers.** `FactGraph.provenance(path)` traces a figure to its source document and character span. The player's provenance is screen-cell level only, and only for one fact.
7. **Ingest itself.** `ingest_desktop_record` / `ingest_screen_frames` (Door 2 as an action: bring a new trace in) have no UI. The player can only display traces ingested before it was built.
8. **Library exports.** `export_html` (per-cell provenance scrubber) and Door 1 mp4 export are backend outputs the player re-implements in baked form rather than calling.
9. **Hash-chain verification.** `store.verify(branch)` (and per-event `hash`/`prev_hash` fields) could back a "record intact" indicator; nothing displays it.
10. **Encryption posture.** Stores are encrypted and fail closed on a wrong key; the player bakes decrypted content into a standalone HTML file, silently dropping that property for anything built this way.
