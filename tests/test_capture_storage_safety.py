"""Capture and encrypted workspace regressions; synthetic data only."""
import io
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

from living_replay.capture import PtyCapture
from living_replay.crypto import LocalKeyProvider, TimelineKeyError
from living_replay.forking import restore_workspace, snapshot_workspace
from living_replay.redaction import redact_bytes, split_redaction_buffer
from living_replay.replay import reconstruct
from living_replay.store import TimelineStore


class CaptureStorageSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stores = []

    def tearDown(self):
        for store in self.stores:
            store.db.close()
        self.tmp.cleanup()

    def store(self, name="timeline", key=None):
        store = TimelineStore(self.root / name, key_provider=key)
        self.stores.append(store)
        return store

    def terminal_bytes(self, store):
        return b"".join(store.get_blob(e["payload"]["blob"])
                        for e in store.events("main") if e["kind"] == "terminal_chunk")

    def test_live_artificial_cut_cannot_split_credential(self):
        store = self.store()
        secret = b"sk_abcdefghijklmnop"
        raw = b" " * 70 + secret + b" " * 55
        capture = PtyCapture(store)
        code = "import os; os.write(1, " + repr(raw) + ")"
        self.assertEqual(capture.run([sys.executable, "-c", code]), 0)
        self.assertEqual(self.terminal_bytes(store), redact_bytes(raw))
        self.assertNotIn(secret, self.terminal_bytes(store))
        persisted = b"".join(p.read_bytes() for p in store.root.rglob("*") if p.is_file())
        self.assertNotIn(secret, persisted)
        self.assertTrue(store.verify("main"))
        self.assertEqual(reconstruct(store, "main").screen(), capture.grid.screen())

    def test_redaction_is_independent_of_read_boundaries(self):
        raw = (b"prefix sk_abcdefghijklmnop password \n = " + b"x" * 200 + b" "
               b"token: synthetic-value AKIAIOSFODNN7EXAMPLE 123-45-6789 "
               + "café 日本".encode() + b" suffix")
        expected = redact_bytes(raw)
        for split in range(len(raw) + 1):
            with self.subTest(split=split):
                pending = b""
                emitted = []
                for chunk in (raw[:split], raw[split:]):
                    prefix, pending = split_redaction_buffer(pending + chunk)
                    emitted.append(redact_bytes(prefix))
                prefix, pending = split_redaction_buffer(pending, final=True)
                emitted.append(redact_bytes(prefix))
                self.assertEqual(pending, b"")
                self.assertEqual(b"".join(emitted), expected)

    def test_utf8_survives_old_tail_boundary_and_offsets(self):
        store = self.store()
        raw = b" " * 70 + "€".encode() + b" " * 63
        cap = PtyCapture(store)
        self.assertEqual(cap.run([sys.executable, "-c", "import os; os.write(1, " + repr(raw) + ")"]), 0)
        self.assertEqual(self.terminal_bytes(store), raw)
        offset = 0
        for event in store.events("main"):
            if event["kind"] == "terminal_chunk":
                self.assertEqual(event["payload"]["offset"], offset)
                offset += event["payload"]["length"]
        self.assertEqual(offset, len(raw))
        self.assertEqual(reconstruct(store, "main").screen(), cap.grid.screen())

    def test_timeout_stops_silent_child(self):
        store = self.store()
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            PtyCapture(store).run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.15)
        self.assertLess(time.monotonic() - start, 1.5)

    def test_timeout_stops_descendant_holding_pty(self):
        store = self.store()
        code = "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])"
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            PtyCapture(store).run([sys.executable, "-c", code], timeout=0.15)
        self.assertLess(time.monotonic() - start, 1.5)

    def test_encrypted_store_rejects_missing_key_without_mutation(self):
        key = LocalKeyProvider(LocalKeyProvider.generate())
        store = self.store(key=key)
        store.append("main", "context_note", {"text": "synthetic marker"})
        before = store.events("main")
        with self.assertRaises(TimelineKeyError):
            TimelineStore(store.root)
        self.assertEqual(store.events("main"), before)
        self.assertTrue(store.verify("main"))

    def test_existing_plaintext_store_cannot_silently_enable_encryption(self):
        store = self.store()
        store.append("main", "context_note", {"text": "synthetic marker"})
        key = LocalKeyProvider(LocalKeyProvider.generate())
        with self.assertRaises(TimelineKeyError):
            TimelineStore(store.root, key_provider=key)
        self.assertFalse((store.root / "key.json").exists())
        self.assertTrue(store.verify("main"))

    def test_encrypted_workspace_has_no_plaintext_archive_and_restores(self):
        key = LocalKeyProvider(LocalKeyProvider.generate())
        store = self.store(key=key)
        source = self.root / "source"
        source.mkdir()
        marker = b"SYNTHETIC-WORKSPACE-PRIVATE-MARKER"
        (source / "data.txt").write_bytes(marker)
        event = snapshot_workspace(store, "main", source)
        self.assertFalse(list(store.root.glob("snapshot-*")))
        persisted = b"".join(p.read_bytes() for p in store.root.rglob("*") if p.is_file())
        self.assertNotIn(marker, persisted)
        dest = restore_workspace(store, event, self.root / "restored")
        self.assertEqual((dest / "data.txt").read_bytes(), marker)
        self.assertFalse((dest / ".living-replay-snapshot.tar.gz").exists())
        self.assertTrue(store.verify("main"))

    def test_workspace_restore_rejects_traversal(self):
        store = self.store()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            member = tarfile.TarInfo("../escaped.txt")
            data = b"synthetic"
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
        event = store.append("main", "workspace_snapshot", {"blob": store.put_blob(buffer.getvalue()), "format": "tar.gz"})
        with self.assertRaises(tarfile.FilterError):
            restore_workspace(store, event, self.root / "restored")
        self.assertFalse((self.root / "escaped.txt").exists())


if __name__ == "__main__":
    unittest.main()
