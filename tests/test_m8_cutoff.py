"""M8: the model-layer early cutoff, measured (P7 refinement).

The harness in living_replay.cutoff force-recomputes every invalidated
node and compares canonical bytes (node layer), and recomputes every
recorded model call's context bytes under a counterfactual rewrite of
the record (session layer). These tests pin the measured numbers on
the corpora that exist in this repo, cross-check the node layer
against the shipped Engine's own execution counts (B2-G6/B2-G6b's
42-of-93 must reproduce), and assert the forced walk is sound: its
final state equals a real edit's final state, every time.
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from living_replay import cutoff, flagship  # noqa: E402
from living_replay.incremental import Engine  # noqa: E402

WAGES_CHAIN = ["/agi", "/taxableIncome", "/taxBeforeCredits", "/credit",
               "/totalTax", "/refund"]


class TestNodeLayerFlagship(unittest.TestCase):
    def setUp(self):
        self.engine = cutoff.flagship_engine()

    def test_wages_clamp_one_identical_node(self):
        row = cutoff.node_cutoff(self.engine, "/wages", 48000.0)
        self.assertEqual(row["invalidated"], WAGES_CHAIN)
        # The phase-out credit absorbs the change: agi 48,000 is still
        # under the 75,000 threshold, so /credit recomputes to the
        # recorded 200 — byte-identical. Everything else moves.
        self.assertEqual(row["byte_identical"], ["/credit"])
        self.assertEqual(row["changed_n"], 5)
        self.assertEqual(row["byte_identical_fraction"], 1 / 6)
        # The sink (/refund) is last in topo order and changed, so
        # nothing sits after the cutoff: the tail is empty.
        self.assertEqual(row["cutoff_position"], 6)
        self.assertEqual(row["tail_stoppable_n"], 0)
        self.assertEqual(row["engine_executed_n"], 6)

    def test_threshold_crossing_leaves_nothing_identical(self):
        row = cutoff.node_cutoff(self.engine, "/wages", 76000.0)
        self.assertEqual(row["byte_identical"], [])
        self.assertEqual(row["changed_n"], 6)  # /credit flips 200 -> 0

    def test_noop_edit_is_all_identical(self):
        row = cutoff.node_cutoff(self.engine, "/wages", 52000.0)
        self.assertEqual(row["changed"], [])
        self.assertEqual(row["byte_identical_n"], 6)
        self.assertEqual(row["cutoff_position"], 0)
        self.assertEqual(row["tail_stoppable_n"], 6)
        self.assertEqual(row["engine_executed_n"], 0)

    def test_type_sensitivity_of_byte_identity(self):
        # The recorded wages is a float (lens-extracted). The same
        # number as an int is different canonical bytes, so the
        # measurement counts the int-typed chain head as changed even
        # though == would call it equal. Documented behavior: byte
        # identity is the stricter, conservative standard.
        row = cutoff.node_cutoff(self.engine, "/wages", 52000)
        self.assertIn("/agi", row["changed"])

    def test_forced_walk_matches_real_engine(self):
        for target, value in cutoff.FLAGSHIP_EDITS:
            fresh = cutoff.flagship_engine()
            row = cutoff.node_cutoff(fresh, target, value)
            real = cutoff.flagship_engine()
            expected = real.edit(target, value)
            self.assertEqual(row["final_values"], expected,
                             f"forced walk diverged on {target}={value}")
            self.assertEqual(row["engine_executed_n"], real.executed,
                             f"executed-count simulation diverged on "
                             f"{target}={value}")

    def test_unknown_input_refused(self):
        with self.assertRaises(ValueError):
            cutoff.node_cutoff(self.engine, "/nope", 1)


class TestNodeLayerCorpus93(unittest.TestCase):
    def test_gate_edit_reproduces_b2g6b(self):
        e = cutoff.corpus_engine()
        self.assertEqual(len(e.fns), 93)
        row = cutoff.node_cutoff(e, "A", tuple(x + 999 for x in range(32)))
        # B2-G6/B2-G6b ground truth on this corpus: the shipped engine
        # executes 42 of 93; exactly one executed node (flag) comes out
        # identical and blocks the 11-node gated chain — which a forced
        # recompute confirms are ALL byte-identical.
        self.assertEqual(row["engine_executed_n"], 42)
        self.assertEqual(row["invalidated_n"], 53)
        self.assertEqual(row["byte_identical"],
                         ["flag"] + [f"s{i}" for i in range(11)])
        self.assertEqual(row["changed_n"], 41)
        self.assertEqual(row["cutoff_position"], 53)  # the join, last
        fresh = cutoff.corpus_engine()
        self.assertEqual(row["final_values"],
                         fresh.edit("A", tuple(x + 999 for x in range(32))))

    def test_flag_crossing_edit_ripples_fully(self):
        row = cutoff.node_cutoff(cutoff.corpus_engine(), "A",
                                 tuple(x + 1_000_001 for x in range(32)))
        self.assertEqual(row["byte_identical"], [])
        self.assertEqual(row["engine_executed_n"], 53)

    def test_b_edit_never_touches_a_chain(self):
        row = cutoff.node_cutoff(cutoff.corpus_engine(), "B",
                                 tuple(x + 7 for x in range(100, 132)))
        self.assertEqual(row["invalidated_n"], 41)  # b1..b40 + join
        self.assertEqual(row["changed_n"], 41)


class TestSessionLayerScripted(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store = cutoff.record_scripted_session(self.tmp / "s")
        self.rows = {r["scenario"]: r
                     for r in cutoff.scripted_scenarios(self.store)}

    def test_identity_replays_everything(self):
        row = self.rows["identity (sanity)"]
        self.assertEqual(row["model_calls"], 3)
        self.assertEqual(row["replayable"], 3)
        self.assertIsNone(row["cutoff_index"])

    def test_cutoff_tracks_the_edited_events_position(self):
        first = self.rows["correct the amount (first event)"]
        self.assertEqual((first["replayable"], first["cutoff_index"]), (0, 0))
        mid = self.rows["correct the rate (mid-session)"]
        self.assertEqual((mid["replayable"], mid["cutoff_index"]), (1, 1))
        late = self.rows["correct the final print (after two calls)"]
        self.assertEqual((late["replayable"], late["cutoff_index"]), (2, 2))
        print("\nM8 measured (scripted session, 3 model calls): replayable "
              "fraction is 0/3, 1/3, 2/3, 3/3 as the corrected event moves "
              "from before call 1 to after call 3 — the cutoff is exactly "
              "the first call whose recorded context contains the edit")


class TestSessionLayerFlagshipStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.result = flagship.run_flagship(self.tmp / "flag")
        self.rows = {r["scenario"]: r for r in
                     cutoff.flagship_store_scenarios(self.result["store"])}

    def test_intake_corrections_land_before_the_only_call(self):
        for name in ("correct wages in the intake (lens)",
                     "correct withholding in the intake (lens)"):
            row = self.rows[name]
            self.assertEqual(row["model_calls"], 1)
            self.assertEqual(row["replayable"], 0)
            self.assertEqual(row["cutoff_index"], 0)

    def test_post_call_correction_leaves_the_call_replayable(self):
        row = self.rows["correct the printout (after the call)"]
        self.assertEqual(row["replayable"], 1)
        self.assertIsNone(row["cutoff_index"])
        print("\nM8 measured (flagship store, 1 model call): both intake "
              "corrections put the cutoff at the only call (0 of 1 "
              "replayable); a correction after the call leaves it "
              "replayable (1 of 1) — with n=1 the position effect is "
              "all-or-nothing, which is itself the finding for this store")


if __name__ == "__main__":
    unittest.main()
