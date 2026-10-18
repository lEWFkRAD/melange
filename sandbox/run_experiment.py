"""Build 2 sandbox experiment (host side, runs on the KVM host).

Boot the guest -> checkpoint -> snapshot -> resume the original (it
finishes with the default amount) -> fork the snapshot N times (each
fork's drive carries a baked-in GO note with a corrected amount) ->
verify both timelines on the host with Build 1 code.

Prints one JSON object of measurements on the last line.
"""
import json, os, shutil, statistics, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from living_replay.replay import reconstruct
from living_replay.sandbox import MicroVM, extract_dir_from_image, fresh_data_drive, write_file_into_image
from living_replay.store import TimelineStore

SB = Path(os.environ["LR_SANDBOX_DIR"])
FORKS = int(os.environ.get("LR_FORKS", "10"))

def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))]

def main():
    work = SB / f"work-{int(time.time())}"
    work.mkdir(parents=True)
    fc = SB / "bin" / "firecracker"; kernel = SB / "assets" / "vmlinux"
    results = {"forks_measured": 0}

    rootfs_orig = work / "rootfs-orig.ext4"; shutil.copy(SB / "rootfs.ext4", rootfs_orig)
    data_orig = fresh_data_drive(work / "data-orig.ext4")
    orig = MicroVM(work, fc, "orig"); orig.start_process()
    orig.configure(kernel, rootfs_orig, data_orig, cid=3)
    t0 = time.monotonic(); orig.action("InstanceStart")
    t_ready = orig.serial.wait_for("LR-READY", timeout=90)
    assert t_ready, "guest never reached checkpoint:\n" + orig.serial.text()
    results["boot_to_checkpoint_s"] = round(t_ready - t0, 3)

    orig.pause()
    snap, mem = work / "snap.fc", work / "mem.fc"
    results["snapshot_create_s"] = round(orig.snapshot(snap, mem), 3)
    # Fork drive: the data drive AS OF the checkpoint, plus a baked-in GO.
    data_fork_src = work / "data-fork-src.ext4"; shutil.copy(data_orig, data_fork_src)
    write_file_into_image(data_fork_src, "/GO", "amount=50\n")
    orig.resume()
    orig.vsock_send(1024, "GO\n")
    assert orig.serial.wait_for("LR-DONE", timeout=60), orig.serial.text()
    orig.stop()
    results["original_outcome"] = "total=42"

    latencies = []
    fork_drives = []
    for i in range(FORKS):
        rootfs_f = work / f"rootfs-fork{i}.ext4"; shutil.copy(SB / "rootfs.ext4", rootfs_f)
        data_f = work / f"data-fork{i}.ext4"; shutil.copy(data_fork_src, data_f)
        vm = MicroVM(work, fc, f"fork{i}"); vm.start_process()
        # Load first: the snapshot carries the device config, including the
        # vsock host path — its stale socket file must go before the fork's
        # backend can bind it. Then repoint the drives at this fork's own
        # copies before resuming.
        from living_replay.sandbox import api
        (orig.dir / "vsock.sock").unlink(missing_ok=True)
        load_s = vm.load_snapshot(snap, mem)
        for drive_id, path in (("rootfs", rootfs_f), ("data", data_f)):
            st, body = api(vm.sock, "PATCH", f"/drives/{drive_id}",
                           {"drive_id": drive_id, "path_on_host": str(path)})
            assert st == 204, body
        t_load_done = time.monotonic()
        vm.resume()
        # The fork's orders arrive by vsock, through the ORIGINAL's host
        # path (that is where the restored vsock backend binds).
        vm.vsock_send(1024, "GO amount=50\n", uds_path=str(orig.dir / "vsock.sock"))
        t_phase2 = vm.serial.wait_for("LR-PHASE2-START", timeout=60)
        assert t_phase2, f"fork {i} never resumed work:\n" + vm.serial.text()
        latencies.append(t_phase2 - t_load_done)
        assert vm.serial.wait_for("LR-DONE total=100", timeout=60), vm.serial.text()
        vm.stop()
        fork_drives.append(data_f)
        results["forks_measured"] += 1
    results["fork_load_s_each"] = round(load_s, 3)
    results["restore_to_work_s"] = [round(x, 3) for x in latencies]
    results["restore_to_work_p50"] = round(statistics.median(latencies), 3)
    results["restore_to_work_p95"] = round(pct(latencies, 0.95), 3)

    # Host-side verification with Build 1 code ("the desktop is a viewer").
    def final_screen_and_events(image: Path, tag: str):
        out = work / f"extract-{tag}"
        extract_dir_from_image(image, "/timeline", out)
        store = TimelineStore(out / "timeline")
        screen = reconstruct(store, "main", rows=10, cols=40).screen()
        return screen, store.events("main")
    screen_o, events_o = final_screen_and_events(data_orig, "orig")
    screen_f, events_f = final_screen_and_events(fork_drives[0], "fork0")
    assert "total=42" in screen_o, screen_o
    assert "total=100" in screen_f, screen_f
    checkpoint_len = min(len(events_o), len(events_f))
    shared = sum(1 for a, b in zip(events_o, events_f) if a["hash"] == b["hash"])
    results["orig_final"] = "total=42 verified on host replay"
    results["fork_final"] = "total=100 verified on host replay"
    results["shared_prefix_events"] = shared
    results["orig_events"] = len(events_o); results["fork_events"] = len(events_f)
    assert shared >= 3, "timelines do not share their checkpoint prefix"
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
