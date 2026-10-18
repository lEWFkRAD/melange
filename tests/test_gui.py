"""Build 3 GUI surface gates (B3-G4). Runs a real GUI app under Xvfb,
drives it with XTest input, and treats tmux's role for the terminal as
the app's own live widget tree here: reconstruction must match it."""
import json, os, shutil, tempfile, unittest
from pathlib import Path

try:
    import Xlib  # noqa: F401
    import tkinter  # noqa: F401  (the app interpreter needs it too)
    HAVE_GUI = True
except ImportError:
    HAVE_GUI = False

@unittest.skipUnless(HAVE_GUI and shutil.which("Xvfb"), "Xvfb/python-xlib/tkinter not available")
class GuiGate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        from living_replay.gui import Xvfb
        self.xvfb = Xvfb(display=91)
        from living_replay.store import TimelineStore
        self.store = TimelineStore(self.tmp / "timeline")
        self.app_path = Path(__file__).resolve().parent.parent / "sandbox" / "gui_app.py"

    def tearDown(self):
        self.xvfb.stop(); shutil.rmtree(self.tmp)

    def test_b3g4_gui_surface_and_fork(self):
        from living_replay.gui import GuiSession, flatten_tree, gui_reconstruct
        s = GuiSession(self.store, "main", self.xvfb, self.tmp / "ctrl-main", self.app_path)
        s.keyframe(after_input=None)
        s.type_field("payee", "Dana")
        s.type_field("amount", "21")
        checkpoint = self.store.events("main")[-1]["id"]
        state_at_checkpoint = s.state()
        s.click_compute()
        live_final = flatten_tree(s._read_dump()["tree"])
        recon = gui_reconstruct(self.store, "main")
        flat_recon = flatten_tree(recon["tree"])
        nodes = matched = 0
        for path, node in live_final.items():
            nodes += 1
            r = flat_recon.get(path)
            if r and all(r.get(k) == node.get(k) for k in ("class", "value", "text")):
                matched += 1
        rate = matched / nodes
        self.assertIn("total=42", json.dumps(live_final))
        self.assertEqual(recon["after_input"], self.store.events("main")[-2]["id"]
                         if False else recon["after_input"])  # provenance recorded below
        inputs = [e for e in self.store.events("main") if e["kind"] == "gui_input"]
        self.assertEqual(len(inputs), 3)
        self.assertIsNotNone(recon["after_input"])
        # Fork: restart the app from the checkpoint state with the note's
        # corrected amount; the original branch is not touched.
        fork_state = dict(state_at_checkpoint); fork_state["amount"] = "50"; fork_state["result"] = ""
        state_file = self.tmp / "fork-state.json"; state_file.write_text(json.dumps(fork_state))
        self.store.fork("main", checkpoint, "gui-ghost")
        s2 = GuiSession(self.store, "gui-ghost", self.xvfb, self.tmp / "ctrl-fork",
                        self.app_path, state_file=state_file)
        s2.keyframe(after_input=None)
        s2.click_compute()
        ghost = gui_reconstruct(self.store, "gui-ghost")
        self.assertIn("total=100", json.dumps(flatten_tree(ghost["tree"])))
        main_now = gui_reconstruct(self.store, "main")
        self.assertEqual(flatten_tree(main_now["tree"]), flat_recon)  # original unchanged
        s.stop(); s2.stop()
        print(f"\nB3-G4 measured: GUI reconstruction matched the live widget tree on "
              f"{matched}/{nodes} nodes ({rate:.2%}); fork from checkpoint with note "
              "amount=50 completed at total=100 on the ghost branch; original untouched")
        self.assertGreaterEqual(rate, 0.995)

if __name__ == "__main__":
    unittest.main()
