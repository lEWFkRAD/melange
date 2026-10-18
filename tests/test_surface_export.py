"""Static surface export: the flagship example, baked — and a guard.

surface-export/ is a self-contained copy of the surface that can be
opened from file:// or any static host. Its content rules are hard:

- ONLY the flagship recording (the synthetic Dana Ruiz return) may
  be in it. No desktop-real store, no build2 live session, no other
  store id, under any name.
- NO key material or key-file references (master.b64, key.json).
- The controls that would change the recording (note, fork, clamp,
  explain via the baked refusals; promote/demote/narrate via the
  locking script and the shim's 403) must carry the live-service
  wording — a baked copy must never look able to save a change.

These tests pin those rules so a future rebuild of the export cannot
silently widen what it contains. Regenerate with:
  tools/build_surface_export.py
"""
import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
EXPORT = REPO / "surface-export"

LIVE_WORDING = "This needs the live Melange service"
FORBIDDEN = ["desktop-real", "build2", "master.b64", "key.json"]


def baked() -> dict:
    text = (EXPORT / "baked-data.js").read_text()
    m = re.search(r"window\.MELANGE_BAKED = (\{.*\});\s*$", text, re.S)
    assert m, "baked-data.js does not carry the baked object"
    return json.loads(m.group(1))


class TestSurfaceExport(unittest.TestCase):
    def test_export_files_exist(self):
        for name in ("index.html", "baked-data.js", "README.md"):
            self.assertTrue((EXPORT / name).is_file(), name)

    def test_no_forbidden_content_anywhere_in_the_folder(self):
        for path in sorted(EXPORT.rglob("*")):
            if path.is_file():
                text = path.read_text(errors="replace").lower()
                for bad in FORBIDDEN:
                    self.assertNotIn(
                        bad, text,
                        f"{bad!r} found in surface-export/{path.name}")

    def test_only_the_flagship_store_is_baked(self):
        data = baked()
        self.assertEqual([s["id"] for s in data["stores"]], ["flagship"])
        self.assertEqual([c["id"] for c in data["shelf"]], ["flagship"])
        self.assertEqual(set(data["details"]),
                         {"main", "ghost-corrected-w2"})

    def test_browsing_data_is_complete_for_both_branches(self):
        data = baked()
        for branch, detail in data["details"].items():
            self.assertEqual(detail["kind"], "session")
            steps = data["steps"][branch]
            self.assertEqual(len(steps), detail["steps"], branch)
            for n in range(1, detail["steps"] + 1):
                self.assertIn("screen", steps[str(n)])
                grid = data["wherefrom"][branch][str(n)]["grid"]
                self.assertTrue(grid and grid[0], (branch, n))
        lanes = {lane["branch"] for lane in data["map"]["lanes"]}
        self.assertEqual(lanes, {"main", "ghost-corrected-w2"})

    def test_write_controls_are_locked_with_the_live_wording(self):
        data = baked()
        for branch, detail in data["details"].items():
            for op in ("annotate", "fork", "clamp"):
                self.assertIn(LIVE_WORDING,
                              detail["refusals"].get(op, ""), (branch, op))
        page = (EXPORT / "index.html").read_text()
        self.assertIn(LIVE_WORDING, page)               # shim + locks
        self.assertIn("wrap('renderShelfPanel'", page)  # promote/demote
        self.assertIn("wrap('renderNarration'", page)   # narration
        self.assertIn("Static export", page)            # honest label

    def test_readme_states_the_terms(self):
        readme = (EXPORT / "README.md").read_text()
        self.assertIn("synthetic", readme)
        self.assertIn("GitHub Pages", readme)
        self.assertIn("private", readme)


if __name__ == "__main__":
    unittest.main()
