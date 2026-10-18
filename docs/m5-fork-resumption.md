# M5 — Fork resumption: "Reopen in a live session"

A fork used to be a past you could scrub, clamp, and re-derive from,
but not re-enter. M5 makes the fork a present again: a live agent
boots with the forked branch's workspace restored to its fork-point
state and continues the session, with every new event appended onto
that same branch. The parent branch is never written.

Scope of this build: the **sandbox guest path** (Firecracker on
onyx-Linux, the Build 2 machinery). Resuming a production Hermes
session on SHATNER remains behind Jeff's separate go.

## How it works

Three pieces, matching the three places state lives:

1. **Library — `src/living_replay/resume.py`.** Planning and
   verification, guest-independent.
   - `plan_resume(store, branch, checkpoint)` resolves the checkpoint
     on the branch's *logical* timeline (inherited prefix + fork event
     + local tail, via `store.replay_events`) and refuses checkpoints
     that are not on it — a sibling branch's event, a parent event
     above the fork point, a nonexistent id. The plan captures the
     branch's entire current logical timeline (ids + hashes) as the
     prefix that must survive, plus the latest `workspace_snapshot`
     event on that timeline.
   - `prepare_workspace(store, plan, dest)` restores that snapshot
     through `forking.restore_workspace`; it returns None (says so)
     when the branch carries no snapshot.
   - `capture_branch_state(store, branch)` baselines a branch's LOCAL
     events for the parent-isolation check.
   - `verify_resume(store, plan, parents=...)` reports: prefix
     identity (the pre-resume timeline is still an exact prefix),
     continuation presence, chain integrity **across the whole
     ancestry** (`store.verify` per ancestor — the branch-local check
     alone would miss a rewritten inherited event), and parent
     isolation (baseline equality per named branch).

2. **Guest — `sandbox/live_resume_agent.py`.** The Build 2 live
   agent retargeted at a branch: the host bakes `RUN_RESUME`,
   `RESUME_BRANCH`, and `RESUME_CHECKPOINT` into the data drive; init
   (`sandbox/guest_init.sh`) dispatches on `RUN_RESUME`. The agent
   refuses to boot if the named branch has no events in the store,
   writes a resume note onto the branch (stating plainly that the
   workspace carried over and the model's conversational memory
   restarts), and runs the usual TURN/FINISH control loop — notes,
   screen, and shim-reported model calls all append to the branch.
   The API key never enters the guest, as in Build 2.

3. **Host — `sandbox/run_resume_guest.py`.** Prepares a store copy
   (fork at the checkpoint, snapshot the checkpoint-time workspace
   onto the branch, plan, baselines saved to `baseline.json` BEFORE
   the guest boots), builds the data drive from a staging dir
   (`mkfs.ext4 -d`: timeline + restored ws + control files + entropy
   seed), boots a fresh guest behind the Strata bridge, drives two
   turns, then verifies the EXTRACTED store against the pre-boot
   baselines — verification reads the record, not the runner's memory.

## Proof run (onyx-Linux, 2026-10-18)

Store: the Build 2 live session, `/home/kip/lr-sandbox/live-1792176400`
(original timeline: 153 events on `main`, 16 model calls). Checkpoint:
event **108**, the pinned mid-session `checkpoint` note Build 2 forked
from. Run tree: `/home/kip/lr-sandbox/resume-1792348063`
(`sandbox/run_resume_guest.py`, runner log `m5-run-final.log` beside
the run trees in `/home/kip/lr-sandbox`).

- Fork event **154** created branch `reopen` at checkpoint 108;
  workspace snapshot event **155** carries the checkpoint-time
  workspace (brief 2,161 bytes, from `data-fork-src.ext4`, the drive
  copied at the original snapshot moment). Plan prefix: **110**
  logical events.
- Guest booted fresh from `rootfs-resume.ext4` (live rootfs + resume
  agent + updated init/library), LR-READY, two live turns
  (read the brief, append a `Resumed session` section; then print it),
  LR-DONE, clean serial. 9 bridge exchanges.
- After: branch logical timeline **156** events = 110 prefix + **46
  new** (ids 156–201), including **9 new model_call events**.
  `verify_resume` → `ok: true`: prefix_ok, chain_ok (ancestry-wide),
  parents_ok, continuation_ok. Parent `main`: **153 events before and
  after, unchanged, chain valid.**
- Workspace: brief 2,161 → **2,283 bytes**; it keeps the checkpoint
  figure (99.9, no 99.85 — turn 3's correction never happened on this
  branch) and gained the `Resumed session` section.
- Wrong key is rejected on the resumed store. The credential scan is
  reported honestly: the estate key is a 5-character string that is
  also an ordinary word in Hermes's recorded tool schemas (66
  standalone word matches across the branch timeline, present
  identically in the original Build 2 events); occurrences in a
  credential context (Bearer/api_key/Authorization): **none**.

## Tests

`tests/test_m5_resume.py`, 16 tests, guest-independent: plan shape on
forked and root branches, snapshot precedence (branch-local over
inherited), workspace restore bytes, checkpoint refusal cases
(above-fork, sibling, nonexistent, empty branch), nested-fork
ancestry, honest-continuation verification, and the three failure
detectors (empty continuation, parent appended after baseline,
payload rewritten in the inherited prefix — caught by ancestry-wide
chain verification). One test repeats the flow on an encrypted store.
Full suite: **109 tests OK, skipped=5** (baseline 93 + 16 new).

## Honest limits

- **Sandbox guest only.** The resumed session runs in the Firecracker
  boundary against the sandbox Hermes install. "Reopen" from the
  desktop app or a production gateway session (the rest of M5's
  audit line) still needs Jeff's go for touching production sessions.
- **The model's memory restarts.** The guest boots fresh: Hermes's
  conversational context does not carry over. What carries is the
  recorded workspace (files at their fork-point bytes) and the
  timeline itself. The continuation's first prompt works from the
  workspace, and the resume note on the branch says exactly this.
- **Workspace means the data-drive workspace.** State Hermes keeps in
  its home (session DBs, memories) lives in the rootfs, outside the
  branch snapshot; it is not restored. A checkpoint with no
  `workspace_snapshot` event on the branch yields `prepare_workspace
  → None` and the host must supply the workspace another way — the
  runner sources it from the Build 2 fork-source drive for the proof.
- **Continuation fidelity is live fidelity.** New events are ordinary
  live capture (native profile): the continuation is new sampling
  from the model, not replay. The prefix guarantees are about the
  record, not about the model repeating itself.
- Guests on this host run under sudo (the /dev/kvm ACL names
  jeffrey-watts and root only), same as the Build 2 runs.
