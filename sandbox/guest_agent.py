"""Guest agent — runs INSIDE the Firecracker microVM as /init's main act.

Phase 1 records a small agent session with Build 1 capture onto the data
drive, fsyncs everything, and announces the checkpoint on the serial
console ("LR-READY"). It then waits for a GO signal, from either:
  - a GO file on the data drive (how a FORK receives its orders — the
    host bakes the file into the fork's copied drive before booting it),
  - or a vsock connection carrying one line (how the ORIGINAL is told to
    continue after the host has snapshotted it).
Phase 2 finishes the task — with the note's corrected amount when one
arrived — writes a DONE marker, and powers off.
"""
import os, socket, sys, time

sys.path.insert(0, "/opt/living_replay")
from living_replay.capture import PtyCapture
from living_replay.store import TimelineStore

DATA = "/data"
VSOCK_PORT = 1024

def say(msg):
    print(msg, flush=True)

def wait_for_go() -> str:
    listener = None
    try:
        listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        listener.bind((socket.VMADDR_CID_ANY, VSOCK_PORT))
        listener.listen(1)
        listener.settimeout(0.1)
    except OSError:
        listener = None
    go_file = os.path.join(DATA, "GO")
    while True:
        if os.path.exists(go_file):
            with open(go_file) as f: return f.read().strip()
        if listener is not None:
            try:
                conn, _ = listener.accept()
                with conn:
                    data = conn.recv(4096).decode("utf-8", "replace").strip()
                    if data: return data
            except socket.timeout:
                pass
            except OSError:
                pass
        time.sleep(0.05)

def main():
    store = TimelineStore(os.path.join(DATA, "timeline"))
    cap = PtyCapture(store, rows=10, cols=40)
    ws = os.path.join(DATA, "ws"); os.makedirs(ws, exist_ok=True)
    with open(os.path.join(ws, "data.txt"), "w") as f: f.write("amount=21")
    read = store.append("main", "tool_call", {"name": "read-amount", "amount": 21, "input": "data.txt", "output": "21"})
    cap.record_bytes(b"amount=21\r\n", read)
    os.sync()
    say("LR-READY")
    go = wait_for_go()
    say("LR-PHASE2-START")
    amount = 21
    if "amount=" in go:
        amount = int(go.split("amount=")[1].split()[0])
    total = amount * 2
    store.append("main", "model_call", {"prompt": "double the amount", "tokens": str(total), "replayed": True})
    tool = store.append("main", "tool_call", {"name": "print-total", "input": "print", "output": f"total={total}"})
    cap.record_bytes(f"total={total}\r\n".encode(), tool)
    with open(os.path.join(DATA, "DONE"), "w") as f: f.write(f"amount={amount} total={total}\n")
    os.sync()
    say(f"LR-DONE total={total}")
    poweroff()

def poweroff():
    """Power the microVM off by whichever path the guest kernel honors;
    returning from init instead would panic and reboot-loop the guest."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    # reboot(magic1, magic2, LINUX_REBOOT_CMD_POWER_OFF)
    r = libc.reboot(0xfee1dead, 672274793, 0x4321fedc, None)
    say(f"LR-POWEROFF reboot syscall -> {r} errno={ctypes.get_errno()}")
    os.system("poweroff -f")
    say("LR-POWEROFF busybox poweroff returned")
    try:
        with open("/proc/sysrq-trigger", "w") as f: f.write("o")
    except OSError as e:
        say(f"LR-POWEROFF sysrq failed: {e}")
    while True: time.sleep(60)

if __name__ == "__main__":
    main()
