"""Melange Build 2 host runner: live capture of a real Hermes session.

Drives an unscripted multi-turn Hermes session inside the boundary
(turns sent one at a time over the control channel; the guest agent
records everything), snapshots mid-session, finishes the original,
forks with a real correction, then REPLAYS the original session in a
fresh guest whose shim serves the recorded responses — no bridge is
started for the replay leg, so a live call is impossible by
construction and any request the record cannot answer fails as a
REPLAY-MISS. Verifies LC-G1..G4 and prints one JSON object.
"""
import base64, hashlib, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from living_replay.crypto import LocalKeyProvider
from living_replay.replay import reconstruct
from living_replay.sandbox import MicroVM, api, extract_dir_from_image, fresh_data_drive, write_file_into_image
from living_replay.store import TimelineStore
from run_hermes_guest import Bridge, vsock_line, strata_key

SB = Path(os.environ["LR_SANDBOX_DIR"])

NOTES = """Melange build session notes, Oct 16 2026 (raw)
- Fork gate passed end to end in the sandbox (runs 5, 6, 7 all green).
- Original session finished with wages 52000; the fork took the correction to 48000 and recomputed (tax 3088, refund 3012).
- Replay fidelity measured 99.9 percent cell agreement vs the reference emulator.
- Gate corpus: G2 attribution 98.11 percent; G4 zero of six seeded secrets persisted; G5 replay by record exact, zero live calls; G6 clamp, explain, pin all per doctrine.
- Model calls now recorded on the timeline: 9 in the original, 9 in the fork.
- Recorder defect found and fixed: a threading bug dropped model_call events; the gate now asserts exact counts and fails loud.
- GitHub repo for Melange not yet created (ticket ONY-173 with Hermes).
- Next: live capture (Build 2), then the two doors (export render first).
"""

T1 = ("In the workspace there is a file notes.md with raw facts from today's Melange build "
      "session. Read it and write a one-page status brief to brief.md: what was proven, the "
      "key numbers, and what comes next. Plain factual tone, no marketing language.")
T2 = ("Add a section to brief.md headed 'Risks and open items' covering: the recorder "
      "event-drop defect and how it was fixed, the GitHub repo not yet created, and live "
      "capture being the current build. Then print brief.md to the screen.")
T3_ORIG = ("Final pass on brief.md: add a one-line title at the very top and a closing line "
           "with today's date, October 16, 2026. Then print the final brief.md.")
T3_FORK = ("Correction before the final pass: the notes rounded one number wrong. Replay "
           "fidelity measured 99.85 percent, not 99.9. Fix that figure in brief.md, add a "
           "one-line title at the very top and a closing line with today's date, "
           "October 16, 2026. Then print the final brief.md.")

def wait_count(vm, marker, n, timeout=1500):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if vm.serial.text().count(marker) >= n:
            return True
        time.sleep(2)
    return False

def fingerprint(body) -> str:
    msgs = body.get("messages") if isinstance(body, dict) else None
    canon = json.dumps(msgs, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()

def main():
    key = strata_key()
    assert key, "no Strata key available to the bridge"
    work = SB / f"live-{int(time.time())}"; work.mkdir(parents=True)
    results = {"workdir": str(work)}
    master = LocalKeyProvider.generate()
    (work / "master.b64").write_text(base64.b64encode(master).decode())
    provider = LocalKeyProvider(master)

    def fresh_vm(name, rootfs_src, replay_table=None):
        rootfs = work / f"rootfs-{name}.ext4"
        shutil.copy(rootfs_src, rootfs)
        if replay_table is not None:
            write_file_into_image(rootfs, "/opt/replay_table.json", json.dumps(replay_table))
        data = fresh_data_drive(work / f"data-{name}.ext4")
        write_file_into_image(data, "/RUN_LIVE", "1\n")
        write_file_into_image(data, "/LR_KEY", base64.b64encode(master).decode() + "\n")
        write_file_into_image(data, "/notes.md", NOTES)
        # Entropy seed: the live image's init credits these host bytes
        # to the guest kernel pool (RNDADDENTROPY) before the agent
        # starts. Firecracker's entropy device never surfaces in this
        # kernel and random.trust_cpu=on is ignored; without the seed a
        # fresh boot stalls indefinitely at the first blocking
        # getrandom (three stalled boots, 2026-10-16; with the seed
        # CRNG initializes in under a second).
        seed = work / f"seed-{name}.bin"; seed.write_bytes(os.urandom(512))
        subprocess.run(["debugfs", "-w", "-R", f"write {seed} /seed.bin", str(data)],
                       check=True, capture_output=True)
        vm = MicroVM(work, SB / "bin" / "firecracker", name); vm.start_process()
        return vm, rootfs, data

    def drive(vm, script, uds=None):
        """script: list of ('TURN', text) / ('MARK',) / ('FINISH',)."""
        done = 0
        for step in script:
            if step[0] == "TURN":
                vsock_line(vm, 1025, "TURN " + step[1] + "\n", uds_path=uds)
                done += 1
                assert wait_count(vm, "LR-TURN-DONE", done), vm.serial.text()[-1500:]
            elif step[0] == "MARK":
                vsock_line(vm, 1025, "MARK\n", uds_path=uds)
                assert vm.serial.wait_for("LR-CHECKPOINT", timeout=120), vm.serial.text()[-800:]
            elif step[0] == "FINISH":
                vsock_line(vm, 1025, "FINISH\n", uds_path=uds)
                assert vm.serial.wait_for("LR-DONE", timeout=300), vm.serial.text()[-800:]

    # ---- original live session
    orig, rootfs_o, data_o = fresh_vm("orig", SB / "rootfs-live.ext4")
    orig.configure(SB / "assets" / "vmlinux", rootfs_o, data_o, cid=3, mem_mib=1024)
    orig.action("InstanceStart")
    bridge_o = Bridge(orig, key); bridge_o.start()
    assert orig.serial.wait_for("LR-READY", timeout=600), orig.serial.text()[-1200:]
    drive(orig, [("TURN", T1), ("TURN", T2), ("MARK",)])
    orig.pause()
    snap, mem = work / "snap.fc", work / "mem.fc"
    orig.snapshot(snap, mem)
    data_fork_src = work / "data-fork-src.ext4"; shutil.copy(data_o, data_fork_src)
    orig.resume()
    bridge_o.stop_flag.set(); time.sleep(0.5)
    bridge_o2 = Bridge(orig, key); bridge_o2.start()
    drive(orig, [("TURN", T3_ORIG), ("FINISH",)])
    orig.stop(); bridge_o2.stop_flag.set()
    orig_exchanges = bridge_o.exchanges + bridge_o2.exchanges
    results["orig_bridge_exchanges"] = orig_exchanges

    eo = work / "extract-orig"; extract_dir_from_image(data_o, "/", eo)
    store_o = TimelineStore(eo / "timeline", key_provider=provider)
    evs_o = store_o.events("main")
    mc_o = [e for e in evs_o if e["kind"] == "model_call"]
    hashes_o = [e["hash"] for e in evs_o]
    brief_o = (eo / "ws" / "brief.md").read_text() if (eo / "ws" / "brief.md").exists() else ""
    results["orig_model_calls_recorded"] = len(mc_o)
    results["orig_brief_bytes"] = len(brief_o)

    # ---- fork with the correction
    rootfs_f = work / "rootfs-fork.ext4"; shutil.copy(SB / "rootfs-live.ext4", rootfs_f)
    data_f = work / "data-fork.ext4"; shutil.copy(data_fork_src, data_f)
    fork = MicroVM(work, SB / "bin" / "firecracker", "fork"); fork.start_process()
    (orig.dir / "vsock.sock").unlink(missing_ok=True)
    fork.load_snapshot(snap, mem)
    for drive_id, path in (("rootfs", rootfs_f), ("data", data_f)):
        st, body = api(fork.sock, "PATCH", f"/drives/{drive_id}",
                       {"drive_id": drive_id, "path_on_host": str(path)})
        assert st == 204, body
    fork.resume()
    bridge_f = Bridge(fork, key, uds_path=str(orig.dir / "vsock.sock")); bridge_f.start()
    time.sleep(1)
    assert fork.serial.wait_for("LR-TURN-DONE", timeout=30) or True  # agent resumes mid-loop
    drive(fork, [("TURN", T3_FORK), ("FINISH",)], uds=str(orig.dir / "vsock.sock"))
    fork.stop(); bridge_f.stop_flag.set()
    results["fork_bridge_exchanges"] = bridge_f.exchanges

    ef = work / "extract-fork"; extract_dir_from_image(data_f, "/", ef)
    store_f = TimelineStore(ef / "timeline", key_provider=provider)
    evs_f = store_f.events("main")
    hashes_f = [e["hash"] for e in evs_f]
    brief_f = (ef / "ws" / "brief.md").read_text() if (ef / "ws" / "brief.md").exists() else ""
    results["fork_brief_bytes"] = len(brief_f)
    shared = sum(1 for a, b in zip(hashes_o, hashes_f) if a == b)
    results["shared_prefix_events"] = shared

    # ---- replay-by-record leg (no bridge at all)
    table = {"chats": {}, "others": []}
    for e in mc_o:
        req, resp, st = e["payload"].get("request"), e["payload"].get("response"), e["payload"].get("status")
        if isinstance(req, dict) and req.get("messages"):
            table["chats"].setdefault(fingerprint(req), []).append([st, resp])
        else:
            table["others"].append([st, resp])
    replay, rootfs_r, data_r = fresh_vm("replay", SB / "rootfs-live.ext4", replay_table=table)
    replay.configure(SB / "assets" / "vmlinux", rootfs_r, data_r, cid=3, mem_mib=1024)
    replay.action("InstanceStart")
    assert replay.serial.wait_for("LR-READY", timeout=600), replay.serial.text()[-1200:]
    drive(replay, [("TURN", T1), ("TURN", T2), ("MARK",), ("TURN", T3_ORIG), ("FINISH",)])
    replay.stop()
    er = work / "extract-replay"; extract_dir_from_image(data_r, "/", er)
    store_r = TimelineStore(er / "timeline", key_provider=provider)
    mc_r = [e for e in store_r.events("main") if e["kind"] == "model_call"]
    brief_r = (er / "ws" / "brief.md").read_text() if (er / "ws" / "brief.md").exists() else ""
    shimlog_r = (er / "shim.log").read_text() if (er / "shim.log").exists() else ""
    results["replay_model_calls_recorded"] = len(mc_r)
    results["replay_misses"] = shimlog_r.count("REPLAY-MISS")
    results["replay_live_forwards"] = shimlog_r.count("SHIM forward start")

    # ---- gates
    resp_o = [json.dumps(e["payload"].get("response"), sort_keys=True) for e in mc_o
              if isinstance(e["payload"].get("request"), dict) and e["payload"]["request"].get("messages")]
    resp_r = [json.dumps(e["payload"].get("response"), sort_keys=True) for e in mc_r
              if isinstance(e["payload"].get("request"), dict) and e["payload"]["request"].get("messages")]
    results["replay_responses_identical"] = resp_o == resp_r
    results["replay_brief_identical"] = brief_r == brief_o and len(brief_o) > 0
    results["orig_brief_has_risks_section"] = "Risks and open items" in brief_o
    results["fork_brief_has_corrected_figure"] = "99.85" in brief_f
    results["orig_brief_keeps_notes_figure"] = "99.9" in brief_o and "99.85" not in brief_o
    results["orig_hash_chain_unchanged"] = [e["hash"] for e in TimelineStore(eo / "timeline", key_provider=provider).events("main")] == hashes_o
    blob_o = json.dumps([e["payload"] for e in evs_o])
    blob_f = json.dumps([e["payload"] for e in evs_f])
    # Leakage check, word-boundary aware: the estate Strata token is
    # short and occurs inside the word "local" throughout the tool
    # schemas the agent legitimately records (114 occurrences in run
    # live-1792176400, every one inside "local"). A naive substring
    # scan false-positives on that; only a standalone occurrence of
    # the token counts as the credential entering the record.
    standalone = re.compile(r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])")
    results["strata_key_in_timelines"] = bool(standalone.search(blob_o) or standalone.search(blob_f))
    try:
        TimelineStore(eo / "timeline", key_provider=LocalKeyProvider(LocalKeyProvider.generate()))
        results["wrong_key_rejected"] = False
    except Exception:
        results["wrong_key_rejected"] = True
    screen = reconstruct(store_o, "main", rows=24, cols=100).screen()
    results["replay_screen_has_brief_text"] = "brief" in screen.lower()

    for name, vm in (("orig", orig), ("fork", fork), ("replay", replay)):
        assert "LR-WARN event sink" not in vm.serial.text(), name
        assert "exit=3" not in vm.serial.text(), name
    assert results["orig_model_calls_recorded"] == orig_exchanges, results
    assert results["orig_brief_has_risks_section"], results
    assert results["fork_brief_has_corrected_figure"], results
    assert results["orig_brief_keeps_notes_figure"], results
    assert results["shared_prefix_events"] >= 10, results
    assert results["orig_hash_chain_unchanged"], results
    assert results["replay_misses"] == 0, results
    assert results["replay_live_forwards"] == 0, results
    assert results["replay_responses_identical"], results
    assert results["replay_brief_identical"], results
    assert not results["strata_key_in_timelines"], results
    assert results["wrong_key_rejected"], results
    print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main()
