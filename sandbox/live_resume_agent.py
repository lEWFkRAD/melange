"""Guest agent — Melange M5: fork resumption into a live session.

The Build 2 live agent, reopened on a FORKED BRANCH. The host
prepares the data drive: the full timeline store (with the branch
already forked host-side), the branch's workspace restored from its
snapshot at the fork point in /data/ws, and three small files:

  RUN_RESUME        init dispatches here when this file exists
  RESUME_BRANCH     the branch this session continues
  RESUME_CHECKPOINT the event id the resume is anchored on

Everything this agent records — the resume note, the user's turns,
the screen, the model calls the shim reports — appends to THAT
branch, chained onto the branch tip the record already had. The
parent branch is never named here and never written. Commands over
the control channel match live_agent.py: TURN / FINISH (MARK is
accepted as a no-op checkpoint note for harness compatibility).

Honest limit, by construction: the guest boots fresh, so Hermes's
own conversational memory restarts; what carries over is the
recorded workspace and the timeline. The resume note says exactly
that on the branch itself.
"""
import base64, json, os, socket, subprocess, sys, threading, time
from pathlib import Path

sys.path.insert(0, "/opt/living_replay")
from living_replay.capture import PtyCapture
from living_replay.crypto import LocalKeyProvider
from living_replay.store import TimelineStore

DATA = Path("/data")
CTRL_PORT = 1025
EVENT_SOCK = "/tmp/lr-events.sock"

def say(msg): print(msg, flush=True)

def main():
    key = LocalKeyProvider(base64.b64decode((DATA / "LR_KEY").read_text().strip()))
    store = TimelineStore(DATA / "timeline", key_provider=key)
    branch = (DATA / "RESUME_BRANCH").read_text().strip()
    checkpoint = (DATA / "RESUME_CHECKPOINT").read_text().strip()
    existing = store.events(branch)
    if not existing:
        # No fork event, no branch: the host prepared the wrong store.
        # Fail loud on serial instead of silently starting a new past.
        say(f"LR-ERROR resume branch {branch!r} has no events in this store")
        while True: time.sleep(60)
    ws = DATA / "ws"; ws.mkdir(exist_ok=True)

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
                store.append(branch, event["kind"], event["payload"])
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

    cap = PtyCapture(store, branch=branch, rows=24, cols=100)
    store.append(branch, "context_note",
                 {"text": f"session resumed live on branch {branch} from "
                          f"checkpoint event {checkpoint}: workspace restored "
                          "from the branch snapshot; the agent's conversational "
                          "memory restarts from the workspace, the record "
                          "continues on this branch",
                  "pinned": False, "resume": True, "checkpoint": checkpoint})
    os.environ.update(env); os.chdir(ws)

    listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((socket.VMADDR_CID_ANY, CTRL_PORT)); listener.listen(1)
    say("LR-READY")

    turns = 0
    final_code = 0
    while True:
        conn, _ = listener.accept()
        with conn:
            data = conn.recv(65536).decode("utf-8", "replace").strip()
        if not data:
            continue
        if data.startswith("TURN "):
            prompt = data[5:]
            turns += 1
            store.append(branch, "context_note",
                         {"text": f"USER TURN {turns}: {prompt}", "pinned": False})
            argv = ["hermes", "chat", "-q", prompt, "--yolo", "-Q"]
            if turns > 1:
                argv.insert(4, "--continue")
            code = cap.run(argv, timeout=1500)
            if code != 0 and turns > 1:
                store.append(branch, "context_note",
                             {"text": f"turn {turns} --continue failed; fresh one-shot used",
                              "pinned": False})
                code = cap.run(["hermes", "chat", "-q", prompt, "--yolo", "-Q"], timeout=1500)
            if sink_failures and code == 0: code = 3
            os.sync()
            say(f"LR-TURN-DONE n={turns} exit={code}")
        elif data == "MARK":
            store.append(branch, "context_note", {"text": "checkpoint", "pinned": True})
            os.sync()
            say("LR-CHECKPOINT")
        elif data == "FINISH":
            final_code = 3 if sink_failures else 0
            os.sync()
            say(f"LR-DONE exit={final_code} turns={turns}")
            break
    stop.set()
    while True: time.sleep(60)

if __name__ == "__main__":
    main()
