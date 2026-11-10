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

Door 2 generality (M10): `ingest_generic_events` takes an arbitrary
structured event stream (see docs/generic-ingest.md) from software
that is none of the built-in profiles and files it at the honest
fidelity its CONTENT supports. The level is never taken from the
stream's say-so: snapshots present -> structure; a recorded
computation that passes the bridge's own rebuildability test ->
native; anything else -> screen-only caps. A computation claim that
does not check out is recorded as unverified and buys nothing.
"""
from __future__ import annotations

import json
import math

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
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("AX tree must be a non-empty node list")
    by_id = {}
    for n in nodes:
        if not isinstance(n, dict) or not isinstance(n.get("nodeId"), str):
            raise ValueError("AX node must have a string nodeId")
        if n["nodeId"] in by_id and by_id[n["nodeId"]] != n:
            raise ValueError("conflicting duplicate AX nodeId")
        by_id[n["nodeId"]] = n
    # CDP can repeat an identical node in a full-tree response (the
    # original desktop corpus has one). Collapse only exact repeats.
    nodes = list(by_id.values())
    child_of = set()
    for n in nodes:
        children = n.get("childIds") or []
        if not isinstance(children, list):
            raise ValueError("AX childIds must be a list")
        for child in children:
            if not isinstance(child, str) or child not in by_id:
                raise ValueError("AX tree contains a missing child")
            if child in child_of:
                raise ValueError("AX node has multiple parents")
            child_of.add(child)
    roots = [n for n in nodes if n["nodeId"] not in child_of]
    flat = {}
    visited = set()
    pending = [(root, str(i)) for i, root in reversed(list(enumerate(roots)))]
    while pending:
        node, path = pending.pop()
        if node["nodeId"] in visited:
            raise ValueError("AX tree contains a cycle")
        visited.add(node["nodeId"])
        flat[path] = _slim(node)
        pending.extend((by_id[cid], f"{path}/{idx}") for idx, cid in
                       reversed(list(enumerate(node.get("childIds") or []))))
    if len(visited) != len(nodes):
        raise ValueError("AX tree contains a cycle")
    return flat


def ingest_desktop_record(store, branch: str, jsonl_text: str,
                          source: str = "cdp-ax") -> dict:
    """Import a validated desktop record into a fresh structure branch.

    New records use elapsed seconds in ``ts``; the original spike used
    milliseconds in ``t``. Untimed legacy records remain supported.
    Validate the entire record before writing any events or objects.
    """
    lines = [json.loads(l) for l in jsonl_text.strip().split("\n") if l.strip()]
    if not lines or not isinstance(lines[0], dict) or lines[0].get("type") != "keyframe":
        raise ValueError("desktop record must start with an AX keyframe")
    if store.events(branch):
        raise ValueError("desktop ingest requires a new branch")
    previous_ts = 0
    stamps = []
    for ev in lines:
        if not isinstance(ev, dict):
            raise ValueError("desktop record events must be objects")
        ts = ev.get("ts", ev.get("t"))
        if ts is not None:
            if (isinstance(ts, bool) or not isinstance(ts, (int, float))
                    or not math.isfinite(ts) or ts < 0):
                raise ValueError("desktop timestamp must be finite and nonnegative")
            if "ts" not in ev:
                ts /= 1000
            if ts < previous_ts:
                raise ValueError("desktop timestamps must be monotonic")
            previous_ts = ts
        # Untimed legacy frames retain ordering at the most recent time.
        if previous_ts > (2**63 - 1) / 1_000_000_000:
            raise ValueError("desktop timestamp exceeds the ledger clock range")
        stamp = round(previous_ts * 1_000_000_000)
        if stamp > 2**63 - 1:
            raise ValueError("desktop timestamp exceeds the ledger clock range")
        stamps.append(stamp)
        kind = ev.get("type")
        if kind == "keyframe":
            flatten_ax(ev.get("nodes"))
        elif kind == "delta":
            if not isinstance(ev.get("ops"), list):
                raise ValueError("desktop delta ops must be a list")
            for op in ev["ops"]:
                if (not isinstance(op, dict) or op.get("op") not in {"set", "del"}
                        or not isinstance(op.get("path"), str)
                        or not op["path"]
                        or any(not p.isdecimal() for p in op["path"].split("/"))):
                    raise ValueError("invalid desktop delta operation")
                if op["op"] == "set" and not isinstance(op.get("node"), dict):
                    raise ValueError("desktop set operation requires a node")
        elif kind == "input":
            if not isinstance(ev.get("events", []), list):
                raise ValueError("desktop input events must be a list")
            if not isinstance(ev.get("synthetic", False), bool):
                raise ValueError("desktop input synthetic label must be boolean")
        else:
            raise ValueError(f"unknown desktop record type: {kind!r}")
    store.append(branch, "ingest_profile",
                 {"source": source, "fidelity": "structure", "format": "cdp-ax"},
                 mono_ns=stamps[0])
    counts = {"keyframes": 0, "deltas": 0, "delta_ops": 0, "inputs": 0}
    for ev, stamp in zip(lines, stamps):
        timing = {"ts": stamp / 1_000_000_000}
        if ev["type"] == "keyframe":
            digest = store.put_blob(json.dumps(ev["nodes"]).encode())
            store.append(branch, "ax_keyframe", {"blob": digest, **timing}, mono_ns=stamp)
            counts["keyframes"] += 1
        elif ev["type"] == "delta":
            store.append(branch, "ax_delta", {"ops": ev["ops"], "poll": ev.get("poll"),
                                               **timing}, mono_ns=stamp)
            counts["deltas"] += 1
            counts["delta_ops"] += len(ev["ops"])
        elif ev["type"] == "input":
            store.append(branch, "input_event",
                         {"synthetic": ev.get("synthetic", False),
                          "events": ev.get("events", []), **timing}, mono_ns=stamp)
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


# ---------- generic event streams (any software, M10) ----------

GENERIC_FORMAT = "generic-jsonl"
_SPREAD_KINDS = {"model_call", "tool_call"}
_ANNOTATION_KEYS = {"src", "generic", "state_blob"}


def _parse_generic_lines(jsonl_text: str) -> list:
    """Parse + validate a generic stream. Raises ValueError naming the
    line on any malformed input; nothing is stored by the caller until
    the whole stream parses, so a bad stream leaves no partial branch.
    """
    import hashlib
    parsed = []
    for lineno, raw in enumerate(jsonl_text.splitlines()):
        if not raw.strip():
            continue
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"generic stream line {lineno}: not JSON ({e})")
        if not isinstance(ev, dict):
            raise ValueError(f"generic stream line {lineno}: not an object")
        ts = ev.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)):
            raise ValueError(
                f"generic stream line {lineno}: 'ts' must be a number "
                f"of seconds, got {ts!r}")
        if not isinstance(ev.get("action"), str) or not ev["action"]:
            raise ValueError(
                f"generic stream line {lineno}: 'action' must be a "
                f"non-empty string")
        if "actor" in ev and not isinstance(ev["actor"], str):
            raise ValueError(
                f"generic stream line {lineno}: 'actor' must be a string")
        if "state" in ev and not isinstance(ev["state"], dict):
            raise ValueError(
                f"generic stream line {lineno}: 'state' must be an object")
        parsed.append({
            "line": lineno, "raw": raw,
            "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "ts": ts, "actor": ev.get("actor", "unknown"),
            "action": ev["action"], "payload": ev.get("payload", {}),
            "state": ev.get("state"),
        })
    if not parsed:
        raise ValueError("generic stream: no events")
    return parsed


def _map_generic_event(ev: dict):
    """Map one parsed generic event to (store kind, store payload).

    model_call / tool_call events with object payloads are stored
    under their native kinds with the payload spread, so a genuinely
    recorded computation stays visible to the native machinery (the
    bridge's clamp scans model_call figures and payload strings).
    Everything else is wrapped as a generic_event. Either way the
    event carries its source trace: {"src": {"line", "sha256"}}.
    """
    src = {"line": ev["line"], "sha256": ev["sha256"]}
    payload = ev["payload"]
    if (ev["action"] in _SPREAD_KINDS and isinstance(payload, dict)
            and not (_ANNOTATION_KEYS & payload.keys())):
        stored = dict(payload)
        stored["src"] = src
        stored["generic"] = {"actor": ev["actor"], "ts": ev["ts"]}
        return ev["action"], stored
    stored = {"actor": ev["actor"], "action": ev["action"],
              "payload": payload, "ts": ev["ts"], "src": src}
    return "generic_event", stored


def _computation_status(mapped: list) -> str:
    """Judge a stream's computation claim the way the consumer will.

    Returns "verified" only when the mapped store events contain what
    bridge.clamp itself requires: a model_call carrying figures AND
    an intake string the recorded-computation lens can parse (the
    inputs genuinely rebuildable from the record). A model_call with
    figures but no rebuildable intake is "unverified" — the claim was
    made and did not check out. No model_call at all: "absent".
    """
    has_figures = any(kind == "model_call" and "figures" in payload
                      for kind, payload in mapped)
    if not has_figures:
        return "absent"
    strings = []
    for kind, payload in mapped:
        if kind in _SPREAD_KINDS:
            strings += [v for v in payload.values() if isinstance(v, str)]
        elif isinstance(payload.get("payload"), str):
            strings.append(payload["payload"])
    from . import flagship
    for s in strings:
        try:
            flagship.WagesLens.get(s)
        except (ValueError, AttributeError):
            continue
        return "verified"
    return "unverified"


def ingest_generic_events(store, branch: str, jsonl_text: str,
                          source: str = "generic-jsonl") -> dict:
    """Import an arbitrary structured event stream as a timeline.

    Format (docs/generic-ingest.md): one JSON object per line with
    "ts" (seconds, number) and "action" (string) required, "actor"
    (string) and "payload" (any JSON) optional, and an optional
    "state" object: a full structured snapshot of the program's state
    at that event. The fidelity is derived from the content, never
    declared by the stream:

    - a recorded computation passing the bridge's rebuildability
      test -> native (only then may clamp/fork touch it);
    - at least one state snapshot -> structure (dive = state_at);
    - otherwise -> screen-only caps (scrub + annotate): a transcript
      with no state in it has nothing to dive into.

    Each event keeps a traceable link to its source line (line number
    + SHA-256 of the raw line); see source_trace / verify_source_line.
    """
    import hashlib
    parsed = _parse_generic_lines(jsonl_text)
    mapped = [_map_generic_event(ev) for ev in parsed]
    computation = _computation_status(mapped)
    has_state = any(ev["state"] is not None for ev in parsed)
    if computation == "verified":
        fidelity = "native"
    elif has_state:
        fidelity = "structure"
    else:
        fidelity = "screen-only"
    store.append(branch, "ingest_profile", {
        "source": source, "fidelity": fidelity, "format": GENERIC_FORMAT,
        "stream_sha256": hashlib.sha256(jsonl_text.encode()).hexdigest(),
        "computation": computation, "has_state": has_state,
        "events": len(parsed)})
    counts = {"events": 0, "snapshots": 0, "model_calls": 0,
              "fidelity": fidelity, "computation": computation}
    for ev, (kind, stored) in zip(parsed, mapped):
        if ev["state"] is not None:
            blob = json.dumps(ev["state"], sort_keys=True).encode()
            stored["state_blob"] = store.put_blob(blob)
            counts["snapshots"] += 1
        store.append(branch, kind, stored,
                     mono_ns=int(round(ev["ts"] * 1_000_000_000)))
        counts["events"] += 1
        if kind == "model_call":
            counts["model_calls"] += 1
    return counts


def _original_event(kind: str, payload: dict) -> dict:
    """Rebuild the generic-stream event a store event was mapped from."""
    if kind in _SPREAD_KINDS:
        original_payload = {k: v for k, v in payload.items()
                            if k not in _ANNOTATION_KEYS}
        return {"ts": payload["generic"]["ts"],
                "actor": payload["generic"]["actor"],
                "action": kind, "payload": original_payload}
    return {"ts": payload["ts"], "actor": payload["actor"],
            "action": payload["action"], "payload": payload["payload"]}


def reconstruct_generic_stream(store, branch: str) -> list:
    """Rebuild the original generic events from a generic branch.

    The roundtrip counterpart of ingest_generic_events: one entry per
    ingested line, in order, with state snapshots restored. Equality
    with the parsed source stream is the ingest fidelity check.
    """
    out = []
    for ev in store.events(branch):
        if ev["kind"] == "ingest_profile":
            continue
        original = _original_event(ev["kind"], ev["payload"])
        if "state_blob" in ev["payload"]:
            original["state"] = json.loads(
                store.get_blob(ev["payload"]["state_blob"]))
        out.append(original)
    return out


def generic_state_at(store, branch: str, through: int | None = None) -> dict:
    """The recorded state at a point in a generic branch (dive).

    Returns the most recent state snapshot at or before `through`.
    Honest limit: between snapshots the state is whatever the last
    snapshot says — nothing is interpolated. Raises FidelityError at
    screen-only fidelity and ValueError when no snapshot exists yet.
    """
    require_branch_op(store, branch, "dive")
    state = None
    for ev in store.events(branch, through=through):
        blob = (ev["payload"] or {}).get("state_blob")
        if blob:
            state = json.loads(store.get_blob(blob))
    if state is None:
        raise ValueError("no state snapshot recorded in this branch yet")
    return state


def source_trace(store, branch: str, event_id: int) -> dict:
    """Where one ingested event came from: its source trace link.

    Returns {source, format, line, sha256, stream_sha256} — line and
    per-line digest locate the event in the original stream exactly.
    This is ingest provenance (frame back to trace), not the causal
    'provenance' capability, which stays native-only.
    """
    profile = None
    for ev in store.events(branch):
        if ev["kind"] == "ingest_profile":
            profile = ev["payload"]
            break
    target = store.event(event_id)
    src = (target["payload"] or {}).get("src")
    if profile is None or src is None:
        raise KeyError(f"event {event_id} is not a generic-ingested event "
                       f"on branch {branch!r}")
    return {"source": profile["source"], "format": profile.get("format"),
            "line": src["line"], "sha256": src["sha256"],
            "stream_sha256": profile.get("stream_sha256")}


def verify_source_line(store, branch: str, event_id: int,
                       jsonl_text: str) -> bool:
    """Check an event's source line against a candidate original stream.

    True only if the line the event claims hashes to the digest stored
    at ingest. A tampered or merely different stream fails closed.
    """
    import hashlib
    try:
        trace = source_trace(store, branch, event_id)
    except KeyError:
        return False
    lines = jsonl_text.splitlines()
    if trace["line"] >= len(lines):
        return False
    return hashlib.sha256(
        lines[trace["line"]].encode()).hexdigest() == trace["sha256"]
