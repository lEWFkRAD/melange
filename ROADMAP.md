# Melange Roadmap

Where the project stands and what is open. Updated 2026-10-19, when the
repository went public.

## Where it stands

The engine is built and verified. Builds 1 through 3 landed in one
unified tree:

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

Full test suite: 175 tests passing (3 skipped, environment-gated).

## Open work

### M9: real-desktop structure capture

Today the desktop surface is served by an instrumented synthetic app.
The next fidelity rung is capturing a real desktop application through
its accessibility tree, per `docs/desktop-profile.md`. This needs a
desktop app that exposes a debug or accessibility endpoint to record
against. Help wanted: capture drivers, tree differencing, corpora.

### The live surface

The web surface a visitor can open today is a baked export. Actions
such as clamp and explain render as locked because they need the live
service. Wiring the surface to the service API, with the baked export
kept as the no-server demo, is open work. Help wanted: frontend,
service API polish, auth story for shared hosting.

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
