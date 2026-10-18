# Melange

### A video codec for computation

*Project write-up, October 16, 2026. Owner: Jeff Watts. Builders: Hermes (build), Kip (lead, verification). Status: Build 1 VERIFIED COMPLETE, October 16, 2026. Build 2 (live capture) VERIFIED COMPLETE, October 16, 2026.*

---

## 1. What Melange is

Melange records an agent (or any software) working the way a video codec records a scene, except the recording is not a picture of the work. The recording IS the work, in a form you can rewind.

Scrub back to the moment a decision was made. Insert an adjustment at that layer. The session runs forward again from that point with the new input, and the direction changes. The original timeline is never destroyed; it forks, and both paths stay on the shelf. A video that is also the software, which you can fast-forward and rewind to make edits to data.

The name is the dependency order. In Dune, the spice mélange is what makes seeing the paths possible at all. Here, without the recording there is no rewinding, no branching, and no pinned path. The pinned timeline feature is called the **Golden Path**: the one branch every fork must stay consistent with. Everybody will call the whole thing Spice by week two. That is fine.

## 2. The codec model

A conventional codec stores keyframes and the differences between them. Melange does the same with computation:

- **Keyframes are snapshots**: the full state of the session at a point in time.
- **Deltas are the logged actions and inputs** between snapshots.
- **Playback** is resuming a snapshot and replaying deltas. Cheap to store, fast to scrub.
- **A fork** is resuming a snapshot and changing what happens next: a new branch, cut from living state, not from a transcript.

Depth varies by what the software allows you to capture. A cooperative agent with an instrumented runtime gives full state: resume, fork, edit. Opaque software gives less. The playback experience is uniform; the honest depth underneath is labeled, never faked. (Section 5 covers how outside material enters at its true depth.)

## 3. The edit doctrine

Jeff's formulation, and it governs everything: **Edits apply to frames. Frames compile to inputs.**

Rewinding to a decision and adjusting it is not editing a recording. The frame is compiled back into the inputs that produced the downstream work, the adjustment is applied at the input level, and the session re-executes forward. Three typed edits:

- **CLAMP**: set a value at a layer and cut what fed it, the way a spreadsheet cell overwritten with a number stops listening to its formula. Downstream recomputes. In the interface, you just type.
- **EXPLAIN**: work backward from a wrong result and solve for the input or decision that explains it. The system proposes candidate explanations, each one a fork that must re-execute forward and check out before it counts.
- **PIN**: an invariant that survives every fork. Search only the pasts consistent with the pinned present, iterating fork, forward run, check, adjust, until it holds. In the product, a pinned timeline is a **Golden Path**.

Nothing is accepted on a solver's say-so. Every proposed edit is verified by forward execution; failures become counterexamples that sharpen the next attempt. Ambiguity is not hidden: competing verified explanations appear as ghost branches and the user keeps the one that is right.

The precedent hiding in plain sight is the parametric CAD timeline: edit a feature in the middle of a SolidWorks or Fusion history and the model rebuilds downstream against its constraints, with unresolvable dependents flagged. Accountants and engineers already trust this pattern with geometry. Melange applies it to agent work.

## 4. Why it matters (the uses Jeff named)

- **Showing people the work.** Rewind a Hermes chat or a TUI session to the layer where a decision was made and adjust it live, in front of an audience. The demo is the product: not a transcript you read, a timeline you can reach into.
- **Firm explanatory videos.** Jeff already makes explanatory videos for the partners at Bearden. Inserting context and edits into a recorded work session turns a narration into the actual work, correctable at the layer where it happened.
- **Debugging and trust.** When an agent does something wrong, the question is never "what does the log say." It is "what did it know at that layer, and what changes if this decision changes." Melange answers the second question by running it.

## 5. The two doors (the Suzu architecture)

In the Nous Research Discord on October 16, 2026, Suzu raised the opposite direction: replay traces and changes so they can be transcribed TO video. **Credit: the two-doors framing is Suzu's contribution.** His point became half the architecture. Both directions are now part of the design. One master format, the codec. Material flows in one door and out the other, and in the middle it stays alive.

### The way in: trace transcription (ingest)

Not all software can be snapshotted from the inside. Plenty of it still leaves traces: logs, event streams, files changed, screens. Ingest transcribes a trace into codec frames and deltas:

- Every ingested frame carries a **fidelity label** recording how it was captured (full state, event trace, screen only) and what operations that fidelity honestly supports.
- Scrubbing and annotation work at every fidelity. Forking and editing work only where the captured state supports them, and the interface says so at the layer, not in a footnote.
- Ingest is what makes "universal" an honest word: uniform playback, labeled depth.

### The way out: render (export)

Any point on any timeline, including a fork that never happened in real time, renders down to an ordinary video file:

- An export names its source exactly: which branch, which frame range, which edits applied. The render carries that provenance with it.
- Counterfactuals are exportable. You can show someone the run where the decision went the other way, as a normal video, playable anywhere, no Melange player required.
- Export is the distribution channel: partners, clients, a Discord channel, a conference screen.

### The rules that bind both doors

1. **The codec is the master.** Video renders and trace transcriptions are derivatives. Nothing derivative is ever mistaken for state.
2. **Fidelity is data, not marketing.** Every frame knows its capture depth, and every operation advertises the depth it requires.
3. **Edits never exceed the fidelity of the frames they touch.** A screen-only frame can be annotated, not clamped.
4. **Provenance crosses both doors.** An export can be traced back to its branch and frames; an ingested frame can be traced back to its trace.

## 6. Where it stands today (verified October 16, 2026)

Stated plainly, because this project has already survived one round of agents calling it impossible and one board status that claimed more than the evidence:

- **Proven in the sandbox, October 16, 2026:** the fork gate passes end to end. A live Hermes session ran a task, was snapshotted mid-run, and both the original and a fork resumed from that snapshot. The original finished unchanged. The fork woke knowing what the session knew, took a reviewer's correction, and recomputed its downstream figures, with the original untouched beside it. Model calls are recorded on the encrypted timeline in both legs.
- **The gate corpus passes:** replay fidelity 99.85% cell agreement against a reference emulator; pixel-to-cause attribution 98.11%; zero of six seeded secrets in the persisted timeline; replay by record reproduces the transcript with zero live model calls; typed edits (clamp, explain, pin) behave per the doctrine in Section 3.
- **One honesty label:** the sandbox workload's tax arithmetic is simplified fixture math written for the gate, not the real federal tables. Any demo using its figures carries that label.
- **Live capture proven, October 16, 2026 (Build 2):** a real, unscripted Hermes session ran inside the boundary through the Strata engine, driven turn by turn from the host: it read the session notes on its data drive and wrote a status brief, took a second turn adding a risks section, was snapshotted mid-session, and finished. The original closed with 153 recorded events and 16 model calls. A fork resumed from the mid-session snapshot, shares a 108-event hash-identical prefix with the original, and finished with the fidelity figure corrected to 99.85 where the original keeps the notes' rounded 99.9 (fork: 182 events, 15 model calls; both hash chains verify). A fresh guest then replayed the original session from the record alone, with no model bridge running at all: 153 events, 16 model calls, zero replay misses, every chat response identical to the original's, and the brief reproduced byte for byte. One infrastructure lesson, now fixed in the harness: these guests have no working hardware entropy path, so fresh boots could stall indefinitely at the agent's first blocking random call; the live image's init now credits host-supplied random bytes into the guest kernel at boot, and CRNG initializes in under a second.
- **Both doors built, October 16, 2026:** Door 1 exports any recorded terminal timeline as an ordinary mp4 (the live session exports as 66 frames, 49.6 seconds; the fork as 81 frames, 60.0 seconds). Door 2 ingests traces recorded elsewhere at a labeled fidelity enforced in the library: a desktop accessibility record imports as `structure` (scrub, dive, annotate; clamp, fork, and provenance refused), and video frames import as `screen-only` (scrub and annotate only), coming back out of the store byte-identical.
- **Desktop capture proven, October 16, 2026:** the Hermes desktop app (Electron) was recorded over CDP after an approved relaunch with a debug port: accessibility-tree keyframes (1,802 nodes) plus structural deltas. A still window costs zero deltas; opening and closing the Settings view mid-record produced 7,285 delta ops. Reconstruction from the record alone is exact in both cases (1,801 and 1,818 nodes, zero differing). The profile, including its honest fork semantics (a desktop fork re-renders GUI state from a forked session and is labeled a re-render), is written up in the repo as `docs/desktop-profile.md`.
- **Working surface v1, October 16, 2026:** a self-contained player over the real timelines: play, pause, scrub, and step across all 153 original events (182 on the fork), a shared-prefix-shaded scrubber, a frame inspector, per-cell provenance for the fidelity figure, the clamp performed as a branch switch to the verified recomputed future, and the two ingested fidelities presented with their refused operations disabled at the control level. Render-verified in a real browser with screenshots.

## 7. Sequence

1. **Build 1** (done, October 16, 2026): fork state gate green, gate corpus green, report verified.
2. **Live capture** (done, October 16, 2026): a real Hermes session recorded, forked, and replayed from the record with zero live calls, as detailed in Section 6.
3. **The doors** (done, October 16, 2026): export render first, then trace ingest at labeled fidelity, including the desktop structure profile.
4. **The surface** (v1 done, October 16, 2026): a working player over the real timelines, detailed in Section 6. A hosted version of the surface, and the public GitHub repository (ONY-173, still with Hermes), remain the open items.

The through-line: the spice first, then the paths, then the Golden one.
