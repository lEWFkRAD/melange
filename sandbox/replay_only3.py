#!/usr/bin/env python3
"""Replay-leg salvage run v3 for Melange Build 2 (tree live-1792176400).

Orig + fork legs of the full runner completed and were verified from
their extracts (108-event shared prefix, chains verify, fork brief
99.85-only, orig brief 99.9-only). The replay guest stalled at boot in
three attempts: Firecracker's entropy device does not surface in this
kernel (PUT /entropy accepted, no device registers, CRNG never
initializes) and random.trust_cpu=on has no effect. The live image
(rootfs-live.ext4) therefore carries an init that credits host-written
/data/seed.bin into the kernel pool via RNDADDENTROPY before any agent
starts. This script boots ONLY the replay guest on that image, with
the runner's own replay table (copied out of rootfs-replay.ext4),
drives the same turns, and runs the replay assertions.
"""
import base64, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, "/home/kip/lr-repo/src")
sys.path.insert(0, "/home/kip/lr-repo/sandbox")
from living_replay.crypto import LocalKeyProvider
from living_replay.sandbox import (MicroVM, extract_dir_from_image,
                                   fresh_data_drive, write_file_into_image)
from living_replay.store import TimelineStore
from run_hermes_guest import vsock_line
from run_live_guest import NOTES, T1, T2, T3_ORIG

SB = Path(os.environ["LR_SANDBOX_DIR"])
work = Path("/home/kip/lr-sandbox/live-1792176400")
master = (work / "master.b64").read_text().strip()

# The runner's replay table, byte for byte, out of the first replay rootfs.
subprocess.run(["debugfs", "-R", "dump /opt/replay_table.json /tmp/replay_table.json",
                str(work / "rootfs-replay.ext4")], check=True, capture_output=True)
table = Path("/tmp/replay_table.json").read_text()

rootfs = work / "rootfs-replay3.ext4"
shutil.copy2(SB / "rootfs-live.ext4", rootfs)
write_file_into_image(rootfs, "/opt/replay_table.json", table)

seed = Path("/tmp/seed.bin")
seed.write_bytes(os.urandom(512))
data = fresh_data_drive(work / "data-replay3.ext4")
write_file_into_image(data, "/RUN_LIVE", "1\n")
write_file_into_image(data, "/LR_KEY", master + "\n")
write_file_into_image(data, "/notes.md", NOTES)
subprocess.run(["debugfs", "-w", "-R", "write /tmp/seed.bin /seed.bin", str(data)],
               check=True, capture_output=True)

vm = MicroVM(work, SB / "bin" / "firecracker", "replay3")
vm.start_process()
vm.configure(SB / "assets" / "vmlinux", rootfs, data, cid=3, mem_mib=1024)
vm.action("InstanceStart")
t0 = time.time()
assert vm.serial.wait_for("LR-READY", timeout=600), vm.serial.text()[-800:]
ready_s = time.time() - t0
m = re.search(r"\[\s*([\d.]+)\] random: crng init done", vm.serial.text())
crng_guest_s = float(m.group(1)) if m else None


def cmd(text):
    vsock_line(vm, 1025, text + "\n")


def wait_count(marker, n, timeout=1500):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vm.serial.text().count(marker) >= n:
            return True
        time.sleep(2)
    return False


cmd("TURN " + T1); assert wait_count("LR-TURN-DONE", 1), vm.serial.text()[-800:]
cmd("TURN " + T2); assert wait_count("LR-TURN-DONE", 2), vm.serial.text()[-800:]
cmd("MARK"); assert vm.serial.wait_for("LR-CHECKPOINT", timeout=120)
cmd("TURN " + T3_ORIG); assert wait_count("LR-TURN-DONE", 3), vm.serial.text()[-800:]
cmd("FINISH"); assert vm.serial.wait_for("LR-DONE", timeout=300)
serial = vm.serial.text()
vm.stop()

ext = work / "extract-replay3"
extract_dir_from_image(data, "/", ext)
shim = (ext / "shim.log").read_text(errors="replace")


def load(name):
    store = TimelineStore(work / name / "timeline",
                          key_provider=LocalKeyProvider(base64.b64decode(master)))
    return store.events("main")


def chat_resps(events):
    out = []
    for e in events:
        p = e.get("payload") or {}
        req = p.get("request")
        if e.get("kind") == "model_call" and isinstance(req, dict) and "messages" in req:
            out.append(p.get("response"))
    return out


eo = load("extract-orig")
er = load("extract-replay3")
brief_o = (work / "extract-orig" / "ws" / "brief.md").read_bytes()
brief_r = (ext / "ws" / "brief.md").read_bytes()
out = {
    "lr_ready_wall_s": round(ready_s, 1),
    "crng_guest_s": crng_guest_s,
    "replay_events": len(er),
    "replay_model_calls": sum(1 for e in er if e.get("kind") == "model_call"),
    "replay_misses": shim.count("REPLAY-MISS"),
    "forward_starts": shim.count("SHIM forward start"),
    "replay_serves": shim.count("SHIM replay serve"),
    "chat_responses_equal": chat_resps(eo) == chat_resps(er),
    "brief_bytes_equal": brief_r == brief_o,
    "serial_clean": ("LR-WARN event sink" not in serial and "exit=3" not in serial
                     and "LR-WARN entropy seed failed" not in serial),
}
print(json.dumps(out, indent=2))
assert out["replay_misses"] == 0 and out["forward_starts"] == 0
assert out["chat_responses_equal"] and out["brief_bytes_equal"] and out["serial_clean"]
print("REPLAY LEG: ALL ASSERTIONS PASS")
