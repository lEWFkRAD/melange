#!/usr/bin/env python3
"""Assemble the Melange working surface (single self-contained HTML).

Data: real timelines extracted from the Build 2 live run
(surface-data.json), the desktop record summary + tree sample and the
Door 1 video stills (surface-extra.json). No invented content.
"""
import json
from pathlib import Path

data = Path("/tmp/melange/surface-data.json").read_text()
extra = Path("/tmp/melange/surface-extra.json").read_text()

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Melange — working surface</title>
<style>
  :root { --bg:#0b0e13; --panel:#12161d; --line:#232a35; --ink:#dbe2ec; --dim:#8b96a5;
          --acc:#e0a458; --good:#7fc97f; --bad:#e07a5f; --shared:#2c4a6e; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }
  header { padding:18px 22px 10px; border-bottom:1px solid var(--line); }
  h1 { margin:0; font-size:20px; letter-spacing:.4px; }
  h1 .sub { color:var(--dim); font-size:13px; font-weight:400; margin-left:10px; }
  .tabs { display:flex; gap:8px; padding:12px 22px 0; flex-wrap:wrap; }
  .tab { background:var(--panel); border:1px solid var(--line); color:var(--ink);
         padding:7px 14px; border-radius:20px; cursor:pointer; font-size:13px; }
  .tab.on { border-color:var(--acc); color:var(--acc); }
  .tab .fid { color:var(--dim); font-size:11px; margin-left:6px; }
  main { padding:16px 22px 30px; max-width:1060px; }
  .pane { display:none; } .pane.on { display:block; }
  .screen { background:#05070a; border:1px solid var(--line); border-radius:8px;
            padding:10px 12px; overflow-x:auto; }
  .screen pre { margin:0; font:11.5px/1.35 'SF Mono',Consolas,'DejaVu Sans Mono',monospace;
                color:#cfe3cf; white-space:pre; }
  .transport { display:flex; align-items:center; gap:12px; margin:14px 0 6px; flex-wrap:wrap; }
  button.ctl { background:var(--panel); border:1px solid var(--line); color:var(--ink);
               padding:7px 16px; border-radius:6px; cursor:pointer; font-size:13px; }
  button.ctl:hover { border-color:var(--acc); }
  button.ctl:disabled { opacity:.38; cursor:not-allowed; }
  button.ctl:disabled:hover { border-color:var(--line); }
  input[type=range] { flex:1; min-width:200px; accent-color:var(--acc); }
  .readout { color:var(--dim); font-size:12.5px; }
  .readout b { color:var(--ink); }
  .cols { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin-top:14px; }
  @media (max-width:760px){ .cols{grid-template-columns:1fr;} }
  .card { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:12px 14px; }
  .card h3 { margin:0 0 8px; font-size:13px; color:var(--acc); letter-spacing:.3px; }
  .card p { margin:6px 0; color:var(--ink); font-size:13px; }
  .card .dim { color:var(--dim); }
  .branch { display:flex; gap:8px; align-items:center; margin:4px 0 12px; flex-wrap:wrap; }
  .branch .lbl { color:var(--dim); font-size:12.5px; }
  .pill { border:1px solid var(--line); background:var(--panel); color:var(--ink);
          border-radius:16px; padding:5px 13px; cursor:pointer; font-size:12.5px; }
  .pill.on { border-color:var(--acc); color:var(--acc); }
  .bars { display:flex; align-items:flex-end; gap:3px; height:90px; margin:10px 0 4px; }
  .bar { flex:1; background:var(--acc); min-height:2px; border-radius:2px 2px 0 0; }
  .bar.zero { background:#2a3342; }
  table.tree { width:100%; border-collapse:collapse; font-size:12px; }
  table.tree td { padding:3px 6px; border-bottom:1px solid #1a212c; color:var(--ink); }
  table.tree td.r { color:var(--acc); white-space:nowrap; }
  table.tree td.p { color:var(--dim); font-family:Consolas,monospace; white-space:nowrap; }
  .caps { display:flex; gap:8px; flex-wrap:wrap; margin:10px 0; }
  .stamp { display:inline-block; border:1px solid var(--good); color:var(--good);
           border-radius:6px; padding:2px 9px; font-size:12px; }
  .stamp.no { border-color:var(--bad); color:var(--bad); }
  textarea { width:100%; background:#0b0f14; color:var(--ink); border:1px solid var(--line);
             border-radius:6px; padding:8px; font:inherit; font-size:13px; }
  .noteitem { border-top:1px solid #1a212c; padding:6px 0; font-size:12.5px; }
  .noteitem .where { color:var(--acc); }
  img.still { width:100%; border:1px solid var(--line); border-radius:8px; background:#000; }
  .legend { font-size:12px; color:var(--dim); margin-top:4px; }
  .legend .sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px 0 10px; }
</style></head><body>
<header>
  <h1>MELANGE <span class="sub">working surface — real timelines, no mock data</span></h1>
</header>
<div class="tabs">
  <button class="tab on" data-pane="native">Live session <span class="fid">fidelity: native</span></button>
  <button class="tab" data-pane="structure">Desktop record <span class="fid">fidelity: structure</span></button>
  <button class="tab" data-pane="video">Session video <span class="fid">fidelity: screen-only</span></button>
</div>
<main>

<!-- ================= NATIVE ================= -->
<section class="pane on" id="pane-native">
  <div class="branch">
    <span class="lbl">Branch</span>
    <button class="pill on" id="br-orig">Original — as it happened</button>
    <button class="pill" id="br-fork">Fork — clamped with 99.85</button>
    <button class="ctl" id="do-fork" title="Fork from the checkpoint with the corrected figure">Fork from checkpoint (CLAMP 99.9 → 99.85)</button>
  </div>
  <div class="screen"><pre id="screen">loading…</pre></div>
  <div class="transport">
    <button class="ctl" id="play">▶ Play</button>
    <button class="ctl" id="back">⟨ event</button>
    <button class="ctl" id="fwd">event ⟩</button>
    <input type="range" id="scrub" min="0" max="152" value="0" step="1">
    <span class="readout" id="readout"></span>
  </div>
  <div class="legend"><span class="sw" style="background:var(--shared)"></span>shared prefix (108 events, hash-identical)
    <span class="sw" style="background:var(--acc)"></span>after the fork point / branch-unique</div>
  <div class="cols">
    <div class="card"><h3>FRAME INSPECTOR</h3><div id="inspector"></div></div>
    <div class="card"><h3>PROVENANCE</h3><div id="provenance"></div></div>
  </div>
  <div class="card" style="margin-top:14px"><h3>ANNOTATE THIS FRAME</h3>
    <textarea id="note" rows="2" placeholder="A note on this frame. Annotations are allowed at every fidelity."></textarea>
    <div style="margin-top:8px"><button class="ctl" id="save-note">Save annotation</button></div>
    <div id="notes"></div>
  </div>
</section>

<!-- ================= STRUCTURE ================= -->
<section class="pane" id="pane-structure">
  <p class="readout" style="margin-top:2px">Ingested through Door 2 from the CDP accessibility record of the Hermes desktop (ONY-189).
  The frames are a real interface tree, so you can scrub and dive. There is no executable session behind them,
  so clamp, fork and causal provenance are refused in the library, and the controls below are disabled, not just labeled.</p>
  <div class="cols">
    <div class="card"><h3>THE RECORD</h3><div id="desk-stats"></div></div>
    <div class="card"><h3>DELTA OPS PER POLL (1.5s)</h3><div class="bars" id="bars"></div>
      <p class="dim" style="font-size:12px;margin:2px 0">Settings opened at poll 3 (2,415 ops) and closed with Escape at poll 9 (2,534 ops). Quiet polls cost zero.</p></div>
  </div>
  <div class="card" style="margin-top:14px"><h3>CAPABILITIES AT THIS FIDELITY</h3>
    <div class="caps">
      <button class="ctl" id="dive-btn">Dive into the tree</button>
      <button class="ctl" disabled title="Refused: FidelityError at fidelity 'structure'">Clamp (disabled)</button>
      <button class="ctl" disabled title="Refused: FidelityError at fidelity 'structure'">Fork (disabled)</button>
      <button class="ctl" disabled title="Refused: FidelityError at fidelity 'structure'">Provenance (disabled)</button>
    </div>
    <p class="dim" style="font-size:12.5px">Enforced by living_replay.ingest.require_branch_op, the same check the tests exercise.</p>
    <div id="tree-wrap" style="display:none"><table class="tree" id="tree"></table>
    <p class="dim" style="font-size:12px">First 40 named nodes of the reconstructed final tree (1,818 nodes total, exact match against the live capture).</p></div>
  </div>
</section>

<!-- ================= VIDEO ================= -->
<section class="pane" id="pane-video">
  <p class="readout" style="margin-top:2px">The Door 1 export, re-imported through Door 2 as screen-only frames. Pixels carry no state:
  scrub and annotate work; dive, clamp, fork and provenance are refused in the library.</p>
  <img class="still" id="still" alt="Session video frame">
  <div class="transport">
    <button class="ctl" id="v-back">⟨ frame</button>
    <input type="range" id="v-scrub" min="0" max="5" value="0" step="1">
    <button class="ctl" id="v-fwd">frame ⟩</button>
    <span class="readout" id="v-readout"></span>
  </div>
  <div class="caps">
    <button class="ctl" disabled title="Refused: FidelityError at fidelity 'screen-only'">Dive (disabled)</button>
    <button class="ctl" disabled title="Refused: FidelityError at fidelity 'screen-only'">Clamp (disabled)</button>
    <button class="ctl" disabled title="Refused: FidelityError at fidelity 'screen-only'">Fork (disabled)</button>
  </div>
</section>
</main>

<script>
const DATA = __DATA__;
const EXTRA = __EXTRA__;
const $ = s => document.querySelector(s);

// ---- tabs ----
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
  document.querySelectorAll('.pane').forEach(p => p.classList.toggle('on', p.id === 'pane-' + t.dataset.pane));
});

// ---- native player ----
let branch = 'orig', idx = 0, playing = false, timer = null;
const B = () => DATA[branch];
function shade() {
  const total = B().events.length, shared = Math.min(DATA.meta.shared_prefix_events, total);
  const pct = (shared / total * 100).toFixed(1);
  $('#scrub').style.background = `linear-gradient(90deg, var(--shared) ${pct}%, #3a4353 ${pct}%)`;
  $('#scrub').max = total - 1;
}
function notesKey() { return 'melange-notes-' + branch + '-' + idx; }
function allNotes() {
  const out = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith('melange-notes-')) out.push([k, localStorage.getItem(k)]);
  }
  return out.sort();
}
function render() {
  const b = B(), ev = b.events[idx];
  $('#screen').textContent = b.frames[ev.frame].text;
  $('#scrub').value = idx;
  $('#readout').innerHTML = `event <b>${ev.id}</b> of ${b.events.length} · kind <b>${ev.kind}</b> · frame ${ev.frame + 1} of ${b.frames.length}`;
  const shared = idx < DATA.meta.shared_prefix_events;
  $('#inspector').innerHTML =
    `<p>Branch: <b>${branch === 'orig' ? 'Original' : 'Fork'}</b></p>` +
    `<p class="dim">${shared ? 'Inside the shared prefix: this frame is hash-identical on both branches.'
                              : 'Past the fork point: this future belongs to this branch alone.'}</p>` +
    `<p class="dim">Screen reconstructed from the record by replaying capture chunks and grid keyframes. Nothing here is a screenshot.</p>`;
  let prov = '<p class="dim">Scrub to the moment the uptime figure appears.</p>';
  if (branch === 'orig' && ev.id >= DATA.meta.orig_999.event) {
    prov = `<p><span class="stamp">99.9</span></p>
      <p>The uptime figure <b>99.9</b> first appears at event <b>25</b>, row 13, column 67 of the screen,
      and was produced by capture chunk 25 of the original timeline.</p>
      <p class="dim">In the fork, that input was clamped to the corrected figure before the session resumed.</p>`;
  }
  if (branch === 'fork' && ev.id >= DATA.meta.fork_9985.event) {
    prov = `<p><span class="stamp">99.85</span> <span class="stamp no">99.9</span></p>
      <p>The corrected figure <b>99.85</b> first appears at event <b>141</b>. The string 99.9 never appears
      anywhere on this branch: the clamped input compiled forward into a different future, verified by re-execution.</p>`;
  }
  if (branch === 'fork' && ev.id < DATA.meta.fork_9985.event && idx >= DATA.meta.shared_prefix_events)
    prov = '<p class="dim">Resumed from the checkpoint with the clamped input. The corrected figure has not reached the screen yet.</p>';
  $('#provenance').innerHTML = prov;
  $('#note').value = localStorage.getItem(notesKey()) || '';
  $('#notes').innerHTML = allNotes().filter(([k]) => k.startsWith('melange-notes-' + branch + '-'))
    .map(([k, v]) => `<div class="noteitem"><span class="where">event ${k.split('-').pop()}</span> — ${v.replace(/</g,'&lt;')}</div>`).join('');
}
function stop() { playing = false; clearTimeout(timer); $('#play').textContent = '▶ Play'; }
function step() {
  if (!playing) return;
  if (idx >= B().events.length - 1) { stop(); return; }
  timer = setTimeout(() => { idx++; render(); step(); }, Math.max(60, B().gaps[idx] * 1000 * 0.6));
}
$('#play').onclick = () => { if (playing) { stop(); } else { playing = true; $('#play').textContent = '⏸ Pause'; step(); } };
$('#back').onclick = () => { stop(); idx = Math.max(0, idx - 1); render(); };
$('#fwd').onclick = () => { stop(); idx = Math.min(B().events.length - 1, idx + 1); render(); };
$('#scrub').oninput = e => { stop(); idx = +e.target.value; render(); };
function setBranch(br) {
  branch = br; stop();
  $('#br-orig').classList.toggle('on', br === 'orig');
  $('#br-fork').classList.toggle('on', br === 'fork');
  if (idx >= B().events.length) idx = B().events.length - 1;
  shade(); render();
}
$('#br-orig').onclick = () => setBranch('orig');
$('#br-fork').onclick = () => setBranch('fork');
$('#do-fork').onclick = () => { setBranch('fork'); idx = DATA.meta.shared_prefix_events; render(); };
$('#save-note').onclick = () => {
  const v = $('#note').value.trim();
  if (v) localStorage.setItem(notesKey(), v); else localStorage.removeItem(notesKey());
  render();
};
shade(); render();

// ---- structure pane ----
$('#desk-stats').innerHTML =
  `<p>Keyframe: <b>1,819</b> accessibility nodes · Polls: <b>14</b> · Delta ops recorded: <b>7,285</b></p>
   <p>Reconstruction from the ingested record: <b>1,818 nodes, exact match</b> with the live final tree.</p>
   <p><span class="stamp">RECONSTRUCTED == LIVE</span></p>
   <p class="dim">Source: Hermes desktop on SHATNER via CDP, recorded 2026-10-16. A still window costs a keyframe and zero deltas.</p>`;
const maxOps = Math.max(...EXTRA.per_poll_ops);
$('#bars').innerHTML = EXTRA.per_poll_ops.map(v =>
  `<div class="bar ${v === 0 ? 'zero' : ''}" style="height:${Math.max(3, v / maxOps * 100)}%" title="${v} ops"></div>`).join('');
$('#dive-btn').onclick = () => {
  const w = $('#tree-wrap'); const show = w.style.display === 'none';
  w.style.display = show ? 'block' : 'none';
  if (show) $('#tree').innerHTML = EXTRA.tree_sample.map(n =>
    `<tr><td class="p">${n.path}</td><td class="r">${n.role}</td><td>${n.name.replace(/</g,'&lt;')}</td></tr>`).join('');
};

// ---- video pane ----
let vi = 0;
function vrender() {
  $('#still').src = EXTRA.video_frames[vi];
  $('#v-scrub').value = vi;
  $('#v-readout').innerHTML = `frame <b>${vi + 1}</b> of ${EXTRA.video_frames.length} · from melange-live-session.mp4 · byte-identical out of the store`;
}
$('#v-back').onclick = () => { vi = Math.max(0, vi - 1); vrender(); };
$('#v-fwd').onclick = () => { vi = Math.min(EXTRA.video_frames.length - 1, vi + 1); vrender(); };
$('#v-scrub').oninput = e => { vi = +e.target.value; vrender(); };
vrender();
</script>
</body></html>
"""

out = HTML.replace("__DATA__", data).replace("__EXTRA__", extra)
dest = Path.home() / "workspace/your_files/melange-player"
dest.mkdir(parents=True, exist_ok=True)
(dest / "melange-player.html").write_text(out)
print("wrote", dest / "melange-player.html", len(out), "bytes")
