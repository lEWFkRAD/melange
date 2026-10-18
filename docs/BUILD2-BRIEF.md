# Living Replay — Build 2 brief (Kip, 2026-10-15)

Builds on Build 1 (commit 813ff20, gates G1-G6 measured green). Jeff's order: "Do build 2." Builder: Kip (Jeff reassigned after Codex credited out and Hermes's run timed out). Repo: same — C:\Users\Administrator\Projects\living-replay\ on SHATNER; sandbox host: onyx-Linux (native KVM, 24 cores, 62 GB; Kip's VM has NO /dev/kvm — verified 2026-10-15; SHATNER WSL also has /dev/kvm via nested virt but onyx is the clean target). Synthetic data only. Do NOT disturb Strata or any running service on onyx: guests stay ≤1 GB RAM, work lives in a self-contained directory.

## Deliverables

1. **Architecture B sandbox (Firecracker).** A `sandbox/` toolkit that boots a Firecracker microVM on onyx-Linux with a minimal guest (pinned Firecracker release, CI kernel, custom rootfs with standalone CPython + the living_replay package). The guest runs a scripted agent session INSIDE the boundary with Build 1 capture; the timeline lands on a second drive image the host reads back and scrubs with Build 1 code (desktop = viewer). At a checkpoint the guest waits on a vsock control channel; the host snapshots the VM (Firecracker snapshot API); a FORK restores the snapshot into a second microVM, receives a pinned context note over vsock, and completes the task there with a different outcome. The original VM also completes, unmodified — two citizens, one past.
2. **Solver rung 1 — lenses.** `lenses.py`: a Lens abstraction (get/put) with round-trip law checking, plus concrete lenses over a synthetic source document (form-like text): extraction get = document -> fields; put = fields -> document with ONLY the target region rewritten. A clamp on a lens-sourced value compiles to a put() back into the document.
3. **Solver rung 2 — SMT goal seek.** `smt.py`: the recorded pipeline as an arithmetic dependency graph; an explain target becomes a Z3 problem (change as few inputs as possible, then minimum total change), including discrete structure (thresholds / phase-outs via conditionals). Every solution is forward-verified through the graph before acceptance. Z3 is an optional dependency (pip `z3-solver`, `solver` extra); tests skip cleanly without it.
4. **Solver rung 4 — lazy taint.** `taint.py`: byte-level taint over the recorded pipeline. Nothing is taint-tracked during recording; on a provenance query, only the slice of events that fed the queried value is replayed with byte taint on, returning the exact input byte ranges that flowed into it.
5. **Dependents-only fork.** `incremental.py`: Salsa-style memoized evaluation over the pipeline graph — an edit invalidates only transitive dependents; recompute is demand-driven with early cutoff when a recomputed value is unchanged. Measured against full re-execution on the same graph.
6. **Viewer export.** `export_viewer.py`: a timeline (with branches and ghost branches) exports to ONE self-contained HTML file: frame scrubber, per-cell provenance panel (chunk, tool call, byte offset), branch list. No server, no external assets.

## Gates (all measured, none asserted)

- **B2-G1 (in-boundary capture):** a session run inside the microVM produces a timeline on the host that replays to the expected final screen, cell-exact.
- **B2-G2 (forkable frame, in-VM):** fork from the checkpoint snapshot completes with the injected note and a different result; the original VM's completion is unaffected; ≥10 forks measured, restore-to-interactive p50/p95 reported against the 1 s bar from the research (report the number even if it misses).
- **B2-G3 (lens laws):** GetPut and PutGet hold over the document corpus; put() byte-diff outside the target region is zero on every corpus doc.
- **B2-G4 (SMT explain):** on the pipeline corpus (incl. one threshold case), the solver's minimal-change assignment forward-verifies to the target; a no-solution case is reported as unsatisfiable, not forced.
- **B2-G5 (lazy taint):** taint query on the demo workload's printed total returns exactly the source byte ranges of the amount it derived from; the replayed slice is smaller than the full history.
- **B2-G6 (dependents-only):** on the corpus graph, a mid-graph edit recomputes <50% of the nodes a full re-execution runs, outputs are identical to full recompute, and wall time is lower.

## Out of Build 2

GUI/AT-SPI capture, CRIU, layers 4-6, real Hermes integration, multi-VM orchestration beyond one fork, networking for guests (vsock control only), Windows hosts.
