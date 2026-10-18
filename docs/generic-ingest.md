# Melange generic ingest (Door 2 for arbitrary software)

Status: implemented in `living_replay.ingest` (`ingest_generic_events`),
2026-10-18 (M10). Proof workload: a shell session running git and this
repo's own unittest runner, recorded by `tools/make_generic_fixture.py`
into `tests/generic-build-record.jsonl` and verified end to end by
`tests/test_ingest_generic.py`.

The built-in profiles (Hermes session, desktop AX, screen frames) each
know their source's shape. This path knows none: any program that can
emit a timestamped event stream can be recorded, at the honest depth
its stream supports. No per-program code, no profile to register.

## Stream format

JSONL, one object per line:

| field | required | meaning |
|---|---|---|
| `ts` | yes | event time, seconds (number; epoch or session-relative) |
| `action` | yes | what happened (`command`, `output`, `model_call`, anything) |
| `actor` | no | who did it (default `unknown`) |
| `payload` | no | any JSON value (default `{}`) |
| `state` | no | a full snapshot (object) of the program's state at this event |

Malformed lines (not JSON, missing/non-numeric `ts`, missing
`action`, non-object `state`) abort the ingest with the line number;
nothing is stored from a stream that does not parse whole.

## Fidelity is derived, never declared

The stream does not get to name its depth. Ingest inspects the
content and files the branch at exactly what checks out:

- **native** — only when the stream carries a recorded computation
  that passes the same rebuildability test `bridge.clamp` applies:
  a `model_call` event with `figures`, plus an intake string the
  recorded-computation lens can parse, so the inputs genuinely
  rebuild from the record and a clamp genuinely re-executes.
  `model_call` / `tool_call` payloads are stored under their native
  event kinds so the native machinery sees them.
- **structure** — at least one `state` snapshot. Dive is
  `generic_state_at`: the latest snapshot at or before the point.
  Nothing is interpolated between snapshots.
- **screen-only** caps — anything else. An event transcript with no
  state in it can be scrubbed and annotated; there is nothing to
  dive into and nothing to recompute, so dive/clamp/fork/causal
  provenance are refused by `require_branch_op`, as everywhere else.

A `model_call` with figures whose intake does not rebuild is recorded
in the branch's `ingest_profile` as `computation: "unverified"` and
buys no fidelity. There is no path by which a label alone upgrades a
recording.

## Traceability

Every ingested event stores `src: {"line", "sha256"}` — its line
number in the source stream and the SHA-256 of that raw line — and
the profile event stores the whole stream's SHA-256. `source_trace`
returns the link for any event; `verify_source_line` re-hashes a
candidate original and fails closed on any difference. This is how an
ingested frame traces back to its trace (P11); it is not the causal
`provenance` capability, which stays native-only.

## Roundtrip

`reconstruct_generic_stream` rebuilds the original events (ts, actor,
action, payload, state) from the store. For the proof fixture the
reconstruction equals the parsed source stream exactly, and the
store's hash-chain seal verifies.

## What "general" still does not cover

- No capture: the program (or a wrapper like the fixture tool) must
  emit the stream. Arbitrary running programs are not tapped.
- State is snapshots only: no deltas, no interpolation, and snapshots
  are the emitter's word for the state — ingest verifies the record's
  integrity, not the emitter's honesty.
- The native tier recognizes the recorded-computation shape the
  engine can actually re-execute today (the flagship FactGraph
  intake). Other computation shapes ingest at structure or below
  until the engine can rebuild them; they are never relabeled.
- No fidelity raising after the fact: a screen-only-caps transcript
  cannot gain structure later (reconstruction, e.g. OCR/AX recovery,
  remains future work under M10's second half).
