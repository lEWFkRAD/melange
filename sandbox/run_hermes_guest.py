"""Build 4 host runner: a real Hermes session inside the boundary.

Boots the hermes rootfs, bridges its model pipe to Strata (the bridge
holds the API key, read from Strata's own config; it never enters the
guest or the record), snapshots at Hermes's phase-1 checkpoint, resumes
the original to finish at wages 52000, forks the snapshot with the
reviewer's correction (48000), then verifies the extracted encrypted
timelines on the host. Prints one JSON object of gate evidence.
"""
import base64, json, os, socket, struct, subprocess, sys, threading, time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from living_replay.crypto import LocalKeyProvider, TimelineKeyError
from living_replay.flagship import expected_figures
from living_replay.replay import reconstruct
from living_replay.sandbox import MicroVM, api, extract_dir_from_image, fresh_data_drive, write_file_into_image
from living_replay.store import TimelineStore

SB = Path(os.environ["LR_SANDBOX_DIR"])
STRATA_CONFIG = "/etc/onyx-inference/strata-server-huihui.json"
STRATA_URL = "http://127.0.0.1:8002"

def strata_key() -> str:
    out = subprocess.run(["sudo", "python3", "-c",
                          "import json;c=json.load(open('" + STRATA_CONFIG + "'));"
                          "print(c.get('api_key') or (c.get('compatibility_api_keys') or [''])[0])"],
                         capture_output=True, text=True)
    return out.stdout.strip()

def _send(sock, obj):
    raw = json.dumps(obj).encode()
    sock.sendall(struct.pack(">I", len(raw)) + raw)

class _Framed:
    """Length-prefixed reader that survives socket timeouts: partial
    frames stay buffered instead of desynchronizing the stream."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def _fill(self, n, stop_flag):
        while len(self.buf) < n:
            if stop_flag.is_set():
                raise ConnectionError("bridge stopped")
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("pipe closed")
            self.buf += chunk

    def read_msg(self, stop_flag):
        self._fill(4, stop_flag)
        (n,) = struct.unpack(">I", self.buf[:4])
        self.buf = self.buf[4:]
        self._fill(n, stop_flag)
        raw, self.buf = self.buf[:n], self.buf[n:]
        return json.loads(raw)

def _recv(sock):
    head = b""
    while len(head) < 4:
        chunk = sock.recv(4 - len(head))
        if not chunk: raise ConnectionError("pipe closed")
        head += chunk
    (n,) = struct.unpack(">I", head)
    raw = b""
    while len(raw) < n:
        chunk = sock.recv(n - len(raw))
        if not chunk: raise ConnectionError("pipe closed")
        raw += chunk
    return json.loads(raw)


def _collapse_body(raw: bytes):
    """Collapse an upstream reply body to one completion dict.

    The guest asks with stream=true, so Strata answers with an SSE chunk
    stream; json.loads on that stream used to kill this bridge thread
    silently, which hung the in-guest shim and surfaced only as a model
    timeout. Non-SSE bodies pass through as parsed JSON.
    """
    text = raw.decode("utf-8", "replace")
    if not text.lstrip().startswith("data:"):
        return json.loads(text)
    completion = None
    content, tool_calls, finish, usage = "", {}, None, None
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        if completion is None:
            completion = {"id": chunk.get("id"), "object": "chat.completion",
                          "created": chunk.get("created"), "model": chunk.get("model")}
        if chunk.get("usage"):
            usage = chunk["usage"]
        for ch in chunk.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("content"):
                content += d["content"]
            for tc in d.get("tool_calls") or []:
                slot = tool_calls.setdefault(tc.get("index", 0),
                    {"id": tc.get("id"), "type": "function",
                     "function": {"name": "", "arguments": ""}})
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]
                if tc.get("id"):
                    slot["id"] = tc["id"]
            if ch.get("finish_reason"):
                finish = ch["finish_reason"]
    if completion is None:
        raise ValueError("empty SSE stream")
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = [tool_calls[k] for k in sorted(tool_calls)]
    completion["choices"] = [{"index": 0, "message": msg,
                              "finish_reason": finish or "stop"}]
    if usage:
        completion["usage"] = usage
    return completion

class Bridge(threading.Thread):
    """One VM's model pipe: guest shim <-> Strata, key added here."""
    def __init__(self, vm: MicroVM, key: str, uds_path: str | None = None):
        super().__init__(daemon=True)
        self.vm, self.key, self.uds_path = vm, key, uds_path
        self.exchanges = 0
        self.stop_flag = threading.Event()
    def run(self):
        uds = self.uds_path or str(self.vm.dir / "vsock.sock")
        logf = open(self.vm.dir / "bridge.log", "a", buffering=1)

        def _connect():
            # The guest shim needs seconds to come up; retry the CONNECT
            # until it accepts (an early attempt is refused with an empty
            # ack while no guest listener exists yet).
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline and not self.stop_flag.is_set():
                sock = None
                try:
                    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    sock.connect(uds)
                    sock.sendall(b"CONNECT 1024\n")
                    ack = sock.recv(64)
                    if b"OK" in ack:
                        sock.settimeout(1.0)
                        return sock
                    sock.close()
                except OSError:
                    if sock: sock.close()
                time.sleep(0.5)
            return None

        sock = _connect()
        if sock is None:
            (self.vm.dir / "bridge.log").write_text("BRIDGE connect FAILED after 180s\n")
            raise RuntimeError("bridge could not connect to the guest shim")
        logf.write(f"BRIDGE connected uds={uds}\n")
        while not self.stop_flag.is_set():
            if sock is None:
                sock = _connect()
                if sock is None:
                    logf.write("BRIDGE reconnect FAILED\n")
                    break
                logf.write("BRIDGE reconnected\n")
            reader = _Framed(sock)
            try:
                while not self.stop_flag.is_set():
                    req = reader.read_msg(self.stop_flag)
                    status, payload = self._exchange(req)
                    logf.write(f"BRIDGE exchange {self.exchanges} path={req.get('path')} status={status}\n")
                    _send(sock, {"status": status, "body": payload})
            except (ConnectionError, OSError) as e:
                logf.write(f"BRIDGE link lost: {e}; will reconnect\n")
                try: sock.close()
                except OSError: pass
                sock = None
        try:
            if sock: sock.close()
        except OSError: pass

    def _exchange(self, req):
        if True:
            body = req.get("body")
            raw = json.dumps(body).encode() if not isinstance(body, (bytes, str)) else (
                body if isinstance(body, bytes) else body.encode())
            http = urllib.request.Request(STRATA_URL + req.get("path", "/v1/chat/completions"),
                                          data=raw, method="POST",
                                          headers={"Content-Type": "application/json",
                                                   "Authorization": f"Bearer {self.key}"})
            try:
                with urllib.request.urlopen(http, timeout=600) as resp:
                    payload, status = _collapse_body(resp.read()), resp.status
            except urllib.error.HTTPError as e:
                try:
                    payload = _collapse_body(e.read() or b"{}")
                except Exception:
                    payload = {"error": "upstream http error body unparseable"}
                status = e.code
            except Exception as e:
                print(f"BRIDGE-ERROR: {type(e).__name__}: {e}",
                      file=sys.stderr, flush=True)
                payload = {"error": f"bridge: {type(e).__name__}: {e}"}
                status = 502
            self.exchanges += 1
            return status, payload

def vsock_line(vm: MicroVM, port: int, line: str, uds_path: str | None = None):
    uds = uds_path or str(vm.dir / "vsock.sock")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.settimeout(10)
    s.connect(uds); s.sendall(f"CONNECT {port}\n".encode())
    ack = s.recv(64)
    if b"OK" not in ack: raise RuntimeError(f"connect {port} refused: {ack!r}")
    s.sendall(line.encode()); s.close()

def parse_return(text: str) -> dict[str, float]:
    out = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            try: out[k.strip()] = float(v.strip())
            except ValueError: pass
    return out

def main():
    key = strata_key()
    assert key, "no Strata key available to the bridge"
    work = SB / f"hermes-{int(time.time())}"; work.mkdir(parents=True)
    results = {}
    master = LocalKeyProvider.generate()
    (work / "master.b64").write_text(base64.b64encode(master).decode())
    provider = LocalKeyProvider(master)

    def fresh_vm(name: str, rootfs_src: Path, run_flag: bool = True):
        rootfs = work / f"rootfs-{name}.ext4"; 
        import shutil; shutil.copy(rootfs_src, rootfs)
        data = fresh_data_drive(work / f"data-{name}.ext4")
        if run_flag:
            write_file_into_image(data, "/RUN_HERMES", "1\n")
            # Synthetic-run key delivery: the timeline master key rides
            # the data drive as a boot file (the guest's provider wraps a
            # fresh DEK with it). It is not part of the timeline itself —
            # the leakage scan below checks the timeline dir specifically.
            write_file_into_image(data, "/LR_KEY", base64.b64encode(master).decode() + "\n")
        vm = MicroVM(work, SB / "bin" / "firecracker", name); vm.start_process()
        return vm, rootfs, data

    # ---- original session
    orig, rootfs_o, data_o = fresh_vm("orig", SB / "rootfs-hermes.ext4")
    orig.configure(SB / "assets" / "vmlinux", rootfs_o, data_o, cid=3, mem_mib=1024)
    orig.action("InstanceStart")
    bridge_o = Bridge(orig, key); bridge_o.start()
    assert orig.serial.wait_for("LR-CHECKPOINT", timeout=1500), orig.serial.text()[-1500:]
    results["phase1_serial"] = next(l for _, l in orig.serial.lines if "LR-CHECKPOINT" in l)
    orig.pause()
    snap, mem = work / "snap.fc", work / "mem.fc"
    orig.snapshot(snap, mem)
    import shutil
    data_fork_src = work / "data-fork-src.ext4"; shutil.copy(data_o, data_fork_src)
    orig.resume()
    # The snapshot/restore kills the guest shim's pipe (its next forward
    # fails ENOTCONN and re-accepts). The pre-snapshot bridge's stream is
    # silently dead on this side too, so restart the bridge: the fresh
    # connection waits in the shim listener's backlog and the shim's
    # retry-accept picks it up.
    bridge_o.stop_flag.set()
    time.sleep(0.5)
    bridge_o2 = Bridge(orig, key); bridge_o2.start()
    vsock_line(orig, 1025, "GO\n")
    assert orig.serial.wait_for("LR-DONE", timeout=1500), orig.serial.text()[-1500:]
    orig.stop(); bridge_o2.stop_flag.set()
    results["orig_done_serial"] = next(l for _, l in orig.serial.lines if "LR-DONE" in l)
    results["orig_model_exchanges"] = bridge_o.exchanges + bridge_o2.exchanges

    # ---- fork with the correction
    rootfs_f = work / "rootfs-fork.ext4"; shutil.copy(SB / "rootfs-hermes.ext4", rootfs_f)
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
    vsock_line(fork, 1025, "GO correct\n", uds_path=str(orig.dir / "vsock.sock"))
    assert fork.serial.wait_for("LR-DONE", timeout=1500), fork.serial.text()[-1500:]
    fork.stop(); bridge_f.stop_flag.set()
    results["fork_done_serial"] = next(l for _, l in fork.serial.lines if "LR-DONE" in l)
    results["fork_model_exchanges"] = bridge_f.exchanges

    # ---- host-side verification from the extracted drives
    def load(image: Path, tag: str):
        out = work / f"extract-{tag}"
        extract_dir_from_image(image, "/", out)
        return out
    eo = load(data_o, "orig"); ef = load(data_f, "fork")
    ret_o = parse_return((eo / "ws" / "return.txt").read_text()) if (eo / "ws" / "return.txt").exists() else {}
    ret_f = parse_return((ef / "ws" / "return.txt").read_text()) if (ef / "ws" / "return.txt").exists() else {}
    exp_o, exp_f = expected_figures(52000), expected_figures(48000)
    results["orig_return"] = ret_o; results["fork_return"] = ret_f
    results["orig_figures_match"] = (ret_o.get("wages") == 52000
                                     and abs(ret_o.get("total_tax", -1) - exp_o["/totalTax"]) < 0.01)
    results["fork_figures_match"] = (ret_f.get("wages") == 48000
                                     and abs(ret_f.get("total_tax", -1) - exp_f["/totalTax"]) < 0.01)
    store_o = TimelineStore(eo / "timeline", key_provider=provider)
    store_f = TimelineStore(ef / "timeline", key_provider=provider)
    mc_o = [e for e in store_o.events("main") if e["kind"] == "model_call"]
    mc_f = [e for e in store_f.events("main") if e["kind"] == "model_call"]
    results["orig_model_calls_recorded"] = len(mc_o)
    results["fork_model_calls_recorded"] = len(mc_f)
    results["model_bodies_present"] = all(
        e["payload"].get("request") and e["payload"].get("response") for e in mc_o + mc_f)
    hashes_o = [e["hash"] for e in store_o.events("main")]
    hashes_f = [e["hash"] for e in store_f.events("main")]
    shared = sum(1 for a, b in zip(hashes_o, hashes_f) if a == b)
    results["shared_prefix_events"] = shared
    results["fork_has_own_tail"] = len(hashes_f) > shared
    screen = reconstruct(store_o, "main", rows=24, cols=100).screen()
    results["replay_has_summary"] = "SUMMARY" in screen
    try:
        TimelineStore(eo / "timeline", key_provider=LocalKeyProvider(LocalKeyProvider.generate()))
        results["wrong_key_rejected"] = False
    except Exception:
        results["wrong_key_rejected"] = True
    # Leakage scan: neither the Strata key nor the timeline master key may
    # appear in the guest image or the extracted timelines.
    hay = (SB / "rootfs-hermes.ext4").read_bytes()
    timeline_bytes = b""
    for base in (eo, ef):
        for p in base.rglob("*"):
            if p.is_file(): hay += p.read_bytes()
        for p in (base / "timeline").rglob("*"):
            if p.is_file(): timeline_bytes += p.read_bytes()
    results["strata_key_absent"] = key.encode() not in hay
    results["master_key_absent_from_timeline"] = base64.b64encode(master) not in timeline_bytes
    # The gate asserts, it does not merely observe: exact recorded
    # model_call counts for the flagship fixture (5 shared-prefix calls
    # from phase 1 plus 4 per phase-2 leg) and zero event-sink failures
    # anywhere in either serial. A recorder that drops silently fails here.
    assert results["orig_model_calls_recorded"] == 9, results
    assert results["fork_model_calls_recorded"] == 9, results
    assert "LR-WARN event sink" not in orig.serial.text()
    assert "LR-WARN event sink" not in fork.serial.text()
    print(json.dumps(results, indent=2, default=str))

if __name__ == "__main__":
    main()
