import shutil, tempfile, unittest
from pathlib import Path

from living_replay.capture import PtyCapture
from living_replay.grid import Grid
from living_replay.redaction import contains_seeded_secret
from living_replay.replay import provenance, reconstruct
from living_replay.store import TimelineStore
from living_replay.edits import apply_clamp, check_pins, explain

class BuildOneTests(unittest.TestCase):
    def setUp(self): self.tmp=Path(tempfile.mkdtemp())
    def tearDown(self): shutil.rmtree(self.tmp)
    def store(self): return TimelineStore(self.tmp / "timeline")

    def test_g1_replay_matches_reference_grid(self):
        store=self.store(); capture=PtyCapture(store, rows=4, cols=20)
        script=b"alpha\r\n\x1b[2;1Hbeta\x1b[K\r\n\x1b[1;1Homega"
        tool=store.append("main","tool_call",{"name":"synthetic-shell","input":"fixture","output":"recorded"})
        capture.record_bytes(script, tool)
        reference=Grid(4,20); reference.feed(script, 2, tool, 0)
        self.assertEqual(reconstruct(store,"main",rows=4,cols=20).screen(), reference.screen())
        self.assertTrue(store.verify("main"))

    def test_own_pty_records_real_child_output(self):
        store=self.store(); capture=PtyCapture(store,rows=2,cols=20)
        self.assertEqual(capture.run(["bash","-lc","printf 'pty-owned'"],timeout=3),0)
        self.assertIn("pty-owned",reconstruct(store,"main",rows=2,cols=20).screen())

    def test_g1_hundred_sampled_frames_match_ground_truth(self):
        store=self.store(); capture=PtyCapture(store,rows=4,cols=25)
        samples=[]
        for n in range(100):
            eid=capture.record_bytes(f"{n:03d} ".encode())
            samples.append((eid,capture.grid.screen()))
        matches=sum(reconstruct(store,"main",eid,4,25).screen()==truth for eid,truth in samples)
        self.assertGreaterEqual(matches/len(samples),.995, f"fidelity={matches/len(samples):.3%}")

    def test_g2_cell_resolves_to_owning_tool(self):
        store=self.store(); capture=PtyCapture(store, rows=2, cols=20)
        tool=store.append("main","tool_call",{"name":"cat","input":"synthetic.txt","output":"hello"})
        event=capture.record_bytes(b"hello",tool)
        cause=provenance(store,"main",event,0,1)
        self.assertEqual(cause["tool_event"],tool); self.assertTrue(cause["attributed"])
        self.assertFalse(provenance(store,"main",event,1,1)["attributed"])

    def test_g3_branch_is_immutable_and_context_is_pinned(self):
        store=self.store(); capture=PtyCapture(store, rows=2, cols=20)
        checkpoint=capture.record_bytes(b"base")
        before=store.events("main")
        fork=store.fork("main",checkpoint,"fork-1",{"kind":"clamp","target":"answer","value":42})
        store.append("fork-1","context_note",{"text":"Inject context","pinned":True},parent_event=fork)
        inherited=reconstruct(store,"main",checkpoint,2,20)
        capture2=PtyCapture(store,"fork-1",rows=2,cols=20,grid=inherited,offset=4); capture2.record_bytes(b" done")
        self.assertEqual(store.events("main"),before); self.assertTrue(store.verify("fork-1"))
        self.assertTrue(reconstruct(store,"fork-1",rows=2,cols=20).screen().startswith("base done"))

    def test_g4_secrets_never_reach_storage(self):
        seeded=b"token=sk_FAKE123456789012345 fake-ssn 123-45-6789 password=correct-horse"
        store=self.store(); capture=PtyCapture(store); capture.record_bytes(seeded)
        persisted=(store.root / "timeline.sqlite").read_bytes()+b"".join(p.read_bytes() for p in store.blobs.iterdir())
        self.assertFalse(contains_seeded_secret(persisted)); self.assertIn(b"[REDACTED]",persisted)

    def test_g5_recorded_chunks_replay_without_process_or_model(self):
        store=self.store(); capture=PtyCapture(store,rows=2,cols=20)
        model=store.append("main","model_call",{"prompt":"synthetic","tokens":"hello","replayed":True})
        capture.record_bytes(b"model says hello",model)
        first=reconstruct(store,"main",rows=2,cols=20).screen()
        second=reconstruct(store,"main",rows=2,cols=20).screen()
        self.assertEqual(first,second)

    def test_g6_typed_edits_verify_or_report(self):
        store=self.store()
        def derive(v):
            x=v.get("x",0); out={"x":x,"total":x*2}
            out.update(v.get("__clamps__",{})); return out
        store.typed_edit("main","clamp","total",99)
        self.assertEqual(apply_clamp({"x":2},"total",99,derive)["total"],99)
        self.assertEqual(check_pins({"total":99},{"tax-total":100}),["tax-total"])
        result=explain([("bad",{"x":4}),("good",{"x":5})],"total",10,derive,lambda name,p: "ghost-"+name)
        self.assertEqual(result.branch,"ghost-good"); self.assertEqual(len(result.counterexamples),1)

if __name__ == "__main__": unittest.main()
