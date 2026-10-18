"""Melange M5 host runner: fork resumption into a live session.

Takes a recorded session store (default: the Build 2 live run tree),
forks a branch at its pinned mid-session checkpoint, snapshots the
checkpoint-time workspace onto the branch, then boots a FRESH sandbox
guest whose data drive carries the store and the restored workspace.
The guest's resume agent runs a real Hermes session that appends onto
the forked branch — the "Reopen in a live session" path. Afterwards
the extracted store is checked with living_replay.resume.verify_resume
against baselines recorded BEFORE the guest booted:

  (a) the branch's pre-resume prefix is byte-identical,
  (b) the continuation seals on the branch's hash chain (ancestry-wide),
  (c) the parent branch is untouched,

plus content checks: the resumed workspace is the checkpoint brief
(99.9 figure, no final title) with the new section appended, and the
Strata credential appears nowhere in a credential context (the bare
word scan is reported, not asserted — see the note at the check).
Prints one JSON object.

Env: LR_SANDBOX_DIR (required), LR_RUN_TREE (Build 2 run tree),
LR_RESUME_ROOTFS (default $LR_SANDBOX_DIR/rootfs-resume.ext4),
LR_M5_WORK (default $LR_SANDBOX_DIR/resume-<ts>).
"""
import base64, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from living_replay import resume as resume_lib
from living_replay.crypto import LocalKeyProvider
from living_replay.forking import snapshot_workspace
from living_replay.sandbox import MicroVM, extract_dir_from_image
from living_replay.store import TimelineStore
from run_hermes_guest import Bridge, vsock_line, strata_key

SB = Path(os.environ["LR_SANDBOX_DIR"])
RUN_TREE = Path(os.environ.get("LR_RUN_TREE", "/home/kip/lr-sandbox/live-1792176400"))
ROOTFS = Path(os.environ.get("LR_RESUME_ROOTFS", str(SB / "rootfs-resume.ext4")))
BRANCH = os.environ.get("LR_RESUME_BRANCH", "reopen")

RT1 = ("This session was reopened from a mid-session checkpoint. The workspace "
       "holds brief.md and notes.md as they were at that checkpoint. Read "
       "brief.md, then append one new section at the very end of brief.md "
       "headed 'Resumed session' that says the session was reopened live from "
       "the checkpoint and names one next step the brief lists. Do not change "
       "anything else in the file.")
RT2 = "Print brief.md to the screen."

def wait_count(vm, marker, n, timeout=1500):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vm.serial.text().count(marker) >= n:
            return True
        time.sleep(2)
    return False

def build_data_image(stage: Path, image: Path) -> None:
    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
    image.parent.mkdir(parents=True, exist_ok=True)
    with open(image, "wb") as f:
        f.truncate(max(512 * 1024 * 1024, size * 3 + 128 * 1024 * 1024))
    subprocess.run(["mkfs.ext4", "-q", "-d", str(stage), "-F", str(image)],
                   check=True, capture_output=True)

def main():
    key = strata_key()
    assert key, "no Strata key available to the bridge"
    assert ROOTFS.exists(), f"resume rootfs missing: {ROOTFS}"
    work = Path(os.environ.get("LR_M5_WORK", str(SB / f"resume-{int(time.time())}")))
    work.mkdir(parents=True, exist_ok=True)
    results: dict = {"workdir": str(work), "run_tree": str(RUN_TREE), "branch": BRANCH}
    master_b64 = (RUN_TREE / "master.b64").read_text().strip()
    master = base64.b64decode(master_b64)
    provider = LocalKeyProvider(master)

    # ---- prepare the store: fork at the pinned checkpoint, snapshot
    # the checkpoint-time workspace onto the branch, plan the resume.
    store_dir = work / "store"
    shutil.copytree(RUN_TREE / "extract-orig" / "timeline", store_dir)
    for p in store_dir.rglob("*"):
        p.chmod(0o644 if p.is_file() else 0o755)
    store = TimelineStore(store_dir, key_provider=provider)
    evs = store.events("main")
    ckpts = [e for e in evs if e["kind"] == "context_note"
             and e["payload"].get("pinned") and e["payload"].get("text") == "checkpoint"]
    assert len(ckpts) == 1, f"expected one pinned checkpoint, got {len(ckpts)}"
    ckpt = ckpts[0]["id"]
    results["checkpoint_event"] = ckpt
    results["parent_events_before"] = len(evs)
    parent_state = resume_lib.capture_branch_state(store, "main")

    ws_extract = work / "ws-checkpoint"
    extract_dir_from_image(RUN_TREE / "data-fork-src.ext4", "/ws", ws_extract)
    ws_src = ws_extract / "ws"  # rdump nests the source dir under the dest
    brief_ckpt = (ws_src / "brief.md").read_text()
    results["checkpoint_brief_bytes"] = len(brief_ckpt)

    fork_id = store.fork("main", ckpt, BRANCH,
                         edit={"intent": "reopen in a live session", "milestone": "M5"})
    results["fork_event"] = fork_id
    snap_id = snapshot_workspace(store, BRANCH, ws_src)
    results["workspace_snapshot_event"] = snap_id
    plan = resume_lib.plan_resume(store, BRANCH, ckpt)
    assert plan.workspace_snapshot_event == snap_id, plan
    results["prefix_events"] = len(plan.prefix_ids)
    baseline = {"plan": plan.to_dict(), "parents": {"main": parent_state}}
    (work / "baseline.json").write_text(json.dumps(baseline, indent=1))

    # ---- stage the guest data drive from the plan
    stage = work / "stage"
    store.db.execute("PRAGMA wal_checkpoint(TRUNCATE)"); store.db.close()
    shutil.copytree(store_dir, stage / "timeline")
    restored = resume_lib.prepare_workspace(
        TimelineStore(store_dir, key_provider=provider), plan, stage / "ws")
    assert restored is not None
    (stage / "RUN_RESUME").write_text("1\n")
    (stage / "RESUME_BRANCH").write_text(BRANCH + "\n")
    (stage / "RESUME_CHECKPOINT").write_text(str(ckpt) + "\n")
    (stage / "LR_KEY").write_text(master_b64 + "\n")
    (stage / "seed.bin").write_bytes(os.urandom(512))
    data = work / "data-resume.ext4"
    build_data_image(stage, data)
    rootfs = work / "rootfs-resume.ext4"; shutil.copy(ROOTFS, rootfs)

    # ---- boot the resume guest and drive a short live continuation
    vm = MicroVM(work, SB / "bin" / "firecracker", "resume"); vm.start_process()
    vm.configure(SB / "assets" / "vmlinux", rootfs, data, cid=3, mem_mib=1024)
    vm.action("InstanceStart")
    bridge = Bridge(vm, key); bridge.start()
    assert vm.serial.wait_for("LR-READY", timeout=600), vm.serial.text()[-1200:]
    assert "LR-ERROR" not in vm.serial.text(), vm.serial.text()[-1200:]
    for i, turn in enumerate((RT1, RT2), start=1):
        vsock_line(vm, 1025, "TURN " + turn + "\n")
        assert wait_count(vm, "LR-TURN-DONE", i), vm.serial.text()[-1500:]
    vsock_line(vm, 1025, "FINISH\n")
    assert vm.serial.wait_for("LR-DONE", timeout=300), vm.serial.text()[-800:]
    vm.stop(); bridge.stop_flag.set()
    results["bridge_exchanges"] = bridge.exchanges
    results["serial_clean"] = "LR-WARN event sink" not in vm.serial.text()

    # ---- verify from the extracted store against the pre-boot baseline
    ext = work / "extract-resume"; extract_dir_from_image(data, "/", ext)
    after = TimelineStore(ext / "timeline", key_provider=provider)
    plan2 = resume_lib.ResumePlan.from_dict(baseline["plan"])
    report = resume_lib.verify_resume(after, plan2, parents=baseline["parents"])
    results["verify"] = report
    logical = after.replay_events(BRANCH)
    results["branch_logical_events_after"] = len(logical)
    results["parent_events_after"] = len(after.events("main"))
    brief_after = (ext / "ws" / "brief.md").read_text()
    results["brief_bytes_after"] = len(brief_after)
    results["brief_keeps_checkpoint_figure"] = "99.9" in brief_after and "99.85" not in brief_after
    results["brief_gained_resumed_section"] = "Resumed session" in brief_after
    blob = json.dumps([e["payload"] for e in logical])
    standalone = re.compile(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])")
    results["strata_key_standalone_word_matches"] = len(standalone.findall(blob))
    # The current estate key is a 5-character string that is also an
    # ordinary word Hermes's own tool schemas use throughout (the same
    # standalone matches exist in the ORIGINAL Build 2 events: "local
    # session DB", "deliver='local'", ...), so a bare substring scan
    # cannot indict the record. The check that can: the credential in
    # a credential context (a Bearer header, an api_key field). The
    # shim never sees the key and headers are never recorded, so any
    # such occurrence would be a real leak; word matches are reported
    # above for honesty, not asserted on.
    cred_ctx = re.compile(r"(Bearer\s+" + re.escape(key) + r"|Authorization|api_key)")
    results["strata_key_credential_context"] = bool(cred_ctx.search(blob))
    try:
        TimelineStore(ext / "timeline", key_provider=LocalKeyProvider(LocalKeyProvider.generate()))
        results["wrong_key_rejected"] = False
    except Exception:
        results["wrong_key_rejected"] = True

    assert report["ok"], report
    assert results["serial_clean"], results
    assert results["brief_keeps_checkpoint_figure"], results
    assert results["brief_gained_resumed_section"], results
    assert not results["strata_key_credential_context"], results
    assert results["wrong_key_rejected"], results
    print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main()
