#!/usr/bin/env python3
"""Melange M3 — the bridge as a live service.

A zero-dependency (Python stdlib only) HTTP service that wraps the
canonical bridge (living_replay.bridge) over a configured set of
TimelineStores and serves JSON + frame bytes to the reference surface
in service/static/.

Design rules (UX design §7 + the M3 brief):
- Every read and write goes through the bridge; fidelity is enforced
  server-side by ingest.require_branch_op / the bridge's own gates.
  A refused operation returns HTTP 403 with the library's refusal
  sentence — the design's one-line reason, verbatim.
- The seal is store.verify(branch) computed AT REQUEST TIME. A store
  that does not verify reports seal:false in a normal 200 response —
  never a 500 that hides the fact.
- Stores are opened fresh per request (cheap SQLite opens), so what
  the surface sees is what is on disk right now, and writes are
  serialized per store with a lock.
- Binds 127.0.0.1 only. Default port 8798 (8796/8797 are the SHATNER
  bridge ports; this is a local VM service, no relation).

Config: a JSON registry at $MELANGE_STORES_FILE (default:
service/stores.json next to this file):

  {"stores": {
     "<id>": {"path": "~/.../store", "label": "Human name",
              "profile_dir": "~/.../melange-excel",   (workbook only)
              "fixture": "~/.../melange-fixture.xlsx", (workbook only)
              "generate": "flagship"}                  (optional)
  }}

"path" is the TimelineStore root (the directory holding
timeline.sqlite). "generate": "flagship" runs the canonical
flagship.run_flagship into the store's parent directory the first
time the store is opened, if the timeline is absent.

Steps: a branch's navigable steps depend on its kind —
  video    (screen-only): one step per kept picture (screen_frame);
  workbook:               one step per recorded cell_frame;
  structure / session:    one step per event in the branch's replay.
Step numbers in the API are 1-based.
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))          # workbook_eval
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from living_replay import bridge, house_rules, ingest, shelf  # noqa: E402
from living_replay.ingest import FidelityError  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402

ALL_OPS = ["scrub", "dive", "annotate", "provenance", "clamp", "fork"]
STATIC_DIR = Path(__file__).resolve().parent / "static"


# ---------------------------------------------------------------- stores

class StoreRegistry:
    def __init__(self, config: dict):
        self.entries: dict[str, dict] = {}
        for sid, entry in config.get("stores", {}).items():
            e = dict(entry)
            e["path"] = Path(os.path.expanduser(e["path"]))
            if not e["path"].is_absolute():
                e["path"] = (Path(__file__).resolve().parent.parent
                             / e["path"]).resolve()
            self.entries[sid] = e
        self._locks = {sid: threading.Lock() for sid in self.entries}
        self._generated: set[str] = set()

    def ids(self) -> list[str]:
        return list(self.entries)

    def lock(self, sid: str) -> threading.Lock:
        return self._locks[sid]

    def open(self, sid: str) -> TimelineStore:
        entry = self.entries[sid]
        root = entry["path"]
        if entry.get("generate") == "flagship" and sid not in self._generated:
            if not (root / "timeline.sqlite").exists():
                from living_replay import flagship
                flagship.run_flagship(root.parent)
            self._generated.add(sid)
        # Encrypted stores carry a wrapped key (key.json): open them the
        # same way the TUI does — master key from LIVING_REPLAY_KEY, else
        # a master.b64 inside or beside the store tree.
        provider = None
        rootp = Path(root).expanduser()
        if (rootp / "key.json").exists():
            import os
            from living_replay.crypto import LocalKeyProvider
            if os.environ.get("LIVING_REPLAY_KEY"):
                provider = LocalKeyProvider.from_env()
            else:
                for cand in (rootp / "master.b64", rootp.parent / "master.b64"):
                    if cand.exists():
                        provider = LocalKeyProvider.from_file(cand)
                        break
        return TimelineStore(root, key_provider=provider)


REGISTRY: StoreRegistry | None = None


def load_registry() -> StoreRegistry:
    path = os.environ.get("MELANGE_STORES_FILE")
    cfg_path = Path(path) if path else Path(__file__).resolve().parent / "stores.json"
    config = json.loads(cfg_path.read_text())
    return StoreRegistry(config)


# ------------------------------------------------------------ step model

def generic_branch(store, branch: str) -> bool:
    """Whether the recording uses the generic JSONL ingest contract."""
    return any(e["kind"] == "ingest_profile"
               and e["payload"].get("format") == ingest.GENERIC_FORMAT
               for e in store.replay_events(branch))


def branch_kind(store, branch: str) -> str:
    fidelity = ingest.branch_fidelity(store, branch)
    if fidelity == "screen-only":
        return "session" if generic_branch(store, branch) else "video"
    kinds = {e["kind"] for e in store.replay_events(branch)}
    if "cell_frame" in kinds:
        return "workbook"
    if fidelity == "structure":
        return "structure"
    return "session"


def step_events(store, branch: str):
    """(kind, [events]) — the branch's navigable steps, in order."""
    kind = branch_kind(store, branch)
    events = store.replay_events(branch)
    if kind == "video":
        events = [e for e in events if e["kind"] == "screen_frame"]
    elif kind == "workbook":
        events = [e for e in events if e["kind"] == "cell_frame"]
    elif kind == "structure" or generic_branch(store, branch):
        events = [e for e in events if e["kind"] != "ingest_profile"]
    return kind, events


def split_step(store, fork: dict) -> int:
    """The 1-based step on the PARENT branch at which this fork split,
    so the surface's volume can draw the branch leaving at the right
    place. Falls back to the parent's last step when the checkpoint is
    not itself a navigable step (e.g. a workbook tip edit event)."""
    parent = fork["parent_branch"]
    _, parent_steps = step_events(store, parent)
    for i, ev in enumerate(parent_steps, start=1):
        if ev["id"] == fork["checkpoint"]:
            return i
    return len(parent_steps)


def refusals(fidelity: str) -> dict:
    """The design's one-line reason for every operation this fidelity
    refuses, computed from the library's own gate text."""
    out = {}
    for op in ALL_OPS:
        try:
            ingest.require_op(fidelity, op)
        except FidelityError as exc:
            out[op] = str(exc)
    return out


def workbook_values(store, branch: str, entry: dict):
    """Current full values of a workbook branch: the finished book's
    inputs, with the branch's own clamp edits applied through the
    workbook profile's incremental Engine. None if not computable."""
    import workbook_eval
    frames = [e for e in store.replay_events(branch)
              if e["kind"] == "cell_frame"]
    if not frames:
        return None
    finished = frames[-1]["payload"]["values"]
    base_inputs = {k: finished.get(k) for k in
                   ("wages", "withholding", "other_income", "threshold_limit")}
    clamps = {e["payload"]["target"]: e["payload"]["value"]
              for e in store.replay_events(branch)
              if e["kind"] == "edit"
              and e["payload"].get("edit_kind") == "clamp"}
    evaluate = workbook_eval.make_evaluate(entry, base_inputs)
    return evaluate(clamps)


def branch_detail(store, branch: str, entry: dict) -> dict:
    fidelity = ingest.branch_fidelity(store, branch)
    kind, steps = step_events(store, branch)
    fork = None
    for v in bridge.versions(store):
        if v["name"] == branch:
            fork = v["fork"]
    if fork:
        fork = dict(fork)
        fork["split_step"] = split_step(store, fork)
    pins = house_rules.pins_on(store, branch)
    rules = []
    if pins:
        if kind == "workbook":
            values = workbook_values(store, branch, entry)
            if values is not None:
                rules = house_rules.house_rules(store, branch, values)
        if not rules:
            rules = [{"target": t, "pinned": v, "current": None,
                      "status": "Unknown — not computable in this service"}
                     for t, v in pins.items()]
    return {
        "branch": branch,
        "kind": kind,
        "fidelity": fidelity,
        "caps": bridge.caps(store, branch),
        "refusals": refusals(fidelity),
        "steps": len(steps),
        "timeline": [{"step": i, "event_id": ev["id"],
                      "kind": ev["kind"],
                      "ts": ev["payload"].get("ts", ev["mono_ns"] / 1_000_000_000)}
                     for i, ev in enumerate(steps, 1)],
        "computation_step": next((i for i, ev in reversed(list(enumerate(steps, 1)))
                                  if ev["kind"] == "model_call"
                                  and "figures" in ev["payload"]), None),
        "seal": bridge.seal(store, branch),
        "fork": fork,
        "house_rules": rules,
        "notes": bridge.notes(store, branch),
        "computation": (bridge.computation(store, branch)
                        if kind == "session" else None),
        # M11: the shelf standing, how this version was made, and its
        # spoken story (script + engine facts, never the audio bytes).
        "kept": shelf.shelf_state(store, branch),
        "provenance": shelf.provenance(store, branch),
        "narration": shelf.narration(store, branch),
    }


def pin_status(store, branch: str, entry: dict) -> str | None:
    """The Golden Path standing of a branch, in one word for the
    shelf: None (no rules), 'Holding', 'Broken', or 'Not checked'
    (rules exist but this service cannot compute the branch's values
    — said plainly rather than guessed). Workbook values and a
    session branch's recorded computation are both computable here.
    """
    pins = house_rules.pins_on(store, branch)
    if not pins:
        return None
    values = None
    kind, _ = step_events(store, branch)
    if kind == "workbook":
        values = workbook_values(store, branch, entry)
    elif kind == "session":
        comp = bridge.computation(store, branch)
        if comp is not None:
            values = comp["figures"]
    if values is None:
        return "Not checked"
    rules = house_rules.house_rules(store, branch, values)
    if any(r["status"] == "Broken" for r in rules):
        return "Broken"
    return "Holding"


def shelf_entry(store, branch: str, entry: dict) -> dict:
    """One version's shelf card: the facts the shelf shows about it."""
    fidelity = ingest.branch_fidelity(store, branch)
    kind, steps = step_events(store, branch)
    fork = None
    for v in bridge.versions(store):
        if v["name"] == branch:
            fork = v["fork"]
    if fork:
        fork = dict(fork)
        fork["split_step"] = split_step(store, fork)
    narr = shelf.narration(store, branch)
    return {
        "name": branch,
        "fidelity": fidelity,
        "kind": kind,
        "steps": len(steps),
        "seal": bridge.seal(store, branch),
        "fork": fork,
        "pins": len(house_rules.pins_on(store, branch)),
        "pin_status": pin_status(store, branch, entry),
        "kept": shelf.shelf_state(store, branch),
        "provenance": shelf.provenance(store, branch),
        "narration": ({"has_audio": narr["has_audio"],
                        "engine": narr["engine"]} if narr else None),
    }


def branch_map(store, sid: str) -> dict:
    """The spatial map of one recording: a lane per version, a
    positioned entry per step, built entirely from the store.

    Markers, all read off real events: 'pin' (this step IS a house
    rule being pinned), 'note' (a Note is pinned to this step),
    'checkpoint' (another version split from this step), 'split'
    (this step is where this version left its parent).
    """
    versions = bridge.versions(store)
    checkpoints = {v["fork"]["checkpoint"] for v in versions if v["fork"]}
    lanes = []
    for v in versions:
        name = v["name"]
        kind, steps = step_events(store, name)
        note_targets = {n["at_event"] for n in bridge.notes(store, name)}
        fork = v["fork"]
        lane_steps = []
        for i, ev in enumerate(steps, start=1):
            markers = []
            if ev["id"] in checkpoints:
                markers.append("checkpoint")
            if ev["id"] in note_targets:
                markers.append("note")
            if ev["kind"] == "edit" \
                    and (ev["payload"] or {}).get("edit_kind") == "pin":
                markers.append("pin")
            if fork and ev["kind"] == "fork":
                markers.append("split")
            lane_steps.append({"n": i, "event_id": ev["id"],
                               "kind": ev["kind"], "markers": markers})
        lanes.append({
            "branch": name, "kind": kind, "fidelity": v["fidelity"],
            "original": fork is None,
            "parent_branch": fork["parent_branch"] if fork else None,
            "split_step": split_step(store, fork) if fork else None,
            "kept": shelf.shelf_state(store, name),
            "steps": lane_steps,
        })
    return {"store": sid, "lanes": lanes}


def sniff_image(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "application/octet-stream"


# ---------------------------------------------------------------- server

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt, *args):  # keep test output readable
        sys.stderr.write("melange-service: %s\n" % (fmt % args))

    def _send(self, code: int, body: bytes, ctype: str,
              extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj, extra: dict | None = None):
        self._send(code, json.dumps(obj).encode(), "application/json", extra)

    def _error(self, code: int, message: str):
        self._json(code, {"error": message})

    def _body_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode() or "{}")

    # -- routing -------------------------------------------------------
    def do_GET(self):
        try:
            self._route_get()
        except FidelityError as exc:
            self._error(403, str(exc))
        except KeyError as exc:
            self._error(404, f"not found: {exc}")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # never hide a failure behind a bare 500 page
            self._error(500, f"{type(exc).__name__}: {exc}")

    def do_POST(self):
        try:
            self._route_post()
        except FidelityError as exc:
            self._error(403, str(exc))
        except KeyError as exc:
            self._error(404, f"not found: {exc}")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:
            self._error(500, f"{type(exc).__name__}: {exc}")

    def _parts(self):
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.split("/") if p != ""]
        return parts, parse_qs(parsed.query)

    def _route_get(self):
        parts, query = self._parts()
        if parts == [] or parts == ["index.html"]:
            return self._static("index.html")
        if parts[0] == "static" and len(parts) == 2:
            return self._static(parts[1])
        if parts == ["api", "health"]:
            return self._json(200, {"ok": True, "stores": len(REGISTRY.ids())})
        if parts == ["api", "stores"]:
            return self._stores()
        if parts == ["api", "shelf"]:
            return self._shelf()
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "store" \
                and parts[3] == "branch":
            sid, branch = parts[2], parts[4] if len(parts) > 4 else None
            if branch is None:
                raise KeyError("branch")
            entry = self._entry(sid)
            with REGISTRY.lock(sid):
                store = REGISTRY.open(sid)
                if len(parts) == 5:
                    return self._json(200, {"id": sid, "label": entry.get("label", sid),
                                            **branch_detail(store, branch, entry)})
                if len(parts) == 6 and parts[5] == "map":
                    return self._json(200, branch_map(store, sid))
                if len(parts) == 7 and parts[5] == "narration" \
                        and parts[6] == "audio":
                    return self._narration_audio(store, branch)
                if len(parts) == 7 and parts[5] == "step":
                    return self._step(store, branch, int(parts[6]), query, entry)
                if len(parts) == 7 and parts[5] == "wherefrom":
                    return self._wherefrom(store, branch, int(parts[6]), query)
            raise KeyError(parsed_path(parts))
        raise KeyError(parsed_path(parts))

    def _route_post(self):
        parts, _ = self._parts()
        if len(parts) == 6 and parts[0] == "api" and parts[1] == "store" \
                and parts[3] == "branch" \
                and parts[5] in ("note", "fork", "explain", "promote",
                                 "demote", "narration"):
            sid, branch = parts[2], parts[4]
            entry = self._entry(sid)
            body = self._body_json()
            with REGISTRY.lock(sid):
                store = REGISTRY.open(sid)
                if parts[5] == "note":
                    return self._note(store, branch, body)
                if parts[5] == "explain":
                    return self._explain(store, branch, body)
                if parts[5] == "promote":
                    return self._promote(store, branch, body)
                if parts[5] == "demote":
                    return self._demote(store, branch)
                if parts[5] == "narration":
                    return self._make_narration(store, branch)
                return self._fork(store, branch, body, entry)
        raise KeyError(parsed_path(parts))

    # -- endpoints ------------------------------------------------------
    def _entry(self, sid: str) -> dict:
        if sid not in REGISTRY.entries:
            raise KeyError(f"store {sid!r}")
        return REGISTRY.entries[sid]

    def _stores(self):
        out = []
        for sid in REGISTRY.ids():
            entry = REGISTRY.entries[sid]
            with REGISTRY.lock(sid):
                store = REGISTRY.open(sid)
                branches = []
                for v in bridge.versions(store):
                    kind, steps = step_events(store, v["name"])
                    fork = v["fork"]
                    if fork:
                        fork = dict(fork)
                        fork["split_step"] = split_step(store, fork)
                    branches.append({
                        "name": v["name"], "fidelity": v["fidelity"],
                        "kind": kind, "steps": len(steps), "fork": fork,
                        "seal": bridge.seal(store, v["name"]),
                    })
            out.append({"id": sid, "label": entry.get("label", sid),
                        "branches": branches})
        return self._json(200, out)

    def _shelf(self):
        """The shelf as a place (M11): every recording in the
        registry with every version on it — kind badge facts, branch
        count, Golden Path standing, seal, and which What-ifs are
        kept, under what name, and how they were made."""
        out = []
        for sid in REGISTRY.ids():
            entry = REGISTRY.entries[sid]
            with REGISTRY.lock(sid):
                store = REGISTRY.open(sid)
                branches = [shelf_entry(store, v["name"], entry)
                            for v in bridge.versions(store)]
            out.append({"id": sid, "label": entry.get("label", sid),
                        "branch_count": len(branches),
                        "branches": branches})
        return self._json(200, out)

    def _promote(self, store, branch, body):
        state = shelf.promote(store, branch, body.get("name", ""))
        return self._json(201, {"branch": branch, **state})

    def _demote(self, store, branch):
        state = shelf.demote(store, branch)
        return self._json(200, {"branch": branch, **state})

    def _make_narration(self, store, branch):
        made = shelf.make_narration(store, branch)
        return self._json(201, made)

    def _narration_audio(self, store, branch):
        audio = shelf.narration_audio(store, branch)
        if audio is None:
            narr = shelf.narration(store, branch)
            if narr is None:
                raise KeyError("narration")
            if narr["engine"]:
                msg = "this version's story has no audio attached"
            else:
                msg = ("this version's story is words only here: "
                       + shelf.NO_ENGINE_NOTE)
            return self._error(404, msg)
        return self._send(200, audio, "audio/wav",
                          {"X-Melange-Narration": "flite-wav"})

    def _step(self, store, branch, n, query, entry):
        kind, steps = step_events(store, branch)
        if not 1 <= n <= len(steps):
            raise KeyError(f"step {n} of {len(steps)}")
        ev = steps[n - 1]
        if kind == "video":
            if query.get("meta"):
                return self._json(200, {
                    "kind": kind, "step": n, "of": len(steps),
                    "event_id": ev["id"], "ts": ev["payload"].get("ts")})
            data = bridge.frame_at(store, branch, n - 1)
            return self._send(200, data, sniff_image(data),
                              {"X-Melange-Step": str(n),
                               "X-Melange-Steps": str(len(steps))})
        if kind == "workbook":
            return self._json(200, {
                "kind": kind, "step": n, "of": len(steps),
                "event_id": ev["id"], "label": ev["payload"].get("label"),
                "values": ev["payload"]["values"]})
        if kind == "structure":
            if generic_branch(store, branch):
                has_state = any(e["payload"].get("state_blob")
                                for e in store.events(branch, through=ev["id"]))
                parts = (ingest.generic_state_at(store, branch, through=ev["id"])
                         if has_state else None)
            else:
                parts = bridge.parts_at(store, branch, through=ev["id"])
            return self._json(200, {
                "kind": kind, "step": n, "of": len(steps),
                "event_id": ev["id"], "event_kind": ev["kind"],
                "ts": ev["payload"].get("ts", ev["mono_ns"] / 1_000_000_000),
                "parts": parts, "state_available": parts is not None,
                "payload": ev["payload"]})
        if generic_branch(store, branch):
            return self._json(200, {
                "kind": kind, "step": n, "of": len(steps),
                "event_id": ev["id"], "event_kind": ev["kind"],
                "ts": ev["payload"].get("ts", ev["mono_ns"] / 1_000_000_000),
                "screen": json.dumps(ev["payload"], ensure_ascii=False, indent=2),
                "payload": ev["payload"]})
        return self._json(200, {
            "kind": kind, "step": n, "of": len(steps),
            "event_id": ev["id"], "event_kind": ev["kind"],
            "screen": bridge.screen_at(store, branch, through=ev["id"]),
            "payload": ev["payload"]})

    def _wherefrom(self, store, branch, n, query):
        kind, steps = step_events(store, branch)
        if not 1 <= n <= len(steps):
            raise KeyError(f"step {n} of {len(steps)}")
        row = int(query.get("row", ["0"])[0])
        col = int(query.get("col", ["0"])[0])
        result = bridge.where_from(store, branch, steps[n - 1]["id"], row, col)
        return self._json(200, {"step": n, "event_id": steps[n - 1]["id"],
                                **result})

    def _note(self, store, branch, body):
        text = body.get("text", "")
        if not text:
            raise ValueError("a note needs text")
        step = int(body.get("step", 1))
        kind, steps = step_events(store, branch)
        if not 1 <= step <= len(steps):
            raise KeyError(f"step {step} of {len(steps)}")
        event_id = bridge.add_note(store, branch, steps[step - 1]["id"], text)
        return self._json(201, {"event_id": event_id,
                                "notes": bridge.notes(store, branch)})

    def _fork(self, store, branch, body, entry):
        kind, steps = step_events(store, branch)
        if body.get("step"):
            step = int(body["step"])
            if not 1 <= step <= len(steps):
                raise KeyError(f"step {step} of {len(steps)}")
            checkpoint = steps[step - 1]["id"]
        else:
            checkpoint = store.replay_events(branch)[-1]["id"]
        instruction = body.get("note", "")
        clamp = body.get("clamp")
        if clamp:
            kind0, _ = step_events(store, branch)
            if kind0 == "workbook":
                return self._fork_clamp(store, branch, checkpoint,
                                        instruction, clamp, entry)
            return self._fork_clamp_session(store, branch, instruction,
                                            clamp)
        names = {v["name"] for v in bridge.versions(store)}
        new_branch = body.get("branch") or self._fresh_name(names, "whatif")
        if new_branch in names:
            raise ValueError(f"branch {new_branch!r} already exists")
        made = bridge.try_differently(store, branch, checkpoint,
                                      new_branch, instruction)
        return self._json(201, {"accepted": True, **made})

    def _fork_clamp(self, store, branch, checkpoint, instruction, clamp, entry):
        import workbook_eval
        kind, _ = step_events(store, branch)
        if kind != "workbook":
            raise ValueError("clamp forks need a workbook recording")
        cell, value = clamp.get("cell"), clamp.get("value")
        if not cell:
            raise ValueError("a clamp needs a cell")
        frames = [e for e in store.replay_events(branch)
                  if e["kind"] == "cell_frame"]
        finished = frames[-1]["payload"]["values"]
        base_inputs = {k: finished.get(k) for k in
                       ("wages", "withholding", "other_income",
                        "threshold_limit")}
        evaluate = workbook_eval.make_evaluate(entry, base_inputs)
        names = {v["name"] for v in bridge.versions(store)}
        new_branch = self._fresh_name(names, f"whatif-{cell}-{value}")
        if not instruction:
            instruction = f"Change this step: {cell} corrected to {value}"
        result = house_rules.checked_fork(store, branch, checkpoint,
                                          new_branch, instruction,
                                          {cell: value}, evaluate)
        if not result["accepted"]:
            return self._json(422, {
                "accepted": False,
                "violations": result["violations"],
                "reason": result["reason"]})
        cand = result["candidate"]
        return self._json(201, {
            "accepted": True, "branch": result["branch"],
            "fork_event": result["fork_event"],
            "values": {k: cand.get(k) for k in
                       ("wages", "withholding", "agi", "tax", "refund",
                        "over_threshold", "review_flag")},
            "pins_inherited": result["pins_inherited"],
            "violations": result["violations"]})

    def _fork_clamp_session(self, store, branch, instruction, clamp):
        """Clamp fork on a session recording (M4): the bridge forks at
        the recorded computation step itself (the step being edited),
        re-executes its dependents, and reports the ripple."""
        target = clamp.get("target") or clamp.get("cell")
        if not target:
            raise ValueError("a clamp needs a target")
        result = bridge.clamp(store, branch, target, clamp.get("value"),
                              instruction=instruction)
        if not result["accepted"]:
            return self._json(422, {
                "accepted": False,
                "violations": result["violations"],
                "reason": result["reason"]})
        return self._json(201, {
            "accepted": True, "branch": result["branch"],
            "fork_event": result["fork_event"],
            "values": result["figures"],
            "recomputed": result["recomputed"],
            "reused": result["reused"],
            "pins_inherited": result["pins_inherited"],
            "violations": result["violations"]})

    def _explain(self, store, branch, body):
        """What went wrong? (M4): solve backward from a figure of a
        session recording's computation to the single recorded-input
        changes that would have produced the desired value. Every
        candidate the bridge returns was forward-executed through
        the same Engine path clamp uses; the bridge presents them
        all and never chooses. Pin-blocked candidates come back
        named inside a normal 200 — the explanation succeeded; some
        of its answers are rules-blocked. Fidelity refusals stay
        403 and honest non-computations 400 via the handler."""
        target = body.get("target")
        if not target:
            raise ValueError("an explain needs a target figure")
        if body.get("desired") is None:
            raise ValueError("an explain needs the value it should be")
        result = bridge.explain(store, branch, target, body["desired"])
        return self._json(200, result)

    @staticmethod
    def _fresh_name(existing: set, base: str) -> str:
        if base not in existing:
            return base
        i = 2
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    def _static(self, name: str):
        target = (STATIC_DIR / name).resolve()
        if target.parent != STATIC_DIR.resolve() or not target.is_file():
            raise KeyError(name)
        ctype = {".html": "text/html; charset=utf-8",
                 ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8"}.get(
                     target.suffix, "text/plain; charset=utf-8")
        return self._send(200, target.read_bytes(), ctype)


def parsed_path(parts) -> str:
    return "/" + "/".join(parts)


def main() -> int:
    global REGISTRY
    REGISTRY = load_registry()
    port = int(os.environ.get("MELANGE_PORT", "8798"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"melange-service on http://127.0.0.1:{port} "
          f"({len(REGISTRY.ids())} stores: {', '.join(REGISTRY.ids())})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
