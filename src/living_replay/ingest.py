"""Door 2: trace ingest at labeled fidelity (ONY-169).

Melange's second door takes traces recorded ELSEWHERE (another tool, a
desktop session, a plain video) and imports them as timelines. Every
ingested branch carries a declared fidelity, and the fidelity is a
capability contract enforced here, in the library, at the control
level (ONY-169 amendment 1): an operation the capture depth does not
support is refused by the code path itself, not by a label in a UI.

Fidelities:
- native:      Melange's own capture (Builds 1-2). Full surface:
               scrub, dive, annotate, provenance, clamp, fork.
- structure:   an ingested structural trace (e.g. a CDP accessibility
               record of a desktop app). The frames are real state
               (a tree), so scrub, dive and annotate work; there is no
               executable session behind them, so clamp/fork and
               causal provenance are refused.
- screen-only: ingested video frames. Pixels only: scrub and annotate.
               No state to dive into, nothing to recompute.
"""
from __future__ import annotations

import json

FIDELITY_CAPS = {
    "native": {"scrub", "dive", "annotate", "provenance", "clamp", "fork"},
    "structure": {"scrub", "dive", "annotate"},
    "screen-only": {"scrub", "annotate"},
}


class FidelityError(Exception):
    """Raised when an operation exceeds an ingested trace's fidelity."""


def require_op(fidelity: str, op: str) -> None:
    caps = FIDELITY_CAPS.get(fidelity)
    if caps is None:
        raise FidelityError(f"unknown fidelity: {fidelity!r}")
    if op not in caps:
        raise FidelityError(
            f"operation {op!r} refused at fidelity {fidelity!r}: "
            f"this capture depth supports {sorted(caps)}")


def branch_fidelity(store, branch: str) -> str:
    for ev in store.events(branch):
        if ev["kind"] == "ingest_profile":
            return ev["payload"]["fidelity"]
    return "native"


def require_branch_op(store, branch: str, op: str) -> None:
    require_op(branch_fidelity(store, branch), op)


# ---------- desktop structure traces (CDP accessibility records) ----------

def _slim(node: dict) -> dict:
    props = {}
    for p in sorted(node.get("properties") or [], key=lambda p: p["name"]):
        v = p.get("value") or {}
        props[p["name"]] = v.get("value")
    return {"role": (node.get("role") or {}).get("value", ""),
            "name": (node.get("name") or {}).get("value", ""),
            "desc": (node.get("description") or {}).get("value", ""),
            "props": props}


def flatten_ax(nodes: list) -> dict:
    """Flatten a CDP accessibility tree to {structural_path: slim node}.

    Paths are built from childIds linkage (roots are nodes no other
    node lists as a child), matching the recorder's keying exactly.
    """
    by_id = {n["nodeId"]: n for n in nodes}
    child_of = set()
    for n in nodes:
        child_of.update(n.get("childIds") or [])
    roots = [n for n in nodes if n["nodeId"] not in child_of]
    flat = {}

    def walk(node, path):
        flat[path] = _slim(node)
        for idx, cid in enumerate(node.get("childIds") or []):
            child = by_id.get(cid)
            if child is not None:
                walk(child, f"{path}/{idx}")

    for i, root in enumerate(roots):
        walk(root, str(i))
    return flat


def ingest_desktop_record(store, branch: str, jsonl_text: str,
                          source: str = "cdp-ax") -> dict:
    """Import a desktop recorder JSONL (keyframe/delta/input lines)."""
    lines = [json.loads(l) for l in jsonl_text.strip().split("\n") if l.strip()]
    store.append(branch, "ingest_profile",
                 {"source": source, "fidelity": "structure"})
    counts = {"keyframes": 0, "deltas": 0, "delta_ops": 0, "inputs": 0}
    for ev in lines:
        if ev["type"] == "keyframe":
            digest = store.put_blob(json.dumps(ev["nodes"]).encode())
            store.append(branch, "ax_keyframe", {"blob": digest})
            counts["keyframes"] += 1
        elif ev["type"] == "delta":
            store.append(branch, "ax_delta", {"ops": ev["ops"], "poll": ev.get("poll")})
            counts["deltas"] += 1
            counts["delta_ops"] += len(ev["ops"])
        elif ev["type"] == "input":
            store.append(branch, "input_event",
                         {"synthetic": ev.get("synthetic", False),
                          "events": ev.get("events", [])})
            counts["inputs"] += 1
    return counts


def tree_state_at(store, branch: str, through: int | None = None) -> dict:
    """Reconstruct the flattened tree at a point in an ingested branch."""
    require_branch_op(store, branch, "dive")
    state = None
    for ev in store.events(branch, through=through):
        if ev["kind"] == "ax_keyframe":
            state = flatten_ax(json.loads(store.get_blob(ev["payload"]["blob"])))
        elif ev["kind"] == "ax_delta":
            if state is None:
                raise ValueError("ax_delta before any ax_keyframe")
            for op in ev["payload"]["ops"]:
                if op["op"] == "set":
                    state[op["path"]] = op["node"]
                elif op["op"] == "del":
                    state.pop(op["path"], None)
    if state is None:
        raise ValueError("no ax_keyframe in branch")
    return state


# ---------- screen-only traces (video frames) ----------

def ingest_screen_frames(store, branch: str, frames: list,
                         source: str = "video") -> dict:
    """Import ordered (png_bytes, timestamp_s) frames as screen-only."""
    store.append(branch, "ingest_profile",
                 {"source": source, "fidelity": "screen-only"})
    for png, ts in frames:
        digest = store.put_blob(png)
        store.append(branch, "screen_frame", {"blob": digest, "ts": ts})
    return {"frames": len(frames)}


def screen_frame_at(store, branch: str, index: int) -> bytes:
    require_branch_op(store, branch, "scrub")
    frames = [ev for ev in store.events(branch) if ev["kind"] == "screen_frame"]
    return store.get_blob(frames[index]["payload"]["blob"])
