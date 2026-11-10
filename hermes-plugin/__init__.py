"""Melange plugin for Hermes Agent.

Melange is a video codec for computation: it records a terminal session
into an append-only, hash-chained timeline, then lets you scrub to any
step, ask where a character on screen came from, fork a What-if, clamp a
recorded input and watch only its dependents recompute, or ask what went
wrong and get forward-verified candidate answers.

This plugin exposes the Melange bridge (living_replay.bridge) as Hermes
tools. Everything runs locally on stdlib Python; no network calls.
Recordings live under the Hermes home at plugins-data/melange/.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# The engine modules the plugin needs are bundled beside it (living_replay/),
# because `hermes plugins install` copies only this directory. They are kept in
# step with src/living_replay by tools/sync_hermes_plugin.py.
_LIB = Path(__file__).resolve().parent
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

from living_replay import bridge, shelf  # noqa: E402
from living_replay.capture import PtyCapture  # noqa: E402
from living_replay.ingest import FidelityError  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402


def _home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        root = Path(get_hermes_home())
    except Exception:
        root = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    return root / "plugins-data" / "melange"


def _store(params):
    name = (params.get("recording") or "default").strip() or "default"
    if not name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("recording name must be letters, digits, '-' or '_'")
    return TimelineStore(_home() / name)


def _ok(**kw):
    return json.dumps({"success": True, **kw})


def _err(msg):
    return json.dumps({"success": False, "error": str(msg)})


# ------------------------------------------------------------------ tools

def melange_record(params):
    """Run a command in a PTY and record it onto a recording's timeline."""
    try:
        store = _store(params)
        command = params.get("command")
        if not command:
            return _err("command is required")
        cap = PtyCapture(store, rows=int(params.get("rows", 24)),
                        cols=int(params.get("cols", 80)))
        cap.run(command if isinstance(command, list) else ["/bin/sh", "-lc", command],
                timeout=float(params.get("timeout", 30)))
        return _ok(recording=str(store.root.name),
                   steps=len(store.events("main")),
                   screen=cap.grid.screen())
    except Exception as e:
        return _err(e)


def melange_versions(params):
    """List versions (the Original and every What-if) in a recording."""
    try:
        store = _store(params)
        out = []
        for v in bridge.versions(store):
            out.append({**v, "seal": store.verify(v["name"])})
        return _ok(recording=str(store.root.name), versions=out,
                   shelf=shelf.kept_branches(store))
    except Exception as e:
        return _err(e)


def melange_screen(params):
    """The reconstructed screen at a step (scrub the recording)."""
    try:
        store = _store(params)
        through = params.get("through")
        screen = bridge.screen_at(store, params.get("version", "main"),
                                  int(through) if through is not None else None)
        return _ok(screen=screen)
    except Exception as e:
        return _err(e)


def melange_where_from(params):
    """Where the character at (row, col) came from, in plain words."""
    try:
        store = _store(params)
        result = bridge.where_from(store, params.get("version", "main"),
                                   int(params["event"]), int(params["row"]),
                                   int(params["col"]))
        return _ok(**result)
    except Exception as e:
        return _err(e)


def melange_note(params):
    """Pin a note to a step, written into the recording itself."""
    try:
        store = _store(params)
        eid = bridge.add_note(store, params.get("version", "main"),
                              int(params["event"]), params.get("text", ""))
        return _ok(event_id=eid)
    except Exception as e:
        return _err(e)


def melange_whatif(params):
    """Fork a What-if at a step and write the new instruction in."""
    try:
        store = _store(params)
        result = bridge.try_differently(store, params.get("version", "main"),
                                        int(params["checkpoint"]),
                                        params["branch"],
                                        params.get("instruction", ""))
        return _ok(**result)
    except Exception as e:
        return _err(e)


def melange_clamp(params):
    """Change one recorded input and re-execute only its dependents."""
    try:
        store = _store(params)
        value = params["value"]
        try:
            value = float(value) if isinstance(value, str) and "." in value else int(value)
        except (TypeError, ValueError):
            pass
        result = bridge.clamp(store, params.get("version", "main"),
                              params["target"], value,
                              params.get("branch"), params.get("instruction", ""))
        return _ok(**result)
    except Exception as e:
        return _err(e)


def melange_explain(params):
    """What went wrong? Solve backward from a figure to forward-verified causes."""
    try:
        store = _store(params)
        desired = params["desired"]
        try:
            desired = float(desired) if isinstance(desired, str) and "." in desired else int(desired)
        except (TypeError, ValueError):
            pass
        result = bridge.explain(store, params.get("version", "main"),
                                params["target"], desired,
                                params.get("instruction", ""))
        return _ok(**result)
    except Exception as e:
        return _err(e)


def melange_shelf(params):
    """Keep or release a What-if on the shelf, or list what is kept."""
    try:
        store = _store(params)
        action = params.get("action", "list")
        if action == "keep":
            return _ok(**shelf.promote(store, params["version"], params.get("name", "")))
        if action == "release":
            return _ok(**shelf.demote(store, params["version"]))
        return _ok(kept=shelf.kept_branches(store))
    except Exception as e:
        return _err(e)


def melange_demo(params):
    """Run the bundled flagship demo: a synthetic return, corrected, end to end."""
    try:
        import shutil
        import tempfile
        from living_replay import flagship
        if params.get("demo", "tax") == "coding":
            from living_replay import coding_demo
            kept = _home() / "coding"
            with tempfile.TemporaryDirectory(prefix="melange-demo-") as td:
                report = coding_demo.run_demo(Path(td))
                shutil.rmtree(kept, ignore_errors=True)
                kept.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(Path(td) / "timeline", kept)
            return _ok(
                recording="coding",
                inputs=report["inputs"],
                figures=report["figures"],
                test_output=report["execution"]["output"],
                note="a retry helper with a budget of 2 fails 1 of its 6 real tests. Kept as recording "
                     "'coding' (version 'main'): melange_clamp target '/retryBudget' re-runs the tests "
                     "in a What-if and leaves the Original untouched.")
        kept = _home() / "demo"
        with tempfile.TemporaryDirectory(prefix="melange-demo-") as td:
            facts = flagship.run_flagship(Path(td),
                                          corrected_wages=float(params.get("corrected_wages", 48000)))
            # Keep the demo's timeline as recording "demo" so the other tools
            # (clamp, explain, versions, screen) have a computation to work on.
            shutil.rmtree(kept, ignore_errors=True)
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(Path(td) / "timeline", kept)
        return _ok(
            recording="demo",
            original_figures=facts["figures"],
            amended_figures=facts["amended_figures"],
            note="wages corrected; only the wages chain recomputed; the Original is untouched. "
                 "Kept as recording 'demo' (version 'main'): melange_clamp and melange_explain work on it.")
    except Exception as e:
        return _err(e)


# ---------------------------------------------------------------- schemas

def _schema(name, description, props, required):
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": props, "required": required}}


_REC = {"type": "string", "description": "Recording name (default 'default')"}
_VER = {"type": "string", "description": "Version (branch) name, e.g. 'main'"}

TOOLS = [
    ("melange_record",
     _schema("melange_record",
             "Run a shell command in a PTY and record it as a rewindable Melange timeline. Returns the final screen.",
             {"command": {"type": "string", "description": "Shell command to run and record"},
              "recording": _REC, "rows": {"type": "integer"}, "cols": {"type": "integer"},
              "timeout": {"type": "number", "description": "Seconds before the command is cut off (default 30)"}},
             ["command"]),
     melange_record),
    ("melange_versions",
     _schema("melange_versions",
             "List every version in a recording (the Original and each What-if), with fidelity, step count, fork info, seal status, and what is kept on the shelf.",
             {"recording": _REC}, []),
     melange_versions),
    ("melange_screen",
     _schema("melange_screen",
             "Scrub: the reconstructed terminal screen of a version at a step (default: latest).",
             {"recording": _REC, "version": _VER,
              "through": {"type": "integer", "description": "Event id to scrub up to"}}, []),
     melange_screen),
    ("melange_where_from",
     _schema("melange_where_from",
             "Provenance: where the character at (row, col) on screen came from, in a plain sentence.",
             {"recording": _REC, "version": _VER,
              "event": {"type": "integer", "description": "Event id whose screen to inspect"},
              "row": {"type": "integer"}, "col": {"type": "integer"}},
             ["event", "row", "col"]),
     melange_where_from),
    ("melange_note",
     _schema("melange_note",
             "Pin a note to a step, written into the recording itself.",
             {"recording": _REC, "version": _VER,
              "event": {"type": "integer"}, "text": {"type": "string"}},
             ["event", "text"]),
     melange_note),
    ("melange_whatif",
     _schema("melange_whatif",
             "Fork a What-if: branch a version at a checkpoint and write a new instruction into it.",
             {"recording": _REC, "version": _VER,
              "checkpoint": {"type": "integer", "description": "Event id to fork at"},
              "branch": {"type": "string", "description": "Name for the new What-if"},
              "instruction": {"type": "string"}},
             ["checkpoint", "branch"]),
     melange_whatif),
    ("melange_clamp",
     _schema("melange_clamp",
             "Change this step: clamp one recorded input of the version's computation and re-execute only its dependents. Returns the amended figures and what recomputed vs was reused.",
             {"recording": _REC, "version": _VER,
              "target": {"type": "string", "description": "Recorded input path, e.g. '/wages'"},
              "value": {"description": "New value for that input"},
              "branch": {"type": "string", "description": "Optional name for the What-if this creates"},
              "instruction": {"type": "string"}},
             ["target", "value"]),
     melange_clamp),
    ("melange_explain",
     _schema("melange_explain",
             "What went wrong? Solve backward from a figure to a desired value; every forward-verified single-input cause is returned as a ghost What-if.",
             {"recording": _REC, "version": _VER,
              "target": {"type": "string", "description": "Derived figure path, e.g. '/totalTax'"},
              "desired": {"description": "The value it should have been"},
              "instruction": {"type": "string"}},
             ["target", "desired"]),
     melange_explain),
    ("melange_shelf",
     _schema("melange_shelf",
             "The shelf: keep a What-if under a name, release it, or list what is kept.",
             {"recording": _REC,
              "action": {"type": "string", "enum": ["list", "keep", "release"]},
              "version": _VER, "name": {"type": "string"}}, []),
     melange_shelf),
    ("melange_demo",
     _schema("melange_demo",
             "Run the bundled flagship demo end to end: a synthetic tax return is computed, one input is corrected, only its dependents recompute, and the Original stays byte-identical. The result is kept as recording 'demo' for melange_clamp and melange_explain. No arguments needed.",
             {"demo": {"type": "string", "enum": ["tax", "coding"],
                       "description": "'tax' (default): the synthetic return. 'coding': a retry helper whose real test suite fails 1 of 6, kept as recording 'coding' for melange_clamp on '/retryBudget'"},
              "corrected_wages": {"type": "number", "description": "Tax demo only: corrected wages for the What-if (default 48000)"}}, []),
     melange_demo),
]


def register(ctx):
    for name, schema, handler in TOOLS:
        ctx.register_tool(name=name, toolset="melange", schema=schema,
                          handler=lambda params, _h=handler, **kw: _h(params))
