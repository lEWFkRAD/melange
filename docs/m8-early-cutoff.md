# M8 — Model-layer early cutoff: measurement

**What this is.** The P7 refinement (2026-10-16) proposed that after an
edit, a fork should resume re-asking the model "from the first model
call whose context bytes actually changed," replaying earlier calls
from the record. It was an unmeasured proposal. This document reports
the measurement, run by the harness in `src/living_replay/cutoff.py`
(tests: `tests/test_m8_cutoff.py`). No behavior changed; this counts.

**Corpus honesty, up front.** The Build 2 live-session store (153
events, 16 model calls) does not exist in this repo — it lives on the
sandbox host. Of the stores registered in `service/stores.json`, only
the flagship carries recorded model calls at all:

| Store | Contents | Model calls | Measurable |
|---|---|---|---|
| flagship (generated fixture) | intake + computation + print | 1 | yes, via `flagship.run_flagship` |
| desktop-real | 16 screen frames, ingest profile | 0 | no |
| workbook | 5 cell frames, 1 edit | 0 | no |
| workbook-pinned | cell frames, edits, a fork | 0 | no |

Every number below is therefore a **fixture/harness measurement**:
the flagship graph and store, the Build 2 gate-corpus graph (93
nodes, the B2-G6 corpus), and a scripted three-call session recorded
into a real TimelineStore through the runner's append path (built
because no multi-call recorded session ships in this repo).

## Method

**Byte identity** is canonical JSON bytes (`store.canonical`) — the
same serialization the store hash-chains. Not `==`: bytes are
type-sensitive (see Findings, item 4).

**Node layer** (`node_cutoff`): for one edit on a built incremental
Engine, force-recompute *every* invalidated node (transitive
dependents of the edited input, topological order) and compare each
output's bytes to the recorded output. Report per edit: invalidated
count, byte-identical count, truly-changed count, the **cutoff
position** (position in the invalidated order of the last changed
node; everything after it is provably wasted recompute), the tail
after the cutoff, and how many nodes the shipped Engine actually
executes under its value-cutoff rule. The harness's forced walk is
validated for soundness in tests: its final state equals a real
`Engine.edit` final state on every measured edit, and its simulated
executed-count equals the Engine's real executed count.

**Session layer** (`session_cutoff`): a model call's context is the
canonical bytes of its recorded context prefix — the
`runner.context_at` stream (tool / model / note payloads) strictly
before the call — plus the call's own prompt. A counterfactual
rewrite of the record (a lens-amended intake, a corrected tool
output) produces a rewritten stream; each call's context bytes are
recomputed and compared. Calls before the first difference are
**replayable** (their recorded outputs could be served verbatim);
the first differing call is the **cutoff**. The rule stops at the
first difference deliberately: once a call is re-asked, its new
output can differ, so later contexts are unverifiable against the
record even when their static bytes match again.

## Node layer: results

Flagship graph (10 derived nodes), 14 edits across all 7 inputs:

| Edit | Invalidated | Byte-identical | Changed | Cutoff | Tail | Engine executes |
|---|---|---|---|---|---|---|
| wages → 48,000 | 6 | 1 (`/credit`) | 5 | 6 of 6 | 0 | 6 |
| wages → 50,000 | 6 | 1 (`/credit`) | 5 | 6 of 6 | 0 | 6 |
| wages → 51,900 | 6 | 1 (`/credit`) | 5 | 6 of 6 | 0 | 6 |
| wages → 52,100 | 6 | 1 (`/credit`) | 5 | 6 of 6 | 0 | 6 |
| wages → 76,000 | 6 | 0 | 6 | 6 of 6 | 0 | 6 |
| wages → 52,000 (no-op) | 6 | 6 | 0 | 0 | 6 | 0 |
| withholding → 6,000 / 6,200 | 1 | 0 | 1 | 1 of 1 | 0 | 1 |
| other income → 500 | 6 | 1 (`/credit`) | 5 | 6 of 6 | 0 | 6 |
| std. deduction → 15,000 | 4 | 0 | 4 | 4 of 4 | 0 | 4 |
| state wages → 48,000 | 3 | 0 | 3 | 3 of 3 | 0 | 3 |
| state withholding → 950 | 1 | 0 | 1 | 1 of 1 | 0 | 1 |
| dependents → 2 / → 0 | 3 | 0 | 3 | 3 of 3 | 0 | 3 |

Aggregate (n=14): byte-identical fraction mean 0.13, median 0.00,
min 0.00, max 1.00 (the no-op). Tail fraction median 0.00.

Build 2 gate corpus (93 derived nodes), 4 edits:

| Edit | Invalidated | Byte-identical | Changed | Cutoff | Tail | Engine executes |
|---|---|---|---|---|---|---|
| A +999 (the B2-G6 gate edit) | 53 | 12 (flag, s0–s10) | 41 | 53 of 53 | 0 | 42 |
| A +1,000,001 (flag crosses) | 53 | 0 | 53 | 53 of 53 | 0 | 53 |
| B +7 | 41 | 0 | 41 | 41 of 41 | 0 | 41 |
| A unchanged (no-op) | 53 | 53 | 0 | 0 | 53 | 0 |

Aggregate (n=4): byte-identical fraction mean 0.31, median 0.11,
min 0.00, max 1.00 (again the no-op).

The gate edit reproduces B2-G6b exactly (engine executes 42 of 93;
the one executed-and-identical node is `flag`) and extends it: a
forced recompute shows all 11 nodes the engine *skipped* behind the
flag are also byte-identical — 12 of 53 invalidated nodes (23%)
recompute to the recorded bytes.

## Session layer: results

Flagship store, main branch, 1 model call (n=1 per scenario):

| Counterfactual | Replayable | Cutoff |
|---|---|---|
| identity (sanity) | 1 of 1 | none |
| wages corrected in intake (lens) | 0 of 1 | call 0 |
| withholding corrected in intake (lens) | 0 of 1 | call 0 |
| printout corrected (after the call) | 1 of 1 | none |

Scripted session, 3 model calls (amount → double → rate → apply →
print → summarize):

| Counterfactual | Replayable | Cutoff |
|---|---|---|
| identity (sanity) | 3 of 3 | none |
| amount corrected (before call 1) | 0 of 3 | call 0 |
| rate corrected (before call 2) | 1 of 3 | call 1 |
| final print corrected (before call 3) | 2 of 3 | call 2 |

## Findings

1. **At the deterministic layer, almost nothing is left on the
   table.** The shipped Engine already captures what byte-identity
   offers: on the gate edit it executes 42 nodes, of which 41 truly
   change. The single extra execution (`flag`) is the price of
   learning the ripple died, and it blocks 11 more. A backdating or
   context-bytes scheme at this layer would save about 1 execution
   in 42 (≈2%). This quantifies B2-G6b's "adds 0" across 18 edits on
   two graphs.
2. **The tail is the wrong place to look.** For every non-trivial
   edit on both graphs, the cutoff position is the *last* invalidated
   node (tail = 0): the sinks (`/refund`, `join`) sit last in
   topological order and almost always change. The identical nodes
   are in the *middle* (threshold absorbers like `/credit`, gated
   chains behind a flag) — which is exactly the shape the Engine's
   value cutoff already exploits.
3. **At the session layer, position is everything, and the savings
   are real but unclaimed.** The replayable fraction is precisely
   the fraction of model calls that precede the first context event
   a correction touches: 0/3, 1/3, 2/3, 3/3 as the corrected event
   moves later through the scripted session. Each replayed call is
   a full model invocation saved, with the recorded output preserved
   exactly (no re-sample drift). No fork path today claims any of
   it: forks re-sample from the split regardless of context bytes.
4. **Byte identity is type-sensitive.** The recorded wages is the
   float `52000.0`; the int `52000` produces different canonical
   bytes and counts as a change at the chain head. For contexts this
   is conservative in the safe direction (a spurious mismatch costs
   a re-ask, never a wrong replay), but it means context must be
   serialized once, canonically, at record time — a context rebuilt
   through a different serializer can fail identity while being
   semantically the same.
5. **The flagship store cannot show a partial session win.** With
   one model call, and both realistic corrections (intake fields)
   sitting in its only context event, the measured session result is
   0 of 1. That is a property of the fixture, not of the rule — see
   the scripted session for the graded version.

## What this does NOT prove (honest limits)

- **No real session was measured.** The Build 2 live-session store
  is not in this repo; the flagship is a synthetic fixture and the
  three-call session is scripted. Real Hermes sessions have longer,
  messier contexts; the position effect will differ in degree. The
  harness runs unchanged on any store with model calls the day one
  is available locally (`session_cutoff` takes any branch's events).
- **Context completeness is assumed, and the flagship violates it.**
  The rule is sound where the recorded context is the whole context
  — true by construction for runner-recorded sessions, where
  `context_at` is literally what a fork re-primes with. The
  flagship's recorded "prompt" is a label (`compute return from Fact
  Graph`), and its computation has inputs (the standard deduction,
  state facts) that appear in no event payload. Its session-layer
  counts are mechanics demonstrations, and upper bounds at that.
- **The node layer assumes deterministic node functions** — true of
  both corpora and of the Engine's design. "Byte-identical on
  recompute" is meaningless for a non-deterministic node; that is
  precisely why the model layer needs the context-bytes check
  instead of recompute-and-compare.
- **No wall-clock numbers.** A replayed model call saves a model
  invocation, the expensive unit, but no live-model timings were
  taken; the claim is in calls, not seconds.
- **Nothing here implements context-bytes replay in forks.** The
  audit's conditional ("if the number is real, implement") now has
  its number: real at the session layer, position-dependent, and
  near-zero at the node layer beyond what the Engine already does.
  Implementing it is a separate decision, not part of this
  measurement.

## Reproduce

```sh
PYTHONPATH=src python3 -m living_replay.cutoff --out /tmp/m8.json
PYTHONPATH=src python3 -m unittest tests.test_m8_cutoff
```
