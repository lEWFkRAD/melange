"""Flagship-in-guest runner (Build 3, host side): boot one microVM
whose data drive carries the RUN_FLAGSHIP flag, let the guest run the
whole synthetic-return demo inside the boundary, then verify the
extracted timeline on the host. Prints the guest's JSON summary line
plus host-side checks."""
import json, os, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from living_replay.flagship import expected_figures
from living_replay.replay import reconstruct
from living_replay.sandbox import MicroVM, extract_dir_from_image, fresh_data_drive, write_file_into_image
from living_replay.store import TimelineStore

SB = Path(os.environ["LR_SANDBOX_DIR"])

def main():
    work = SB / f"flagship-{int(time.time())}"; work.mkdir(parents=True)
    rootfs = work / "rootfs.ext4"; shutil.copy(SB / "rootfs.ext4", rootfs)
    data = fresh_data_drive(work / "data.ext4")
    write_file_into_image(data, "/RUN_FLAGSHIP", "1\n")
    vm = MicroVM(work, SB / "bin" / "firecracker", "guest"); vm.start_process()
    vm.configure(SB / "assets" / "vmlinux", rootfs, data, cid=3)
    vm.action("InstanceStart")
    assert vm.serial.wait_for("LR-FLAGSHIP-DONE", timeout=180), vm.serial.text()[-2000:]
    line = next(l for _, l in vm.serial.lines if l.startswith("LR-FLAGSHIP "))
    summary = json.loads(line.split(" ", 1)[1])
    vm.stop()
    out = work / "extract"; extract_dir_from_image(data, "/flagship-run", out)
    store = TimelineStore(out / "flagship-run" / "timeline")
    ghost = reconstruct(store, "ghost-corrected-w2", rows=12, cols=60).screen()
    exp = expected_figures(52000)
    checks = {
        "guest_totalTax": summary["totalTax"], "expected_totalTax": exp["/totalTax"],
        "guest_amended_totalTax": summary["amended_totalTax"],
        "guest_parent_unchanged": summary["parent_unchanged"],
        "guest_ripple": f"{summary['recomputed']}/{summary['graph_nodes']}",
        "wages_span_text": summary["wages_span_text"],
        "host_ghost_screen_has_amended": "AMENDED" in ghost and "3,088" in ghost,
        "host_verify_main": store.verify("main"),
    }
    assert checks["guest_totalTax"] == exp["/totalTax"]
    assert checks["guest_amended_totalTax"] == 3088.0
    assert checks["guest_parent_unchanged"] is True
    assert checks["host_ghost_screen_has_amended"] and checks["host_verify_main"]
    print(json.dumps(checks, indent=2))

if __name__ == "__main__":
    main()
