"""M5: fork resumption — reopen a recorded branch as a live session.

A fork in the store is a past: a parent prefix plus the fork event.
Resumption makes it a present again: a live agent boots with the
branch's workspace restored to its state at the fork point and
appends NEW events onto that same branch, parented on the branch's
hash chain exactly where the record left off. The original branch is
never written by the continuation.

This module is the planning and verification half, and it is strict
about the three things a resume must prove afterwards:

  (a) prefix identity — the branch's pre-resume logical timeline
      (inherited prefix + fork event + any local events that already
      existed) is still an exact prefix of the branch, event id by
      event id, hash by hash;
  (b) continuation validity — the branch's own hash chain still seals
      (store.verify), so the new events are chained onto the old tip;
  (c) parent isolation — every branch named in the baseline (the
      parent above all) has byte-identical local events to before.

The guest half lives in sandbox/live_resume_agent.py; the host
driver that ties them together is sandbox/run_resume_guest.py.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .forking import restore_workspace
from .store import TimelineStore


@dataclass
class ResumePlan:
    """Everything a resume needs and everything verification checks.

    `prefix_ids`/`prefix_hashes` are the branch's LOGICAL timeline
    (store.replay_events) at plan time: the inherited prefix, the fork
    event, and any local tail. A correct resume leaves all of it as an
    exact prefix and only ever appends after it.
    """
    branch: str
    checkpoint: int                 # event id the resume is anchored on
    checkpoint_hash: str
    fork_event: int | None          # local fork event id; None on a root branch
    parent_branch: str | None
    prefix_ids: list[int]
    prefix_hashes: list[str]
    tip_event: int                  # last logical event id at plan time
    workspace_snapshot_event: int | None  # latest workspace_snapshot on the logical timeline

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResumePlan":
        return cls(**data)


def logical_timeline(store: TimelineStore, branch: str) -> list[dict[str, Any]]:
    """The branch's full logical timeline (inherited prefix + local tail)."""
    return store.replay_events(branch)


def resolve_checkpoint(store: TimelineStore, branch: str,
                       checkpoint: int) -> dict[str, Any]:
    """Return the checkpoint event, requiring it to sit on the branch's
    logical timeline. An event id from a sibling branch, a parent event
    above the fork point, or a nonexistent id all refuse — resuming
    from a point the branch never contained would fabricate a past."""
    logical = logical_timeline(store, branch)
    if not logical:
        raise ValueError(f"branch {branch!r} has no events to resume from")
    for e in logical:
        if e["id"] == checkpoint:
            return e
    try:
        store.event(checkpoint)
    except KeyError:
        raise ValueError(f"checkpoint event {checkpoint} does not exist") from None
    raise ValueError(
        f"checkpoint event {checkpoint} is not on branch {branch!r}'s timeline")


def plan_resume(store: TimelineStore, branch: str, checkpoint: int) -> ResumePlan:
    """Build the plan for resuming `branch` live from `checkpoint`.

    The checkpoint anchors the resume (for a forked branch it is
    normally the fork point or an inherited event the user picked);
    the continuation itself appends at the branch tip, so the plan
    captures the branch's ENTIRE current logical timeline as the
    prefix that must survive untouched.
    """
    anchor = resolve_checkpoint(store, branch, checkpoint)
    logical = logical_timeline(store, branch)
    local = store.events(branch)
    fork = next((e for e in local if e["kind"] == "fork"), None)
    snapshot = None
    for e in reversed(logical):
        if e["kind"] == "workspace_snapshot":
            snapshot = e["id"]
            break
    return ResumePlan(
        branch=branch,
        checkpoint=checkpoint,
        checkpoint_hash=anchor["hash"],
        fork_event=fork["id"] if fork else None,
        parent_branch=fork["payload"]["parent_branch"] if fork else None,
        prefix_ids=[e["id"] for e in logical],
        prefix_hashes=[e["hash"] for e in logical],
        tip_event=logical[-1]["id"],
        workspace_snapshot_event=snapshot,
    )


def capture_branch_state(store: TimelineStore, branch: str) -> dict[str, Any]:
    """A branch's LOCAL events as ids + hashes, for parent-isolation
    baselines. Local on purpose: a child appending to itself must not
    move the parent's state, and only the parent's own rows prove it."""
    local = store.events(branch)
    return {"ids": [e["id"] for e in local],
            "hashes": [e["hash"] for e in local]}


def prepare_workspace(store: TimelineStore, plan: ResumePlan,
                      destination: str | Path) -> Path | None:
    """Restore the branch's workspace from the snapshot the plan found.

    Returns the destination path, or None when the branch's timeline
    carries no workspace snapshot at or before the resume point — the
    caller then supplies the workspace another way (or resumes with an
    empty one), but the plan said so out loud instead of guessing.
    """
    if plan.workspace_snapshot_event is None:
        return None
    return restore_workspace(store, plan.workspace_snapshot_event, destination)


def ancestry(store: TimelineStore, branch: str) -> list[str]:
    """The branch plus every ancestor reached through fork events,
    nearest first. A forked branch's logical timeline spans all of
    them, so integrity checks must too: store.verify alone seals only
    one branch's local rows and would not see a rewritten event in an
    inherited prefix."""
    seen: set[str] = set()
    out: list[str] = []
    cur: str | None = branch
    while cur and cur not in seen:
        seen.add(cur)
        out.append(cur)
        local = store.events(cur)
        fork = next((e for e in local if e["kind"] == "fork"), None)
        cur = fork["payload"]["parent_branch"] if fork else None
    return out


def verify_resume(store: TimelineStore, plan: ResumePlan,
                  parents: dict[str, dict[str, Any]] | None = None,
                  require_new: bool = True) -> dict[str, Any]:
    """Check a finished resume against its plan and parent baselines.

    Returns a report dict; nothing raises — the caller decides what a
    failed check means. `ok` is the conjunction of every check that
    ran. With require_new, an empty continuation (the guest appended
    nothing) fails: a resume that recorded nothing is not a resume.
    """
    logical = logical_timeline(store, plan.branch)
    n = len(plan.prefix_ids)
    prefix_ok = (len(logical) >= n
                 and [e["id"] for e in logical[:n]] == plan.prefix_ids
                 and [e["hash"] for e in logical[:n]] == plan.prefix_hashes)
    new_events = logical[n:]
    # The chain must seal across the whole ancestry, not just the
    # branch's local rows — the inherited prefix IS the branch's past.
    chain_ok = all(store.verify(b) for b in ancestry(store, plan.branch))
    report: dict[str, Any] = {
        "branch": plan.branch,
        "prefix_events": n,
        "prefix_ok": prefix_ok,
        "new_events": len(new_events),
        "new_event_ids": [e["id"] for e in new_events],
        "new_model_calls": sum(1 for e in new_events if e["kind"] == "model_call"),
        "continuation_ok": bool(new_events) if require_new else True,
        "chain_ok": chain_ok,
        "parents": {},
    }
    parents_ok = True
    for name, baseline in (parents or {}).items():
        now = capture_branch_state(store, name)
        same = now == baseline
        chain = store.verify(name)
        report["parents"][name] = {"unchanged": same, "chain_ok": chain,
                                   "events": len(now["ids"])}
        parents_ok = parents_ok and same and chain
    report["parents_ok"] = parents_ok
    report["ok"] = bool(prefix_ok and chain_ok and parents_ok
                        and report["continuation_ok"])
    return report


def assert_resume(store: TimelineStore, plan: ResumePlan,
                  parents: dict[str, dict[str, Any]] | None = None,
                  require_new: bool = True) -> dict[str, Any]:
    """verify_resume, raising AssertionError with the report on failure."""
    report = verify_resume(store, plan, parents=parents, require_new=require_new)
    if not report["ok"]:
        raise AssertionError(f"resume verification failed: {report}")
    return report
