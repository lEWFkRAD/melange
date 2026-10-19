# Melange Roadmap

Where the project stands and what is open. Updated 2026-10-19, when the
repository went public.

## The north star

Melange is a universal video codec for computation. The destination is
ordinary software in ordinary hands: an accountant working in QuickBooks
or Sage 50 should see the same screens, the same functions, the same
vendor product she has always used. The codec adds one simple layer: the
work becomes a video she can rewind and fast-forward, and clicking a
number in that video lets her change it and watch the rest of the work
redo itself.

Agent sessions are the proving ground where the mechanics are being
built and measured, because they are the hardest sessions to fake. The
codec itself is software-agnostic: traces enter at a labeled fidelity
(native, structure, or screen-only), and every branch renders back out
to plain video.

## Where it stands

The engine is built and verified (proven on agent sessions and synthetic
surfaces; existing vendor software is the M9 rung below). Builds 1
through 3 landed in one unified tree:

- **Capture and replay.** A PTY tap records terminal sessions into an
  append-only, hash-chained timeline. A deterministic grid reconstructs
  any frame, with per-cell provenance back to the chunk and tool call
  that produced it. Replay fidelity against reference terminals is
  measured, gate by gate, in the README.
- **Forks and typed edits.** Any frame can fork. Edits are operators:
  CLAMP sets a value and recomputes only its dependents, EXPLAIN solves
  backward and accepts only candidates that verify by running forward,
  PIN (the Golden Path) holds an invariant that candidate futures must
  satisfy.
- **Solver rungs.** Bidirectional lenses, an SMT goal seek with
  forward verification, and lazy byte-level taint scoped to declared
  pipeline steps.
- **Encryption.** Timelines encrypt at rest with per-timeline keys;
  the store fails closed on a wrong key.
- **Sandbox.** A Firecracker microVM boundary for running sessions in
  isolation, checkpointing them, and forking the checkpoint.
- **Live service.** The bridge runs as a local service with encrypted
  stores, a shelf of timelines, and live clamp and explain.
- **Static export.** The flagship example (a synthetic tax return) is
  baked for static hosting in `surface-export/`.

Full test suite measured 2026-10-19 on WSL/Python 3.12.3: 225 tests ran,
209 passed and 16 skipped for external artifacts or Firecracker. See the
README and `docs/code-review-2026-10-19.md` for the environment and gates.

## Open work

### M9: real-desktop structure capture

The reusable Chromium/Electron CDP recorder now lives in
`living_replay.desktop`. It captures a selected application's accessibility
tree and structural deltas without changing the application, preserves
recorded timing, and feeds the live service's structure viewer. See
`docs/m9-desktop-capture.md` for setup and forward verification against
a real browser with synthetic content.

This completes the **structure capture and replay** rung. These recordings
support scrub, inspect and annotate; they refuse clamp, fork and causal
provenance because an accessibility tree is not an executable checkpoint.

Next: connect a managed executable desktop to the player, using a reusable
environment boundary. Application-specific adapters can later add semantic
editing, but should not be prerequisites for basic record, restore and
continue. Windows UI Automation drivers, cross-origin frame coverage and
synthetic vendor-app corpora remain open. The CDP recorder alone does not
provide vendor-app editing.

### Next acceptance milestone: a real desktop you can continue

The next deliverable is one unmodified editor, terminal and browser running
inside a managed desktop environment, controlled through the normal player:
**Record work → Rewind → Try it differently → Continue → Compare Original**.
Use a real code change in Melange itself, with actual source files, tests and
a browser preview. The bundled retry demonstration is useful evidence of the
current player, but does not satisfy this milestone.

Build one session supervisor with start, checkpoint, restore, input, capture
and stop operations. A checkpoint must bind RAM/process/device state, every
writable disk and the input-log position to one timeline step. Correct the
existing VM experiments before generalizing them: they preserve checkpoint
data but clone the fork's rootfs from a pristine image. That cannot preserve
arbitrary applications' checkpoint-time state.

Acceptance requires all of the following:

- The UI starts and records the session without manual import or registry edits.
- A restored What-if retains the chosen files, unsaved editor buffer and live
  application state. Subsequent changes from the Original must be absent.
- An unchanged continuation reproduces recorded file hashes and test outcomes;
  disagreement is visible. A changed continuation edits real code, runs real
  tests and updates the real browser, appending new events to the child.
- The Original's disks and timeline remain unchanged; reopening the supervisor
  retains both versions. Missing snapshots and failed runners never report success.
- A second unmodified desktop application uses the same environment backend,
  without a replacement calculation or an app-specific synthetic state file.

Begin with preinstalled dependencies and an offline session. Then generalize
the external-input journal to network responses, model replies, time and
randomness. Historical playback must not repeat external writes; a divergent
future needs an explicit live-I/O boundary. Remote server state is outside a
local checkpoint unless a provider adapter can version it.

The later universal-codec gates are portable checkpoint packaging, verified
replay between checkpoints, Windows and Linux application coverage, and
mapping visible values to their responsible inputs for semantic edits.
Track executable continuation separately from screen/outline playback and
from click-to-cause editing; each needs its own measured evidence.

### The live surface

The public static surface is a baked export. Actions such as clamp and
explain render as locked because they need the live service. The local
`service/static/` surface already calls the service API; `python3 service/melange_service.py`
serves it. The default player now puts the recording and playback bar first,
with optional step, inspection, note and correction panels. It opens real
recalculated session results immediately and can compare the unchanged
Original. The previous volume/map surface is available in Advanced view.
Windows users can start the synthetic example with `./start-melange.ps1`
(WSL required). Open work includes shared-hosting authentication and a
similarly direct workflow for executable vendor-app recordings. The baked
export remains the no-server demo.

### PANDA rung 4: opaque-binary taint

The spike (report in the README) showed PANDA boots and its taint
engine loads, while the Python binding layer blocked the
record-to-taint-replay chain. Named next steps, in order: add
`genisoimage` to the spike container and retry `record_cmd`; pin a
pandare release whose serial and replay API matches its documentation
and rerun `sandbox/panda_spike.py` unchanged; or drive PANDA through
its QEMU monitor and taint2 configuration directly. Help wanted:
anyone with PANDA or QEMU internals experience.

### Public demo hosting

The static export is ready to host. Standing up a public demo page,
with the synthetic-data labeling intact, is a small piece of work with
outsized value for new contributors.

### Packaging and platform reach

- The package still carries its working name internally
  (`living-replay` in `pyproject.toml`). A clean rename and a first
  tagged release are open.
- Capture is POSIX-only. A Windows capture path (ConPTY) is design
  work: the library already imports cleanly on Windows with capture
  unavailable there.

## Good first contributions

- Documentation: walk a new reader through fork, clamp, and explain
  with runnable examples.
- Test corpora: hostile terminal scenarios for the grid (scroll
  regions, alt screen, wide characters, partial escape sequences).
- CI hardening: the starter workflow runs the suite on Linux; macOS
  and dependency caching are welcome.
- Viewer polish: the exported timeline scrubber in
  `export_viewer.py` output can always use better keyboard support
  and accessibility.

Pick anything here, or open an issue with your own idea. The
contribution rules live in `CONTRIBUTING.md`.
