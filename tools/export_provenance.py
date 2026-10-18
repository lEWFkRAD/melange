#!/usr/bin/env python3
"""Melange M6 — Door 1 exports WITH provenance.

The intent audit (M6) found that Door 1 exports were bare mp4s: the
write-up (§5) claims "the render carries that provenance with it", but
export_render.py wrote no metadata and no manifest, so an exported video
could not be traced back to the recording it came from.

This module closes that gap for screen-only (video) branches:

  export_branch(store_root, branch, out_mp4, step_range=None)
      Renders the branch's screen frames to mp4 (same approach as
      export_render.py: per-frame durations from the frames' own
      timestamps, clamped, libx264) and
        * embeds provenance in the mp4 metadata (title, and a
          branch/steps/frames-hash/head-hash string in comment +
          description — the mp4 muxer drops unknown keys, so the
          standard fields are the carrier);
        * writes a sidecar manifest (<out>.sidecar.json) listing every
          source frame's event id, md5 and byte size, the store's branch
          head hash, and the exported file's sha256.

  verify_export(mp4, sidecar, store_root) -> report dict
      Re-opens the store and proves the export traces back to exactly
      those frames:
        1. manifest binding recomputes (see SIGNING CHOICE below);
        2. the store's own hash chain verifies (store.verify);
        3. frames re-read from the store match the manifest's md5 list;
        4. the mp4 file's sha256 matches the manifest;
        5. the mp4 metadata carries the same frame-sequence hash;
        6. the mp4's decoded frame count equals the manifest's count;
        7. each source frame's segment of the video decodes to a frame
           perceptually matching the source (ffmpeg SSIM >= threshold).

SIGNING CHOICE (stated plainly): the desktop-real store was created
without a key provider — there is no store signing key to HMAC with.
The manifest "binding" is therefore
    sha256( canonical_json(manifest core) || branch head hash )
i.e. the manifest is hash-bound to the store's own hash chain tip. This
is tamper-EVIDENCE anchored in the store (the source of record): edit
the manifest, the mp4, or the store and some check above fails. It is
NOT an identity signature — anyone with the store can mint a valid
manifest for frames the store actually holds. That is the correct
guarantee for provenance: "this video is exactly these recorded frames",
not "a particular person exported it".

Verification limits (honest): mp4/H.264 is lossy, so decoded frames can
never be byte-compared to sources. Step 7 uses SSIM at the segment middle
frame with threshold 0.95 (the reference desktop export measures ~0.99).
SSIM proves perceptual identity of content, not byte identity; the byte
identity anchor is step 3 (manifest vs the store's hash-chained frames).

CLI:
  export_provenance.py export <store_root> <branch> <out.mp4> [start end]
  export_provenance.py verify <file.mp4> <sidecar.json> <store_root>
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

FPS = 30
MIN_DUR, MAX_DUR = 0.4, 4.0
SSIM_THRESHOLD = 0.95
FORMAT = "melange-export-manifest/1"


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- store side

def _open_store(store_root):
    """Open the canonical TimelineStore; fall back to the canonical tree
    location relative to this file when living_replay is not installed."""
    try:
        from living_replay.store import TimelineStore
    except ImportError:
        src = Path(__file__).resolve().parents[3] / "tree-inventory" / "lr-repo" / "src"
        sys.path.insert(0, str(src))
        from living_replay.store import TimelineStore
    return TimelineStore(store_root)


def _screen_events(store, branch: str):
    return [e for e in store.events(branch) if e["kind"] == "screen_frame"]


def _frame_rows(store, branch: str, start: int, end: int):
    """(event, frame_bytes) pairs for screen-frame steps [start, end)."""
    events = _screen_events(store, branch)
    if not (0 <= start <= end <= len(events)):
        raise ValueError(f"step range {start}..{end} outside 0..{len(events)}")
    rows = []
    for ev in events[start:end]:
        rows.append((ev, store.get_blob(ev["payload"]["blob"])))
    return rows


def _durations(rows) -> list[float]:
    ts = [float(ev["payload"].get("ts", i)) for i, (ev, _) in enumerate(rows)]
    dts = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    med = sorted(dts)[len(dts) // 2] if dts else 1.4
    dts.append(med)
    return [min(max(d, MIN_DUR), MAX_DUR) for d in dts]


def _binding(core: dict, head_hash: str) -> str:
    return sha256_hex(canonical(core) + head_hash.encode())


# ------------------------------------------------------------------- export

def export_branch(store_root, branch: str, out_mp4,
                  step_range: tuple[int, int] | None = None,
                  store=None) -> dict:
    """Export a screen-only branch (or step range) to a provenance mp4.

    Returns the manifest dict (also written to <out_mp4>.sidecar.json).
    """
    own_store = store is None
    if own_store:
        store = _open_store(store_root)
    if not store.verify(branch):
        raise ValueError(f"store.verify({branch!r}) failed — refusing to export")

    total = len(_screen_events(store, branch))
    start, end = step_range or (0, total)
    rows = _frame_rows(store, branch, start, end)
    durations = _durations(rows)
    counts = [max(1, round(d * FPS)) for d in durations]

    frames_meta = []
    seq = hashlib.sha256()
    for i, ((ev, data), cnt) in enumerate(zip(rows, counts)):
        seq.update(data)
        frames_meta.append({
            "step": start + i,
            "event_id": ev["id"],
            "md5": hashlib.md5(data).hexdigest(),
            "bytes": len(data),
            "ts": float(ev["payload"].get("ts", start + i)),
            "video_frames": cnt,
        })
    frames_sha256 = seq.hexdigest()
    head_hash = store.events(branch)[-1]["hash"]

    out_mp4 = Path(out_mp4)
    tmp = Path(tempfile.mkdtemp(prefix="melange-m6-"))
    seqdir = tmp / "seq"
    seqdir.mkdir()
    n = 0
    for i, (_, data) in enumerate(rows):
        src = tmp / f"src{i:03d}.jpg"
        src.write_bytes(data)
        for _ in range(counts[i]):
            os.link(src, seqdir / f"{n:05d}.jpg")
            n += 1
    title = f"Melange export — {branch} steps {start}-{end - 1}"
    description = (f"branch={branch}; steps={start}..{end - 1}; "
                   f"frames_sha256={frames_sha256}; head={head_hash}")
    cmd = ["ffmpeg", "-y", "-v", "error", "-framerate", str(FPS),
           "-i", str(seqdir / "%05d.jpg"),
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
           "-metadata", f"title={title}",
           "-metadata", f"description={description}",
           "-metadata", f"comment={description}",
           str(out_mp4)]
    # NOTE: ffmpeg's mp4 muxer silently drops unknown metadata keys, so
    # the melange_* fields ride inside comment/description (verified with
    # ffprobe against the reference export; see verify.log).
    subprocess.run(cmd, check=True, capture_output=True)

    file_bytes = out_mp4.read_bytes()
    core = {
        "format": FORMAT,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "store": {
            "root_name": Path(store_root).name,
            "branch": branch,
            "head_hash": head_hash,
            "verify_at_export": True,
        },
        "step_range": {"start": start, "end": end, "count": end - start},
        "fps": FPS,
        "frames": frames_meta,
        "frames_sha256": frames_sha256,
        "export_file": {
            "name": out_mp4.name,
            "sha256": sha256_hex(file_bytes),
            "bytes": len(file_bytes),
            "video_frame_count": sum(counts),
        },
    }
    manifest = {**core, "binding": _binding(core, head_hash)}
    sidecar = out_mp4.with_suffix(out_mp4.suffix + ".sidecar.json")
    sidecar.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


# ------------------------------------------------------------------- verify

def _ffprobe_tags(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags",
         "-of", "json", str(path)], check=True, capture_output=True)
    return json.loads(out.stdout).get("format", {}).get("tags", {})


def _ffprobe_frame_count(path: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True)
    return int(out.stdout.decode().strip().rstrip(","))


def _extract_frame(mp4: Path, index: int, dest: Path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp4),
         "-vf", f"select='eq(n\\,{index})'", "-vframes", "1", str(dest)],
        check=True, capture_output=True)


def _ssim(a: Path, b: Path) -> float:
    out = subprocess.run(
        ["ffmpeg", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"],
        capture_output=True)
    text = out.stderr.decode(errors="replace")
    for token in text.replace("\n", " ").split():
        if token.startswith("All:"):
            return float(token[4:])
    raise RuntimeError(f"SSIM value not found in ffmpeg output: {text[-300:]}")


def verify_export(mp4, sidecar, store_root, store=None) -> dict:
    """Prove an export traces back to exactly the frames in the store.

    Returns a report dict; report["ok"] is True only if every check passes.
    All checks run even after a failure, so the report shows which link
    in the chain broke.
    """
    mp4, sidecar = Path(mp4), Path(sidecar)
    manifest = json.loads(sidecar.read_text())
    branch = manifest["store"]["branch"]
    start = manifest["step_range"]["start"]
    end = manifest["step_range"]["end"]
    checks: dict = {}

    core = {k: v for k, v in manifest.items() if k != "binding"}
    checks["binding_ok"] = (
        _binding(core, manifest["store"]["head_hash"]) == manifest["binding"])

    own_store = store is None
    if own_store:
        store = _open_store(store_root)
    checks["store_verify_ok"] = bool(store.verify(branch))

    rows = _frame_rows(store, branch, start, end)
    now_md5 = [hashlib.md5(data).hexdigest() for _, data in rows]
    man_md5 = [f["md5"] for f in manifest["frames"]]
    seq = hashlib.sha256()
    for _, data in rows:
        seq.update(data)
    checks["store_frames_ok"] = (now_md5 == man_md5
                                 and seq.hexdigest() == manifest["frames_sha256"])
    head_now = store.events(branch)[-1]["hash"]
    checks["store_head_ok"] = head_now == manifest["store"]["head_hash"]

    checks["file_hash_ok"] = (sha256_hex(mp4.read_bytes())
                              == manifest["export_file"]["sha256"])

    tags = _ffprobe_tags(mp4)
    carrier = tags.get("comment", "") + " " + tags.get("description", "")
    checks["metadata_ok"] = (
        f"frames_sha256={manifest['frames_sha256']}" in carrier
        and f"branch={branch}" in carrier
        and f"head={manifest['store']['head_hash']}" in carrier)

    total_video = _ffprobe_frame_count(mp4)
    checks["frame_count_ok"] = (
        total_video == manifest["export_file"]["video_frame_count"]
        == sum(f["video_frames"] for f in manifest["frames"]))

    # Perceptual identity per source frame: middle decoded frame of each
    # source frame's video segment vs the store's source frame bytes.
    tmp = Path(tempfile.mkdtemp(prefix="melange-m6-verify-"))
    ssim_scores = []
    offset = 0
    for i, ((_, data), fmeta) in enumerate(zip(rows, manifest["frames"])):
        mid = offset + fmeta["video_frames"] // 2
        decoded = tmp / f"dec{i:03d}.png"
        _extract_frame(mp4, mid, decoded)
        src = tmp / f"src{i:03d}.jpg"
        src.write_bytes(data)
        ssim_scores.append(round(_ssim(decoded, src), 4))
        offset += fmeta["video_frames"]
    checks["ssim_scores"] = ssim_scores
    checks["ssim_min"] = min(ssim_scores) if ssim_scores else 0.0
    checks["ssim_ok"] = bool(ssim_scores) and checks["ssim_min"] >= SSIM_THRESHOLD

    bool_keys = [k for k, v in checks.items() if isinstance(v, bool)]
    report = {"mp4": str(mp4), "sidecar": str(sidecar), "branch": branch,
              "steps": f"{start}..{end - 1}", "checks": checks,
              "ok": all(checks[k] for k in bool_keys)}
    return report


# ---------------------------------------------------------------------- CLI

def main(argv):
    if argv[1] == "export":
        store_root, branch, out = argv[2], argv[3], argv[4]
        rng = (int(argv[5]), int(argv[6])) if len(argv) > 6 else None
        manifest = export_branch(store_root, branch, out, rng)
        print(json.dumps({"exported": out,
                          "sidecar": out + ".sidecar.json",
                          "frames": manifest["step_range"]["count"],
                          "frames_sha256": manifest["frames_sha256"],
                          "binding": manifest["binding"]}, indent=2))
        return 0
    if argv[1] == "verify":
        report = verify_export(argv[2], argv[3], argv[4])
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
