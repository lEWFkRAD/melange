"""M7 — House rules (pins) as a bridge-level surface.

The canonical tree has all the pin machinery but no bridge endpoint for
it: pins are `edit` events written by store.typed_edit(branch, "pin",
target, value); runner.run_fork collects them from a fork's
replay_events and edits.check_pins(values, pins) reports violations BY
NAME (the G6 gate pattern). The UX design (§4) asks every surface to
list "House rules" with a live status (Holding / Broken), and the
doctrine is that pins are checked on EVERY fork.

This companion module composes those canonical pieces into the missing
bridge surface, without modifying the canonical tree:

  pins_on(store, branch)            -> {target: value} from replay_events
  house_rules(store, branch, values)-> [{target, pinned, current, status}]
  checked_fork(store, parent, checkpoint, new_branch, instruction,
               clamps, evaluate)    -> the bridge fork path
                                       (bridge.try_differently) gated by
                                       the pins: the fork's defining
                                       clamps are evaluated first; if
                                       they break a pin, the fork is
                                       REJECTED (never created) and the
                                       violated rules are named. If it
                                       passes, the fork is created, the
                                       clamps are recorded as typed
                                       edits, and the pins collected
                                       from the fork's own replay are
                                       re-checked against its values
                                       (the runner.run_fork audit).

`evaluate(overrides) -> values dict` is supplied by the caller: pins can
only be pre-checked where the branch's values are computable (the
workbook profile's incremental Engine here). For branches whose values
are not computable up front, checked_fork's post-fork audit is the
floor — the same report-by-name semantics the gates use.
"""
from __future__ import annotations

from living_replay import bridge
from living_replay.edits import check_pins


def pins_on(store, branch: str) -> dict:
    """All pins visible on a branch (its own + inherited via forks)."""
    return {e["payload"]["target"]: e["payload"]["value"]
            for e in store.replay_events(branch)
            if e["kind"] == "edit" and e["payload"].get("edit_kind") == "pin"}


def house_rules(store, branch: str, values: dict) -> list[dict]:
    """Live status of every house rule on a branch, in office words."""
    broken = set(check_pins(values, pins_on(store, branch)))
    return [{"target": t, "pinned": v, "current": values.get(t),
             "status": "Broken" if t in broken else "Holding"}
            for t, v in pins_on(store, branch).items()]


def checked_fork(store, parent_branch: str, checkpoint: int, new_branch: str,
                 instruction: str, clamps: dict, evaluate) -> dict:
    """Fork through the bridge, gated by the parent's house rules.

    clamps: {target: new_value} — the What-if's defining edits.
    evaluate: callable mapping input overrides to the branch's full
              values dict (deterministic profiles only).
    """
    pins = pins_on(store, parent_branch)
    candidate = evaluate(dict(clamps))
    violations = check_pins(candidate, pins)
    if violations:
        return {"accepted": False, "branch": None,
                "violations": violations,
                "candidate": candidate,
                "reason": "House rules broken: " + ", ".join(
                    f"{t} must stay {pins[t]!r} (this What-if makes it "
                    f"{candidate.get(t)!r})" for t in violations)}
    made = bridge.try_differently(store, parent_branch, checkpoint,
                                  new_branch, instruction)
    for target, value in clamps.items():
        store.typed_edit(new_branch, "clamp", target, value)
    # Post-fork audit, runner.run_fork style: pins as the fork itself
    # inherits them, checked against the fork's evaluated values.
    fork_pins = pins_on(store, new_branch)
    audit = check_pins(evaluate(dict(clamps)), fork_pins)
    return {"accepted": True, "branch": new_branch,
            "fork_event": made["fork_event"], "note_event": made["note_event"],
            "violations": audit, "pins_inherited": fork_pins,
            "candidate": candidate}
