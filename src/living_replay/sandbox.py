"""Architecture B host driver (Build 2): Firecracker microVM lifecycle.

Boots the Living Replay guest, watches its serial console for the
checkpoint marker, snapshots the VM, forks it (snapshot restore into a
second microVM whose data drive carries a baked-in GO note), and lets
the original finish through its vsock doorbell. All timings are recorded
so the gate reports measurements, not vibes.

Runs on the sandbox host (KVM required). Guest RAM is capped small out
of respect for the host's day job.
"""
from __future__ import annotations
import http.client, json, os, shutil, socket, subprocess, threading, time
from pathlib import Path

class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, sock_path: str):
        super().__init__("localhost", timeout=60); self._sock_path = sock_path
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self._sock_path)

def api(sock_path: str, method: str, path: str, body: dict | None = None) -> tuple[int, str]:
    conn = _UnixHTTP(sock_path)
    payload = json.dumps(body) if body is not None else None
    conn.request(method, path, payload, {"Accept": "application/json", "Content-Type": "application/json"})
    resp = conn.getresponse(); data = resp.read().decode("utf-8", "replace")
    conn.close()
    return resp.status, data

class SerialLog:
    def __init__(self, stream, mirror_path=None):
        self.lines: list[tuple[float, str]] = []
        self._lock = threading.Lock()
        self._mirror = open(mirror_path, "ab", buffering=0) if mirror_path else None
        self._thread = threading.Thread(target=self._pump, args=(stream,), daemon=True)
        self._thread.start()
    def _pump(self, stream):
        buf = b""
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk: break
            if self._mirror: self._mirror.write(chunk)
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                with self._lock:
                    self.lines.append((time.monotonic(), line.decode("utf-8", "replace").strip()))
    def wait_for(self, needle: str, timeout: float = 60.0) -> float | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for t, line in self.lines:
                    if needle in line: return t
            time.sleep(0.02)
        return None
    def text(self) -> str:
        with self._lock: return "\n".join(line for _, line in self.lines)

class MicroVM:
    def __init__(self, workdir: Path, fc_bin: Path, name: str):
        self.dir = workdir / name; self.dir.mkdir(parents=True, exist_ok=True)
        self.sock = str(self.dir / "fc.sock")
        self.proc: subprocess.Popen | None = None
        self.serial: SerialLog | None = None
        self.fc_bin = fc_bin

    def start_process(self):
        log = open(self.dir / "fc.log", "wb")
        self.proc = subprocess.Popen([str(self.fc_bin), "--api-sock", self.sock],
                                     stdout=subprocess.PIPE, stderr=log)
        self.serial = SerialLog(self.proc.stdout, self.dir / "serial.log")
        for _ in range(100):
            if os.path.exists(self.sock): return
            time.sleep(0.05)
        raise RuntimeError("firecracker api socket never appeared")

    def configure(self, kernel: Path, rootfs: Path, data_drive: Path, cid: int, mem_mib: int = 512):
        st, body = api(self.sock, "PUT", "/boot-source",
                       {"kernel_image_path": str(kernel), "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/init"})
        assert st == 204, body
        st, body = api(self.sock, "PUT", "/drives/rootfs",
                       {"drive_id": "rootfs", "path_on_host": str(rootfs), "is_root_device": True, "is_read_only": False})
        assert st == 204, body
        st, body = api(self.sock, "PUT", "/drives/data",
                       {"drive_id": "data", "path_on_host": str(data_drive), "is_root_device": False, "is_read_only": False})
        assert st == 204, body
        st, body = api(self.sock, "PUT", "/machine-config", {"vcpu_count": 1, "mem_size_mib": mem_mib})
        assert st == 204, body
        st, body = api(self.sock, "PUT", "/vsock",
                       {"guest_cid": cid, "uds_path": str(self.dir / "vsock.sock")})
        assert st == 204, body

    def action(self, action_type: str):
        st, body = api(self.sock, "PUT", "/actions", {"action_type": action_type})
        assert st == 204, body

    def pause(self):
        st, body = api(self.sock, "PATCH", "/vm", {"state": "Paused"})
        assert st == 204, body

    def resume(self):
        st, body = api(self.sock, "PATCH", "/vm", {"state": "Resumed"})
        assert st == 204, body

    def snapshot(self, snap_path: Path, mem_path: Path) -> float:
        start = time.monotonic()
        st, body = api(self.sock, "PUT", "/snapshot/create",
                       {"snapshot_type": "Full", "snapshot_path": str(snap_path), "mem_file_path": str(mem_path)})
        assert st == 204, body
        return time.monotonic() - start

    def load_snapshot(self, snap_path: Path, mem_path: Path) -> float:
        start = time.monotonic()
        st, body = api(self.sock, "PUT", "/snapshot/load",
                       {"snapshot_path": str(snap_path), "mem_file_path": str(mem_path), "resume_vm": False})
        assert st == 204, body
        return time.monotonic() - start

    def vsock_send(self, port: int, message: str, timeout: float = 10.0, uds_path: str | None = None) -> None:
        # After a snapshot restore, the guest's vsock backend binds the
        # host path stored IN the snapshot (the original VM's path), so a
        # fork is reached through the original's uds path, not its own.
        uds = uds_path or str(self.dir / "vsock.sock")
        deadline = time.monotonic() + timeout
        while True:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.settimeout(5); s.connect(uds)
                s.sendall(f"CONNECT {port}\n".encode())
                ack = s.recv(64)
                if b"OK" not in ack: raise OSError(f"vsock connect refused: {ack!r}")
                s.sendall(message.encode()); s.close(); return
            except OSError:
                if time.monotonic() > deadline: raise
                time.sleep(0.1)

    def wait_exit(self, timeout: float = 60.0) -> int:
        return self.proc.wait(timeout=timeout)

    def stop(self) -> None:
        """End the microVM from the host. A halted guest does not exit
        Firecracker on these minimal kernels, so completion is a host act:
        the guest signals DONE on serial, the host tears the VM down."""
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try: self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired: self.proc.kill()

def fresh_data_drive(path: Path, size_mb: int = 64) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f: f.truncate(size_mb * 1024 * 1024)
    subprocess.run(["mkfs.ext4", "-q", "-F", str(path)], check=True)
    return path

def write_file_into_image(image: Path, dest: str, content: str) -> None:
    """Write a small file into an ext4 image with debugfs (image must not
    be mounted by a running guest)."""
    tmp = image.parent / "debugfs-input.txt"
    tmp.write_text(content)
    subprocess.run(["debugfs", "-w", "-R", f"write {tmp} {dest}", str(image)],
                   check=True, capture_output=True)
    tmp.unlink()

def extract_dir_from_image(image: Path, src: str, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(["debugfs", "-R", f"rdump {src} {dest}", str(image)],
                   check=True, capture_output=True)
