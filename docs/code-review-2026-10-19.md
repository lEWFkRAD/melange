# Code review — 2026-10-19

Reviewed baseline: `8fe1daf` on the public canonical `main` branch.
The local unpublished `agent-surface` branch was preserved and is outside
this review. All new regression fixtures use synthetic content.

## Confirmed findings

### P1 — live capture splits secrets before redaction

`capture.py:31-33` cuts raw bytes before the redactor sees them. A seeded
credential crossing the artificial 64-byte tail boundary survives in
concatenated persisted chunks. Fixed by retaining incomplete tokens and
assignments; tests cover every two-read split of a mixed secret/UTF-8
corpus and inspect live captured storage. The same path's unbounded
blocking read after its timeout is fixed and tested with both a silent
child and a descendant retaining the terminal.

### P1 — encryption can be bypassed and snapshots leave plaintext archives

`store.py:19-25` permits opening a keyed timeline without a key provider,
then writing plaintext. `forking.py:7-8` creates a plaintext workspace tar
beside the encrypted store and leaves it there. Fixed: missing-key opens
and implicit plaintext-to-encrypted conversions fail closed, snapshot
archives remain in memory, and safe extraction rejects traversal.
Regressions scan persisted files and verify successful restore.

### P1 — runner payloads bypass capture redaction

`runner.py:50-59` stores tool input/output and model prompt/tokens before
the terminal capture redacts output. The synthetic persisted-secret
regression failed before the fix and passes after redacting these
payloads and persisted fork notes at the recording boundary.

### P1 — chained corrections reset earlier input changes

`bridge.py:156-199` rebuilds inputs from the original intake without
applying inherited edits. Reproduced: after wages become 48,000, correcting
withholding resets wages to 52,000. Fixed by applying recorded input
clamps through the selected computation. Forward execution now retains
48,000 wages, yields tax 3,088/refund 3,112 and preserves the parent;
explain also starts from those corrected figures.

### P1 — recorded text can escape the standalone viewer's script

`src/living_replay/export_viewer.py:78` replaces only the exact lowercase
`</script>` string in embedded JSON. HTML recognizes mixed-case and
whitespace-delimited closing tags, so a recorded branch name or terminal
output can inject markup and scripts when a viewer is opened.

Fixed by encoding every `<` in the JSON payload. The regression parses
the exported HTML, verifies there is exactly one script and no injected
image, and decodes the JSON to check that the original data survives.
Against `8fe1daf`, all three adversarial closing-tag cases fail this test;
with the fix they pass.

### P2 — desktop ingestion loses the original recording clock

`src/living_replay/ingest.py:108-128` writes events with import-time
timestamps and drops the recorder's `t` field. Polls separated by seconds
in the source become events separated by the importer's execution time.

Fixed as part of M9: elapsed `ts` seconds and legacy `t` milliseconds are
preserved in both the event clock and payload. Synthetic tests compare
each replayed frame, check clock intervals, and assert fidelity refusals.
The importer now validates the complete record before writing it and
rejects attempts to reclassify an existing branch.

### P2 — service routes ingested records to the wrong frame reader

`service/melange_service.py:124-145,549-553` exposes import metadata as a
desktop step before the first tree, routes generic snapshots to the AX
reader, and treats generic transcripts as zero-frame videos. Fixed with
profile-aware navigation and readers. Four synthetic HTTP tests exercise
every recorded state, timestamp, note roundtrip and fidelity refusal
without relying on the unavailable historical store fixtures.

### P1 — real desktop session text is committed as test data

The `tests/desktop*-record.jsonl` and corresponding final-tree files are
real desktop accessibility captures, including session text and local
environment details. The fixture tests explicitly describe them as real
recordings, while `CONTRIBUTING.md` requires synthetic data only.

**Open:** replace this corpus with synthetic recordings that retain its
structural coverage. Removing files in a new commit would not remove
existing copies from public Git history; history cleanup is a separate
repository operation. This review does not reproduce the captured text,
rewrite history, or claim a complete secret scan.

## Baseline validation

On WSL Ubuntu, Python 3.12.3, with pyte, Z3, cryptography, python-xlib and
tmux available: `PYTHONPATH=src python3 -m unittest discover -s tests`
ran **181 tests: 164 passed, 17 skipped**. The skipped tests require
external workbook/store fixtures, Firecracker, or missing GUI support.

After installing Python Tk, the existing GUI gate was run separately:
**7/7 nodes matched (100%)**, the fork completed with the amended total,
and the original state remained unchanged. Legacy process/file cleanup
warnings were observed; they are not reported as test failures.

## Final validation

Full combined change on WSL Ubuntu / Python 3.12.3: **215 tests ran,
199 passed, 16 skipped** in 42.887 seconds. The 16 skips are the external
workbook/store artifacts and Firecracker integration. Existing cleanup
warnings remain. The GUI gate ran and passed.

G1 remains 100% (151 sampled baseline frames, 155 after the streaming
boundary fix); the altered chunk boundaries change the sample count.
Tmux agreement remains 100%, G2 remains 98.11%, G4 remains 0/6 seeded
secrets, and the dependent recomputation gate remains 42/93 nodes.

Real Edge on Windows / Python 3.14: **four captured frames reconstructed
exactly, zero differing paths, 18 delta operations, zero still-poll
operations**, seal verified, and clamp/fork/provenance refused at
structure fidelity. The two UI changes were synthetic mouse clicks in a
fresh browser profile. Ten additional driver/transport tests passed on
Windows as well as in the Linux suite.

M9's design, reproduction commands and explicit limits are documented in
`m9-desktop-capture.md`. This is a focused correctness/security review,
not a complete audit or a certification for arbitrary vendor software.
