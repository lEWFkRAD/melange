# Melange UX Design System

Version 1, 2026-10-16. Author: Kip. For: Hermes desktop (bottom bar), Hermes TUI
(dock-bottom widget), and the Melange reference surface.

Grounding documents: `backend-api-map.md` (what the backend really does),
`hermes-tui-recon.md` (how the TUI really renders). Rule zero: **no control may
promise something the backend cannot do.** Where the backend records intent
rather than executing (fork, typed edits), the UI says so in plain words.

## 1. The one idea

Melange is a **recording of work** that you can play back, inspect, and try
differently. An office worker already knows this shape from two places: a
video player, and a spreadsheet. Every word in the interface comes from one of
those two worlds. No developer vocabulary appears anywhere: no "events",
"branches", "provenance", "clamp", "fidelity", "hash chain" in user-facing
text. (Backend names are given in brackets for builders.)

## 2. Words (the whole vocabulary)

| Backend | Interface word | Why an office worker gets it |
|---|---|---|
| timeline / store | **Recording** | It is a recording of a work session. |
| branch (original) | **Original** | The version that actually happened. |
| branch (fork) | **What-if** | A copy where something was tried differently. |
| event | **step** | "Step 25 of 153." Work happened in steps. |
| reconstructed screen | **the screen at this step** | What the screen showed then. |
| scrub [scrub] | **slide** (the slider) | Video player. |
| play | **Play / Pause** | Video player. |
| dive [dive] | **Look inside** | See the parts the screen is made of. |
| provenance [provenance] | **Where did this come from?** | Click any word or number on the screen. |
| annotation [annotate] | **Note** | A sticky note pinned to a step. Saved in the recording. |
| clamp [typed_edit clamp] | **Change this step** | Like fixing a cell: the steps after it redo themselves. |
| fork + inject [fork + context_note] | **Try it differently from here** | Type a new instruction; a What-if is made. |
| pin [typed_edit pin] | **House rule (Golden Path)** | "This must always be true." Checked on every What-if. |
| explain [explain] | **What went wrong?** | Works backward to the step that caused a result. |
| verify() | **Recording checked** | A seal: complete and untampered, or a plain warning. |
| fidelity native | **Full recording** | Everything below works. |
| fidelity structure | **Outline recording** | You can watch and look inside. Steps cannot be changed: the words themselves were not kept. |
| fidelity screen-only | **Video-only recording** | You can watch. Nothing inside can be inspected or changed: only pictures of the screen were kept. |

Two phrases carry the whole mental model, and both appear in the UI:

- On Change this step: **"Like fixing a cell in a spreadsheet. The steps after
  it redo themselves. The original never changes."**
- On Try it differently: **"This makes a What-if copy. The original stays on
  the shelf, untouched."**

## 3. The fidelity rule (honesty in the interface)

Every recording carries one of the three kinds above, shown as a small badge
next to the recording's name, always visible, never hidden in a menu. Controls
that the kind does not support are **not removed and not silently greyed**:
they stay visible with a lock and, when tapped, answer with the one-line
reason from the table ("Steps cannot be changed in an outline recording: the
words themselves were not kept."). This is the Door 2 contract made visible;
the bridge enforces it with `require_branch_op` before any op runs, because
the store itself does not.

## 4. The transport bar (desktop and TUI, same bar)

One bar, identical in words, order, and behavior on both Hermes surfaces.

Desktop: docked at the bottom of the normal session window (ONY-191), full
width, two rows when open:

```
Row 1 (always):  [⏮] [▶ Play] [⏭]  ────────●──────────  Step 25 of 153 · Original ▾  [✓ Recording checked] [Full recording]
Row 2 (actions): [Try it differently from here…] [Change this step…] [Note] [Where did this come from?] [House rules]
```

TUI: the same bar in the widget SDK's `dock-bottom` zone, text form:

```
[<<] [> play] [>>]  step 25/153  =========*----------  Original | checked | full recording
keys: space play/pause · ←/→ step · shift+←/→ jump 10 · i try differently · n note · w where-from · q close
```

Behavior, identical everywhere:

- Play advances steps at the recording's real pace (recorded gaps, clamped so
  long pauses do not stall the show; a speed control offers 1x / 2x / 4x).
- The slider's track is shaded up to the point where a What-if splits from
  the Original, so "the part that is the same in both" is visible at a glance.
- Switching Original / What-if is instant and never loses the step: if the
  step exists in both, you stay on it; past the split, the readout says which
  version you are in, in words ("What-if: tax rate changed at step 108").
- **Try it differently from here** opens one small panel: a text box ("New
  instruction at this step") and a Make the What-if button. The result is
  labeled honestly: the What-if is created and the instruction is written
  into it at that step; if running it needs the work session to be live, the
  panel says **"Saved as the first step of the What-if. It runs when this
  recording is reopened in a live session."** No fake playback of things that
  were not recorded or computed.
- **Change this step** is offered only where a real recompute path exists for
  that kind of step (value pipelines and documents, via the bridge). On a
  session recording it is replaced by Try it differently, which is the honest
  equivalent there. The spreadsheet line above is its help text.
- **Where did this come from?** turns the screen into a picker: click any
  word or number; the answer panel says, in a sentence, "This came from step
  25 (the assistant's calculation), 66 characters into that step's output."
  If the recording does not link a screen word to the step that produced it,
  the answer says exactly that: "This recording can show which step's output
  this is (step 25), but did not keep which action inside the step made it."
  Never a confident half-answer.
- **Note**: a sticky note on the current step, written into the recording
  itself (an annotation event through the bridge), so the note shows up on
  every surface, for everyone who opens the recording. A dot on the slider
  marks steps that carry notes.
- **House rules**: lists the Golden Path rules on this recording, each with a
  plain statement and a live status (Holding / Broken at step N) wherever the
  backend can check it, and "Not checked" where it cannot.

## 5. The full surface (reference player v2)

The full surface is what opens when a recording is opened outside a live
session. Same words, same bar, more room:

- Left: the screen at this step (reconstructed, never a screenshot for Full
  recordings; labeled "Re-drawn from the recording" so nobody mistakes it for
  a photograph of the past).
- Right, three tabs in office words: **Steps** (a readable list of what
  happened: "The assistant calculated…", "A file was written…", with the
  current step highlighted and notes shown inline), **Look inside** (the
  parts list for outline recordings), **Where it came from** (provenance
  answers and house rules).
- The top line states the recording kind and the seal: "Full recording ·
  Recording checked ✓ · Made Oct 16, 2026, 42 minutes of work in 153 steps."

## 6. States that must all be designed, not discovered

- Empty recording (no steps yet): "This recording has no steps yet."
- Seal broken (verify fails): a red banner in plain words: "This recording
  does not check out. A step is missing or was changed after the fact. You
  can watch it, but do not trust it." Watching still allowed; changing is not.
- Recording still being made (live session): the bar shows "Recording now"
  and the slider's end follows the live edge.
- A What-if whose instruction has not run yet: its Steps list shows the
  instruction card at the split step with the honest label from section 4.

## 7. What the builders owe this design

Desktop (Hermes, ONY-191 amended): the bar per section 4, calling the bridge
for every op; no local reimplementation of replay or gating.
TUI (Hermes, follow-on ticket): the dock-bottom widget with the same keys and
words; transcript panels for Steps and Where-it-came-from answers.
Bridge (Kip, lr-repo): `living_replay/bridge.py` exposing list of recordings
and versions, screen at step, parts at step (structure), frame at index
(screen-only), where-from for a cell, notes read/write as store events,
try-differently (fork + instruction note through `require_branch_op`), seal
status (`verify`), and house-rule status where checkable. The bridge is the
only place fidelity is enforced for UI callers.
Surface v2 (Kip): implements sections 4 and 5 against bridge-exported data
from the real Build 2 recording, with the two-store reality shown honestly as
Original and What-if versions of one recording.
