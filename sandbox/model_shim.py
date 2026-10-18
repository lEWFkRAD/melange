"""In-guest model shim (Build 4): Hermes's model endpoint, inside the
boundary. Listens on guest loopback :8642 (OpenAI-shaped HTTP), forwards
each request over the single host-initiated vsock pipe to the host
bridge (which adds the real Authorization header and talks to Strata),
and reports every exchange to the guest agent over a unix socket so the
AGENT — the timeline's only writer — records it as a model_call event.
Request/response JSON bodies only; headers (and the API key, which the
shim never sees) never enter the record.

Pipe protocol: 4-byte big-endian length + JSON envelope
{"path": str, "body": <parsed json or raw string>} each way.
If the pipe breaks (a snapshot restore kills the host end), the shim
goes back to accept() and Hermes's next request rides the fresh pipe —
a fork's model channel is a new channel, per doctrine.
"""
import hashlib, json, os, socket, struct, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Replay-by-record (Melange Build 2): when /opt/replay_table.json exists,
# the shim serves recorded responses instead of forwarding — no pipe, no
# bridge, no live model. Chat requests are matched by a fingerprint of
# their message list; any other forwarded request draws from a FIFO of
# the recorded non-chat responses. A request with no recorded match is a
# REPLAY-MISS: it fails loudly (500 + a shim.log line), because the point
# where the record runs out is exactly where new sampling would begin.
REPLAY = None
if os.path.exists("/opt/replay_table.json"):
    REPLAY = json.loads(open("/opt/replay_table.json").read())

def _fingerprint(body_obj) -> str:
    msgs = body_obj.get("messages") if isinstance(body_obj, dict) else None
    canon = json.dumps(msgs, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canon.encode()).hexdigest()

def _replay_forward(path: str, body_obj) -> tuple[int, bytes]:
    if isinstance(body_obj, dict) and body_obj.get("messages"):
        fp = _fingerprint(body_obj)
        bucket = REPLAY["chats"].get(fp)
        if bucket:
            status, response = bucket.pop(0)
            print(f"SHIM replay hit path={path}", flush=True)
            _report({"kind": "model_call",
                     "payload": {"request": body_obj, "response": response,
                                 "status": status, "via": "replay"}})
            return status, json.dumps(response).encode()
        print(f"SHIM REPLAY-MISS path={path} fp={fp[:12]}", flush=True)
        _report({"kind": "model_call",
                 "payload": {"request": body_obj, "response": {"error": "REPLAY-MISS"},
                             "status": 599, "via": "replay"}})
        return 500, json.dumps({"error": "REPLAY-MISS: no recorded response for this request"}).encode()
    if REPLAY["others"]:
        status, response = REPLAY["others"].pop(0)
        print(f"SHIM replay other path={path}", flush=True)
        _report({"kind": "model_call",
                 "payload": {"request": body_obj, "response": response,
                             "status": status, "via": "replay"}})
        return status, json.dumps(response).encode()
    print(f"SHIM REPLAY-MISS (other) path={path}", flush=True)
    return 500, json.dumps({"error": "REPLAY-MISS: no recorded response for this request"}).encode()

VSOCK_PORT = 1024
EVENT_SOCK = "/tmp/lr-events.sock"
_lock = threading.Lock()
_pipe: socket.socket | None = None
_listener: socket.socket | None = None

def _accept_pipe() -> socket.socket:
    global _listener
    if _listener is None:
        _listener = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        _listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _listener.bind((socket.VMADDR_CID_ANY, VSOCK_PORT))
        _listener.listen(1)
        with open("/tmp/lr-pipe-listening", "w") as f: f.write("1")
    conn, _ = _listener.accept()
    return conn

def _send(sock: socket.socket, obj: dict):
    raw = json.dumps(obj).encode()
    sock.sendall(struct.pack(">I", len(raw)) + raw)

def _recv(sock: socket.socket) -> dict:
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

def _report(event: dict):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.sendto(json.dumps(event).encode(), EVENT_SOCK)
        s.close()
    except OSError:
        pass

def forward(path: str, body_obj) -> tuple[int, bytes]:
    global _pipe
    if REPLAY is not None:
        return _replay_forward(path, body_obj)
    print(f"SHIM forward start path={path}", flush=True)
    with _lock:
        for attempt in (1, 2):
            try:
                if _pipe is None:
                    _pipe = _accept_pipe()
                    _pipe.settimeout(180)
                    print("SHIM pipe accepted", flush=True)
                _send(_pipe, {"path": path, "body": body_obj})
                print("SHIM envelope sent", flush=True)
                resp = _recv(_pipe)
                print(f"SHIM forward ok path={path} status={resp.get('status')}", flush=True)
                _report({"kind": "model_call",
                         "payload": {"request": body_obj, "response": resp.get("body"),
                                     "status": resp.get("status"), "via": "vsock-bridge"}})
                return resp.get("status", 200), json.dumps(resp.get("body")).encode()
            except (ConnectionError, OSError) as e:
                print(f"SHIM forward pipe error attempt={attempt}: {e}", flush=True)
                try: _pipe.close()
                except Exception: pass
                _pipe = None
                if attempt == 2: raise
    raise AssertionError


def _to_sse(payload: bytes):
    """Re-frame a complete chat.completion body as an SSE stream.

    Hermes asks with stream=true and its client parses SSE; the host
    bridge collapses the upstream stream to one JSON body (that JSON is
    what the timeline records via the model_call report). Transport
    framing is rebuilt here, at the edge. Returns None when the body is
    not a completion (the caller then sends it raw).
    """
    try:
        body = json.loads(payload)
        choice = body["choices"][0]
        msg = choice.get("message") or {}
    except Exception:
        return None
    base = {"id": body.get("id", "chatcmpl-shim"), "object": "chat.completion.chunk",
            "created": body.get("created", 0), "model": body.get("model", "")}
    delta = {"role": "assistant"}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [
            {"index": i, "id": tc.get("id", "call_%d" % i), "type": "function",
             "function": {"name": (tc.get("function") or {}).get("name", ""),
                          "arguments": (tc.get("function") or {}).get("arguments", "")}}
            for i, tc in enumerate(msg["tool_calls"])]
    else:
        delta["content"] = msg.get("content") or ""
    chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
              {**base, "choices": [{"index": 0, "delta": {},
                                     "finish_reason": choice.get("finish_reason") or "stop"}]}]
    if body.get("usage"):
        chunks[1]["usage"] = body["usage"]
    out = "".join("data: %s\n\n" % json.dumps(c) for c in chunks) + "data: [DONE]\n\n"
    return out.encode()

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try: body_obj = json.loads(raw) if raw else {}
        except json.JSONDecodeError: body_obj = raw.decode("utf-8", "replace")
        try:
            status, payload = forward(self.path, body_obj)
        except Exception as e:
            status, payload = 502, json.dumps({"error": f"shim: {e}"}).encode()
        ctype = "application/json"
        if isinstance(body_obj, dict) and body_obj.get("stream") and status == 200:
            sse = _to_sse(payload)
            if sse is not None:
                payload, ctype = sse, "text/event-stream"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    do_POST = _handle
    def do_GET(self):
        if self.path.endswith("/models"):
            payload = json.dumps({"object": "list", "data": [
                {"id": "qwen3.8-flash-next", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers(); self.wfile.write(payload)
        else: self._handle()

if __name__ == "__main__":
    # Pre-accept the pipe in a thread so the marker drops as soon as the
    # host dials in, without blocking the HTTP listener. In replay mode
    # there is no pipe at all: drop the marker immediately and never
    # listen on vsock, so a replay forward attempt has nothing to reach.
    if REPLAY is not None:
        with open("/tmp/lr-pipe-listening", "w") as f: f.write("replay")
        print("SHIM replay mode: no pipe, serving the record", flush=True)
    else:
        threading.Thread(target=_accept_pipe, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 8642), Handler).serve_forever()
