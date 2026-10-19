"""Read-only local CDP accessibility capture at structure fidelity.

A failed capture raises and leaves only the validated, redacted prefix in
its exclusively created output file. Run python -m living_replay.desktop.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .ingest import flatten_ax
from .redaction import redact_text


class CaptureError(RuntimeError):
    """Capture failed; no successful completion may be inferred."""


def _local_url(url: str, schemes: set[str]):
    try:
        if not isinstance(url, str):
            raise ValueError
        parsed = urlsplit(url)
        host = parsed.hostname
        local = host == "localhost" or (
            host is not None and ipaddress.ip_address(host).is_loopback)
        parsed.port
        if (parsed.scheme not in schemes or not local or parsed.username
                or parsed.password or parsed.fragment or parsed.query):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("CDP URL must use a loopback host, without credentials, query or fragment") from None
    return parsed


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CaptureError("CDP discovery redirects are refused")


def select_target(endpoint: str, target_id: str, *, timeout: float = 10) -> str:
    """Resolve one explicit target id from a local /json/list."""
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("an explicit CDP target id is required")
    parsed = _local_url(endpoint, {"http"})
    if parsed.path not in ("", "/", "/json/list"):
        raise ValueError("CDP endpoint must be its origin or /json/list")
    url = urlunsplit((parsed.scheme, parsed.netloc, "/json/list", "", ""))
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(url, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise CaptureError("CDP target list exceeds the discovery limit")
        targets = json.loads(raw)
    except CaptureError:
        raise
    except Exception:
        raise CaptureError("could not read the local CDP target list") from None
    if not isinstance(targets, list) or any(not isinstance(t, dict) for t in targets):
        raise CaptureError("malformed CDP target list")
    selected = [t for t in targets if t.get("id") == target_id]
    if len(selected) != 1:
        raise CaptureError("target id must identify exactly one available CDP target")
    target = selected[0]
    if target.get("type") not in {"page", "webview"}:
        raise CaptureError("selected CDP target is not a page or webview")
    websocket_url = target.get("webSocketDebuggerUrl")
    _local_url(websocket_url, {"ws", "wss"})
    return websocket_url


class CDPClient:
    """Synchronous single-request transport with finite deadlines.

    websocket-client is imported only when connecting. The recorder uses
    only Accessibility.getFullAXTree; the synthetic verification harness
    can separately drive its own browser through other methods.
    """
    def __init__(self, websocket_url: str, *, timeout: float = 10):
        _local_url(websocket_url, {"ws", "wss"})
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("CDP timeout must be finite and positive")
        try:
            import websocket
        except ImportError:
            raise CaptureError("desktop transport requires pip install 'living-replay[desktop]'") from None
        self.timeout = timeout
        self._next_id = 0
        try:
            self._socket = websocket.create_connection(
                websocket_url, timeout=timeout, suppress_origin=True,
                http_no_proxy=["*"], redirect_limit=0)
        except Exception:
            raise CaptureError("could not connect to the selected local CDP target") from None

    def call(self, method: str, params: dict | None = None) -> dict:
        self._next_id += 1
        request_id = self._next_id
        deadline = time.monotonic() + self.timeout
        try:
            self._socket.settimeout(self.timeout)
            self._socket.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CaptureError("CDP request timed out")
                self._socket.settimeout(remaining)
                raw = self._socket.recv()
                if not raw:
                    raise CaptureError("CDP target disconnected")
                reply = json.loads(raw)
                if not isinstance(reply, dict):
                    raise CaptureError("malformed CDP response")
                if reply.get("method") == "Inspector.detached":
                    raise CaptureError("CDP target detached")
                if "id" not in reply:
                    if not isinstance(reply.get("method"), str):
                        raise CaptureError("malformed CDP notification")
                    continue
                if reply["id"] != request_id:
                    raise CaptureError("unexpected CDP response id")
                if "error" in reply:
                    raise CaptureError("CDP request was refused")
                if not isinstance(reply.get("result"), dict):
                    raise CaptureError("malformed CDP result")
                return reply["result"]
        except CaptureError:
            raise
        except Exception:
            raise CaptureError("CDP request failed or target disconnected") from None

    def close(self) -> None:
        self._socket.close()


def _redact_value(value):
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    if isinstance(value, dict):
        return {redact_text(k): _redact_value(v) for k, v in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise ValueError("AX property value is not JSON")


def sanitize_ax(nodes: list) -> list:
    """Validate, strip CDP metadata and redact semantic text before storage."""
    try:
        flatten_ax(nodes)
        unique = {node["nodeId"]: node for node in nodes}
        ids = {node_id: str(index) for index, node_id in enumerate(unique)}
        safe = []
        for node_id, node in unique.items():
            out = {"nodeId": ids[node_id],
                   "childIds": [ids[c] for c in (node.get("childIds") or [])]}
            for field in ("role", "name", "description"):
                value = node.get(field) or {}
                if not isinstance(value, dict) or not isinstance(value.get("value", ""), str):
                    raise ValueError("AX text must be a string")
                out[field] = {"value": redact_text(value.get("value", ""))}
            properties = node.get("properties") or []
            if not isinstance(properties, list):
                raise ValueError("AX properties must be a list")
            out["properties"] = []
            names = set()
            for prop in properties:
                if not isinstance(prop, dict) or not isinstance(prop.get("name"), str):
                    raise ValueError("AX property must have a string name")
                if prop["name"] in names:
                    raise ValueError("duplicate AX property name")
                names.add(prop["name"])
                value = prop.get("value") or {}
                if not isinstance(value, dict):
                    raise ValueError("AX property value must be an object")
                out["properties"].append({"name": redact_text(prop["name"]),
                    "value": {"value": _redact_value(value.get("value"))}})
            out["properties"].sort(key=lambda p: p["name"])
            safe.append(out)
        json.dumps(safe, allow_nan=False)
        return safe
    except (KeyError, TypeError, ValueError, AttributeError, RecursionError):
        raise CaptureError("CDP returned a malformed accessibility tree") from None


def diff_ax(previous: dict, current: dict) -> list:
    """Deterministic operations on flattened structural paths."""
    removed = [{"op": "del", "path": path} for path in sorted(previous.keys() - current.keys())]
    changed = [{"op": "set", "path": path, "node": current[path]}
               for path in sorted(current) if path not in previous or previous[path] != current[path]]
    return removed + changed


def capture_desktop(client, output_path: str | Path, *, samples: int = 20,
                    interval: float = 1.5, clock=time.monotonic, sleep=time.sleep) -> dict:
    """Persist bounded keyframe + polls without overwriting existing files.

    samples includes the keyframe. Still polls emit empty deltas. ts is
    elapsed monotonic seconds at response completion. Failure raises;
    any persisted prefix remains an incomplete trace.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 100_000:
        raise ValueError("samples must be an integer between 1 and 100000")
    if (isinstance(interval, bool) or not isinstance(interval, (int, float))
            or not math.isfinite(interval) or not 0 <= interval <= 3600):
        raise ValueError("interval must be finite seconds between 0 and 3600")
    counts = {"keyframes": 0, "deltas": 0, "delta_ops": 0, "fidelity": "structure"}
    with Path(output_path).open("x", encoding="utf-8", newline="\n") as output:
        started = clock()
        previous = {}
        previous_ts = 0
        for poll in range(samples):
            if poll:
                sleep(interval)
            result = client.call("Accessibility.getFullAXTree")
            if not isinstance(result, dict) or "nodes" not in result:
                raise CaptureError("CDP response has no accessibility tree")
            ts = clock() - started
            if not math.isfinite(ts) or ts < previous_ts:
                raise CaptureError("capture clock is not monotonic")
            safe = sanitize_ax(result["nodes"])
            current = flatten_ax(safe)
            if poll == 0:
                event = {"type": "keyframe", "ts": ts, "nodes": safe}
                counts["keyframes"] += 1
            else:
                ops = diff_ax(previous, current)
                event = {"type": "delta", "ts": ts, "poll": poll, "ops": ops}
                counts["deltas"] += 1
                counts["delta_ops"] += len(ops)
            output.write(json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
            output.flush()
            previous, previous_ts = current, ts
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only local CDP AX capture (structure fidelity)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--endpoint", help="local HTTP endpoint; requires --target-id")
    source.add_argument("--websocket", help="explicit local page websocket URL")
    parser.add_argument("--target-id", help="exact page/webview id from /json/list")
    parser.add_argument("--output", required=True, type=Path, help="new JSONL file")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--interval", type=float, default=1.5)
    args = parser.parse_args(argv)
    if bool(args.endpoint) != bool(args.target_id):
        parser.error("--endpoint requires --target-id; --websocket must not use --target-id")
    client = None
    try:
        url = select_target(args.endpoint, args.target_id) if args.endpoint else args.websocket
        client = CDPClient(url)
        result = capture_desktop(client, args.output, samples=args.samples, interval=args.interval)
    except (CaptureError, ValueError, OSError) as exc:
        print(f"Capture incomplete: {redact_text(str(exc))}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Capture interrupted; output is an incomplete trace.", file=sys.stderr)
        return 130
    finally:
        if client is not None:
            client.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
