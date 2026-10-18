"""M3 tests: the bridge as a live service + the served surface.

Spins service/melange_service.py on an ephemeral port against TEMP
COPIES of the shipped stores (the originals are never opened for
writing), plus a flagship store generated into the temp dir. Asserts:

- health and the store list come from the registry;
- a branch's seal is store.verify() at request time (true at open);
- a desktop step returns the frame bytes, md5-equal to the store's;
- a note POSTed through the API is a real annotation event in the
  store afterwards (checked by reopening the store directly) and
  appears in the branch GET;
- a fork POST on the workbook makes a real new branch and leaves the
  original's events untouched;
- a clamp fork on the pinned workbook copy that breaks a house rule
  (withholding 6100 -> 5000) is refused 422 with the rule NAMED, and
  the honest clamp (wages -> 48000) lands with tax 3088 / refund 3012;
- a tampered store copy reports seal:false in a normal 200 response;
- fidelity gates hold server-side: fork and where-from on the
  screen-only desktop branch are refused 403 with the library's reason;
- the served surface (jsdom, via node) builds its tabs from the API,
  shows the seal the API reported, plays/scrubs from fetched steps,
  round-trips a note — and with the API down shows the unreachable
  state with zero recording data.

Skips: the surface test needs node + jsdom (harness in
/tmp/melange-test); the whole module needs the shipped stores under
~/workspace/your_files.
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
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
YOUR_FILES = Path(os.environ.get("MELANGE_YOUR_FILES",
                                 Path.home() / "workspace" / "your_files"))
EXCEL_DIR = YOUR_FILES / "melange-excel"
HAVE_STORES = (YOUR_FILES / "melange-desktop-video" / "store").is_dir() \
    and (EXCEL_DIR / "store").is_dir() \
    and (YOUR_FILES / "melange-smalls" / "M7" / "workbook-store-pinned").is_dir()


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def service_python() -> str:
    """First interpreter that can import living_replay + openpyxl."""
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    for cand in [sys.executable, shutil.which("python3")]:
        if not cand:
            continue
        probe = subprocess.run(
            [cand, "-c", "import living_replay, openpyxl"],
            env=env, capture_output=True)
        if probe.returncode == 0:
            return cand
    return sys.executable


@unittest.skipUnless(HAVE_STORES, "shipped Melange stores not present")
class ServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="melange-service-test-"))
        copies = {}
        for sid, src in [
                ("desktop-real", YOUR_FILES / "melange-desktop-video" / "store"),
                ("tamper-target", YOUR_FILES / "melange-desktop-video" / "store"),
                ("workbook", EXCEL_DIR / "store"),
                ("workbook-pinned",
                 YOUR_FILES / "melange-smalls" / "M7" / "workbook-store-pinned")]:
            dst = cls.tmp / sid
            shutil.copytree(src, dst)
            copies[sid] = dst
        cls.copies = copies
        registry = {"stores": {
            "desktop-real": {"label": "Hermes desktop (real)",
                             "path": str(copies["desktop-real"])},
            "tamper-target": {"label": "Tamper target",
                              "path": str(copies["tamper-target"])},
            "flagship": {"label": "Flagship demo", "generate": "flagship",
                         "path": str(cls.tmp / "flagship" / "timeline")},
            "workbook": {"label": "Workbook",
                         "path": str(copies["workbook"]),
                         "profile_dir": str(EXCEL_DIR),
                         "fixture": str(EXCEL_DIR / "melange-fixture.xlsx")},
            "workbook-pinned": {"label": "Workbook, with house rules",
                                "path": str(copies["workbook-pinned"]),
                                "profile_dir": str(EXCEL_DIR),
                                "fixture": str(EXCEL_DIR / "melange-fixture.xlsx")},
        }}
        cls.registry_file = cls.tmp / "stores.json"
        cls.registry_file.write_text(json.dumps(registry))
        cls.port = free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = dict(os.environ,
                   PYTHONPATH=f"{REPO / 'src'}:{REPO / 'service'}",
                   MELANGE_STORES_FILE=str(cls.registry_file),
                   MELANGE_PORT=str(cls.port))
        cls.proc = subprocess.Popen(
            [service_python(), str(REPO / "service" / "melange_service.py")],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                cls.call("GET", "/api/health")
                break
            except Exception:
                if cls.proc.poll() is not None:
                    out = cls.proc.stdout.read().decode(errors="replace")
                    raise RuntimeError(f"service exited early:\n{out}")
                time.sleep(0.25)
        else:
            raise RuntimeError("service did not come up")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @classmethod
    def call(cls, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            cls.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                ctype = resp.headers.get_content_type()
                return resp.status, (json.loads(raw) if ctype == "application/json"
                                     else raw)
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, raw

    # -- API ------------------------------------------------------------
    def test_health(self):
        status, data = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["stores"], 5)

    def test_stores_list(self):
        status, stores = self.call("GET", "/api/stores")
        self.assertEqual(status, 200)
        by_id = {s["id"]: s for s in stores}
        self.assertEqual(set(by_id), {"desktop-real", "tamper-target",
                                      "flagship", "workbook", "workbook-pinned"})
        desk = by_id["desktop-real"]["branches"][0]
        self.assertEqual(desk["fidelity"], "screen-only")
        self.assertEqual(desk["kind"], "video")
        self.assertEqual(desk["steps"], 16)
        wb = by_id["workbook"]["branches"][0]
        self.assertEqual(wb["kind"], "workbook")
        self.assertEqual(wb["steps"], 5)

    def test_branch_seal_true_at_open(self):
        for sid, branch in [("desktop-real", "desktop-real"),
                            ("workbook", "return-workbook"),
                            ("flagship", "main")]:
            status, detail = self.call("GET", f"/api/store/{sid}/branch/{branch}")
            self.assertEqual(status, 200, (sid, detail))
            self.assertTrue(detail["seal"], sid)
            self.assertEqual(detail["steps"],
                             {"desktop-real": 16, "workbook": 5,
                              "flagship": detail["steps"]}[sid])

    def test_desktop_step_bytes_match_store(self):
        sys.path.insert(0, str(REPO / "src"))
        from living_replay import bridge
        from living_replay.store import TimelineStore
        store = TimelineStore(self.copies["desktop-real"])
        expect = bridge.frame_at(store, "desktop-real", 2)
        status, raw = self.call(
            "GET", "/api/store/desktop-real/branch/desktop-real/step/3")
        self.assertEqual(status, 200)
        self.assertIsInstance(raw, bytes)
        self.assertEqual(hashlib.md5(raw).hexdigest(),
                         hashlib.md5(expect).hexdigest())

    def test_note_round_trip_is_a_real_store_event(self):
        sys.path.insert(0, str(REPO / "src"))
        from living_replay.store import TimelineStore
        text = "M3 test note — written through the service"
        status, made = self.call(
            "POST", "/api/store/desktop-real/branch/desktop-real/note",
            {"step": 3, "text": text})
        self.assertEqual(status, 201, made)
        store = TimelineStore(self.copies["desktop-real"])
        notes = [e for e in store.events("desktop-real")
                 if e["kind"] == "annotation"]
        self.assertTrue(any(e["payload"]["text"] == text for e in notes),
                        "note must exist as an annotation event in the store")
        self.assertEqual(notes[-1]["id"], made["event_id"])
        status, detail = self.call(
            "GET", "/api/store/desktop-real/branch/desktop-real")
        self.assertIn(text, [n["text"] for n in detail["notes"]])

    def test_workbook_fork_makes_branch_original_untouched(self):
        sys.path.insert(0, str(REPO / "src"))
        from living_replay.store import TimelineStore
        store = TimelineStore(self.copies["workbook"])
        before = len(store.events("return-workbook"))
        status, made = self.call(
            "POST", "/api/store/workbook/branch/return-workbook/fork",
            {"note": "M3 test What-if"})
        self.assertEqual(status, 201, made)
        store2 = TimelineStore(self.copies["workbook"])
        self.assertEqual(len(store2.events("return-workbook")), before)
        self.assertTrue(store2.events(made["branch"]))
        self.assertTrue(store2.verify(made["branch"]))

    def test_clamp_fork_accepted_with_values(self):
        status, made = self.call(
            "POST", "/api/store/workbook-pinned/branch/return-workbook/fork",
            {"clamp": {"cell": "wages", "value": 48000}})
        self.assertEqual(status, 201, made)
        self.assertTrue(made["accepted"])
        self.assertEqual(made["values"]["tax"], 3088)
        self.assertEqual(made["values"]["refund"], 3012)

    def test_clamp_fork_rejected_by_named_house_rule(self):
        status, refused = self.call(
            "POST", "/api/store/workbook-pinned/branch/return-workbook/fork",
            {"clamp": {"cell": "withholding", "value": 5000}})
        self.assertEqual(status, 422, refused)
        self.assertFalse(refused["accepted"])
        self.assertEqual(refused["violations"], ["withholding"])
        self.assertIn("withholding", refused["reason"])
        self.assertIn("must stay 6100", refused["reason"])
        status, stores = self.call("GET", "/api/stores")
        pinned = {s["id"]: s for s in stores}["workbook-pinned"]
        self.assertNotIn("whatif-withholding-5000",
                         [b["name"] for b in pinned["branches"]])

    def test_tampered_store_reports_seal_false_not_error(self):
        import sqlite3
        db = sqlite3.connect(self.copies["tamper-target"] / "timeline.sqlite")
        row = db.execute("SELECT id, payload FROM events "
                         "WHERE kind='screen_frame' LIMIT 1").fetchone()
        payload = json.loads(row[1])
        payload["ts"] = 999.5
        db.execute("UPDATE events SET payload=? WHERE id=?",
                   (json.dumps(payload), row[0]))
        db.commit()
        db.close()
        status, detail = self.call(
            "GET", "/api/store/tamper-target/branch/desktop-real")
        self.assertEqual(status, 200, detail)
        self.assertFalse(detail["seal"])

    def test_fidelity_gate_refuses_fork_on_video(self):
        status, refused = self.call(
            "POST", "/api/store/desktop-real/branch/desktop-real/fork",
            {"note": "should not happen"})
        self.assertEqual(status, 403, refused)
        self.assertIn("refused at fidelity 'screen-only'", refused["error"])

    def test_fidelity_gate_refuses_wherefrom_on_video(self):
        status, refused = self.call(
            "GET", "/api/store/desktop-real/branch/desktop-real/wherefrom/1?row=0&col=0")
        self.assertEqual(status, 403, refused)
        self.assertIn("provenance", refused["error"])

    def test_wherefrom_on_session_branch(self):
        status, detail = self.call("GET", "/api/store/flagship/branch/main")
        self.assertEqual(status, 200, detail)
        last = detail["steps"]
        status, answer = self.call(
            "GET", f"/api/store/flagship/branch/main/wherefrom/{last}?row=0&col=0")
        self.assertEqual(status, 200, answer)
        self.assertIn("sentence", answer)

    # -- surface ----------------------------------------------------------
    @unittest.skipUnless(
        shutil.which("node") and
        (Path("/tmp/melange-test/node_modules/jsdom").is_dir()),
        "node/jsdom harness not available")
    def test_surface_live_from_api(self):
        script = Path(self.tmp) / "surface-test.mjs"
        script.write_text(SURFACE_TEST_JS)
        env = dict(os.environ,
                   MELANGE_HARNESS_DIR="/tmp/melange-test",
                   MELANGE_BASE=self.base,
                   MELANGE_DEAD=f"http://127.0.0.1:{free_port()}")
        run = subprocess.run(["node", str(script)], env=env,
                             capture_output=True, text=True, timeout=180)
        self.assertEqual(run.returncode, 0,
                         f"stdout:\n{run.stdout}\nstderr:\n{run.stderr}")


SURFACE_TEST_JS = r"""
import { createRequire } from 'node:module';
const require = createRequire(process.env.MELANGE_HARNESS_DIR + '/');
const { JSDOM } = require('jsdom');

const BASE = process.env.MELANGE_BASE;
const DEAD = process.env.MELANGE_DEAD;
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

async function loadPage(origin, apiOrigin) {
  const html = await (await fetch(origin + '/')).text();
  const dom = new JSDOM(html, { runScripts: 'dangerously', url: origin + '/',
    pretendToBeVisual: true,
    beforeParse(window) {
      window.Element.prototype.scrollIntoView = function () {};
      window.HTMLCanvasElement.prototype.getContext = function () { return makeCtx(); };
      window.fetch = (u, o) => fetch(new URL(u, apiOrigin || origin).href, o);
    } });
  return dom;
}

async function waitFor(fn, timeout = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    if (fn()) return true;
    await sleep(200);
  }
  return false;
}

// --- live page ---
{
  const expected = await (await fetch(BASE + '/api/stores')).json();
  const dom = await loadPage(BASE);
  const d = dom.window.document;
  const readout = () => d.querySelector('#readout').textContent;
  check('tabs built from the API',
        await waitFor(() => d.querySelectorAll('#tabs button').length === expected.length),
        'tabs=' + d.querySelectorAll('#tabs button').length + ' api=' + expected.length);
  check('first recording opens at step 1 of 16',
        await waitFor(() => /Step 1 of 16/.test(readout())), readout());
  const seal = d.querySelector('#seal');
  check('seal chip shows Recording checked (API said seal:true)',
        seal.classList.contains('seal-ok') && /Recording checked/.test(seal.textContent),
        seal.textContent);
  check('viewer shows a fetched picture',
        !!d.querySelector('#viewer img'), '');
  d.querySelector('#btn-play').click();
  check('play advances from fetched steps',
        await waitFor(() => /Step [2-9] of 16/.test(readout()), 12000), readout());
  d.querySelector('#btn-play').click();  // pause
  await sleep(500);                      // let any in-flight step settle
  const held = readout();
  await sleep(2200);
  check('pause holds the step', readout() === held, held);
  const scrub = d.querySelector('#scrub');
  scrub.value = '5';
  scrub.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  check('scrub lands on step 5', await waitFor(() => /Step 5 of 16/.test(readout())), readout());
  // note round-trip through the real API + store
  const noteText = 'surface test note ' + Date.now();
  d.querySelector('#note-text').value = noteText;
  d.querySelector('#btn-note').click();
  check('note appears after save (server round-trip)',
        await waitFor(() => d.querySelector('#notes-list').textContent.includes(noteText), 12000),
        d.querySelector('#notes-list').textContent.slice(0, 120));
  dom.window.close();
}

// --- API down: honest unreachable state, zero baked data ---
{
  // same page, but every API call is pointed at a dead origin
  const dom = await loadPage(BASE, DEAD);
  const d = dom.window.document;
  check('unreachable state shows when the API is down',
        await waitFor(() => !d.querySelector('#unreachable').hidden, 8000), '');
  check('no tabs and no recording data when the API is down',
        d.querySelectorAll('#tabs button').length === 0 &&
        d.querySelector('#surface').hidden, '');
  dom.window.close();
}

console.log(fails ? fails + ' SURFACE FAILURES' : 'ALL SURFACE CHECKS PASSED');
process.exit(fails ? 1 : 0);
"""


if __name__ == "__main__":
    unittest.main()
