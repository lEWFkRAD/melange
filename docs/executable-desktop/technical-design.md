# Executable desktop: technical design

**Proposed v1, not an implemented API or a successful VM receipt.** See the
[system map](README.md) for scope and [implementation plan](implementation-plan.md)
for acceptance. Contracts are deliberately narrow: one qualified offline
desktop, exact checkpoints, one writer and a paused Original.

## 1. Invariants and identities

- `recording_id`: persistent UUID; the existing registry `sid` remains a local
  alias. Export/reimport must not silently create a second authority for it.
- `branch`: immutable internal identity with a separate display label. Keep
  existing branch names compatible; new desktop children use UUID-based names.
- `anchor`: `{branch, event_id, event_hash}` in the recording's logical ancestry.
  Step numbers and wall-clock timestamps are presentation indexes, not identity.
- `checkpoint_id`: immutable artifact bundle identity; `manifest_digest` binds
  its exact UTF-8 manifest bytes. No self-referential digest inside the manifest.
- `session_id`: one managed live workspace; `runtime_id` changes on restore.
- `operation_id`: durable start/checkpoint/stop/fork/restore/continue/cancel work.
- `input_id`, `sequence`: unique command and monotonically increasing admission
  order for a runtime incarnation. Receipts distinguish admission from delivery.
- `revision`: server-side compare-and-swap version. `fencing_token`: increasing
  generation that every runtime command and state commit must validate.

A child inherits the exact logical prefix through its checkpoint anchor.
Source events, checkpoint artifacts and Original disks are immutable during
the fork audit. The child writes private storage. Displaying a frame, verifying
a local hash chain, or appending an instruction is never proof of execution.

## 2. Runtime interface

Proposed module boundary: `src/living_replay/execution/`. Keep policy in the
supervisor and backend-specific commands in `backends/`. The HTTP service
submits operations; it does not spawn QEMU while holding `REGISTRY.lock`.

```python
class DesktopBackend(Protocol):
    def qualify(self, profile_id: str) -> Qualification: ...
    def start(self, request: StartRequest, lease: Lease) -> RuntimeHandle: ...
    def inspect(self, runtime: RuntimeHandle, lease: Lease) -> RuntimeStatus: ...
    def close_admission(self, runtime: RuntimeHandle, lease: Lease) -> Barrier: ...
    def checkpoint(self, runtime: RuntimeHandle, barrier: Barrier,
                   sink: ArtifactSink, lease: Lease) -> SnapshotDraft: ...
    def restore(self, checkpoint: VerifiedCheckpoint,
                resources: PrivateResources, lease: Lease) -> RuntimeHandle: ...
    def verify_restored(self, runtime: RuntimeHandle,
                        expected: VerifiedCheckpoint, lease: Lease) -> RestoreReceipt: ...
    def deliver_input(self, runtime: RuntimeHandle,
                      command: InputCommand, lease: Lease) -> DeliveryReceipt: ...
    def observe(self, runtime: RuntimeHandle, after: ObservationCursor,
                lease: Lease) -> ObservationBatch: ...
    def pause(self, runtime: RuntimeHandle, lease: Lease) -> PauseReceipt: ...
    def resume(self, runtime: RuntimeHandle, lease: Lease) -> ResumeReceipt: ...
    def open_admission(self, runtime: RuntimeHandle, cursor: ObservationCursor,
                       control: ControlLease, lease: Lease) -> AdmissionReceipt: ...
    def stop(self, runtime: RuntimeHandle, lease: Lease) -> StopReceipt: ...
```

These are interface sketches, not importable Python. `pause` preserves the
guest for Stop recording; `stop` releases an owned process only after its
preservation policy is satisfied. Restore returns paused or externally gated
until readiness is verified. Every operation has a deadline and an inspectable
outcome; cancellation is cooperative, not an assumption that work vanished.

`seek_verified(checkpoint, target_cursor)` is a future optional capability.
Absent qualification, its action is unavailable. Do not implement it by
sleeping for the original elapsed time or replaying mouse coordinates blindly.

For QEMU, use a dedicated QMP connection and command IDs, asynchronous job
tracking, and an allowlisted machine/device configuration. `snapshot-save`
and `snapshot-load` return before their jobs finish; inspect job completion
and error state. Inventory all writable block nodes. The upstream reference
recommends including them all for consistent snapshots.
[QMP specification](https://www.qemu.org/docs/master/interop/qmp-spec.html),
[QMP reference](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html).

C0 must select and record an exact installed QEMU build, machine type, CPU
model, firmware, display device and acceleration mode. Upstream `master`
documentation is a research reference, not a pinned dependency. Start with
software display and no device passthrough. Internal snapshots, export/clone
mechanics and whether acceleration supports the eventual replay mode remain
qualification decisions, not inferred guarantees.

## 3. Consistent checkpoint protocol

```mermaid
sequenceDiagram
  participant P as Player
  participant S as Supervisor
  participant R as Runtime and capture
  participant A as Artifact store
  participant L as Ledger and catalog
  P->>S: Save moment (idempotency key, revision)
  S->>L: Reserve operation and lease
  S->>R: Close input/I-O admission; drain acknowledged producers
  R-->>S: Barrier cursors and no unresolved external outcome
  S->>R: Pause machine and quiesce devices
  R-->>S: Paused frame and snapshot consistency boundary
  S->>L: Commit anchor frame after draining prior observations
  S->>R: Capture RAM/devices and every writable disk
  R->>A: Stream staged encrypted artifacts
  A-->>S: Durable verified bundle and manifest digest
  S->>L: Commit catalog + execution_checkpoint + operation result
  S->>R: Resume and reopen admission, if recording continues
  S-->>P: Saved exact moment (anchor and checkpoint ID)
```

Detailed ordering:

1. Reserve the operation before VM side effects. Close user/agent input and
   brokered I/O admission. Drain all admitted inputs to a known delivery state;
   unresolved delivery blocks an exact checkpoint. Flush each capture producer
   through acknowledged sequence numbers. A dropped socket report is a failure.
2. Request the backend's qualified machine consistency barrier. Pause all
   vCPUs and establish a stable device/block state using supported snapshot
   facilities. Capture a framebuffer from that stopped boundary. Drain earlier
   observations and commit this frame as the anchor; its payload includes the
   checkpoint UUID and cursors, **not** the eventual manifest digest.
3. Preserve the machine state and **all** writable storage from that same
   paused interval: root disk, data disk, application profiles, swap and any
   additional writable block device. Include all immutable backing identities.
   A snapshot containing RAM plus yesterday's root disk is invalid.
4. Publish artifacts using the crash protocol below. A checkpoint-complete
   event comes after the anchor and refers to the manifest and anchor. The
   manifest points to the anchor, not its own completion event; this avoids a
   digest cycle. A failed attempt may leave a watchable frame without a usable
   checkpoint. Eligibility comes from the catalog, never the frame's UUID alone.
5. If recording continues, resume and reopen input after the barrier releases.
   If Stop recording requested this checkpoint, remain paused. A failed attempt
   must resume safely or expose a recoverable paused state, never lose the last
   good checkpoint.

**Do not force applications to save.** Their unsaved buffers and open handles
are part of RAM state. Whole-machine consistency is different from an
application-level transaction boundary. Optional filesystem freeze is allowed
only if the backend proves a matching thaw path, including recovery after
coordinator failure. It is not a substitute for RAM/device/disk consistency.
When the VM resumes, all vCPUs may run; do not claim only a helper executes.
Keep host input and external-I/O gates closed during readiness checks.

The first safe baseline can use full immutable disk copies made through a
qualified paused/export procedure. Copying a live QEMU-owned image with an
ordinary filesystem copy is not accepted evidence of consistent export. C0
must prove the chosen backend procedure before CoW optimization is considered.
Guest edits happen through the restored guest, never by patching a disk paired
with already-captured RAM.

## 4. Artifact and database transactions

Draft shape: [checkpoint.schema.json](contracts/checkpoint.schema.json).
Schema validation checks syntax; runtime qualification checks meaning and
actual artifacts. A manifest lists the complete block-device inventory and
RAM/device-state coverage, even if the backend stores several roles inside
one physical container. Role references may share an artifact ID.

Store large artifacts through a streaming sink, not `TimelineStore.put_blob`
(which receives an entire `bytes` object). Encrypt chunks with authenticated
encryption, unique nonces and artifact/chunk-index binding. Record ciphertext
digests and sizes in the manifest; validate AEAD before use. The existing
recording key hierarchy can wrap artifact keys, but the chunk format and
recovery rules need an implementation review. No plaintext snapshot staging
on an unprotected volume. Restored writable VM disks require protected local
storage and restricted ownership; encryption of the archive alone is insufficient.

Publication is a recoverable transaction across two systems:

1. Create operation-owned staging on the destination filesystem; stream, flush
   and verify each artifact. Flush the manifest and directory metadata using
   the platform's documented durability primitives.
2. Atomically publish an immutable bundle on that filesystem. Record its ID
   and digest in the durable operation journal. No available catalog row yet.
3. In one SQLite transaction, insert the catalog entry, append completion and
   mark the operation completed. Crash recovery reconciles a published bundle
   against the operation. Missing publication means unavailable, not success.
4. Collect orphans only after reference/lease checks and a retention interval.
   Never delete a runtime or directory merely because its name looks temporary.

Transaction-aware timeline append uses `BEGIN IMMEDIATE` **before** reading
the branch tip. Reserve the branch, write its `fork` event and explicit inherited
capture profile, create its operation, and update its expected tip in one
transaction. A Python object lock is insufficient across processes.

Proposed persistent tables (in the recording database, with a versioned migration):

| Table | Minimum fields / uniqueness |
|---|---|
| `execution_operations` | operation_id PK, kind, request_digest, idempotency_scope/key UNIQUE, state, phase, revision, result, error, cancel_requested |
| `execution_sessions` | session_id PK, branch UNIQUE for active writer, runtime_id, profile_id, state, revision, owner, lease_expiry, fencing_token, source_hold_owner |
| `execution_checkpoints` | checkpoint_id PK, anchor, manifest_digest, bundle_id, qualification_id, availability |
| `execution_inputs` | input_id PK, runtime_id/sequence UNIQUE, digest, state, receipt_ref |
| `execution_branches` | branch PK, source_anchor, inherited_capture_profile, expected_tip, active_operation |

The service's global registry also needs durable recording UUID-to-store
registration. Creating a recording reserves its UUID/store before starting
the guest; retry attaches the same store rather than creating a duplicate.

One supervisor holds a renewable lease per runtime. The runtime command
gateway enforces the fencing token; database fencing alone cannot stop a
stale worker from typing into the VM. On lease expiry, gate inputs and pause
or quarantine the known runtime before transfer. Rediscovery uses operation,
runtime and generation identities; it never launches an untracked duplicate.

Fork reservation also atomically reserves the source session's stopped state
and revision, not only its ledger tip. Keep this source hold through child
execution and its isolation audit; conflicting continue/input/restore calls
return 409. The first milestone permits one active child for that source.
Service restart must recover the hold before accepting mutations. Releasing
it requires a stopped child and completed isolation check, or an explicit
failed/interrupted disposition with preserved evidence; lease expiry alone
does not establish that the Original is safe to resume.

Enforce the source hold in the shared transactional append boundary, covering
**all** ledger writers in both API namespaces, including legacy notes and
narration. Held-source mutations return 409; inspection and comparison remain
available. Runtime/hold status can update control tables or the child ledger,
but must not append to the held Original. Otherwise a harmless-looking note
would invalidate the promised unchanged-ledger audit.

## 5. HTTP and state contracts

Use a **new** namespace, `R=/api/runtime/v1`. Existing `/api/store/.../fork`
keeps its current saved-instruction/native-computation behavior. It must not
unexpectedly launch a VM. Legacy structure refusal tests remain valid.

All mutations require a session-bound authorization token, allowed Origin,
`Content-Type: application/json`, an `Idempotency-Key`, and expected revision
where changing an existing resource. Loopback binding alone is insufficient
for an API that launches processes. Server-owned target/profile IDs replace
client-provided host paths or shell commands. Enforce bounded payload sizes.

| Route | Body / result |
|---|---|
| `GET R/targets` | Named projects and qualified profiles; unavailable reasons |
| `POST R/recordings` | `{target_id, profile_id, label?}` → 202 operation, recording and session IDs |
| `GET R/recordings/{id}/sessions` | Branch-to-session mapping; recording detail also includes each branch's session ID |
| `GET R/sessions/{id}` | Revision, session/runtime state, branch, latest frame, current operation, own control status |
| `POST R/sessions/{id}/checkpoints` | `{expected_revision}` → 202 checkpoint operation |
| `POST R/sessions/{id}/stop-recording` | `{expected_revision}` → 202 flush/checkpoint/pause operation |
| `POST R/recordings/{id}/forks` | `{source_branch, source_session_id, anchor, checkpoint_id, expected_source_tip, expected_source_revision, instruction?}` → 202 reserve source hold, child and restore operation |
| `POST R/sessions/{id}/restore` | `{checkpoint_id, expected_revision}` → 202 retry original preparation or recover latest verified stopped state, subject to the rules below |
| `POST R/sessions/{id}/continue` | `{expected_revision, mode:"manual"}` → 202 attach capture, resume, verify live state; input stays gated until control acquisition |
| `POST R/sessions/{id}/control` | `{expected_revision, action:"acquire"|"renew"|"release", lease_id?}` → 200 owned control lease/expiry or release acknowledgement |
| `GET R/sessions/{id}/frames?after={cursor}` | Authenticated bounded live-frame poll; same observations are appended to the branch |
| `POST R/sessions/{id}/inputs` | `{runtime_id, expected_revision, control_lease, sequence, input}` → 202 admission receipt; observation follows |
| `GET R/operations/{id}` | Durable operation state, revision, phase, result or error |
| `POST R/operations/{id}/cancel` | `{expected_revision}` → 202 cancellation requested; poll terminal state |

Every 202 returns an operation location. Polling is sufficient initially;
streaming updates can follow. Reusing an idempotency key with the same canonical
request returns the same operation; different content returns 409. Commit this
mapping before any side effect. Canonicalization must use a versioned,
documented JSON encoding; do not use Python's process-specific `hash()`.

Restore has two permitted cases: retry the child checkpoint/anchor already
reserved by its initial fork, before any user work; or recover that branch's
latest verified stopped checkpoint with no subsequent work. The server resolves
and checks the permitted anchor. Any other historical selection creates a new
child. A changed checkpoint on a retry is a conflict, not an instruction to
rewrite the branch's past. Readiness observations from an abandoned preparation
remain recorded, followed by an explicit recovery boundary on retry.

`inputs` initially accepts typed key/button/pointer/text commands with bounded
data. It does not accept arbitrary host commands. All connected clients share
one explicit control lease; playback clients cannot inject input. Guest command
execution for test receipts is a separately scoped helper capability, not an
unrestricted host shell endpoint.

Continue results include `session_id`, `runtime_id` and `live_frame_path`.
After completion the same UI acquires control automatically through `/control`;
only that authenticated client receives the opaque token and expiry. Renewals
must prove ownership, and expiry/release/Stop recording/relevant cancellation
close input admission. A reconnect checks existing ownership before renewal.
Shared operation polling never exposes another client's token. Control grant
is a durable, fenced short transaction, not a long worker operation. This
keeps the normal flow one Continue click while retaining recoverable handoffs.

Operation states: `queued → running → completed | failed | canceled`.
`phase` supplies details such as `checking_artifacts`, `restoring`, `verifying`.
`cancel_requested` is independent; a completion racing cancellation remains
completed. Cancellation updates the target operation; it is not a separate
operation kind. A completed `continue` means capture and live state are ready, **not**
that the user's task succeeded. Workload verification is a separate receipt.
The [operation schema](contracts/operation.schema.json) enforces the envelope.

Session states: `starting`, `recording`, `checkpointing`, `stopping`, `stopped`,
`restoring`, `ready`, `continuing`, `interrupted`. A failed operation retains
the last safe session state and an error. If live input delivery is uncertain,
enter `interrupted` with input disabled until reconciliation.
Successful Stop recording requires a durable checkpoint, anchor and preservation
receipt proving the VM paused. If its final checkpoint fails, preserve the
recording and leave the session explicitly interrupted/paused with an error;
do not report ordinary stopped success.

Errors have `{code, message, retryable, operation_id?}`: 409 stale revision,
writer conflict or key conflict; 403 no permission/capability; 422 unusable
checkpoint; 503 unavailable backend. Never return a success frame as a
replacement for a failed restore.

## 6. Eligibility, events and player behavior

Add a branch/selected-step `execution` descriptor independently of capture caps:

```json
{
  "mode": "checkpoint",
  "actions": ["fork_from_checkpoint"],
  "selected_checkpoint_id": "11111111-1111-4111-8111-111111111111",
  "nearest_checkpoint_step": 12,
  "unavailable_reason": null
}
```

This is an illustrative response, not a live claim. The server derives actions
from a trusted catalog, complete verified artifacts, correct logical ancestry,
installed compatibility profile, stopped Original and permissions. It rechecks
them at mutation time. Unknown/imported checkpoint metadata is inert until a
separate verification/admission process grants local authority.

Proposed events: `execution_profile`, `execution_checkpoint`, `execution_input`,
`execution_receipt`, `desktop_frame`, `execution_state`, `execution_verification`.
Use the existing `fork` for lineage and `context_note` for instructions.
Only navigable observations produce player steps; lifecycle chatter must not
create blank frames. Read inherited observations through `replay_events`.

The player maintains separate playback selection and live-session state.
Rewind never stops capture. Back to now resumes following the live edge.
Stop recording freezes Original before What-if. At a non-checkpoint frame,
offer Go to saved moment; do not restore it silently. Continue working opens
the controlled live viewport, while Compare Original remains read-only.

Keep request-generation guards for frame loads; use a separate monotonically
checked session revision. Pin recording/branch/anchor before awaiting any
mutation. Aborting a fetch does not cancel its operation. After a timeout,
query the same operation/key. Keep playback usable while preparation runs.
On disconnect retain the frame and draft, and say the recording status is
being checked. Reopening an earlier historical moment creates a new child;
resuming the latest verified stopped state may append to that same branch.

## 7. Restore, input and proof

Restore validation occurs before guest execution: manifest schema and digest,
AEAD/artifact hashes, all declared devices/backings, ancestry and anchor,
runtime compatibility, allowed storage paths, and sufficient resources.
Allocate private writable disks, namespaces and control endpoints. Check
snapshot-embedded paths **before load**; use a qualified remapping mechanism
or an isolated namespace. Never unlink another runtime's socket.

Load paused and verify resource ownership. Attach capture before any readiness
resume, keeping outside I/O and user input gated. Observe helper identity/cursors
and a real frame; check known workload invariants, then pause again before
reporting `ready`. Background activity during verification is recorded and
belongs to the child, never an invisible interval. C0 must qualify this method
or prove fully paused verification. A new incarnation challenges the helper
to prevent stale replies. If readiness fails, keep the child unavailable.
Continue attaches/verifies capture, resumes, verifies live state, then permits
the requesting client to acquire control and open input admission.

Input states are `accepted`, `dispatched`, `observed`, `uncertain`, `rejected`.
Durably record admission before dispatch. A QMP acknowledgement proves backend
delivery, not application acceptance. Record subsequent observations and their
cursors. A crash between dispatch and receipt cannot be solved by HTTP
idempotency: never blindly redeliver a possibly applied click or command.
Reconcile via a qualified guest acknowledgement, or restore a checkpoint and
replay a verified prefix when supported; otherwise remain interrupted.

Execution proof includes all of:

- Verified source anchor, full ancestor chains and published artifacts.
- Restored runtime identity, matching cursors and observed checkpoint state.
- New child inputs plus resulting screen/file/process evidence.
- Test process exit status, output digest and relevant file hashes from the
  actual guest. Missing receipts mean unknown, never pass.
- Original ledger **and actual backing disks**, checkpoint bundle and referenced
  blobs unchanged against a baseline taken after stopping Original.

Ledger hashes authenticate recorded bytes relative to a trusted baseline;
they do not prove that an untrusted recorder told the truth. Receipts come
from the owned runtime boundary and are independently checked where possible.

## 8. Later replay, I/O and portability

Checkpoint restore works without proving deterministic replay between moments.
For C4, qualify the backend's record/replay mode, snapshot linkage, target
execution cursor, supported devices and ability to leave replay into a private
live child. QEMU's `replay-seek` operates within replay from a preceding
snapshot; successful seeking alone does not prove live branching.
[QMP reference](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html).

Recorded broker I/O entries need request ID, channel, full behavior-relevant
request digest, response/status digest, sequence and delivery state. Include
model, tools, endpoint and sampling settings, not just message text. Commit
responses before delivery. Replay matches the expected cursor and digest;
a miss stops execution. Do not retry an external write with unknown outcome
unless its provider supplies a verified idempotency contract.

Host time, randomness, device scheduling and packet arrival are not completely
captured by an HTTP proxy. Whole-machine nondeterminism must be handled by the
qualified replay backend or explicitly excluded. Matching final test outcomes
alone does not qualify instruction-level replay.

Historical replay must not emit live external writes. A divergent future
changes to an explicit live mode with a new journal suffix. A local snapshot
cannot roll back remote SaaS state; versioned provider resources or isolated
test accounts are necessary for that promise. Credentials stay outside shared
bundles and require deliberate rebinding.

Portable packaging must include manifest, encrypted artifacts, ancestry,
input/I/O log prefixes, dependency/base-image identities and compatible backend
requirements. Imported manifests are data, never host paths or executable
launch scripts. Reject missing dependencies, unsupported devices/versions,
path traversal and untrusted runtime definitions. A recipient can still watch
the recorded frames when execution cannot be admitted.

## 9. Existing code to preserve or replace carefully

| Code | Verified limitation and integration decision |
|---|---|
| [store.py](../../src/living_replay/store.py) | Object-local lock, per-event commits, whole-buffer blob writes. Add transactional append and streaming artifacts. Keep branch prefix format. |
| [ingest.py](../../src/living_replay/ingest.py) | Capture caps remain unchanged. Local-only profile lookup defaults to native; explicitly inherit profile on executable children. |
| [bridge.py](../../src/living_replay/bridge.py) | `try_differently` stores intent; `seal` checks local rows. New execution API checks full ancestry and artifact catalog. |
| [resume.py](../../src/living_replay/resume.py) | `plan_resume` selects tip workspace state; `verify_resume` counts any new event. Reuse prefix logic, not checkpoint selection or event-count execution proof. |
| [service](../../service/melange_service.py) | Add durable registration and operations outside long-held registry locks; keep legacy endpoints. |
| [player.js](../../service/static/player.js) | Preserve dark player and stale-response guards; split playback, operation and session state. |
| [run_live_guest.py](../../sandbox/run_live_guest.py), [run_experiment.py](../../sandbox/run_experiment.py) | Snapshot data disk but fork pristine writable rootfs; reuse vsock endpoints. Isolated all-disk restore is unproven. Quarantine these assumptions from new backend. |

Firecracker snapshots cover memory/device state while disk handling remains
the caller's responsibility; connection continuity also has limits. That
supports retaining it for a separately qualified headless profile, not treating
the current experiment as a complete desktop backend.
[Firecracker snapshot support](https://github.com/firecracker-microvm/firecracker/blob/main/docs/snapshotting/snapshot-support.md).
