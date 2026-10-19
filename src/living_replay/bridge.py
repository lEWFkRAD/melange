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


def _recorded_computation(store, branch: str):
    """The branch's re-executable computation, rebuilt from its record.

    Returns (comp_event, graph, inputs): the latest model_call whose
    payload carries figures, the FactGraph rebuilt from the recorded
    intake document, and the computation's recorded inputs. Raises
    ValueError — an honest refusal — where the recording carries no
    such computation or its inputs cannot be rebuilt.
    """
    from . import flagship

    events = store.replay_events(branch)
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
    # Rebuild the selected computation's effective inputs, including
    # edits inherited from earlier What-ifs. Starting from the original
    # intake alone silently resets every previous correction on a fork.
    for ev in events:
        if ev["id"] > comp["id"]:
            break
        payload = ev["payload"] or {}
        if (ev["kind"] == "edit" and payload.get("edit_kind") == "clamp"
                and payload.get("target") in inputs):
            inputs[payload["target"]] = payload["value"]
    return comp, graph, inputs


def _make_evaluate(graph, inputs):
    """The forward-execution path clamp and explain share.

    Returns (evaluate, ripple): evaluate(overrides) rebuilds the
    incremental Engine from the recorded inputs, applies the overrides
    as edits, and returns the full values; ripple is refreshed on
    every call with the derived figures that recomputed vs were
    reused (early cutoff), in flagship.DERIVED_ORDER.
    """
    from . import flagship

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

    return evaluate, ripple


def computation(store, branch: str) -> dict | None:
    """The branch's recorded computation, for surfaces: {inputs,
    figures} rebuilt from the record, or None where the recording
    carries no re-executable computation."""
    try:
        comp, _graph, inputs = _recorded_computation(store, branch)
    except ValueError:
        return None
    return {"inputs": dict(inputs), "figures": dict(comp["payload"]["figures"])}


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
    comp, graph, inputs = _recorded_computation(store, parent_branch)
    if target not in inputs:
        raise ValueError(
            f"clamp target {target!r} is not a recorded input of this "
            f"computation (recorded inputs: {sorted(inputs)})")
    evaluate, ripple = _make_evaluate(graph, inputs)

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


def _ancestor_inputs(graph, target: str, inputs: dict) -> list[str]:
    """Recorded inputs the target figure transitively rests on."""
    seen: set[str] = set()
    frontier = [target]
    while frontier:
        path = frontier.pop()
        if path in seen:
            continue
        seen.add(path)
        fact = graph.facts.get(path)
        if fact is not None and fact.formula is not None:
            frontier.extend(fact.inputs)
    return sorted(p for p in seen if p in inputs)


def _solve_single_input(evaluate, target: str, desired, path: str,
                        current):
    """Solve backward for ONE input: the value that, forward-executed
    through the same Engine path clamp uses, makes target come out
    exactly `desired` — or None.

    Bisection over an expanding bracket around the recorded value
    (steps growing x4, out to ~1.6e7), then the root is snapped —
    whole number first, then two decimals, then the raw root — and
    each snapped value is accepted only if a fresh forward execution
    reproduces `desired` EXACTLY. A value that merely comes close is
    not an explanation and is never returned.
    """
    def gap(v):
        return evaluate({path: v})[target] - desired

    if gap(current) == 0:
        return None  # this input needs no change; nothing to explain
    step = 1.0
    while step <= 4.0 ** 12:
        for lo, hi in ((current, current + step),
                       (current - step, current)):
            glo, ghi = gap(lo), gap(hi)
            root = None
            if glo == 0 and lo != current:
                root = lo
            elif ghi == 0 and hi != current:
                root = hi
            elif (glo < 0) != (ghi < 0):
                for _ in range(200):
                    mid = (lo + hi) / 2
                    gm = gap(mid)
                    if gm == 0:
                        root = mid
                        break
                    if (gm < 0) == (glo < 0):
                        lo, glo = mid, gm
                    else:
                        hi = mid
                else:
                    root = (lo + hi) / 2
            if root is not None:
                for cand in dict.fromkeys(
                        (round(root), round(root, 2), root)):
                    if cand == current:
                        continue
                    if evaluate({path: cand})[target] == desired:
                        return cand
                return None
        step *= 4
    return None


def explain(store, parent_branch: str, target: str, desired_value,
            instruction: str = "") -> dict:
    """What went wrong? Solve backward from a figure to its cause.

    EXPLAIN per the doctrine: for every recorded input the target
    figure rests on, solve for the single-input change that would
    have produced `desired_value`, and present each one that
    FORWARD-EXECUTION VERIFIES (through the same incremental Engine
    path clamp uses) as a ghost What-if branch. The bridge never
    chooses between candidates — every verified one is forked and
    returned, and the user keeps the one that is right. A candidate
    that breaks a house rule is reported with the rule named and
    creates nothing, exactly as clamp behaves. When no single input
    explains the figure, the result says so (unresolved True) and
    nothing is fabricated; explanations needing two inputs changed
    at once are beyond this rung and are not guessed at.

    Gated on the 'clamp' capability: every candidate explain can
    present is a clamp it has itself executed, so a recording whose
    fidelity refuses clamp refuses explain the same way
    (FidelityError). Raises ValueError where the recording carries
    no re-executable computation, or the target is not one of its
    derived figures (a recorded input is changed with clamp, not
    explained).

    Returns {target, desired, current, candidates, unresolved};
    each candidate is {input, from, to, accepted, branch,
    fork_event, figures, recomputed, reused, violations,
    pins_inherited} or, when a house rule blocks it, {input, from,
    to, accepted: False, branch: None, violations, reason}.
    """
    from . import flagship, house_rules

    ingest.require_branch_op(store, parent_branch, "clamp")
    comp, graph, inputs = _recorded_computation(store, parent_branch)
    fact = graph.facts.get(target)
    if fact is None or fact.formula is None:
        if target in inputs:
            raise ValueError(
                f"explain target {target!r} is a recorded input of this "
                f"computation; change it directly with clamp")
        raise ValueError(
            f"explain target {target!r} is not a figure of this "
            f"computation (figures: "
            f"{sorted(p for p, f in graph.facts.items() if f.formula is not None)})")
    evaluate, ripple = _make_evaluate(graph, inputs)
    current = evaluate({})[target]

    solved = []
    if current != desired_value:
        for path in _ancestor_inputs(graph, target, inputs):
            value = _solve_single_input(evaluate, target, desired_value,
                                        path, inputs[path])
            if value is not None:
                solved.append((path, value))

    candidates = []
    names = set(_branch_names(store))
    for path, value in solved:
        base = ("explain-" + target.strip("/").replace("/", "-")
                + "-via-" + path.strip("/").replace("/", "-"))
        branch_name = base
        i = 2
        while branch_name in names:
            branch_name = f"{base}-{i}"
            i += 1
        text = instruction or (
            f"What went wrong? {target} should be {desired_value}: "
            f"if {path} had been {value} instead of {inputs[path]}")
        result = house_rules.checked_fork(store, parent_branch, comp["id"],
                                          branch_name, text,
                                          {path: value}, evaluate)
        if not result["accepted"]:
            candidates.append({
                "input": path, "from": inputs[path], "to": value,
                "accepted": False, "branch": None,
                "violations": result["violations"],
                "reason": result["reason"]})
            continue
        names.add(branch_name)
        values = result["candidate"]
        figures = {p: values[p] for p in flagship.DERIVED_ORDER
                   if p in values}
        store.append(branch_name, "model_call",
                     {"prompt": "explain candidate", "figures": figures,
                      "explained": {"target": target,
                                    "desired": desired_value},
                      "clamped": {path: value},
                      "recomputed": ripple["recomputed"],
                      "reused": ripple["reused"], "replayed": True},
                     parent_event=result["fork_event"])
        candidates.append({
            "input": path, "from": inputs[path], "to": value,
            "accepted": True, "branch": branch_name,
            "fork_event": result["fork_event"],
            "figures": figures,
            "recomputed": ripple["recomputed"],
            "reused": ripple["reused"],
            "violations": result["violations"],
            "pins_inherited": result["pins_inherited"]})
    return {"target": target, "desired": desired_value,
            "current": current, "candidates": candidates,
            "unresolved": not any(c["accepted"] for c in candidates)}


def seal(store, branch: str) -> bool:
    """True iff the version's record is complete and untampered."""
    return store.verify(branch)
