#!/usr/bin/env python3
"""Melange Door 1 (ONY-169): export a recorded session as ordinary video.

Reads a captured timeline (screen stream: terminal_chunk + grid_keyframe
events), reconstructs the terminal screen at each screen-changing event,
renders frames with PIL, and encodes an mp4 with ffmpeg. Frame durations
come from the events' own monotonic timestamps, clamped for watchability.

Usage: export_render.py <tree_dir> <extract_name> <out.mp4> [rows cols]
"""
import base64
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/home/kip/lr-repo/src")
from living_replay.crypto import LocalKeyProvider
from living_replay.replay import reconstruct
from living_replay.store import TimelineStore

from PIL import Image, ImageDraw, ImageFont

tree = Path(sys.argv[1])
extract = sys.argv[2]
out = Path(sys.argv[3])
rows = int(sys.argv[4]) if len(sys.argv) > 4 else 24
cols = int(sys.argv[5]) if len(sys.argv) > 5 else 100

master = (tree / "master.b64").read_text().strip()
store = TimelineStore(tree / extract / "timeline",
                      key_provider=LocalKeyProvider(base64.b64decode(master)))
events = store.events("main")
screen_events = [e for e in events if e["kind"] in ("terminal_chunk", "grid_keyframe")]
print(f"timeline events: {len(events)}; screen events: {len(screen_events)}")

frames = []  # (text, duration_s)
for i, e in enumerate(screen_events):
    grid = reconstruct(store, "main", through=e["id"], rows=rows, cols=cols)
    text = grid.screen()
    if i + 1 < len(screen_events):
        dt = (screen_events[i + 1]["mono_ns"] - e["mono_ns"]) / 1e9
    else:
        dt = 2.0
    dt = min(max(dt, 0.2), 4.0)
    if frames and frames[-1][0] == text:
        frames[-1] = (text, frames[-1][1] + dt)
    else:
        frames.append((text, dt))
print(f"distinct frames: {len(frames)}; total duration: {sum(d for _, d in frames):.1f}s")

font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 15)
cell_w = font.getbbox("M")[2]
cell_h = 19
W, H = cols * cell_w + 16, rows * cell_h + 16

tmp = Path(tempfile.mkdtemp(prefix="melange-export-"))
concat = []
for i, (text, dur) in enumerate(frames):
    img = Image.new("RGB", (W, H), (11, 14, 20))
    d = ImageDraw.Draw(img)
    for r, line in enumerate(text.split("\n")[:rows]):
        d.text((8, 8 + r * cell_h), line, font=font, fill=(214, 222, 235))
    p = tmp / f"f{i:04d}.png"
    img.save(p)
    concat.append(f"file '{p}'\nduration {dur:.3f}")
concat.append(f"file '{tmp / f'f{len(frames) - 1:04d}.png'}'")
(tmp / "concat.txt").write_text("\n".join(concat))
subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "concat.txt"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out)],
               check=True, capture_output=True)
print("wrote", out, out.stat().st_size, "bytes")
