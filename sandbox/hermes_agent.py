"""Guest agent — Build 4: a real Hermes session inside the boundary.

Owns the (encrypted) timeline exclusively. Starts the model shim,
runs Hermes under PTY capture for phase 1, signals the checkpoint,
waits for the host's GO on the control channel, then runs phase 2 —
with the reviewer's correction appended when the GO carries one (the
fork's case). Everything the session produces lands on the data drive.
"""
import base64, json, os, socket, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, "/opt/living_replay")
from living_replay.capture import PtyCapture
from living_replay.crypto import LocalKeyProvider
from living_replay.flagship import INTAKE
from living_replay.store import TimelineStore

DATA = Path("/data")
CTRL_PORT = 1025
EVENT_SOCK = "/tmp/lr-events.sock"

RULES = ("compute the federal return using these rules: standard deduction 14600 for a single filer; "
         "tax is 10% of taxable income up to 11000, then 1100 plus 12% of the excess over 11000; "
         "credits are 200 if AGI is 75000 or less, plus 500 per dependent; total tax is tax minus "
         "credits, not below zero; refund is withholding minus total tax")
PHASE1 = ("You are preparing a synthetic individual tax return. The file intake.txt in the current "
          f"directory holds the taxpayer's intake summary. Read it, {RULES}. Write the figures to "
          "return.txt with exactly these lines: wages=<n>, agi=<n>, total_tax=<n>, refund=<n> "
          "(plain numbers, no commas, no dollar signs). Then reply with just PHASE1-DONE.")
PHASE2 = ("Finalise the return: re-check return.txt against intake.txt, then print exactly one line "
          "in the form SUMMARY wages=<n> total_tax=<n> refund=<n> and reply DONE.")
CORRECTION = (" Correction from the reviewer: the W-2 was amended — wages are 48000, not 52000. "
              "Recompute the return with the corrected wages, update return.txt with the corrected "
              "figures, then print the SUMMARY line and reply DONE.")

def say(msg): print(msg, flush=True)

def main():
    key = LocalKeyProvider(base64.b64decode((DATA / "LR_KEY").read_text().strip()))
    store = TimelineStore(DATA / "timeline", key_provider=key)
    ws = DATA / "ws"; ws.mkdir(exist_ok=True)
    (ws / "intake.txt").write_text(INTAKE)

    # Event sink: the shim reports model exchanges here; this process is
    # the timeline's only writer.
    if os.path.exists(EVENT_SOCK): os.unlink(EVENT_SOCK)
    sink = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sink.bind(EVENT_SOCK)
    stop = threading.Event()
    sink_failures = []
    def drain():
        sink.settimeout(0.2)
        while not stop.is_set():
            try:
                raw = sink.recv(1 << 20)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                event = json.loads(raw)
                store.append("main", event["kind"], event["payload"])
            except Exception as e:
                sink_failures.append(str(e))
                say(f"LR-WARN event sink: {e}")
    threading.Thread(target=drain, daemon=True).start()

    env = {**os.environ, "HERMES_HOME": "/root/hermes-home",
           "PATH": "/usr/local/python/bin:/usr/local/bin:/bin", "HOME": "/root"}
    shim_log = open(DATA / "shim.log", "ab", buffering=0)
    shim = subprocess.Popen([sys.executable, "/opt/model_shim.py"], env=env,
                            stdout=shim_log, stderr=shim_log)
    for _ in range(100):
        if Path("/tmp/lr-pipe-listening").exists(): break
        time.sleep(0.1)

    cap = PtyCapture(store, rows=24, cols=100)
    store.append("main", "context_note", {"text": "Build 4: real Hermes session, synthetic data", "pinned": False})
    # PtyCapture.run inherits this process's cwd/env — set both here.
    os.environ.update(env); os.chdir(ws)
    code = cap.run(["hermes", "chat", "-q", PHASE1, "--yolo", "-Q"], timeout=1200)
    if sink_failures and code == 0: code = 3  # a dropped event fails the run loudly
    os.sync()
    say(f"LR-CHECKPOINT phase1-exit={code} return={(ws / 'return.txt').read_text().strip() if (ws / 'return.txt').exists() else 'MISSING'}")

    # Control channel: one line from the host. After a snapshot restore
    # the original connection is dead, so accept in a loop.
    listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((socket.VMADDR_CID_ANY, CTRL_PORT)); listener.listen(1)
    go = ""
    while not go:
        conn, _ = listener.accept()
        with conn:
            data = conn.recv(65536).decode("utf-8", "replace").strip()
            if data: go = data
    say("LR-PHASE2-START")
    prompt = PHASE2 + (CORRECTION if "correct" in go.lower() else "")
    code2 = cap.run(["hermes", "chat", "-q", prompt, "--continue", "--yolo", "-Q"], timeout=1200)
    if code2 != 0:  # resume failed: fresh one-shot with the same instruction
        store.append("main", "context_note", {"text": "phase2 --continue failed; fresh one-shot used", "pinned": False})
        code2 = cap.run(["hermes", "chat", "-q", prompt, "--yolo", "-Q"], timeout=1200)
    if sink_failures and code2 == 0: code2 = 3  # a dropped event fails the run loudly
    os.sync()
    say(f"LR-DONE phase2-exit={code2} return={(ws / 'return.txt').read_text().strip() if (ws / 'return.txt').exists() else 'MISSING'}")
    stop.set()
    while True: time.sleep(60)

if __name__ == "__main__":
    main()
