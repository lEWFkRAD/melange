"""M11 — the shelf: kept What-ifs, their provenance, and their stories.

The volume doctrine (audit P14) says kept forks live on a shelf in the
periphery — a place, not a strand state. This companion module is the
shelf's library surface, composing the canonical pieces the way
house_rules.py composes the pin machinery, without modifying the
canonical tree:

  provenance(store, branch)   -> how a What-if was made: which parent
                                 it split from, and whether a clamp, an
                                 explain, or a plain instruction made
                                 it (with the edit that defines it).
  shelf_state(store, branch)  -> {kept, name, event_id}: the branch's
                                 current shelf standing, read from its
                                 own 'shelf' events.
  promote(store, branch, name)-> keep a What-if on the shelf under a
                                 name. Appends a 'shelf' event to the
                                 What-if branch ONLY — the Original's
                                 events are never touched, and the
                                 standing survives reopening the store
                                 (and so a service restart).
  demote(store, branch)       -> take a kept What-if back off the
                                 shelf (another 'shelf' event; the
                                 branch and its history stay).
  narration_script(store, branch) -> the branch's story in office
                                 words, composed from the record:
                                 what was changed, what redid itself,
                                 and the figures it came out with.
  make_narration(store, branch)   -> speak the story where a speech
                                 engine exists on this machine (ffmpeg's
                                 flite filter today), attach the audio
                                 to the branch as a content-addressed
                                 blob, and record a 'narration' event
                                 carrying the script and the engine's
                                 name. Where no engine exists the event
                                 still carries the script and says so —
                                 the story is words only, never a
                                 silent file dressed up as speech.
  narration(store, branch) / narration_audio(store, branch)
                              -> the latest narration and its audio
                                 bytes (None where there is none).

Shelf and narration writes are writes INTO the recording, so both are
gated on the 'annotate' capability by the library's own fidelity gate,
exactly as notes are.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from living_replay import bridge, ingest

VOICE = "slt"
ENGINE_NAME = "flite (ffmpeg), voice slt — a plain synthesized voice"
NO_ENGINE_NOTE = ("No voice engine is installed on this machine, so "
                  "this story is words only for now.")


# ------------------------------------------------------------ provenance

def provenance(store, branch: str) -> dict | None:
    """How this version was made, or None for an Original.

    {parent_branch, checkpoint, via, instruction, detail}: via is
    'clamp' or 'explain' where the branch's own record carries the
    re-execution that made it (bridge.clamp / bridge.explain model_call
    events), else 'try-differently' with the instruction that was
    written into it; detail carries the defining edit ({clamped} or
    {explained, clamped}) where there is one.
    """
    fork = bridge._fork_info(store, branch)
    if fork is None:
        return None
    own = store.events(branch)
    via, detail, instruction = "try-differently", None, ""
    for ev in own:
        if ev["kind"] == "context_note" and not instruction:
            instruction = ev["payload"].get("text", "")
        if ev["kind"] != "model_call":
            continue
        p = ev["payload"] or {}
        if "explained" in p:
            via = "explain"
            detail = {"explained": p["explained"],
                      "clamped": p.get("clamped", {})}
        elif "clamped" in p and via != "explain":
            via = "clamp"
            detail = {"clamped": p["clamped"]}
    return {"parent_branch": fork["parent_branch"],
            "checkpoint": fork["checkpoint"],
            "via": via, "instruction": instruction, "detail": detail}


# ---------------------------------------------------------------- shelf

def shelf_state(store, branch: str) -> dict:
    """The branch's shelf standing: {kept, name, event_id}.

    Read from the branch's OWN 'shelf' events (the latest one wins),
    never from an inherited prefix — a fork of a kept What-if is not
    itself kept.
    """
    state = {"kept": False, "name": None, "event_id": None}
    for ev in store.events(branch):
        if ev["kind"] != "shelf":
            continue
        p = ev["payload"] or {}
        if p.get("action") == "keep":
            state = {"kept": True, "name": p.get("name"),
                     "event_id": ev["id"]}
        elif p.get("action") == "release":
            state = {"kept": False, "name": None, "event_id": ev["id"]}
    return state


def kept_branches(store) -> dict:
    """{branch: kept name} for every branch currently on the shelf."""
    out = {}
    for v in bridge.versions(store):
        st = shelf_state(store, v["name"])
        if st["kept"]:
            out[v["name"]] = st["name"]
    return out


def promote(store, branch: str, name: str) -> dict:
    """Keep a What-if on the shelf under `name`.

    Only a What-if can be kept: the Original is the recording itself
    and is always here. The name must be free on this store's shelf.
    Appends one 'shelf' event to the What-if branch; nothing else in
    the store changes. Returns the branch's new shelf state plus its
    provenance.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("a kept What-if needs a name for the shelf")
    if not store.events(branch):
        raise KeyError(branch)
    if bridge._fork_info(store, branch) is None:
        raise ValueError(
            "the Original is the recording itself — it is always on "
            "the shelf; only a What-if can be kept")
    ingest.require_branch_op(store, branch, "annotate")
    for other, taken in kept_branches(store).items():
        if taken == name and other != branch:
            raise ValueError(
                f"the name {name!r} is already on the shelf "
                f"(it is the kept name of {other!r})")
    event_id = store.append(branch, "shelf",
                            {"action": "keep", "name": name})
    state = shelf_state(store, branch)
    state["event_id"] = event_id
    return {**state, "provenance": provenance(store, branch)}


def demote(store, branch: str) -> dict:
    """Take a kept What-if back off the shelf.

    The branch keeps everything it is — its record, its name as a
    branch, its provenance — it simply stops being kept. Raises
    ValueError where the branch is not on the shelf.
    """
    if not store.events(branch):
        raise KeyError(branch)
    state = shelf_state(store, branch)
    if not state["kept"]:
        raise ValueError("this What-if is not on the shelf")
    ingest.require_branch_op(store, branch, "annotate")
    event_id = store.append(branch, "shelf",
                            {"action": "release", "name": state["name"]})
    return {**shelf_state(store, branch), "event_id": event_id}


# ------------------------------------------------------------- narration

def _spoken_path(path: str) -> str:
    """'/taxableIncome' -> 'taxable income', for words and for speech."""
    tail = str(path).strip("/").split("/")[-1]
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", tail).replace("_", " ")
    return words.lower()


def _spoken_num(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _figures_sentence(figures: dict) -> str:
    """The headline figures, in office words; refund and total tax
    first where the computation has them, else the first two."""
    order = [p for p in ("/refund", "/totalTax") if p in figures]
    order += [p for p in figures if p not in order][:max(0, 2 - len(order))]
    parts = [f"the {_spoken_path(p)} came out {_spoken_num(figures[p])}"
             for p in order]
    if not parts:
        return ""
    return "In the end, " + " and ".join(parts) + "."


def narration_script(store, branch: str) -> str:
    """The branch's story, composed from its record alone.

    Every sentence is built from events and figures the store holds;
    where the record carries nothing to narrate (no computation, no
    fork), the script says what the version is and how many steps it
    has, and no more.
    """
    prov = provenance(store, branch)
    comp = bridge.computation(store, branch)
    sentences: list[str] = []
    if prov is None:
        sentences.append("This is the Original — the work as it "
                         "actually happened.")
        if comp:
            inputs = comp["inputs"]
            if inputs:
                said = ", ".join(
                    f"{_spoken_path(p)} {_spoken_num(v)}"
                    for p, v in list(inputs.items())[:3])
                sentences.append(f"It starts from {said}.")
            fig = _figures_sentence(comp["figures"])
            if fig:
                sentences.append(fig)
    else:
        parent = prov["parent_branch"]
        parent_comp = bridge.computation(store, parent)
        detail = prov["detail"] or {}
        if prov["via"] == "clamp" and detail.get("clamped"):
            sentences.append(
                f"This What-if was made by changing one step of "
                f"{parent}, and keeping the change.")
            for target, value in detail["clamped"].items():
                before = (parent_comp or {}).get("inputs", {}).get(target)
                if before is not None:
                    sentences.append(
                        f"{_spoken_path(target).capitalize()} was "
                        f"changed from {_spoken_num(before)} to "
                        f"{_spoken_num(value)}.")
                else:
                    sentences.append(
                        f"{_spoken_path(target).capitalize()} was set "
                        f"to {_spoken_num(value)}.")
            model = _latest_model_call(store, branch)
            if model:
                redone = (model["payload"] or {}).get("recomputed") or []
                kept = (model["payload"] or {}).get("reused") or []
                if redone:
                    sentences.append(
                        "The steps after it redid themselves: "
                        + ", ".join(_spoken_path(p) for p in redone) + ".")
                if kept:
                    sentences.append(
                        "The steps that stayed as recorded: "
                        + ", ".join(_spoken_path(p) for p in kept) + ".")
            if comp:
                fig = _figures_sentence(comp["figures"])
                if fig:
                    sentences.append(fig)
            sentences.append("The Original never changes.")
        elif prov["via"] == "explain" and detail.get("explained"):
            ex = detail["explained"]
            sentences.append(
                "This What-if is one answer to the question: what "
                "went wrong?")
            parent_fig = (parent_comp or {}).get("figures", {})
            if ex["target"] in parent_fig:
                sentences.append(
                    f"On {parent}, the {_spoken_path(ex['target'])} "
                    f"came out {_spoken_num(parent_fig[ex['target']])}. "
                    f"It should have been {_spoken_num(ex['desired'])}.")
            for target, value in detail["clamped"].items():
                before = (parent_comp or {}).get("inputs", {}).get(target)
                sentences.append(
                    f"If {_spoken_path(target)} had been "
                    f"{_spoken_num(value)}"
                    + (f" instead of {_spoken_num(before)}"
                       if before is not None else "")
                    + f", the {_spoken_path(ex['target'])} comes out "
                      f"{_spoken_num(ex['desired'])}.")
            sentences.append(
                "That was re-run and checked before this What-if was "
                "made. There may be other answers; nothing was chosen "
                "for you.")
        else:
            sentences.append(f"This What-if was made from {parent}.")
            if prov["instruction"]:
                sentences.append(
                    f"The instruction written into it was: "
                    f"\u201c{prov['instruction']}\u201d")
            sentences.append(
                "It runs when this recording is reopened in a live "
                "session.")
        if comp and prov["via"] == "try-differently":
            fig = _figures_sentence(comp["figures"])
            if fig:
                sentences.append(fig)
    if not comp and prov is not None:
        steps = len(store.replay_events(branch))
        sentences.append(f"This version has {steps} steps.")
    return " ".join(sentences)


def _latest_model_call(store, branch: str) -> dict | None:
    found = None
    for ev in store.events(branch):
        if ev["kind"] == "model_call":
            found = ev
    return found


# ------------------------------------------------------------ speech out

def render_speech(text: str):
    """Speak `text` with the machine's speech engine, if it has one.

    Returns (engine_name, wav_bytes) or (None, None). The engine is
    ffmpeg's flite filter (real synthesized speech, a plain robotic
    voice — labeled as exactly that wherever it is named). Speech is
    best-effort: any failure returns (None, None) and the caller
    records the story as words only, with the reason.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None, None
    with tempfile.TemporaryDirectory(prefix="melange-narration-") as td:
        script_file = Path(td) / "story.txt"
        script_file.write_text(text)
        try:
            proc = subprocess.run(
                [ffmpeg, "-v", "error", "-f", "lavfi",
                 "-i", f"flite=textfile={script_file}:voice={VOICE}",
                 "-ar", "22050", "-f", "wav", "pipe:1"],
                capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None, None
    audio = proc.stdout
    if proc.returncode != 0 or not audio.startswith(b"RIFF"):
        return None, None
    return ENGINE_NAME, audio


def make_narration(store, branch: str) -> dict:
    """Compose the branch's story and attach its spoken track.

    Records a 'narration' event on the branch carrying the script,
    the engine's name (or None), and the audio's blob digest (or
    None). Returns {event_id, script, engine, voice, has_audio,
    audio_note}: where no engine spoke, audio_note says why, in the
    plain sentence the surface shows.
    """
    if not store.events(branch):
        raise KeyError(branch)
    ingest.require_branch_op(store, branch, "annotate")
    script = narration_script(store, branch)
    engine, audio = render_speech(script)
    blob = store.put_blob(audio) if audio else None
    event_id = store.append(branch, "narration", {
        "script": script, "engine": engine,
        "voice": VOICE if engine else None, "audio_blob": blob})
    return {"event_id": event_id, "script": script, "engine": engine,
            "voice": VOICE if engine else None,
            "has_audio": blob is not None,
            "audio_note": None if engine else NO_ENGINE_NOTE}


def narration(store, branch: str) -> dict | None:
    """The branch's latest narration, or None if it has none."""
    found = None
    for ev in store.events(branch):
        if ev["kind"] == "narration":
            p = ev["payload"] or {}
            found = {"event_id": ev["id"], "script": p.get("script", ""),
                     "engine": p.get("engine"),
                     "voice": p.get("voice"),
                     "has_audio": p.get("audio_blob") is not None}
    return found


def narration_audio(store, branch: str) -> bytes | None:
    """The spoken track's bytes (WAV), or None where there is none."""
    found = None
    for ev in store.events(branch):
        if ev["kind"] == "narration" and (ev["payload"] or {}).get("audio_blob"):
            found = ev["payload"]["audio_blob"]
    if found is None:
        return None
    return store.get_blob(found)
