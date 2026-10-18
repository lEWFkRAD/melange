# UNIFICATION.md — how this tree was built (M1 prep, 2026-10-17)

This repository is the single canonical Melange tree. It was assembled
module by module from three divergent trees, staged locally for this work:

| Tree | Staged at | What it was |
| --- | --- | --- |
| **onyx** | `~/workspace/tree-inventory/lr-repo` | The onyx-Linux working tree. Only tree with the UX program (`bridge.py`, packaged `ingest.py`, `tui.py`) and their tests + desktop fixtures. Built the v2/v3 surfaces. |
| **SHATNER** | `~/workspace/tree-inventory/shatner-living-replay` | The SHATNER `Projects\living-replay` checkout (incl. the ONY-192 TUI port commit cf834ca in its history). Adds `tui_driver.py` + `tools/`. Two of its files (`store.py`, `__init__.py`) carry CRLF line endings. |
| **VM** | `~/workspace/living-replay/repo` + `~/workspace/lr-live` | This VM's Build-3-era tree (subset: no bridge/ingest/tui; non-git) plus the `lr-live` top-level working files (surface builders, an ingest copy, design docs, sandbox working copies). |

Method: content hashes (MD5, CRLF-normalized where noted) for every file in
every tree, then a real diff of every file whose hashes disagreed. Choices
were made **per module, never whole-tree**, on three kinds of evidence:
superset diffs (one copy strictly contains the other's changes), cross-tree
agreement (two trees independently holding identical bytes), and the test
suite of the merged tree (see *Proof* below). The staged trees were not
modified.

## Package modules — `src/living_replay/`

23 of the 27 package files were byte-identical in every tree that had them,
including all of the Build 1–3 engine (`capture`, `grid`, `crypto`, `edits`,
`factgraph`, `flagship`, `forking`, `incremental`, `lenses`, `redaction`,
`replay`, `runner`, `smt`, `taint`, `cli`, `gui`, `export_viewer`).

| Module | onyx | SHATNER | VM | Chosen | Reason |
| --- | --- | --- | --- | --- | --- |
| `bridge.py` | ✓ | ✓ identical | — | onyx/SHATNER | Only exists in the two full trees; byte-identical there. |
| `ingest.py` | ✓ | ✓ identical | — (but see note) | onyx/SHATNER | Byte-identical in onyx + SHATNER. The VM's top-level `lr-live/ingest.py` is *also byte-identical* to it — the "older top-level ingest" was the same file, so nothing was lost by packaging it here. |
| `tui.py` | ✓ | ✓ identical | — | onyx/SHATNER | Byte-identical in both full trees. |
| `tui_driver.py` | — | ✓ only | — | SHATNER | Only-in-SHATNER (ONY-192 TUI port driver). |
| `tools/__init__.py`, `tools/build_demo.py` | — | ✓ only | — | SHATNER | Only-in-SHATNER subpackage. |
| `store.py` | ✓ | ✓ = onyx after CRLF normalization | older | **onyx** | The real three-way split. onyx and SHATNER hold the *same code* (SHATNER's copy is CRLF; normalized diff is empty). The VM copy is an ancestor: it lacks thread-safe append (onyx/SHATNER add `threading.Lock`, `check_same_thread=False`, and `_append_locked`, because guest-agent appends arrive from two threads and append is read-modify-write on the hash chain). VM variant is a contained ancestor — nothing in it is absent from the chosen copy. |
| `__init__.py` | = VM | ✓ differs | = onyx | **SHATNER** (LF-normalized) | SHATNER wraps the POSIX-only `PtyCapture` import in try/except so the library imports on Windows (`PtyCapture = None` there); onyx/VM hard-import it. On POSIX the behavior is identical, so SHATNER's is a strict superset. This is the one package module taken from SHATNER over onyx. |
| `sandbox.py` | = VM | older | = onyx | **onyx/VM** | onyx/VM add a `mem_mib` parameter to `FirecrackerVM.configure()` (default 512); SHATNER hardcodes 512 and has no other change. SHATNER variant is a contained ancestor. |

Known defect carried in unchanged: `TimelineStore.replay_events(through)`
returns nothing pre-split on forked branches (the M2 item from the intent
audit). It is identical in all three trees — a bug to fix (M2), not a
divergence to merge.

## Tests — `tests/`

Union of all three trees, deduplicated by content hash. 9 test files +
4 fixtures.

| File | Source | Note |
| --- | --- | --- |
| `test_bridge.py` (17 tests) | onyx only | UX program. Did not exist on the VM before this merge. |
| `test_tui.py` (16) | onyx = SHATNER | Identical in both full trees. |
| `test_ingest.py` (7) | onyx (= `lr-live/test_ingest.py`, identical) | Previously **could not even import on the VM** (it expects the packaged layout); it runs green here now that the package is whole. |
| `test_build1.py` (8) | all three identical | |
| `test_build2.py` (6) | **onyx** | Onyx adds `test_b2g6b_cutoff_yield` (ONY-188: pins the early-cutoff measurement on the 42/93 corpus — 42 executed, 1 identical recompute, 11 blocked). SHATNER/VM copies are the same file minus that test: contained ancestors. |
| `test_build3.py` (3) | SHATNER = VM | Onyx never had it. |
| `test_gates.py` (7) | **VM/SHATNER** | VM/SHATNER carry the Build 3 alt-screen resolution: the G1 corpus is split into pyte scenarios and tmux scenarios, with `test_g1_alt_screen_vs_real_terminal` proving the grid against a real terminal (tmux). Onyx's copy tests those scenarios against pyte only. **NOT MERGED:** the onyx `test_gates.py` variant (`~/workspace/tree-inventory/lr-repo/tests/test_gates.py`) — superseded ancestor; its pyte alt-screen legs were deliberately replaced by tmux ground-truth legs in Build 3, so keeping both would assert two different reference semantics for the same scenarios. |
| `test_gui.py` (1) | SHATNER = VM | |
| `test_sandbox.py` (1) | SHATNER = VM | Firecracker integration; skips unless `LR_SANDBOX_DIR` is set (sandbox host only). |
| fixtures | onyx | `desktop-record.jsonl` (identical onyx/SHATNER), plus onyx-only `desktop-final.json`, `desktop-live-record.jsonl`, `desktop-live-final.json`. |

## Sandbox harness — `sandbox/`

Taken from the onyx tree, which won **every** divergence — in each case the
onyx copy is a documented superset, and in most cases the VM's `lr-live`
working copy is byte-identical to onyx's (two-tree agreement):

| File | Divergence | Resolution |
| --- | --- | --- |
| `guest_init.sh` | onyx 30 lines ⊃ VM 21 ⊃ SHATNER 16 | onyx adds the devpts mount, the loopback-up fix (guest `lo` boots DOWN; every guest-local HTTP call failed without it), and the `RUN_LIVE` / `RUN_HERMES` entrypoints. Others are contained ancestors. |
| `model_shim.py` | onyx 209 lines; VM 112; lr-live 159 | Only onyx has **replay-by-record** (Build 2): serve recorded model responses from `/opt/replay_table.json`, fail loudly with REPLAY-MISS where the record runs out. VM/lr-live copies are ancestors without it. |
| `run_hermes_guest.py` | onyx 365 lines = lr-live; VM 229 | Chosen: onyx (= the lr-live copy that ran the verified Build 2 live session). **NOT MERGED:** the VM variant (`~/workspace/living-replay/repo/sandbox/run_hermes_guest.py`) — it has its own edits in shared regions (not a pure ancestor), but it is outvoted by two-tree agreement and by verified-run provenance. Preserved at its stated location for hand-merging if a VM-only behavior is ever missed. |
| `hermes_agent.py` | onyx = lr-live; VM differs | onyx adds sink-failure tracking (a dropped store event fails the run loudly, exit 3) and captures the shim log instead of `/dev/null`. |
| `build_rootfs_hermes.sh` | onyx ⊃ VM | onyx adds the bash + library-closure fix (busybox `sh` cannot run Hermes's `builtin cd` wrappers) and copies `guest_init.sh` / `live_agent.py` into the rootfs. |
| `salvage_verify.py` | onyx vs lr-live differ in exactly 1 line | **NOT MERGED:** the lr-live variant (`~/workspace/lr-live/salvage_verify.py`) calls `LocalKeyProvider(master_b64=master)`, but `crypto.LocalKeyProvider.__init__` takes `master_key: bytes` positionally — the lr-live call raises `TypeError` against the canonical crypto API in every tree. Onyx's `LocalKeyProvider(base64.b64decode(master))` is the correct call and is merged. |
| all other files | identical everywhere present | onyx copies (== lr-live where lr-live has them: `export_render.py`, `live_agent.py`, `replay_only.py`, `replay_only3.py`, `run_live_guest.py`). |

## Everything else

- **`pyproject.toml`** — merged: onyx base + the `solver` / `crypto` / `gui`
  optional-dependency groups that SHATNER/VM have and onyx lacked.
- **`tools/`** — the lr-live surface builders the shipped surfaces depend on:
  `build_surface.py` (v1) and `build_surface2.py` (v2/v3 data path). They are
  build scripts, not package code; `build_surface2.py` reads its input export
  from `/tmp/melange2/surface2-data.json` (produced on onyx through the
  bridge), which is why the surfaces were baked on that machine. Carried in
  as-is so the dependency is visible in the canonical tree.
- **`docs/`** — `desktop-profile.md` (onyx `docs/` copy, byte-identical to
  lr-live's), `melange-ux-design.md` (lr-live only), `BUILD1-BRIEF.md` /
  `BUILD2-BRIEF.md` / `BUILD3-BRIEF.md` (Build 2/3 briefs identical in
  SHATNER + VM), `project-writeup-2026-10-16.md`, and the lr-live working
  notes (`backend-api-map.md`, `hermes-tui-recon.md`, `ony187-closeout.md`).
- **`README.md`** — the VM tree's (freshest: Melange-titled, Builds 1+2 with
  credits), plus a canonical-tree banner, a UX-layer paragraph, the honest
  test count below, and two stale sentences corrected: the Security section
  and the non-claims list still said at-rest encryption and xterm alt-screen
  restore were unimplemented; both landed in Build 3 and are claimed with
  evidence in the same document. Onyx's Build-1-era README and SHATNER's
  README are ancestors of this one.
- **`.gitignore`** — onyx's (covers `__pycache__/`, `*.sqlite`, `objects/`).

## Proof — the merged suite, run here

Environment: this VM (Linux x86-64), Python 3.12.3, a venv with **all
declared extras installed** (`pyte`, `z3-solver`, `python-xlib`,
`cryptography`), tmux and Xvfb present on the host.
Command: `PYTHONPATH=src python3 -m unittest discover -s tests`

| File | Ran | Result |
| --- | --- | --- |
| test_bridge.py | 17 | OK |
| test_build1.py | 8 | OK |
| test_build2.py | 6 | OK |
| test_build3.py | 3 | OK |
| test_gates.py | 7 | OK |
| test_gui.py | 1 | OK |
| test_ingest.py | 7 | OK |
| test_sandbox.py | 1 | skipped (see below) |
| test_tui.py | 16 | OK |
| **Total** | **66** | **65 passed, 0 failed, 1 skipped** |

The single skip is environment-only: `test_sandbox.py` is guarded by
`@unittest.skipUnless(SB, "LR_SANDBOX_DIR not set (sandbox host only)")` —
the Firecracker integration test, which needs a KVM sandbox host. With the
extras installed, legs that used to skip on this VM now run and pass: the
G1 pyte corpus, the G1 tmux alt-screen legs (100.00% vs tmux), the B2-G4
Z3 goal seek, the B3-G4 GUI reconstruction under Xvfb, and the bridge/TUI/
ingest suites that did not exist on this VM at all before the merge.
Smoke check: all 24 package modules (`living_replay.*` incl. `tools`)
import cleanly.

**This is the count to quote from now on: 66 tests — 65 passed, 1
environment skip — in the environment stated above.** The retired "60
tests" figure came from the onyx environment over a subset tree; the
VM-only tree collected 25.

## NOT MERGED — flagged variants (complete list)

1. `lr-live/salvage_verify.py` — broken `LocalKeyProvider(master_b64=...)`
   call (see above). Location: `~/workspace/lr-live/salvage_verify.py`.
2. VM `sandbox/run_hermes_guest.py` — own edits outvoted by onyx/lr-live
   agreement + verified-run provenance. Location:
   `~/workspace/living-replay/repo/sandbox/run_hermes_guest.py`.
3. Onyx `tests/test_gates.py` — superseded by the Build 3 tmux-leg version.
   Location: `~/workspace/tree-inventory/lr-repo/tests/test_gates.py`.

Everything else that differed was a contained ancestor of the chosen copy
(VM `store.py`, SHATNER `sandbox.py`, onyx/VM `__init__.py` hard import,
SHATNER/VM `test_build2.py`, the older `guest_init.sh` / `model_shim.py` /
`hermes_agent.py` / `build_rootfs_hermes.sh` copies) — no unique behavior
was found in them that the chosen copies lack, per the diffs cited above.

## What remains for M1

Exactly one step, and it is Jeff's: **create the empty private GitHub repo
named `melange`** (or re-authorize the `gh` device flow), after which this
tree gets a remote and its first push. No remote exists yet and nothing has
been pushed anywhere. Follow-ups that are *not* M1: M2 (the
`replay_events(through)` pre-split fix), M3 (bridge as a live service +
served surface), M6 (Door 1 mp4 provenance), M7 (pins on real recordings).
