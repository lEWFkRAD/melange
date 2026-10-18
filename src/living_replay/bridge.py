"""The bridge: the single UI-facing API over the Living Replay library.

Melange UX design, section 7: every surface (desktop replay bar, TUI
widget, reference player) talks to the backend through this module and
only this module. Replay, reconstruction and the fidelity contract stay
in the library; the bridge's job is to expose them under the exact
operations the UI performs, and to be the one place where fidelity is
enforced for UI callers (the store itself does not refuse an op).

Vocabulary follows the UX design's office words: a branch is a version
(the Original, or a What-if), an event is a step, an annotation event
is a Note saved in the recording itself. Functions take the store plus
plain values and return plain dicts, lists, strings and bytes, so any
surface can consume them without knowing the library's internals.
"""
from __future__ import annotations

from . import ingest, replay


def _branch_names(store) -> list[str]:
    """Every branch present in the store, discovered from the events table."""
    rows = store.db.execute(
        "SELECT DISTINCT branch FROM events ORDER BY branch").fetchall()
    return [r[0] for r in rows]


def _fork_info(store, branch: str) -> dict | None:
    for ev in store.events(branch):
        if ev["kind"] == "fork":
            p = ev["payload"]
            return {"parent_branch": p["parent_branch"],
                    "checkpoint": p["checkpoint"]}
    return None


def versions(store) -> list[dict]:
    """One entry per version (branch) in the recording.

    {name, fidelity, steps, fork}: steps is the length of the version's
    full history (inherited prefix included for a What-if), and fork is
    None for an original or {parent_branch, checkpoint} for a What-if.
    """
    out = []
    for name in _branch_names(store):
        out.append({
            "name": name,
            "fidelity": ingest.branch_fidelity(store, name),
            "steps": len(store.replay_events(name)),
            "fork": _fork_info(store, name),
        })
    return out


def caps(store, branch: str) -> list[str]:
    """The operations this version's recording kind allows, sorted."""
    fidelity = ingest.branch_fidelity(store, branch)
    return sorted(ingest.FIDELITY_CAPS[fidelity])


def screen_at(store, branch: str, through: int | None = None) -> str:
    """The reconstructed screen text at a step (default: the latest)."""
    ingest.require_branch_op(store, branch, "scrub")
    return replay.reconstruct(store, branch, through).screen()


def parts_at(store, branch: str, through: int | None = None) -> dict:
    """The parts the screen is made of, at a step (structure recordings).

    Delegates to ingest.tree_state_at, which enforces 'dive' itself.
    """
    return ingest.tree_state_at(store, branch, through)


def frame_at(store, branch: str, index: int) -> bytes:
    """The index-th kept picture of a video-only recording (PNG bytes).

    Delegates to ingest.screen_frame_at, which enforces 'scrub' itself.
    """
    return ingest.screen_frame_at(store, branch, index)


def where_from(store, branch: str, event_id: int, row: int, col: int) -> dict:
    """Where the character at (row, col) came from, in a plain sentence.

    Returns replay.provenance's dict plus a 'sentence' field in office
    language. Three cases, kept honest per the UX design: if a recorded
    step's output produced the cell, the sentence names the step and the
    character offset into that step's output; if the recording did not
    keep which action inside the step made it (attributed is False),
    the caveat saying exactly that is appended; if no step made the
    cell at all, the sentence says the spot is blank or a redraw.
    """
    ingest.require_branch_op(store, branch, "provenance")
    result = replay.provenance(store, branch, event_id, row, col)
    if "chunk" in result:
        sentence = (f"This came from step {result['chunk']}, "
                    f"{result['offset']} characters into that step's output.")
        if not result["attributed"]:
            sentence += (" This recording shows which step's output it is, "
                         "but did not keep which action inside the step "
                         "made it.")
    else:
        sentence = ("That spot is blank, or the program redrew it; "
                    "no step's output made it.")
    return {**result, "sentence": sentence}


def add_note(store, branch: str, at_event: int, text: str) -> int:
    """Pin a Note to a step, written into the recording itself.

    Returns the new annotation event's id. Notes are ordinary events on
    the branch, so every surface reading the recording sees them.
    """
    ingest.require_branch_op(store, branch, "annotate")
    return store.append(branch, "annotation", {"at_event": at_event, "text": text})


def notes(store, branch: str) -> list[dict]:
    """All Notes on a version: [{event_id, at_event, text}], in order."""
    return [{"event_id": ev["id"],
             "at_event": ev["payload"]["at_event"],
             "text": ev["payload"]["text"]}
            for ev in store.replay_events(branch)
            if ev["kind"] == "annotation"]


def try_differently(store, parent_branch: str, checkpoint: int,
                    new_branch: str, instruction: str) -> dict:
    """Make a What-if: fork at a step and write the new instruction in.

    The instruction is recorded as the What-if's first context note at
    the split step. This records intent, per the UX design's honesty
    rule: running it needs the work session to be live again, so no
    continuation is fabricated here.
    """
    ingest.require_branch_op(store, parent_branch, "fork")
    fork_event = store.fork(parent_branch, checkpoint, new_branch,
                            edit={"instruction": instruction})
    note_event = store.append(new_branch, "context_note",
                              {"text": instruction, "pinned": False})
    return {"branch": new_branch, "fork_event": fork_event,
            "note_event": note_event}


def clamp(store, parent_branch: str, target: str, value,
          new_branch: str | None = None, instruction: str = "") -> dict:
    """Change this step: clamp one recorded input and re-execute.

    The surface-issued edit (M4). Finds the branch's recorded
    computation (the latest model_call whose payload carries figures,
    with inputs rebuildable from the recorded intake document), forks
    at that step through the house-rules gate, re-executes ONLY the
    clamped input's transitive dependents through the incremental
    Engine (early cutoff applies), and appends the amended computation
    to the What-if as a new model_call event carrying the ripple.

    Returns {accepted, branch, fork_event, target, value, values,
    figures, recomputed, reused, violations, pins_inherited}; a pin
    violation returns accepted False with the rules named and creates
    nothing. Raises FidelityError where the recording's fidelity
    refuses 'clamp', and ValueError where the recording carries no
    re-executable computation or the target is not a recorded input —
    an honest refusal, never a fabricated result.
    """
    from . import flagship, house_rules

    ingest.require_branch_op(store, parent_branch, "clamp")
    events = store.replay_events(parent_branch)
    comp = None
    for ev in events:
        if ev["kind"] == "model_call" and "figures" in (ev["payload"] or {}):
            comp = ev
    if comp is None:
        raise ValueError(
            "this recording carries no recorded computation to re-execute")
    intake_text = None
    for ev in events:
        for v in (ev["payload"] or {}).values():
            if isinstance(v, str):
                try:
                    flagship.WagesLens.get(v)
                except (ValueError, AttributeError):
                    continue
                intake_text = v
                break
        if intake_text is not None:
            break
    if intake_text is None:
        raise ValueError(
            "this recording's inputs cannot be rebuilt from its record")
    graph = flagship.build_fact_graph(intake_text)
    inputs = {p: f.value for p, f in graph.facts.items() if f.formula is None}
    if target not in inputs:
        raise ValueError(
            f"clamp target {target!r} is not a recorded input of this "
            f"computation (recorded inputs: {sorted(inputs)})")
    derived = [p for p, f in graph.facts.items() if f.formula is not None]
    ripple: dict[str, list[str]] = {"recomputed": [], "reused": []}

    def evaluate(clamps: dict) -> dict:
        engine = flagship._engine_from_graph(graph, dict(inputs))
        engine.build()
        executed: list[str] = []
        for t, v in clamps.items():
            engine.edit(t, v)
            for n in engine.last_executed_nodes:
                if n not in executed:
                    executed.append(n)
        ripple["recomputed"] = [p for p in flagship.DERIVED_ORDER
                                if p in executed]
        ripple["reused"] = [p for p in flagship.DERIVED_ORDER
                            if p in derived and p not in executed]
        return dict(engine.cache)

    names = set(_branch_names(store))
    if new_branch is None:
        base = "whatif-clamp-" + target.strip("/").replace("/", "-")
        new_branch = base
        i = 2
        while new_branch in names:
            new_branch = f"{base}-{i}"
            i += 1
    if not instruction:
        instruction = f"Change this step: {target} corrected to {value}"
    result = house_rules.checked_fork(store, parent_branch, comp["id"],
                                      new_branch, instruction,
                                      {target: value}, evaluate)
    if not result["accepted"]:
        return {"accepted": False, "branch": None,
                "violations": result["violations"],
                "reason": result["reason"]}
    values = result["candidate"]
    figures = {p: values[p] for p in flagship.DERIVED_ORDER if p in values}
    store.append(new_branch, "model_call",
                 {"prompt": "clamp re-execution", "figures": figures,
                  "clamped": {target: value},
                  "recomputed": ripple["recomputed"],
                  "reused": ripple["reused"], "replayed": True},
                 parent_event=result["fork_event"])
    return {"accepted": True, "branch": new_branch,
            "fork_event": result["fork_event"],
            "target": target, "value": value,
            "values": values, "figures": figures,
            "recomputed": ripple["recomputed"],
            "reused": ripple["reused"],
            "violations": result["violations"],
            "pins_inherited": result["pins_inherited"]}


def seal(store, branch: str) -> bool:
    """True iff the version's record is complete and untampered."""
    return store.verify(branch)
