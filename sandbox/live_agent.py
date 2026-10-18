"""Guest agent — Melange Build 2: live capture of a real Hermes session.

Same boundary discipline as the Build 1 agent (this process owns the
encrypted timeline; the shim reports model exchanges to it; the API key
never enters the guest), but the session is NOT scripted: the host
drives a real multi-turn conversation over the control channel, one
TURN command at a time, and may snapshot the VM whenever this agent is
idle between turns. Commands, one per connection, one line each:

  TURN <text>   run one user turn (first turn plain, later --continue)
  MARK          record a pinned checkpoint note, print LR-CHECKPOINT
  FINISH        print LR-DONE and end the session

Every turn is recorded on the timeline as a context_note before it
runs, so the scrub record shows the user's words next to the model's.
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
    ws = DATA / "ws"; ws.mkdir(exist_ok=True)
    seed = DATA / "notes.md"
    if seed.exists() and not (ws / "notes.md").exists():
        (ws / "notes.md").write_text(seed.read_text())

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
    store.append("main", "context_note",
                 {"text": "Melange Build 2: live capture, unscripted session", "pinned": False})
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
            store.append("main", "context_note",
                         {"text": f"USER TURN {turns}: {prompt}", "pinned": False})
            argv = ["hermes", "chat", "-q", prompt, "--yolo", "-Q"]
            if turns > 1:
                argv.insert(4, "--continue")
            code = cap.run(argv, timeout=1500)
            if code != 0 and turns > 1:
                store.append("main", "context_note",
                             {"text": f"turn {turns} --continue failed; fresh one-shot used",
                              "pinned": False})
                code = cap.run(["hermes", "chat", "-q", prompt, "--yolo", "-Q"], timeout=1500)
            if sink_failures and code == 0: code = 3
            os.sync()
            say(f"LR-TURN-DONE n={turns} exit={code}")
        elif data == "MARK":
            store.append("main", "context_note", {"text": "checkpoint", "pinned": True})
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
