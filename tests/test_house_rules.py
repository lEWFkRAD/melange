"""M7 regression test: house rules (pins) on the real workbook store.

Reproduces the M7 pin demo (melange-smalls/M7/pin_demo.py) as a test,
against a TEMP COPY of the shipped workbook store — the original is
never opened for writing:

- the copy verifies as received, and still verifies after two pins are
  appended as `edit` events (threshold_limit stays 40000, withholding
  stays 6100);
- both rules read back as Holding against the finished book's values;
- a checked fork clamping wages 52000 -> 48000 is ACCEPTED (pins hold),
  inherits both pins, audits clean, and recomputes tax 3088 / refund
  3012 through the workbook profile's incremental Engine;
- a checked fork clamping withholding 6100 -> 5000 is REJECTED before
  creation, the violation is reported by name, and the branch does not
  exist afterwards;
- the store still verifies at the end.

The workbook profile (formula graph + Engine adapter) lives with the
Excel lane's artifacts; the test locates it under
~/workspace/your_files/melange-excel (override with MELANGE_EXCEL_DIR)
and skips if the artifacts are absent.
"""
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

EXCEL_DIR = Path(os.environ.get(
    "MELANGE_EXCEL_DIR",
    Path.home() / "workspace" / "your_files" / "melange-excel"))
BRANCH = "return-workbook"

# The workbook profile needs openpyxl, which is a dependency of the Excel
# lane's artifacts, not of this package; treat a missing openpyxl the same
# as missing artifacts and skip.
HAVE_ARTIFACTS = (EXCEL_DIR / "store").is_dir() and \
    (EXCEL_DIR / "workbook_profile.py").is_file() and \
    (EXCEL_DIR / "melange-fixture.xlsx").is_file() and \
    importlib.util.find_spec("openpyxl") is not None

if HAVE_ARTIFACTS:
    sys.path.insert(0, str(EXCEL_DIR))


@unittest.skipUnless(HAVE_ARTIFACTS, "melange-excel artifacts not present")
class HouseRulesWorkbookTest(unittest.TestCase):
    def setUp(self):
        import workbook_profile as wp
        from living_replay.store import TimelineStore
        self.wp = wp
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        self.copy_root = Path(tmp) / "workbook-store"
        shutil.copytree(EXCEL_DIR / "store", self.copy_root)
        self.store = TimelineStore(self.copy_root)
        frames = [e["payload"] for e in self.store.events(BRANCH)
                  if e["kind"] == "cell_frame"]
        self.finished = frames[-1]["values"]
        self.base_inputs = {k: self.finished[k] for k in
                            ("wages", "withholding", "other_income",
                             "threshold_limit")}
        self.model = wp.load_model(EXCEL_DIR / "melange-fixture.xlsx")

    def evaluate(self, overrides):
        eng = self.wp.build_engine(self.model, self.base_inputs)
        values = eng.build()
        for target, value in overrides.items():
            values = eng.edit(target, value)
        return values

    def test_pins_hold_and_gate_forks(self):
        from living_replay import bridge, house_rules

        store, BR = self.store, BRANCH
        self.assertTrue(store.verify(BR))
        self.assertEqual(self.finished["tax"], 3568)
        self.assertEqual(self.finished["refund"], 2532)

        store.typed_edit(BR, "pin", "threshold_limit", 40000)
        store.typed_edit(BR, "pin", "withholding", 6100)
        self.assertTrue(store.verify(BR), "seal must survive pin appends")

        rules = house_rules.house_rules(store, BR, self.evaluate({}))
        self.assertEqual({r["target"] for r in rules},
                         {"threshold_limit", "withholding"})
        for r in rules:
            self.assertEqual(r["status"], "Holding", r)
            self.assertEqual(r["current"], r["pinned"], r)

        tip = store.events(BR)[-1]["id"]

        ok = house_rules.checked_fork(
            store, BR, tip, "whatif-wages-48000",
            "Change this step: wages corrected to 48,000",
            {"wages": 48000}, self.evaluate)
        self.assertTrue(ok["accepted"], ok)
        self.assertEqual(ok["violations"], [])
        self.assertEqual(ok["pins_inherited"],
                         {"threshold_limit": 40000, "withholding": 6100})
        self.assertEqual(ok["candidate"]["tax"], 3088)
        self.assertEqual(ok["candidate"]["refund"], 3012)
        names = [v["name"] for v in bridge.versions(store)]
        self.assertIn("whatif-wages-48000", names)

        bad = house_rules.checked_fork(
            store, BR, tip, "whatif-withholding-5000",
            "Change this step: withholding to 5,000",
            {"withholding": 5000}, self.evaluate)
        self.assertFalse(bad["accepted"])
        self.assertEqual(bad["violations"], ["withholding"])
        self.assertIn("withholding", bad["reason"])
        names = [v["name"] for v in bridge.versions(store)]
        self.assertNotIn("whatif-withholding-5000", names)

        self.assertTrue(store.verify(BR))
        self.assertTrue(store.verify("whatif-wages-48000"))


if __name__ == "__main__":
    unittest.main()
