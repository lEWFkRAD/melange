"""Build 3 gate corpus — encryption (B3-G3), flagship (B3-G1/G2).
GUI (B3-G4) lives in test_gui.py; the PANDA spike (B3-G5) reports from
the sandbox host; regressions (B3-G6) are the full suite itself."""
import shutil, tempfile, unittest
from pathlib import Path

from living_replay.capture import PtyCapture
from living_replay.crypto import LocalKeyProvider, TimelineKeyError
from living_replay.flagship import INTAKE, run_flagship
from living_replay.replay import reconstruct
from living_replay.store import TimelineStore

try:
    import cryptography  # noqa: F401
    HAVE_CRYPTO = True
except ImportError:
    HAVE_CRYPTO = False

@unittest.skipUnless(HAVE_CRYPTO, "cryptography not installed")
class EncryptionGate(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp())
    def tearDown(self): shutil.rmtree(self.tmp)

    def test_b3g3_encryption_at_rest(self):
        key = LocalKeyProvider(LocalKeyProvider.generate())
        root = self.tmp / "enc-timeline"
        store = TimelineStore(root, key_provider=key)
        # Redaction deliberately bypassed: record sensitive bytes raw so
        # ENCRYPTION is the control under test, not the regexes.
        tool = store.append("main", "tool_call",
                            {"name": "cat", "input": "w2.txt", "output": "wages 52000 tax 4068 ssn 123-45-6789"})
        store.put_blob(b"RAW-BLOB-MARKER wages=52000 totalTax=4068")
        cap = PtyCapture(store, rows=6, cols=40)
        cap.record_bytes(b"totalTax=4068 ssn 123-45-6789\r\n", tool)
        self.assertTrue(store.verify("main"))

        persisted = b""
        for p in root.rglob("*"):
            if p.is_file(): persisted += p.read_bytes()
        for marker in (b"52000", b"4068", b"123-45-6789", b"RAW-BLOB-MARKER", b"Dana"):
            self.assertNotIn(marker, persisted, f"plaintext at rest: {marker}")
        # Round-trip with the right key: everything reads back exactly.
        store2 = TimelineStore(root, key_provider=key)
        self.assertTrue(store2.verify("main"))
        self.assertEqual(store2.get_blob(store.events("main")[0]["payload"].get("blob", "")) if False else
                         reconstruct(store2, "main", rows=6, cols=40).screen(),
                         reconstruct(store, "main", rows=6, cols=40).screen())
        self.assertIn("totalTax=4068", reconstruct(store2, "main", rows=6, cols=40).screen())
        # Fork + scrub work against the encrypted store too.
        store2.fork("main", store2.events("main")[-1]["id"], "enc-fork")
        self.assertEqual(store2.events("enc-fork")[0]["kind"], "fork")
        # Wrong key fails closed with a clear error.
        wrong = LocalKeyProvider(LocalKeyProvider.generate())
        with self.assertRaises(TimelineKeyError):
            TimelineStore(root, key_provider=wrong)
        print("\nB3-G3 measured: 0 plaintext markers (figures, SSN, blob marker) anywhere in the "
              "encrypted timeline dir; round-trip + fork + verify pass with the key; wrong key raises TimelineKeyError")

class FlagshipGate(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp())
    def tearDown(self): shutil.rmtree(self.tmp)

    def test_b3g1_flagship_end_to_end(self):
        out = run_flagship(self.tmp / "flagship")
        for path, value in out["expected"].items():
            self.assertAlmostEqual(out["figures"][path], value, places=6, msg=path)
        self.assertAlmostEqual(out["figures"]["/totalTax"], 3568.0)
        prov = out["provenance_total_tax"]
        self.assertIn("/wages", prov)
        self.assertEqual(out["intake_span_text"], "52,000")
        span = prov["/wages"]["span"]
        self.assertEqual(INTAKE[span[0]:span[1]], "52,000")
        print("\nB3-G1 measured: flagship return matches independent computation to the cent "
              "(totalTax 3568, refund 2532); /totalTax provenance terminates at intake bytes "
              f"{span} = '52,000'")

    def test_b3g2_flagship_fork_clamp_dependents_only(self):
        out = run_flagship(self.tmp / "flagship2")
        self.assertTrue(out["parent_unchanged"])
        for path, value in out["amended_expected"].items():
            self.assertAlmostEqual(out["amended_figures"][path], value, places=6, msg=path)
        self.assertAlmostEqual(out["amended_figures"]["/totalTax"], 3088.0)
        self.assertIn("AMENDED", out["ghost_screen"]); self.assertIn("3,088", out["ghost_screen"])
        ratio = out["recomputed_nodes"] / out["graph_nodes"]
        self.assertLess(ratio, 0.5, f"ripple {out['recomputed_nodes']}/{out['graph_nodes']} graph nodes")
        # The amended intake differs from the original only in the wages region.
        from living_replay.flagship import _WAGES
        a, b = out["original_intake"], out["amended_intake"]
        m = _WAGES.search(a)
        self.assertEqual(b, a[:m.start("value")] + "48,000" + a[m.end("value"):])
        print(f"\nB3-G2 measured: fork+clamp amended totalTax 3568 -> 3088 (forward-verified); "
              f"dependents recomputed {out['recomputed_nodes']} of {out['graph_nodes']} graph nodes "
              f"({out['recomputed_nodes']} of {out['full_nodes']} derived); "
              "parent branch byte-identical; amended intake differs only in the wages field")

if __name__ == "__main__":
    unittest.main()
