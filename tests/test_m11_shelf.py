"""M11: volume doctrine completion — the shelf, the map, the story.

The audit's P14 asks for the shelf as a PLACE (kept What-ifs,
promotable, with how each was made written on it), a spatial dive
(the recording as a map of lanes and steps), and counterfactual
audio (a What-if's story, spoken). This suite pins the contracts:

- promotion/demotion live in the store as 'shelf' events on the
  What-if branch only: they survive reopening the store AND a
  service restart, and the Original's events stay byte-identical;
- provenance names how a kept What-if was made (clamp / explain /
  instruction, and from which parent) from the record itself;
- the shelf listing carries the real facts per version: fidelity
  kind, branch count, seal at request time, and a Golden Path
  standing that is computed where the values are computable and
  reported 'Not checked' where they are not — never guessed;
- the map endpoint builds lanes and positioned steps from real
  events, with markers only where the record has them (a pin step,
  a noted step, a checkpoint another version split from);
- narration composes the branch's story from its figures and, where
  the machine has a speech engine (ffmpeg's flite filter), attaches
  REAL synthesized speech as a blob in the recording. With no
  engine the story is words only and says so — no silent file is
  ever dressed up as speech.

Skips: the audio assertions need ffmpeg with the flite filter; the
surface test needs node + jsdom (harness in /tmp/melange-test).
"""
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import wave
from io import BytesIO
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "service"))

from living_replay import bridge, flagship, ingest, shelf  # noqa: E402
from living_replay.store import TimelineStore  # noqa: E402

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class ShelfStoreCase(unittest.TestCase):
    """A flagship store with a clamp What-if, in a temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="melange-m11-"))
        flagship.run_flagship(self.tmp / "gen")
        self.root = self.tmp / "gen" / "timeline"
        self.store = TimelineStore(self.root)
        made = bridge.clamp(self.store, "main", "/wages", 48000)
        self.assertTrue(made["accepted"])
        self.whatif = made["branch"]

    def reopen(self) -> TimelineStore:
        return TimelineStore(self.root)


class TestProvenance(ShelfStoreCase):
    def test_clamp_branch_provenance(self):
        prov = shelf.provenance(self.store, self.whatif)
        self.assertEqual(prov["parent_branch"], "main")
        self.assertEqual(prov["via"], "clamp")
        self.assertEqual(prov["detail"]["clamped"], {"/wages": 48000})

    def test_explain_ghost_provenance(self):
        out = bridge.explain(self.store, "main", "/refund", 3012)
        ghost = {c["input"]: c for c in out["candidates"]}["/wages"]
        prov = shelf.provenance(self.store, ghost["branch"])
        self.assertEqual(prov["via"], "explain")
        self.assertEqual(prov["detail"]["explained"],
                         {"target": "/refund", "desired": 3012})
        self.assertEqual(prov["detail"]["clamped"], {"/wages": 48000})

    def test_instruction_branch_provenance(self):
        made = bridge.try_differently(
            self.store, "main",
            self.store.replay_events("main")[-1]["id"],
            "whatif-manual", "try the other form")
        prov = shelf.provenance(self.store, made["branch"])
        self.assertEqual(prov["via"], "try-differently")
        self.assertEqual(prov["instruction"], "try the other form")

    def test_original_has_no_provenance(self):
        self.assertIsNone(shelf.provenance(self.store, "main"))


class TestPromotion(ShelfStoreCase):
    def test_promote_persists_and_original_is_untouched(self):
        before = self.store.events("main")
        state = shelf.promote(self.store, self.whatif,
                              "Corrected W-2 wages")
        self.assertTrue(state["kept"])
        self.assertEqual(state["name"], "Corrected W-2 wages")
        # The Original's events are byte-identical and still verify.
        self.assertEqual(self.store.events("main"), before)
        self.assertTrue(self.store.verify("main"))
        # Persistence is the store's, not the process's: a fresh
        # TimelineStore over the same root sees the kept standing.
        again = self.reopen()
        self.assertEqual(shelf.shelf_state(again, self.whatif)["name"],
                         "Corrected W-2 wages")
        self.assertEqual(shelf.kept_branches(again),
                         {self.whatif: "Corrected W-2 wages"})
        self.assertTrue(again.verify(self.whatif))

    def test_promote_original_refused(self):
        with self.assertRaises(ValueError):
            shelf.promote(self.store, "main", "The Original, again")

    def test_promote_needs_a_name(self):
        with self.assertRaises(ValueError):
            shelf.promote(self.store, self.whatif, "   ")

    def test_promote_name_must_be_free_on_the_shelf(self):
        other = bridge.try_differently(
            self.store, "main",
            self.store.replay_events("main")[-1]["id"],
            "whatif-other", "another try")
        shelf.promote(self.store, self.whatif, "Kept answer")
        with self.assertRaises(ValueError):
            shelf.promote(self.store, other["branch"], "Kept answer")

    def test_demote_round_trip(self):
        shelf.promote(self.store, self.whatif, "Kept answer")
        state = shelf.demote(self.store, self.whatif)
        self.assertFalse(state["kept"])
        self.assertIsNone(state["name"])
        again = self.reopen()
        self.assertFalse(shelf.shelf_state(again, self.whatif)["kept"])
        self.assertEqual(shelf.kept_branches(again), {})
        # The branch itself is unharmed by the round trip.
        self.assertTrue(again.verify(self.whatif))
        self.assertEqual(
            shelf.provenance(again, self.whatif)["via"], "clamp")

    def test_demote_what_is_not_kept_refused(self):
        with self.assertRaises(ValueError):
            shelf.demote(self.store, self.whatif)

    def test_kept_standing_is_not_inherited_by_a_fork(self):
        shelf.promote(self.store, self.whatif, "Kept answer")
        child = bridge.try_differently(
            self.store, self.whatif,
            self.store.replay_events(self.whatif)[-1]["id"],
            "whatif-child", "one more try")
        self.assertFalse(
            shelf.shelf_state(self.store, child["branch"])["kept"])


class TestNarrationScript(ShelfStoreCase):
    def test_clamp_story_names_the_change_and_the_figures(self):
        script = shelf.narration_script(self.store, self.whatif)
        self.assertIn("main", script)
        self.assertIn("52,000", script)
        self.assertIn("48,000", script)
        self.assertIn("3,012", script)   # the refund it came out with
        self.assertIn("3,088", script)   # the total tax
        self.assertIn("redid themselves", script)
        self.assertIn("The Original never changes.", script)

    def test_explain_story_names_the_question(self):
        out = bridge.explain(self.store, "main", "/refund", 3012)
        ghost = {c["input"]: c for c in out["candidates"]}["/withholding"]
        script = shelf.narration_script(self.store, ghost["branch"])
        self.assertIn("what went wrong", script)
        self.assertIn("6,580", script)
        self.assertIn("3,012", script)
        self.assertIn("nothing was chosen for you", script)

    def test_original_story(self):
        script = shelf.narration_script(self.store, "main")
        self.assertIn("Original", script)
        self.assertIn("2,532", script)


class TestNarrationAudio(ShelfStoreCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg (flite) not available")
    def test_make_narration_attaches_real_speech(self):
        made = shelf.make_narration(self.store, self.whatif)
        self.assertTrue(made["has_audio"])
        self.assertIn("flite", made["engine"])
        self.assertIsNone(made["audio_note"])
        audio = shelf.narration_audio(self.store, self.whatif)
        self.assertTrue(audio.startswith(b"RIFF"))
        with wave.open(BytesIO(audio)) as wav:
            self.assertGreater(wav.getnframes(), 0)
            self.assertGreater(wav.getframerate(), 0)
        # The narration is IN the recording: a fresh store sees it,
        # with the same audio bytes behind it.
        again = self.reopen()
        narr = shelf.narration(again, self.whatif)
        self.assertEqual(narr["event_id"], made["event_id"])
        self.assertTrue(narr["has_audio"])
        self.assertEqual(
            hashlib.md5(shelf.narration_audio(again, self.whatif)).hexdigest(),
            hashlib.md5(audio).hexdigest())

    def test_no_engine_means_words_only_and_says_so(self):
        with mock.patch.object(shelf, "render_speech",
                               return_value=(None, None)):
            made = shelf.make_narration(self.store, self.whatif)
        self.assertFalse(made["has_audio"])
        self.assertIsNone(made["engine"])
        self.assertEqual(made["audio_note"], shelf.NO_ENGINE_NOTE)
        self.assertIsNone(shelf.narration_audio(self.store, self.whatif))
        narr = shelf.narration(self.store, self.whatif)
        self.assertIn("48,000", narr["script"])
        self.assertFalse(narr["has_audio"])

    def test_render_speech_without_ffmpeg_is_none(self):
        with mock.patch("shutil.which", return_value=None):
            engine, audio = shelf.render_speech("a short story")
        self.assertIsNone(engine)
        self.assertIsNone(audio)


# ------------------------------------------------------------- service

class ServiceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="melange-m11-svc-"))
        flagship.run_flagship(self.tmp / "gen")
        self.root = self.tmp / "gen" / "timeline"
        store = TimelineStore(self.root)
        made = bridge.clamp(store, "main", "/wages", 48000)
        self.whatif = made["branch"]
        # A house rule on the Original, pinned after the clamp split:
        # main holds it; the What-if (split earlier) never inherited it.
        store.typed_edit("main", "pin", "/refund", 2532)
        # A structure recording whose values this service cannot
        # compute: its pin standing must read 'Not checked'.
        struct = TimelineStore(self.tmp / "structstore")
        struct.append("desk", "ingest_profile",
                      {"fidelity": "structure", "source": "test"})
        struct.append("desk", "ax_keyframe", {"blob": "x"})
        struct.typed_edit("desk", "pin", "/anything", 1)
        registry = {"stores": {
            "flag": {"path": str(self.root), "label": "Flagship session"},
            "struct": {"path": str(self.tmp / "structstore"),
                       "label": "Outline recording"}}}
        self.cfg = self.tmp / "stores.json"
        self.cfg.write_text(json.dumps(registry))
        self.port = free_port()
        self.base = f"http://127.0.0.1:{self.port}"
        self.proc = self._start()
        self.addCleanup(self._stop)

    def _start(self):
        env = dict(os.environ, MELANGE_STORES_FILE=str(self.cfg),
                   MELANGE_PORT=str(self.port))
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "service" / "melange_service.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                self.call("GET", "/api/health")
                return proc
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("service did not come up")

    def _stop(self):
        if getattr(self, "proc", None) is not None:
            self.proc.terminate()
            self.proc.wait(timeout=10)
            self.proc = None

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                ctype = resp.headers.get_content_type()
                return resp.status, (json.loads(raw)
                                     if ctype == "application/json" else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw


class TestShelfEndpoint(ServiceCase):
    def test_shelf_lists_every_recording_with_real_facts(self):
        status, shelf_data = self.call("GET", "/api/shelf")
        self.assertEqual(status, 200, shelf_data)
        by_id = {s["id"]: s for s in shelf_data}
        flag = by_id["flag"]
        # main + the flagship's own ghost + the clamp What-if
        self.assertEqual(flag["branch_count"], 3)
        branches = {b["name"]: b for b in flag["branches"]}
        main = branches["main"]
        self.assertEqual(main["fidelity"], "native")
        self.assertTrue(main["seal"])
        self.assertIsNone(main["provenance"])
        self.assertEqual(main["pins"], 1)
        self.assertEqual(main["pin_status"], "Holding")
        whatif = branches[self.whatif]
        self.assertEqual(whatif["provenance"]["via"], "clamp")
        self.assertEqual(whatif["provenance"]["parent_branch"], "main")
        self.assertFalse(whatif["kept"]["kept"])
        struct = by_id["struct"]["branches"][0]
        self.assertEqual(struct["fidelity"], "structure")
        self.assertEqual(struct["pin_status"], "Not checked")

    def test_promote_demote_and_restart_persistence(self):
        status, made = self.call(
            "POST", f"/api/store/flag/branch/{self.whatif}/promote",
            {"name": "Corrected W-2 wages"})
        self.assertEqual(status, 201, made)
        self.assertTrue(made["kept"])
        status, detail = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}")
        self.assertEqual(detail["kept"]["name"], "Corrected W-2 wages")
        # A service restart loses nothing: the standing is the store's.
        self._stop()
        self.proc = self._start()
        status, shelf_data = self.call("GET", "/api/shelf")
        branches = {b["name"]: b
                    for b in {s["id"]: s for s in shelf_data}["flag"]["branches"]}
        self.assertEqual(branches[self.whatif]["kept"]["name"],
                         "Corrected W-2 wages")
        status, gone = self.call(
            "POST", f"/api/store/flag/branch/{self.whatif}/demote", {})
        self.assertEqual(status, 200, gone)
        self.assertFalse(gone["kept"])
        status, detail = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}")
        self.assertFalse(detail["kept"]["kept"])

    def test_promote_original_refused_400(self):
        status, refused = self.call(
            "POST", "/api/store/flag/branch/main/promote", {"name": "x"})
        self.assertEqual(status, 400, refused)
        self.assertIn("Original", refused["error"])


class TestMapEndpoint(ServiceCase):
    def test_map_lanes_steps_and_markers(self):
        status, mp = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}/map")
        self.assertEqual(status, 200, mp)
        lanes = {l["branch"]: l for l in mp["lanes"]}
        self.assertIn("main", lanes)
        self.assertIn(self.whatif, lanes)
        whatif = lanes[self.whatif]
        self.assertFalse(whatif["original"])
        self.assertEqual(whatif["parent_branch"], "main")
        self.assertIsInstance(whatif["split_step"], int)
        main = lanes["main"]
        # The pin typed onto main's tip is a marker on its own step,
        # and the steps the two What-ifs split from are checkpoints.
        marked = {tuple(s["markers"]) for s in main["steps"]}
        self.assertIn(("pin",), marked)
        self.assertTrue(any("checkpoint" in s["markers"]
                            for s in main["steps"]))
        # Every lane's steps are numbered 1..N in order.
        for lane in lanes.values():
            self.assertEqual([s["n"] for s in lane["steps"]],
                             list(range(1, len(lane["steps"]) + 1)))

    def test_map_note_marker_after_note_post(self):
        status, _ = self.call(
            "POST", f"/api/store/flag/branch/{self.whatif}/note",
            {"step": 2, "text": "map test note"})
        self.assertEqual(status, 201)
        status, mp = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}/map")
        lane = {l["branch"]: l for l in mp["lanes"]}[self.whatif]
        self.assertIn("note", lane["steps"][1]["markers"])


class TestNarrationEndpoints(ServiceCase):
    @unittest.skipUnless(HAVE_FFMPEG, "ffmpeg (flite) not available")
    def test_narration_round_trip(self):
        status, made = self.call(
            "POST", f"/api/store/flag/branch/{self.whatif}/narration", {})
        self.assertEqual(status, 201, made)
        self.assertTrue(made["has_audio"])
        self.assertIn("3,012", made["script"])
        status, audio = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}/narration/audio")
        self.assertEqual(status, 200)
        self.assertIsInstance(audio, bytes)
        self.assertTrue(audio.startswith(b"RIFF"))
        status, detail = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}")
        self.assertTrue(detail["narration"]["has_audio"])
        self.assertIn("flite", detail["narration"]["engine"])

    def test_audio_404_before_any_narration(self):
        status, err = self.call(
            "GET", f"/api/store/flag/branch/{self.whatif}/narration/audio")
        self.assertEqual(status, 404, err)


# ------------------------------------------------------------- surface

@unittest.skipUnless(
    shutil.which("node") and
    (Path("/tmp/melange-test/node_modules/jsdom").is_dir()),
    "node/jsdom harness not available")
class TestShelfSurface(ServiceCase):
    def test_surface_shelf_map_and_promotion(self):
        script = self.tmp / "m11-surface-test.mjs"
        script.write_text(SURFACE_TEST_JS)
        env = dict(os.environ,
                   MELANGE_HARNESS_DIR="/tmp/melange-test",
                   MELANGE_BASE=self.base,
                   MELANGE_WHATIF=self.whatif)
        run = subprocess.run(["node", str(script)], env=env,
                             capture_output=True, text=True, timeout=180)
        self.assertEqual(run.returncode, 0,
                         f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")


SURFACE_TEST_JS = r"""
import { createRequire } from 'node:module';
const require = createRequire(process.env.MELANGE_HARNESS_DIR + '/');
const { JSDOM } = require('jsdom');

const BASE = process.env.MELANGE_BASE;
const WHATIF = process.env.MELANGE_WHATIF;
let fails = 0;
const check = (name, cond, det='') => {
  console.log(cond ? 'PASS' : 'FAIL', name, det);
  if (!cond) fails++;
};
const sleep = ms => new Promise(r => setTimeout(r, ms));

function makeCtx() {
  const grad = { addColorStop() {} };
  const base = { createLinearGradient: () => grad, createRadialGradient: () => grad,
                 measureText: () => ({ width: 42 }), canvas: null };
  return new Proxy(base, { get: (t, p) => (p in t ? t[p] : (() => {})),
                           set: () => true });
}

async function loadPage() {
  const html = await (await fetch(BASE + '/')).text();
  return new JSDOM(html, { runScripts: 'dangerously', url: BASE + '/',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.Element.prototype.scrollIntoView = function () {};
      window.HTMLCanvasElement.prototype.getContext = function () { return makeCtx(); };
      window.fetch = (u, o) => fetch(new URL(u, BASE).href, o);
    } });
}
async function waitFor(fn, timeout = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (fn()) return true;
    await sleep(200);
  }
  return false;
}

const dom = await loadPage();
const d = dom.window.document;

// the shelf is a place the page lands on, fed by /api/shelf
check('shelf view shows on landing',
      await waitFor(() => !d.querySelector('#shelf-view').hidden), '');
check('shelf cards name the recordings',
      await waitFor(() => d.querySelector('#shelf-cards').textContent.includes('Flagship session')),
      d.querySelector('#shelf-cards').textContent.slice(0, 120));

// open the clamp What-if from its shelf card
const openBtn = [...d.querySelectorAll('#shelf-cards button[data-branch]')]
  .find(b => b.dataset.branch === WHATIF);
check('shelf card offers the What-if', !!openBtn, '');
openBtn.click();
check('the What-if opens from the shelf',
      await waitFor(() => d.querySelector('#fork-badge') &&
                           !d.querySelector('#fork-badge').hidden), '');

// the spatial map renders lanes and steps from the /map data
check('map renders step marks',
      await waitFor(() => d.querySelectorAll('#map-box .map-step').length >= 9),
      'marks=' + d.querySelectorAll('#map-box .map-step').length);
const readout = () => d.querySelector('#readout').textContent;
const step3 = [...d.querySelectorAll('#map-box .map-step')]
  .find(c => c.dataset.branch === WHATIF && c.dataset.step === '3');
check('map has a step 3 mark for this version', !!step3, '');
step3.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
check('clicking a map step dives to it',
      await waitFor(() => /Step 3 of/.test(readout())), readout());

// promotion from the surface
check('shelf panel says not kept yet',
      /not on the shelf/.test(d.querySelector('#shelf-status').textContent),
      d.querySelector('#shelf-status').textContent);
d.querySelector('#shelf-name').value = 'Kept from the surface test';
d.querySelector('#btn-promote').click();
check('promotion shows in the panel',
      await waitFor(() => /Kept on the shelf as/.test(d.querySelector('#shelf-status').textContent)),
      d.querySelector('#shelf-status').textContent);
check('the shelf itself learns the kept name',
      await waitFor(() => d.querySelector('#shelf-cards').textContent.includes('Kept from the surface test')),
      '');
dom.window.close();

console.log(fails ? fails + ' M11 SURFACE FAILURES' : 'ALL M11 SURFACE CHECKS PASSED');
process.exit(fails ? 1 : 0);
"""


if __name__ == "__main__":
    unittest.main()
