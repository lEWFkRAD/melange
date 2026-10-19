"""Synthetic transport and capture -> ingest -> tree verification."""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from living_replay import desktop, ingest
from living_replay.redaction import contains_seeded_secret
from living_replay.store import TimelineStore


def tree(name="Open details", extra=False):
    nodes = [{"nodeId": "r", "role": {"value": "RootWebArea"},
              "name": {"value": "Synthetic application"}, "childIds": ["b"]},
             {"nodeId": "b", "role": {"value": "button"},
              "name": {"value": name}, "childIds": []}]
    if extra:
        nodes[0]["childIds"].append("s")
        nodes.append({"nodeId": "s", "role": {"value": "heading"},
                      "name": {"value": "Synthetic details"}, "childIds": []})
    return nodes


class FakeClient:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        value = next(self.frames)
        if isinstance(value, Exception):
            raise value
        return {"nodes": deepcopy(value)}


class TestCapture(unittest.TestCase):
    def test_forward_reconstruction_every_frame_and_fidelity(self):
        frames = [tree(), tree(), tree("Close details", True), tree()]
        client = FakeClient(frames)
        clock = iter([100, 100.25, 101.25, 102.25, 103.25])
        sleeps = []
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "capture.jsonl"
            counts = desktop.capture_desktop(client, output, samples=4, interval=1,
                clock=lambda: next(clock), sleep=sleeps.append)
            record = output.read_text(encoding="utf-8")
            events = [json.loads(line) for line in record.splitlines()]
            self.assertEqual(events[1]["ops"], [])
            self.assertTrue(any(op["op"] == "del" for op in events[3]["ops"]))
            self.assertEqual([e["ts"] for e in events], [.25, 1.25, 2.25, 3.25])
            self.assertEqual(sleeps, [1, 1, 1])
            self.assertEqual(counts["fidelity"], "structure")
            self.assertEqual(client.calls, [("Accessibility.getFullAXTree", None)] * 4)
            store = TimelineStore(Path(root) / "timeline")
            try:
                ingest.ingest_desktop_record(store, "desktop", record)
                stored = [e for e in store.events("desktop") if e["kind"] in {"ax_keyframe", "ax_delta"}]
                for event, original, recorded in zip(stored, frames, events):
                    self.assertEqual(ingest.tree_state_at(store, "desktop", event["id"]), ingest.flatten_ax(original))
                    self.assertEqual(event["mono_ns"], round(recorded["ts"] * 1e9))
                for op in ("clamp", "fork", "provenance"):
                    with self.assertRaises(ingest.FidelityError):
                        ingest.require_branch_op(store, "desktop", op)
                self.assertTrue(store.verify("desktop"))
            finally:
                store.db.close()

    def test_redacts_before_storage_and_strips_metadata(self):
        first = tree("password=secret-demo")
        first[0]["name"]["sources"] = [{"value": "private-metadata-never-store"}]
        first[0]["backendDOMNodeId"] = 9999
        first[1]["description"] = {"value": "SSN 123-45-6789"}
        first[1]["properties"] = [{"name": "value", "value": {"value": "sk_abcdefghijklmnop",
            "relatedNodes": [{"text": "private-related-node"}]}}]
        second = deepcopy(first)
        second[1]["name"]["value"] = "token=another-secret"
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "capture.jsonl"
            desktop.capture_desktop(FakeClient([first, second]), output, samples=2, interval=0)
            raw = output.read_text(encoding="utf-8")
            self.assertFalse(contains_seeded_secret(raw))
            for text in ("private-metadata", "private-related-node", "backendDOMNodeId"):
                self.assertNotIn(text, raw)
            self.assertIn("[REDACTED]", raw)
        self.assertEqual(first[1]["name"]["value"], "password=secret-demo")

    def test_existing_output_is_never_overwritten_or_sampled(self):
        client = FakeClient([tree()])
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / "capture.jsonl"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                desktop.capture_desktop(client, output, samples=1)
            self.assertEqual(output.read_text(), "existing")
            self.assertEqual(client.calls, [])

    def test_failure_keeps_only_valid_prefix_and_never_returns_success(self):
        bad = tree()
        bad[0]["childIds"].append("missing")
        for failure in (bad, [], desktop.CaptureError("disconnected")):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as root:
                output = Path(root) / "capture.jsonl"
                with self.assertRaises(desktop.CaptureError):
                    desktop.capture_desktop(FakeClient([tree(), failure]), output, samples=2, interval=0)
                self.assertEqual(len(output.read_text().splitlines()), 1)

    def test_invalid_bounds_create_no_output(self):
        for kwargs in ({"samples": 0}, {"samples": True}, {"samples": 100001},
                       {"interval": -1}, {"interval": float("nan")}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as root:
                output = Path(root) / "capture.jsonl"
                with self.assertRaises(ValueError):
                    desktop.capture_desktop(FakeClient([]), output, **kwargs)
                self.assertFalse(output.exists())

    def test_invalid_semantics_and_graphs_are_refused(self):
        cycle = tree()
        cycle[1]["childIds"] = ["r"]
        conflict = tree() + [{"nodeId": "b", "name": {"value": "conflicting"}}]
        semantic = tree()
        semantic[1]["name"] = {"value": 7}
        nan = tree()
        nan[1]["properties"] = [{"name": "value", "value": {"value": float("nan")}}]
        for nodes in (cycle, conflict, semantic, nan):
            with self.subTest(nodes=nodes), self.assertRaises(desktop.CaptureError):
                desktop.sanitize_ax(nodes)


class TestTargetSelection(unittest.TestCase):
    def select(self, targets, selected="wanted"):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(targets).encode())
        with patch.object(desktop, "build_opener", return_value=opener):
            return desktop.select_target("http://127.0.0.1:9222", selected)

    def test_selects_only_exact_id(self):
        targets = [{"id": "personal", "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/personal"},
                   {"id": "wanted", "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/wanted"}]
        self.assertEqual(self.select(targets), targets[1]["webSocketDebuggerUrl"])
        with self.assertRaises(desktop.CaptureError):
            self.select(targets, "missing")
        with self.assertRaises(ValueError):
            self.select(targets, "")
        with self.assertRaises(desktop.CaptureError):
            self.select([targets[1], targets[1]])

    def test_remote_or_credentialed_endpoint_and_returned_socket_refused(self):
        for url in ("http://example.com:9222", "http://user@127.0.0.1:9222", "http://127.0.0.1:9222/path", "http://127.0.0.1:9222?token=secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                desktop.select_target(url, "wanted")
        with self.assertRaises(ValueError):
            self.select([{"id": "wanted", "type": "page", "webSocketDebuggerUrl": "ws://example.com/devtools/page/wanted"}])


class TestTransport(unittest.TestCase):
    def client(self, messages):
        socket = Mock()
        socket.recv.side_effect = messages
        module = types.SimpleNamespace(create_connection=Mock(return_value=socket))
        with patch.dict("sys.modules", {"websocket": module}):
            client = desktop.CDPClient("ws://127.0.0.1:9222/devtools/page/test")
        self.assertEqual(module.create_connection.call_args.kwargs["redirect_limit"], 0)
        return client, socket

    def test_notifications_are_skipped_and_result_correlated(self):
        client, socket = self.client([json.dumps({"method": "Accessibility.loadComplete", "params": {}}),
                                     json.dumps({"id": 1, "result": {"nodes": tree()}})])
        self.assertEqual(client.call("Accessibility.getFullAXTree"), {"nodes": tree()})
        self.assertEqual(json.loads(socket.send.call_args.args[0])["method"], "Accessibility.getFullAXTree")
        client.close()
        socket.close.assert_called_once()

    def test_closed_malformed_detached_and_error_responses_fail(self):
        for message in ("", "not-json", "[]", '{"id":2,"result":{}}',
                        '{"id":1,"error":{"message":"private error"}}',
                        '{"method":"Inspector.detached","params":{}}'):
            with self.subTest(message=message):
                client, _ = self.client([message])
                with self.assertRaises(desktop.CaptureError):
                    client.call("Accessibility.getFullAXTree")


if __name__ == "__main__":
    unittest.main()
