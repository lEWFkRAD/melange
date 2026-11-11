# Implementation gates and acceptance

**Proposed work, 2026-10-19. No gate below is passed by this design PR.**
The [map](README.md) defines the product; the [technical design](technical-design.md)
defines the runtime boundary. Implement in small reviewable PRs. Each PR records
its exact commit, commands, runtime versions, fixture identity and evidence.

## Next PR: C0 desktop checkpoint qualification

Build an isolated experiment under `sandbox/desktop/` with a pinned manifest,
one managed Linux image, an unmodified editor, terminal and browser, and a
small observation helper. Use preinstalled offline dependencies. Do not change
the player yet. Do not deploy a service or add any fleet dependency.

The first question is whether this precise backend can restore an honest,
private desktop state. Use QEMU as the candidate; select its exact build and
storage/export method from measured evidence. If the profile fails, report
the failing capability rather than hiding it behind an app-specific fixture.

Required experiment:

1. Boot the image; inventory every writable block device and backing chain.
2. In Code-OSS or another unmodified editor, open Melange source and create an
   **unsaved** identifiable edit. Start a long-lived test process with an in-memory
   nonce/open handle. Write distinct markers to root, data and a third disk.
   Open the local browser preview.
   Specifically, disk must contain A while the editor contains unsaved B;
   restoration must preserve B and its undo stack without changing disk A.
3. Capture a paused checkpoint with RAM/device state and every writable disk.
   Resume Original and change all markers, buffer and files; then stop it.
4. Restore a child into private storage and endpoints. Observe the old unsaved
   edit and process state; force disk rereads to distinguish memory-cache
   appearance from actual storage correctness. Later Original changes are absent.
5. Edit actual source in the child, save, run a real targeted test and refresh
   the browser. Record exit status, stdout/stderr, source hashes and real frames.
6. Rehash Original disks, ledger, referenced blobs and checkpoint artifacts.
   Every protected baseline remains unchanged. Repeat after restarting the
   coordinator; demonstrate recovery or an explicit interrupted state.

Produce `qualification.json` (build/config/image identities, supported actions,
consistency method, limitations), verification receipts and one continuous
recording. Report snapshot bytes, checkpoint pause, restore-to-ready time,
CPU/RAM use and input-to-frame latency. These are measurements, not preclaimed
performance guarantees. Set UX budgets only after obtaining this baseline.

## Ordered implementation units

| PR | Deliverable | Gate to merge |
|---|---|---|
| C0 | Desktop backend qualification and all-disk snapshot experiment | RAM, unsaved buffer, open handle, root/data/extra disk restored; private child; measured limits |
| C1a | Versioned operation/session schema, transactional append, durable registry | Concurrent duplicate requests yield one operation/branch; stale writers fenced; old stores still readable |
| C1b | Streaming encrypted artifact store and checkpoint catalog | Partial writes never advertised; corrupt/missing/backing artifacts refused; crash reconciliation tested |
| C1c | Supervisor start/checkpoint/restore/stop, new runtime API | Exact anchor validation, bounded inputs, readiness, auth and operation recovery; no old `/fork` behavior change |
| C2 | Existing player wired to managed desktop | Record without manual imports; Save moment; Stop; What-if; Continue; Compare; reconnect retains work |
| C3 | Two-app end-to-end acceptance and unchanged continuation | Real code/test/browser work plus second unmodified app; full isolation audit; failure states visible |
| C4 | Qualified between-checkpoint deterministic seek and live fork | Replay reaches checked target; divergence stops; live child exits replay safely with independent journals |
| C5 | External-I/O broker with explicit replay/live boundary | Response-before-delivery durability; request matching; unknown writes never blindly repeated |
| C6 | Portable export/import and second OS/backend profile | Clean second host qualifies bundle or gives exact refusal while playback works |
| C7 | Optional semantic cause mapping | User-selected edit maps to responsible input and forward-verifies in actual app |

C1b may be developed against a fake backend while C0 runs; accepting a fake
backend does not pass C0. C1c depends on both a qualified backend and durable
artifacts. C4 needs its own feasibility spike: QEMU replay seeking is not proof
of leaving replay into live execution. Windows/native-host coverage follows
the same contract, with its own compatibility and licensing constraints.

## Concrete acceptance workload

Use a small real Melange UI change, such as keyboard navigation between saved
moments. The fixture includes a test that fails on the baseline and passes
after the change. The user edits the actual repository in the guest; the
supervisor never substitutes canned output or patches a mirrored calculation.

At the checkpoint leave part of the edit unsaved. Original later takes one
implementation; the What-if restores the checkpoint and takes another. Run
the actual relevant tests in both. Compare real diffs, outputs and browser
behavior. Capture process start/exit and file hashes independently of the
player's success banner.

For unchanged continuation, restore a sibling from the same checkpoint and
apply a fixed sequence of ordinary inputs at acknowledged readiness boundaries.
Verify specified final source hashes and test outcomes. A mismatch is a visible
failed equivalence check. Do not require nondeterministic timestamps to match,
or describe this bounded test as universal deterministic replay.

For the second app, use an unmodified text editor or drawing tool with a real
document and unsaved change. Repeat restore, edit, save and disk verification
without changing the backend or introducing synthetic application state.

## Failure matrix

| Injection | Required result | Gate |
|---|---|---|
| Missing rootfs or third disk; wrong immutable backing | Refuse before guest execution | C0/C1b |
| Swapped RAM or corrupted encrypted chunk | Hash/AEAD failure; no ready child | C1b |
| Crash during each artifact write, manifest flush, publication and catalog commit | Last good checkpoint usable; partial bundle unavailable; same operation reconciled | C1b |
| Disk full, short write, failed pause/thaw | Explicit failure and safe Original state | C0/C1b |
| Two workers append or reserve the same child concurrently | One branch chain; one operation/runtime; expired worker cannot command it | C1a/C1c |
| Original continuation races What-if reservation | Source hold atomically wins or fork refuses; Original cannot resume during child isolation audit | C1a/C1c |
| Legacy note/narration races a held Original | Shared append boundary returns 409; no source-ledger change through either namespace | C1a/C1c |
| Same idempotency key with different body | 409; no second side effect | C1a |
| Forged imported execution profile or checkpoint event | Watchable data cannot grant execution | C1c |
| Select old frame while a newer snapshot exists | Exact match or explicit Go to saved moment; never restore future state | C1c/C2 |
| Corrupt an ancestor while local child chain is valid | Eligibility and restore fail | C1c |
| Restore two children with embedded identical socket/path names | No cross-delivery, shared writes or unlinking; production still limits active writers | C0/C1c |
| Crash after input dispatch, before receipt | Input marked uncertain; no blind redelivery | C1c |
| Readiness helper returns stale incarnation or wrong cursor | Child unavailable | C1c |
| An execution-start note but no output/workload receipt | Never passes continuation verification | C1c/C3 |
| Timeout, reconnect, navigation away or cancel/completion race | Same operation recovered; correct final state; no duplicate branch | C2 |
| Preparation retries with a different checkpoint | Conflict; original reserved anchor preserved | C1c |
| Readiness resumes guest before Continue | Capture is already attached; activity recorded; Ready is paused again | C0/C1c |
| Recover a stopped child after its VM disappears | Latest verified stopped checkpoint restored on same branch; older selection creates a new child | C1c/C2 |
| Child writes via host symlink/backing path | Refused or confined to child; Original/checkpoint unchanged | C0/C1c |
| Missing runtime after service restart | Playback survives; execution says interrupted/unavailable | C2 |
| Replay request differs in tools/model/parameters or missing response | Stop at mismatch; no accidental live request | C5 |
| Remote write outcome unknown | Interrupted; no automatic second write | C5 |

Keep legacy structure capture refusal tests and existing resume isolation tests.
Add meaningful new tests at the boundary that can fail; do not manufacture
passing tests by comparing a fake backend's own fabricated output to itself.

## Evidence and release discipline

The release receipt links to the commit, image/profile identity, exact
checkpoint manifest, initial/final hashes, operation and input receipts,
test outputs, and continuous footage. The film can be edited for presentation;
the underlying evidence remains available without the edit.

Only C0–C3 together justify **record, restore and continue ordinary desktop
work**. C4 justifies finer seeking for its qualified profile. Neither means
every application on every machine, remote server or hardware device is already
supported. Maintain a small capability matrix based on demonstrated profiles.

First implementation task: **C0 all-disk desktop checkpoint qualification**.
Its result selects the backend mechanics for C1, instead of building an API
around an assumed snapshot guarantee.
