"""Fork-runner: execute a fork from a checkpoint (Build 1, brief deliverable 5).

A fork is a restart, not a process resurrection: the new branch inherits the
parent timeline prefix, the workspace is restored from the checkpoint's
snapshot, the agent's context is truncated to the checkpoint, and an optional
pinned context note is injected. The task then runs live on the new branch
and its terminal work is recorded there. The parent branch is never written
to — fork isolation is checked by the gate suite, not assumed.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Callable

from .capture import PtyCapture
from .forking import restore_workspace
from .replay import reconstruct
from .redaction import redact_text
from .store import TimelineStore

CONTEXT_KINDS = ("tool_call", "model_call", "context_note")

def context_at(store: TimelineStore, branch: str, checkpoint: int | None = None) -> list[dict[str, Any]]:
    """The restart context for a branch at a checkpoint: the tool/model/note
    events an agent would be re-primed with, in order, nothing after the
    checkpoint."""
    return [
        {"kind": e["kind"], "payload": e["payload"]}
        for e in store.replay_events(branch, checkpoint)
        if e["kind"] in CONTEXT_KINDS
    ]

def prefix_offset(store: TimelineStore, branch: str, checkpoint: int) -> int:
    """Total recorded terminal bytes in a branch prefix — the offset the
    fork's capture continues from, so byte offsets stay monotonic across
    the fork tree."""
    total = 0
    for e in store.replay_events(branch, checkpoint):
        if e["kind"] == "terminal_chunk":
            total += e["payload"]["length"]
    return total

class ForkContext:
    """What a forked task sees: truncated context, the note, the workspace,
    and a capture bound to the new branch."""
    def __init__(self, store, branch, context, note, workspace, capture):
        self.store, self.branch, self.context = store, branch, context
        self.note, self.workspace, self.capture = note, workspace, capture

    def call_tool(self, name: str, output: bytes, tool_input: str = "") -> int:
        """Record one tool call and its terminal output on this branch."""
        event = self.store.append(self.branch, "tool_call",
                                  {"name": redact_text(name), "input": redact_text(tool_input),
                                   "output": redact_text(output.decode("utf-8", "replace"))})
        self.capture.record_bytes(output, event)
        return event

    def call_model(self, prompt: str, tokens: str) -> int:
        """Record a model decision (the recorded tokens ARE the replay)."""
        return self.store.append(self.branch, "model_call",
                                 {"prompt": redact_text(prompt), "tokens": redact_text(tokens), "replayed": True})

def run_fork(store: TimelineStore, parent_branch: str, checkpoint: int, new_branch: str,
             task: Callable[[ForkContext], Any], *, note: str | None = None,
             workspace_snapshot: int | None = None, workspace_dest: str | Path | None = None,
             rows: int = 24, cols: int = 80) -> dict[str, Any]:
    """Fork at `checkpoint` and run `task` live on the new branch.

    Returns the branch, the task's result, the final screen, and any pin
    violations found on the new branch after the run (pins are typed `pin`
    edit events visible in the fork's inherited prefix or added to it;
    a violation is reported by target name, never silently dropped).
    """
    fork_event = store.fork(parent_branch, checkpoint, new_branch)
    if note is not None:
        store.append(new_branch, "context_note", {"text": redact_text(note), "pinned": True}, parent_event=fork_event)
    workspace = None
    if workspace_snapshot is not None:
        if workspace_dest is None:
            raise ValueError("workspace_dest is required with workspace_snapshot")
        workspace = restore_workspace(store, workspace_snapshot, workspace_dest)
    grid = reconstruct(store, parent_branch, checkpoint, rows, cols)
    capture = PtyCapture(store, new_branch, rows=rows, cols=cols, grid=grid,
                         offset=prefix_offset(store, parent_branch, checkpoint))
    ctx = ForkContext(store, new_branch, context_at(store, new_branch), note, workspace, capture)
    result = task(ctx)
    pins = {e["payload"]["target"]: e["payload"]["value"]
            for e in store.replay_events(new_branch) if e["kind"] == "edit" and e["payload"].get("edit_kind") == "pin"}
    return {"branch": new_branch, "fork_event": fork_event, "result": result,
            "screen": capture.grid.screen(), "pins": pins}

def demo_task(amount_from_context: bool = True) -> Callable[[ForkContext], dict]:
    """The scripted demo workload used by the gate suite: a two-step agent
    that reads an amount with a tool, doubles it as its model decision, and
    prints the total. On a fork, a pinned note can correct the amount."""
    def task(ctx: ForkContext) -> dict:
        amount = None
        for item in reversed(ctx.context):
            if item["kind"] == "tool_call" and item["payload"].get("name") == "read-amount":
                amount = item["payload"]["amount"]
        if ctx.note and "amount=" in ctx.note:
            amount = int(ctx.note.split("amount=")[1].split()[0])
        if amount is None:
            raise ValueError("demo task found no amount in context")
        total = amount * 2
        ctx.call_model("double the amount", str(total))
        ctx.call_tool("print-total", f"amount={amount} total={total}\r\n".encode(), "print")
        return {"amount": amount, "total": total}
    return task
