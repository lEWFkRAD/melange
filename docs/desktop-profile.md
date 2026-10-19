# Melange desktop profile (structure fidelity)

Status: spike-proven on the real Hermes desktop, 2026-10-16 (ONY-189,
ONY-169 Door 2). This profile covers GUI applications the way the
terminal profile covers consoles: a structured record of the interface,
reconstructable frame by frame, honest about what it is not.

The reusable M9 recorder and synthetic browser verification are documented
in [m9-desktop-capture.md](m9-desktop-capture.md). The measurements below
describe the historical spike, not newly generated synthetic fixtures.

## Capture

- Target: an Electron/Chromium application relaunched with
  `--remote-debugging-port` (CDP). No application code changes.
- Keyframe: `Accessibility.getFullAXTree` (the full accessibility
  tree). Measured on Hermes desktop: 1,802 nodes, about 707 KB as raw
  JSON. A `DOMSnapshot.captureSnapshot` (with layout rects) is an
  alternative keyframe at about 191 KB for a loading screen; the AX
  tree is the primary because it carries roles and names, not geometry.
- Deltas: poll the tree (1.5 to 2 second cadence in the spike) and diff
  structurally. Nodes are keyed by structural path built from childIds
  linkage; each node is slimmed to role, name, description, and sorted
  properties. A delta is a list of set/del ops on those paths.
  Measured: a still window produces zero ops per poll; opening the
  Settings view produced 2,415 ops, closing it 2,534.
- Input events are recorded as events on the same clock. Injected test
  input is labeled as injected, never presented as the user's.

## Record format

JSONL, one event per line: `keyframe` (raw AX node list), `delta`
(ops, poll number), `input` (labeled). Ingested into a TimelineStore by
`living_replay.ingest.ingest_desktop_record` as `ax_keyframe` /
`ax_delta` / `input_event` events under an `ingest_profile` event that
declares fidelity `structure`.

## Reconstruction

`living_replay.ingest.tree_state_at` replays keyframe + deltas to any
point. Verified exact against independently saved final trees in both
a still window (1,801 nodes, 0 deltas) and a live-change window
(1,818 nodes, 7,285 ops applied, 0 differing paths).

## Fidelity contract

`structure` supports scrub, dive (frame to tree), and annotate.
Clamp, fork, and causal provenance are refused by
`living_replay.ingest.require_op`: an AX trace has no executable state
behind it, and pretending otherwise would fabricate a recompute.

## Fork semantics (honest)

A desktop "fork" in this profile can only be: fork the underlying
agent session at its checkpoint (native machinery, Build 2), then
re-render the GUI from the forked session's state. The re-rendered GUI
is a NEW rendering of forked state, labeled as such; it is not a
continuation of the recorded pixels or tree. Anything weaker (a tree
snapshot you can scrub) is replay, not a fork, and is named replay.

## Operational notes

- Processes launched from a non-interactive session on Windows are
  reaped with that session; capture helpers must run in the user's
  interactive session.
- CDP screenshots (`Page.captureScreenshot`) come from the same
  endpoint and pair with tree frames for human verification.
