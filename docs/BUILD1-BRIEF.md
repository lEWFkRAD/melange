# Living Replay — Build 1 brief (for Codex, SHATNER)

Owner direction (Jeff, 2026-10-15): once the Living Replay feasibility page update is done, start building it. Codex leads the build. Hermes is OUT of the fight right now — do not route this through Hermes, do not wait on Hermes.

## What Living Replay is (one paragraph)

A codec for agent computation: any work an agent does inside a Living Replay machine can be recorded as keyframes plus an input log, scrubbed like video, and forked live from any checkpoint, with semantic depth layered as profiles on one universal timeline. The graded research (two passes, reports in Kip's research notes 2026-10-15) established: capture/playback are proven inside a controlled boundary (QEMU record/replay, PANDA); fork is proven at checkpoints inside the boundary; edit means change-an-input-at-a-checkpoint and re-execute; provenance is exact for explicit data flow inside the boundary and for the agent event graph. Build 1 builds the harness-first core (architecture C), designed so it runs unchanged inside a microVM later (architecture B). Desktop-first (A) is deferred pending a separate spike.

## Build 1 scope — the timeline core, terminal surface only

Repo: create `C:\Users\Administrator\Projects\living-replay\` (git, local). Linux-first Python (developed/tested in SHATNER WSL2 Ubuntu is fine); no Windows-only dependencies in the core. Synthetic data only. No client/firm data anywhere near this repo.

Deliverables:

1. **Timeline store.** Append-only event log (SQLite) + content-addressed store for grid/frame/snapshot payloads. Event schema covers, on one clock with one ID scheme: terminal byte chunks, agent tool calls (input/output), model calls (prompt, sampled tokens, logprobs where available), workspace snapshots (references), context notes (injected context), forks (parent checkpoint + edit). Hash-chained (each event carries the previous event's hash) — this is the OathLedger idea: the event log is the ledger. Fork tree is data: branches are event streams sharing a prefix; the original branch is immutable.
2. **Capture: own PTY tap, NOT tmux control mode.** Research finding that binds this build: tmux control mode has no output sequence numbers, so dropped bytes at a capture boundary cannot be detected — fidelity cannot be proven from it. Record the raw PTY byte stream (with monotonic timestamps + byte offsets) from a pseudo-terminal you own, plus a periodic full-grid keyframe. Pair with harness hooks where available, but the PTY tap is the substrate of record.
3. **Grid model with per-cell provenance.** Your own terminal-emulator grid model fed by the recorded byte stream. Every cell carries provenance: byte offset -> output chunk -> tool call / agent event in flight. Grid keyframes (periodic full-grid snapshots) + deltas, codec-style.
4. **Redaction at capture — FIRST-CLASS, from day one, not a later phase.** Research re-ranked this to spike #1: it is the only legal (not just technical) risk, and capture-side redaction constrains the capture design. Implement: secret-pattern redaction (API keys, tokens, passwords, SSN-shaped strings) applied BEFORE persistence, so a secret never reaches the stored timeline; structural hooks so designated fields/windows can be excluded at capture; timeline encrypted at rest or, if full encryption is too much for Build 1, a documented key design + redaction proven by the gate below. Scanner redaction is a second pass, never the only pass.
5. **Fork from checkpoint.** Fork = new session: restore the workspace snapshot at the chosen checkpoint (filesystem CoW — reflink copy or git-based snapshot; btrfs where available), truncate the agent context/event stream to that checkpoint, optionally append a pinned context note ("Inject context"), and continue live from there as a new branch. Fork restarts the agent process from context; it does NOT resume mid-process memory state (no CRIU/QEMU/Firecracker in Build 1). External effects are never un-happened and never replayed silently: recorded external responses are served back up to the fork point; after it, calls are live and marked as a new branch's effects.
6. **Scrubber (minimal).** A local viewer that opens a recorded timeline, scrubs to any event, renders the grid at that point by decode-forward from the nearest grid keyframe, and shows the provenance panel for a clicked cell (the chunk + tool call that produced it). Function over beauty; a simple web or TUI viewer is fine. (The Quickshell overlay is a later phase.)
7. **Tests + README.** Automated tests for every gate below; README stating the architecture, the event schema, what Build 1 proves and what it explicitly does not claim.

## Gates (Build 1 is done when all pass, with evidence posted on the ticket)

- G1 Record/replay fidelity: record a scripted hostile terminal session (shell commands, a full-screen TUI such as vim or htop, the agent harness itself); reconstruction from the timeline matches a reference emulator's final screen byte-exactly on the test corpus, and grid state at 100 sampled times matches ground truth capture at >=99.5% of cells.
- G2 Pixel-to-cause: on the recorded corpus, clicking any cell of shell/file output resolves to the correct output chunk and tool call in >=95% of sampled cells; failures (e.g. full-screen TUI redraws) are detected and reported as unattributed, never silently misattributed.
- G3 Fork: fork from a mid-run checkpoint with an injected context note; the forked session continues and finishes the scripted task correctly, on a new branch, with the original branch unchanged.
- G4 Redaction: run the seeded-secrets corpus (fake API key in env echoed to screen, fake SSN in a document shown in terminal, password typed at a prompt); automated scan of the persisted timeline finds ZERO seeded secrets, while the timeline remains fully usable for G1-G3.
- G5 Determinism-by-record: replaying a recorded agent run using recorded model/tool responses reproduces the recorded terminal transcript exactly, with zero live model calls.

## Edit doctrine (Jeff, 2026-10-15 — this SUPERSEDES the simpler "edits apply to inputs" framing)

**Edits apply to frames. Frames compile to inputs.** The frame is the interface; a solver sits underneath it. An edit on a derived value is an inverse problem, not undefined behaviour — underdetermined means many candidate pasts, and the system's job is to solve, verify, and branch, not to refuse.

Every edit event in the timeline schema is TYPED, one of three kinds:
- **Clamp** ("make it this") — Pearl's do-operator: cut the value's incoming dependencies, set it, recompute downstream. Fully defined; spreadsheets (overwrite formula with constant) and tax software (field overrides) already do this. A plain type in the UI is a clamp.
- **Explain** ("this should have been this") — abduction: solve backward for which input or decision was wrong. The hard kind; handled by the solver ladder + forward verification, below.
- **Pin** ("keep this true") — an invariant that must hold in every fork (CAD-dimension-style). Pins are checked after every fork/recompute; a fork that violates a pin is not accepted silently — it reports the violated pins (dependents that cannot resolve go "red", CAD-style).

The solver ladder — try the cheapest rung that applies; NOTHING is accepted unless forward execution confirms it lands on the edited value (counterexample-guided loop: failed candidates become counterexamples for the next round):
1. Exact graphs — bidirectional transformations (lenses: Foster/Pierce, Boomerang; get/put with round-trip laws). Design Hermes tools as lenses where feasible: extraction get = document -> value, put = value -> document region. Fact Graph and spreadsheet-like graphs are invertible-ish dependency graphs and live here.
2. Numeric pipelines — differentiable programming / SMT (Z3): gradient or solver search for the minimum-norm / fewest-inputs change that satisfies the edit as a constraint over the dependency graph. Goal Seek across the whole history.
3. Agent reasoning — retrocausal prompting in a CEGIS loop: the agent proposes candidate explanations ("which source or decision was wrong?"), each candidate forks and runs FORWARD to verify it reproduces the edited value; failures feed the next round.
4. Opaque binaries — lazy whole-system taint: recording is cheap; only when the user clicks a value do we replay that slice with byte-level taint (PANDA taint2) to find which input bytes flowed into it. Slow, lazy, on-demand — provenance through uninstrumented programs.

Ambiguity = branches. When several minimal explanations verify, do NOT pick one silently: the scrubber presents them as ghost branches (one per minimal explanation), each a real verified fork; the user scrubs between them and keeps one.

Propagation speed: recompute must be incremental, not a rerun — self-adjusting computation (Acar/Adapton), Salsa-style demand-driven queries (rust-analyzer's engine), differential dataflow. Wrap the agent-graph pipeline so a fork's ripple touches only true dependents. (Measured gate in a later build: dependents-only must beat full re-execution or the feature is cut — see research plan v2 spike 6.)

Precedent to design against: parametric CAD (Fusion 360 / SolidWorks). A history timeline where you drag back, edit a feature mid-history, and everything downstream rebuilds against a constraint solver, with unresolvable dependents flagged. Living Replay is the CAD timeline applied to computation.

Build 1's slice of this doctrine: the event schema carries typed edits from day one; clamp is fully implemented at checkpoint level (set value, cut incoming edge in the agent event graph, recompute/re-run downstream); pins are stored and checked on every fork (violations reported); explain is implemented as the rung-3 CEGIS loop over the agent event graph for the scripted demo workload (propose -> fork -> forward-verify -> accept or counterexample), with rungs 1/2/4 specified in the README as the solver interface (a Solver protocol the ladder plugs into) rather than built. Do not fake explain: if no candidate verifies, the edit stays unresolved and says so.

Additional gate:
- G6 Typed edits: (a) a clamp on a derived value in the demo workload takes effect and downstream values recompute consistently; (b) an explain edit on the demo workload produces at least one forward-verified branch, or reports unresolved with the counterexamples it tried; (c) a pin violated by a fork is reported by name, never silently dropped.

## Explicitly OUT of Build 1

GUI surface / AT-SPI; process-memory restore (CRIU/QEMU/Firecracker); layers 4-6 (call stacks, token forcing UI, tensors); dependents-only re-execution (v1 re-runs everything after the fork); arbitrary agents (one harness: your own scripted test harness / a shell agent loop you control); real taxpayer or any real user data; HyperFormula (GPLv3/paid — licence decision is Jeff's, do not make it load-bearing).

## Working rules

- Read the wiki + search the vault before starting; write back on completion (standing Paperclip knowledge loop).
- Synthetic fixtures only; if you need a W-2-shaped document, generate a fake one.
- If a gate cannot pass, report the measured number and the failure taxonomy on the ticket — do not quietly weaken a gate. Escalate to Kip/Jeff only: missing source material that exists nowhere on the estate, decisions only Jeff can make, and final acts.
- Post progress evidence on the ticket (files, test output), not just claims.
