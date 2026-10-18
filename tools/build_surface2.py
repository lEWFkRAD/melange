#!/usr/bin/env python3
"""Assemble the Melange reference surface v2 (single self-contained HTML).

Implements melange-ux-design.md sections 4 and 5 against REAL backend
data exported by extract2.py through living_replay.bridge /
export_viewer.timeline_frames / ingest (surface2-data.json): per-cell
provenance for every non-blank cell of the live Build 2 recording, the
desktop record's parts at every check, the ingested screen-only frames,
real seals from bridge.seal, and notes written into a scratch copy of
the Original store through bridge.add_note and read back with
bridge.notes. No invented content; no control promises an operation the
exported capability list does not include.
"""
import json
from pathlib import Path

data = Path("/tmp/melange2/surface2-data.json").read_text()

HTML = r"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Melange — recordings</title>
<style>
  :root { --bg:#0b0e13; --panel:#12161d; --panel2:#0d1117; --line:#232a35; --ink:#dbe2ec;
          --dim:#8b96a5; --acc:#e0a458; --good:#7fc97f; --bad:#e07a5f; --shared:#2c4a6e;
          --note:#3d3423; --instr:#26313f; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.5 -apple-system,'Segoe UI',Roboto,sans-serif; }
  header { padding:16px 22px 6px; }
  h1 { margin:0; font-size:20px; letter-spacing:.4px; }
  h1 .sub { color:var(--dim); font-size:13px; font-weight:400; margin-left:10px; }
  .picker { display:flex; gap:10px; padding:10px 22px 4px; flex-wrap:wrap; }
  .rec { background:var(--panel); border:1px solid var(--line); color:var(--ink); text-align:left;
         padding:9px 14px; border-radius:8px; cursor:pointer; font-size:13.5px; min-width:190px; }
  .rec.on { border-color:var(--acc); }
  .rec .kind { display:block; color:var(--dim); font-size:11.5px; margin-top:2px; }
  .topline { padding:8px 22px 0; display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  .topline .name { font-size:16.5px; font-weight:600; }
  .badge { border:1px solid var(--acc); color:var(--acc); border-radius:12px;
           padding:1px 9px; font-size:11.5px; }
  .seal { border:1px solid var(--good); color:var(--good); border-radius:12px;
          padding:1px 9px; font-size:11.5px; }
  .meta { color:var(--dim); font-size:12.5px; padding:2px 22px 0; }
  .banner { margin:10px 22px 0; background:#3a1d18; border:1px solid var(--bad); color:#f3c1b3;
            border-radius:8px; padding:10px 14px; font-size:13.5px; }
  main { padding:14px 22px 10px; display:grid; grid-template-columns:minmax(0,7fr) minmax(300px,5fr);
         gap:16px; align-items:start; }
  @media (max-width:900px){ main{grid-template-columns:1fr;} }
  .caption { color:var(--dim); font-size:12.5px; margin:0 0 6px; }
  .screen { background:#05070a; border:1px solid var(--line); border-radius:8px;
            padding:10px 12px; overflow:auto; }
  .screen pre { margin:0; font:11.5px/1.35 'SF Mono',Consolas,'DejaVu Sans Mono',monospace;
                color:#cfe3cf; white-space:pre; }
  .screen.picking pre { cursor:crosshair; }
  .screen.picking .ch:hover { background:#274b73; }
  .screen .ch { cursor:pointer; }
  .screen img { width:100%; display:block; border-radius:4px; background:#000; }
  .blank-note { color:var(--dim); font:12.5px/1.5 inherit; padding:26px 6px; }
  .side { background:var(--panel); border:1px solid var(--line); border-radius:8px; overflow:hidden; }
  .rtabs { display:flex; border-bottom:1px solid var(--line); }
  .rtab { flex:1; background:var(--panel2); border:0; border-right:1px solid var(--line);
          color:var(--dim); padding:9px 4px; cursor:pointer; font-size:12.5px; }
  .rtab:last-child { border-right:0; }
  .rtab.on { color:var(--acc); background:var(--panel); }
  .rbody { padding:10px 12px; max-height:560px; overflow:auto; }
  .srow { padding:5px 8px; border-radius:5px; cursor:pointer; font-size:13px; display:flex; gap:8px; }
  .srow:hover { background:#18202b; }
  .srow.cur { background:#1d2735; outline:1px solid var(--shared); }
  .srow .n { color:var(--dim); min-width:64px; font-size:12px; padding-top:1px; }
  .card { border-radius:6px; padding:8px 10px; margin:6px 0 6px 8px; font-size:13px; }
  .card .hd { font-size:11px; letter-spacing:.4px; color:var(--acc); margin-bottom:3px; }
  .card.instr { background:var(--instr); border:1px solid #33465e; white-space:pre-wrap; }
  .card.notec { background:var(--note); border:1px solid #5c4d27; }
  .card.pending { background:#2b2136; border:1px dashed #6b557f; }
  .card .honest { color:var(--dim); font-size:12px; margin-top:5px; }
  .prow { display:flex; gap:8px; padding:3.5px 6px; border-bottom:1px solid #1a212c; font-size:12.5px; }
  .prow .role { color:var(--acc); white-space:nowrap; }
  .prow .path { color:var(--dim); font-family:Consolas,monospace; font-size:11px; margin-left:auto;
                white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:38%; }
  .dim { color:var(--dim); } .small { font-size:12.5px; }
  .answer { font-size:13.5px; } .answer .clicked { color:var(--acc); font-weight:600; }
  .rules { margin-top:14px; border-top:1px solid var(--line); padding-top:10px; }
  .rules h4 { margin:0 0 6px; font-size:13px; color:var(--acc); letter-spacing:.3px; }
  input[type=text], textarea, select { background:#0b0f14; color:var(--ink); border:1px solid var(--line);
    border-radius:6px; padding:7px 9px; font:inherit; font-size:13px; }
  textarea { width:100%; }
  .notice { margin:0 22px 8px; background:#1d2735; border:1px solid var(--shared);
            border-radius:8px; padding:9px 14px; font-size:13.5px; display:none; }
  .notice.show { display:block; }
  .notice button { float:right; }
  .panel { margin:0 22px 10px; background:var(--panel); border:1px solid var(--line);
           border-radius:8px; padding:12px 14px; display:none; }
  .panel.show { display:block; }
  .panel h3 { margin:0 0 8px; font-size:14px; color:var(--acc); }
  .offer { background:var(--instr); border:1px solid #33465e; border-radius:6px;
           padding:9px 12px; margin-bottom:10px; font-size:13.5px; }
  .bar { position:sticky; bottom:0; background:#0d1117; border-top:1px solid var(--line);
         padding:10px 22px 12px; }
  .row1 { display:flex; align-items:center; gap:10px; flex-wrap:wrap; }
  button.ctl { background:var(--panel); border:1px solid var(--line); color:var(--ink);
               padding:7px 13px; border-radius:6px; cursor:pointer; font-size:13px; }
  button.ctl:hover { border-color:var(--acc); }
  button.ctl.on { border-color:var(--acc); color:var(--acc); }
  button.ctl.locked { color:var(--dim); }
  .sliderwrap { flex:1; min-width:200px; position:relative; padding-bottom:10px; }
  input[type=range] { width:100%; accent-color:var(--acc); margin:0; }
  .dots { position:absolute; left:0; right:0; bottom:0; height:8px; pointer-events:none; }
  .dot { position:absolute; width:7px; height:7px; border-radius:50%; background:var(--acc);
         transform:translateX(-50%); top:0; }
  .readout { font-size:13px; white-space:nowrap; }
  .readout b { color:var(--acc); }
  .ver { display:inline-flex; gap:4px; margin-left:8px; }
  .ver button { padding:3px 10px; font-size:12px; }
  .row2 { display:flex; gap:8px; margin-top:9px; flex-wrap:wrap; }
  .legend { font-size:12px; color:var(--dim); margin-top:7px; }
  .legend .sw { display:inline-block; width:10px; height:10px; border-radius:2px; margin:0 4px 0 10px; }
</style></head><body>
<header>
  <h1>MELANGE <span class="sub">watch a recording of work, look inside it, try it differently</span></h1>
</header>
<div class="picker" id="picker"></div>
<div class="topline">
  <span class="name" id="rec-name"></span><span class="badge" id="rec-badge"></span>
  <span class="seal" id="rec-seal"></span>
</div>
<div class="meta" id="rec-meta"></div>
<div class="banner" id="badseal" style="display:none">This recording does not check out. A step is missing or was changed after the fact. You can watch it, but do not trust it.</div>
<main>
  <section>
    <p class="caption" id="stage-caption"></p>
    <div class="screen" id="stage"></div>
  </section>
  <aside class="side">
    <div class="rtabs">
      <button class="rtab on" data-tab="steps">Steps</button>
      <button class="rtab" data-tab="inside">Look inside</button>
      <button class="rtab" data-tab="where">Where it came from</button>
    </div>
    <div class="rbody" id="rbody"></div>
  </aside>
</main>
<div class="notice" id="notice"><button class="ctl" id="notice-x">Close</button><span id="notice-text"></span></div>
<div class="panel" id="panel-try"></div>
<div class="panel" id="panel-change"></div>
<div class="panel" id="panel-note"></div>
<div class="bar">
  <div class="row1">
    <button class="ctl" id="btn-first" title="Go to the first step">⏮</button>
    <button class="ctl" id="btn-play">▶ Play</button>
    <button class="ctl" id="btn-back">⟨ step</button>
    <button class="ctl" id="btn-fwd">step ⟩</button>
    <div class="sliderwrap">
      <input type="range" id="scrub" min="1" step="1" value="1">
      <div class="dots" id="dots"></div>
    </div>
    <span class="readout" id="readout"></span>
    <span class="ver" id="ver"></span>
    <select id="speed" title="Playing speed">
      <option value="1">1x</option><option value="2">2x</option><option value="4">4x</option>
    </select>
  </div>
  <div class="row2">
    <button class="ctl" id="btn-try">Try it differently from here…</button>
    <button class="ctl" id="btn-change">Change this step…</button>
    <button class="ctl" id="btn-note">Note</button>
    <button class="ctl" id="btn-where">Where did this come from?</button>
    <button class="ctl" id="btn-rules">House rules</button>
  </div>
  <div class="legend" id="legend"></div>
</div>

<script>
const DATA = __DATA__;
const $ = s => document.querySelector(s);
const KIND = { 'native': 'Full recording', 'structure': 'Outline recording', 'screen-only': 'Video-only recording' };
const RECS = {
  session: { name: 'Hermes work session', fid: 'native' },
  desktop: { name: 'Hermes desktop', fid: 'structure' },
  video:   { name: 'Session video', fid: 'screen-only' }
};
const state = { rec: 'session', ver: 'orig', step: 1, playing: false, timer: null,
                speed: 1, pick: false, tab: 'steps', localNotes: [], notRun: [],
                lastAnswer: null, deskStates: {} };
const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;');

function cur() { return DATA[state.rec]; }
function ver() { return DATA.session.versions[state.ver]; }
function fidelity() { return state.rec === 'session' ? ver().fidelity : cur().fidelity; }
function caps() { return state.rec === 'session' ? ver().caps : cur().caps; }
function can(op) { return caps().includes(op); }
function sealOk() { return state.rec === 'session' ? ver().seal : cur().seal; }
function maxStep() {
  if (state.rec === 'session') return ver().steps;
  if (state.rec === 'desktop') return cur().checks.length;
  return cur().frames.length;
}
function splitStep() { return state.rec === 'session' ? DATA.session.split_step : 0; }

// ---------- stage ----------
function sessionFrame() {
  const v = ver(), fi = v.step_frame[state.step - 1];
  return fi >= 0 ? v.frames[fi] : null;
}
function deskStateAt(pos) {
  if (state.deskStates[pos]) return state.deskStates[pos];
  const d = DATA.desktop, st = {};
  Object.keys(d.initial_parts).forEach(p => st[p] = d.initial_parts[p]);
  for (let i = 1; i < pos; i++) {
    for (const op of d.checks[i].ops) {
      if (op[0] === 's') st[op[1]] = [op[2], op[3]]; else delete st[op[1]];
    }
  }
  state.deskStates[pos] = st;
  return st;
}
function renderStage() {
  const stage = $('#stage'), cap = $('#stage-caption');
  stage.classList.toggle('picking', state.pick && state.rec === 'session');
  if (state.rec === 'video') {
    cap.textContent = 'The picture kept by the recording at this step. Only pictures were kept, so nothing inside can be looked into.';
    stage.innerHTML = '';
    const img = document.createElement('img');
    img.src = 'data:image/png;base64,' + cur().frames[state.step - 1];
    img.alt = 'Picture ' + state.step + ' of ' + cur().frames.length;
    stage.appendChild(img);
    return;
  }
  if (state.rec === 'desktop') {
    const d = cur(), chk = d.checks[state.step - 1], st = deskStateAt(state.step);
    cap.textContent = 'The screen at this step, as a list of its parts. This recording kept the parts of the screen, not a picture of it.';
    const named = Object.keys(st).filter(p => st[p][1]).sort();
    let html = '<p style="margin:2px 0 8px"><b>' + chk.parts.toLocaleString() + '</b> parts on the screen at this step.</p>';
    if (state.step > 1) {
      html += chk.ops.length
        ? '<p class="dim small" style="margin:0 0 8px">This step changed ' + chk.ops.length.toLocaleString() + ' parts.</p>'
        : '<p class="dim small" style="margin:0 0 8px">This step changed nothing.</p>';
    }
    html += named.slice(0, 24).map(p =>
      '<div class="prow"><span class="role">' + esc(st[p][0]) + '</span><span>' + esc(st[p][1]) + '</span></div>').join('');
    if (named.length > 24)
      html += '<p class="dim small">…and ' + (named.length - 24).toLocaleString() + ' more named parts. The full list is under “Look inside”.</p>';
    stage.innerHTML = html;
    return;
  }
  const f = sessionFrame();
  cap.textContent = 'The screen at this step · Re-drawn from the recording';
  if (!f) { stage.innerHTML = '<div class="blank-note">The screen was blank at this step.</div>'; return; }
  if (!state.pick) {
    stage.innerHTML = '';
    const pre = document.createElement('pre');
    pre.textContent = f.screen;
    stage.appendChild(pre);
    return;
  }
  const byPos = {};
  for (const s of f.segs) {
    let off = s.off;
    for (let i = 0; i < s.text.length; i++) {
      byPos[s.y + ',' + (s.x + i)] = { ch: s.text[i], chunk: s.chunk, off: off, attr: s.attr };
      off += new TextEncoder().encode(s.text[i]).length;
    }
  }
  stage.innerHTML = '';
  const pre = document.createElement('pre');
  f.screen.split('\n').forEach((line, y) => {
    [...line].forEach((ch, x) => {
      const span = document.createElement('span');
      span.textContent = ch;
      const cell = byPos[y + ',' + x];
      if (cell && ch !== ' ') {
        span.className = 'ch';
        span.onclick = () => answerWhere(cell);
      } else {
        span.onclick = () => answerBlank();
      }
      pre.appendChild(span);
    });
    pre.appendChild(document.createTextNode('\n'));
  });
  stage.appendChild(pre);
}

// ---------- notes / pending, shared by steps renderers ----------
function visibleNotes() {
  const out = [];
  if (state.rec === 'session')
    for (const n of DATA.session.notes) out.push({ step: n.at_event, text: n.text });
  for (const n of state.localNotes) {
    if (n.rec !== state.rec) continue;
    if (state.rec === 'session' && n.ver !== state.ver && n.step > splitStep()) continue;
    out.push({ step: n.step, text: n.text });
  }
  return out;
}
function noteCardsAt(step) {
  return visibleNotes().filter(n => n.step === step)
    .map(n => '<div class="card notec"><div class="hd">NOTE</div>' + esc(n.text) + '</div>').join('')
    + state.notRun.filter(r => r.rec === state.rec && r.step === step && (state.rec !== 'session' || r.ver === state.ver))
      .map(r => '<div class="card pending"><div class="hd">WHAT-IF — NOT RUN YET</div>' + esc(r.text) +
        '<div class="honest">Saved as the first step of a What-if. It runs when this recording is reopened in a live session.</div></div>').join('');
}

// ---------- Steps ----------
const STEP_WORDS = { model_call: 'The assistant worked out an answer',
                     terminal_chunk: 'The screen updated',
                     context_note: 'An instruction was written here' };
function renderSteps() {
  const b = $('#rbody');
  if (maxStep() === 0) { b.innerHTML = '<p class="dim">This recording has no steps yet.</p>'; return; }
  let html = '';
  if (state.rec === 'session') {
    const v = ver();
    let curRow = null;
    for (const ev of v.events) {
      if (ev.kind === 'grid_keyframe') continue; // merged into the screen step before it
      html += '<div class="srow" data-step="' + ev.id + '"><span class="n">Step ' + ev.id + '</span><span>' +
        (STEP_WORDS[ev.kind] || 'A step was recorded') + '</span></div>';
      if (ev.kind === 'context_note')
        html += '<div class="card instr"><div class="hd">WRITTEN AT THIS STEP</div>' + esc(ev.text) + '</div>';
      html += noteCardsAt(ev.id);
    }
    b.innerHTML = html;
    b.querySelectorAll('.srow').forEach(r => r.onclick = () => { stopPlay(); gotoStep(+r.dataset.step); });
    let cur = state.step;
    while (cur > 1 && v.events[cur - 1].kind === 'grid_keyframe') cur--;
    curRow = b.querySelector('.srow[data-step="' + cur + '"]');
    if (curRow) { curRow.classList.add('cur'); curRow.scrollIntoView({ block: 'nearest' }); }
    return;
  }
  if (state.rec === 'desktop') {
    const d = cur();
    d.checks.forEach((chk, i) => {
      const label = i === 0 ? 'The screen was recorded'
        : (chk.ops.length ? chk.ops.length.toLocaleString() + ' parts changed' : 'Nothing changed');
      html += '<div class="srow" data-step="' + (i + 1) + '"><span class="n">Step ' + (i + 1) + '</span><span>' + label + '</span></div>';
      html += noteCardsAt(i + 1);
      for (const inp of d.inputs.filter(x => x.after_check === i))
        html += '<div class="card instr"><div class="hd">INPUT SENT TO THE SCREEN</div>' + esc(inp.events.join('; ')) + '</div>';
    });
    b.innerHTML = html;
    b.querySelectorAll('.srow').forEach(r => r.onclick = () => { stopPlay(); gotoStep(+r.dataset.step); });
    const curRow = b.querySelector('.srow[data-step="' + state.step + '"]');
    if (curRow) { curRow.classList.add('cur'); curRow.scrollIntoView({ block: 'nearest' }); }
    return;
  }
  cur().frames.forEach((_, i) => {
    html += '<div class="srow" data-step="' + (i + 1) + '"><span class="n">Step ' + (i + 1) + '</span><span>Picture ' + (i + 1) + ' of ' + cur().frames.length + ', kept by the recording</span></div>';
    html += noteCardsAt(i + 1);
  });
  b.innerHTML = html;
  b.querySelectorAll('.srow').forEach(r => r.onclick = () => { stopPlay(); gotoStep(+r.dataset.step); });
  const curRow = b.querySelector('.srow[data-step="' + state.step + '"]');
  if (curRow) { curRow.classList.add('cur'); curRow.scrollIntoView({ block: 'nearest' }); }
}

// ---------- Look inside ----------
function renderInside() {
  const b = $('#rbody');
  if (state.rec !== 'desktop') {
    b.innerHTML = state.rec === 'session'
      ? '<p>There is no parts list for this recording: its screen is kept as words on a page, not as separate parts.</p>' +
        '<p class="dim">To look into any word or number on the screen, use “Where did this come from?” below, then click the word.</p>'
      : '<p>You cannot look inside a video-only recording: only pictures of the screen were kept.</p>';
    return;
  }
  const st = deskStateAt(state.step);
  const q = ($('#partq') ? $('#partq').value : '').toLowerCase();
  const paths = Object.keys(st).sort();
  const hits = paths.filter(p => !q || st[p][0].toLowerCase().includes(q) || (st[p][1] || '').toLowerCase().includes(q) || p.includes(q));
  let html = '<p style="margin-top:2px"><b>' + paths.length.toLocaleString() + '</b> parts on the screen at step ' + state.step + '.</p>' +
    '<input type="text" id="partq" placeholder="Search the parts…" style="width:100%" value="' + esc(q) + '">';
  html += hits.slice(0, 400).map(p =>
    '<div class="prow"><span class="role">' + esc(st[p][0]) + '</span><span>' + esc(st[p][1] || '') + '</span><span class="path">' + esc(p) + '</span></div>').join('');
  if (hits.length > 400) html += '<p class="dim small">Showing the first 400 of ' + hits.length.toLocaleString() + ' matching parts. Type in the search box to narrow it down.</p>';
  if (!hits.length) html += '<p class="dim">No parts match that search.</p>';
  b.innerHTML = html;
  const inp = $('#partq');
  inp.oninput = () => { const pos = inp.selectionStart; renderInside(); const n = $('#partq'); n.focus(); n.setSelectionRange(pos, pos); };
}

// ---------- Where it came from ----------
function renderWhere() {
  const b = $('#rbody');
  let html = '';
  if (state.rec === 'session') {
    html += state.lastAnswer
      ? '<div class="answer">' + state.lastAnswer + '</div>'
      : '<p>Press “Where did this come from?” below, then click any word or number on the screen. The answer says which step made it.</p>';
  } else {
    html += '<p>' + (state.rec === 'desktop'
      ? 'Words cannot be traced in an outline recording: the words themselves were not kept, only the parts of the screen.'
      : 'Words cannot be traced in a video-only recording: only pictures of the screen were kept.') + '</p>';
  }
  const rules = state.rec === 'session' ? DATA.session.rules[state.ver] : cur().rules;
  html += '<div class="rules"><h4>HOUSE RULES</h4>';
  if (!rules.length) {
    html += '<p style="margin:4px 0">No house rules were set on this recording.</p>' +
      '<p class="dim small">A house rule says something that must always be true, like “the total always adds up”. House rules are checked on every What-if.</p>';
  } else {
    html += rules.map(r => '<p style="margin:4px 0">' + esc(r.target || 'Rule') + ': ' + esc(String(r.value)) + '</p>').join('');
  }
  html += '<p class="small" style="margin-top:8px">' + (sealOk()
    ? 'Recording checked ✓ — every step is present, and nothing was changed after the fact.'
    : 'This recording does not check out. Do not trust it.') + '</p></div>';
  b.innerHTML = html;
}
function answerWhere(cell) {
  let s = 'You clicked <span class="clicked">“' + esc(cell.ch) + '”</span>. ' +
    'This came from step ' + cell.chunk + ', ' + cell.off + ' characters into that step’s output.';
  if (!cell.attr)
    s += ' This recording shows which step’s output it is (step ' + cell.chunk + '), but did not keep which action inside the step made it.';
  state.lastAnswer = s;
  setTab('where');
}
function answerBlank() {
  state.lastAnswer = 'That spot is blank, or the program redrew it; no step’s output made it.';
  setTab('where');
}

// ---------- top line, bar, legend ----------
function renderPicker() {
  $('#picker').innerHTML = Object.keys(RECS).map(k =>
    '<button class="rec' + (state.rec === k ? ' on' : '') + '" data-rec="' + k + '">' + RECS[k].name +
    '<span class="kind">' + KIND[RECS[k].fid] + '</span></button>').join('');
  document.querySelectorAll('.rec').forEach(b => b.onclick = () => setRec(b.dataset.rec));
}
function renderTop() {
  $('#rec-name').textContent = RECS[state.rec].name;
  $('#rec-badge').textContent = KIND[fidelity()];
  const seal = $('#rec-seal');
  seal.textContent = sealOk() ? 'Recording checked ✓' : 'Recording does not check out';
  seal.style.borderColor = sealOk() ? 'var(--good)' : 'var(--bad)';
  seal.style.color = sealOk() ? 'var(--good)' : 'var(--bad)';
  $('#badseal').style.display = sealOk() ? 'none' : 'block';
  if (state.rec === 'session') {
    const s = DATA.session;
    $('#rec-meta').textContent = 'Recorded ' + s.made + ' · ' + s.versions.orig.steps +
      ' steps in the Original, ' + s.versions.fork.steps + ' in the What-if · The first ' +
      s.split_step + ' steps are the same in both';
  } else if (state.rec === 'desktop') {
    const d = cur(), span = Math.round((d.poll_ts[d.poll_ts.length - 1] - d.poll_ts[0]) / 1000);
    $('#rec-meta').textContent = 'The screen was checked ' + d.checks.length + ' times over about ' + span +
      ' seconds · ' + d.checks[0].parts.toLocaleString() + ' parts on the screen at the start, ' +
      d.checks[d.checks.length - 1].parts.toLocaleString() + ' at the end';
  } else {
    $('#rec-meta').textContent = cur().frames.length + ' pictures, taken from the session video and kept by the recording';
  }
}
function renderBar() {
  const max = maxStep();
  $('#readout').innerHTML = 'Step <b>' + state.step + '</b> of ' + max +
    (state.rec === 'session' ? ' · ' + (state.ver === 'orig' ? 'Original' : 'What-if') : '');
  $('#ver').innerHTML = state.rec === 'session'
    ? '<button class="ctl' + (state.ver === 'orig' ? ' on' : '') + '" id="v-orig">Original</button>' +
      '<button class="ctl' + (state.ver === 'fork' ? ' on' : '') + '" id="v-fork">What-if</button>' : '';
  if (state.rec === 'session') {
    $('#v-orig').onclick = () => setVer('orig');
    $('#v-fork').onclick = () => setVer('fork');
  }
  const sc = $('#scrub');
  sc.max = max; sc.value = state.step;
  if (state.rec === 'session') {
    const pct = (splitStep() / max * 100).toFixed(1);
    sc.style.background = 'linear-gradient(90deg, var(--shared) ' + pct + '%, #3a4353 ' + pct + '%)';
    $('#legend').innerHTML = '<span class="sw" style="background:var(--shared)"></span>the part that is the same in the Original and the What-if' +
      '<span class="sw" style="background:var(--acc);border-radius:50%"></span>a dot marks a step with a note';
  } else {
    sc.style.background = '#3a4353';
    $('#legend').innerHTML = '<span class="sw" style="background:var(--acc);border-radius:50%"></span>a dot marks a step with a note';
  }
  const dotSteps = [...new Set(visibleNotes().map(n => n.step))];
  $('#dots').innerHTML = dotSteps.map(s =>
    '<span class="dot" style="left:' + (max > 1 ? (s - 1) / (max - 1) * 100 : 0) + '%"></span>').join('');
  const locked = (btn, isLocked) => { btn.classList.toggle('locked', isLocked); };
  locked($('#btn-try'), !can('fork'));
  locked($('#btn-change'), state.rec !== 'session' && !can('clamp'));
  locked($('#btn-where'), !can('provenance'));
  $('#btn-try').textContent = 'Try it differently from here…' + (can('fork') ? '' : ' 🔒');
  $('#btn-change').textContent = 'Change this step…' + (state.rec !== 'session' && !can('clamp') ? ' 🔒' : '');
  $('#btn-where').textContent = 'Where did this come from?' + (can('provenance') ? '' : ' 🔒');
  $('#btn-play').textContent = state.playing ? '⏸ Pause' : '▶ Play';
}
function renderBody() {
  if (state.tab === 'steps') renderSteps();
  else if (state.tab === 'inside') renderInside();
  else renderWhere();
}
function renderAll() { renderPicker(); renderTop(); renderStage(); renderBody(); renderBar(); }
function gotoStep(n) {
  state.step = Math.max(1, Math.min(maxStep(), n));
  renderStage(); renderBody(); renderBar();
}
function setVer(v) {
  if (v === state.ver) return;
  state.ver = v; state.lastAnswer = null;
  state.step = Math.min(state.step, maxStep());
  renderTop(); gotoStep(state.step);
}
function setRec(r) {
  stopPlay(); state.rec = r; state.step = 1; state.pick = false; state.lastAnswer = null;
  closePanels(); renderAll();
}
function setTab(t) {
  state.tab = t;
  document.querySelectorAll('.rtab').forEach(x => x.classList.toggle('on', x.dataset.tab === t));
  renderBody();
}

// ---------- playing ----------
function gapFor(step) {
  if (state.rec === 'session') return ver().events[step - 1].gap;
  if (state.rec === 'desktop') {
    const ts = cur().poll_ts;
    return step < ts.length ? Math.min(Math.max((ts[step] - ts[step - 1]) / 1000, 0.3), 4.0) : 1.0;
  }
  return 1.5;
}
function stopPlay() {
  state.playing = false;
  if (state.timer) clearTimeout(state.timer);
  $('#btn-play').textContent = '▶ Play';
}
function tick() {
  if (!state.playing) return;
  if (state.step >= maxStep()) { stopPlay(); return; }
  const wait = gapFor(state.step) * 1000 / state.speed;
  state.timer = setTimeout(() => { gotoStep(state.step + 1); tick(); }, wait);
}

// ---------- notice + panels ----------
function showNotice(text) {
  $('#notice-text').textContent = text;
  $('#notice').classList.add('show');
}
function closePanels() {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('show'));
}
function openPanel(id) {
  const was = $(id).classList.contains('show');
  closePanels();
  if (!was) $(id).classList.add('show');
}
function buildTryPanel() {
  const p = $('#panel-try');
  let html = '<h3>Try it differently from here</h3>' +
    '<p class="small" style="margin:0 0 8px">This makes a What-if copy. The original stays on the shelf, untouched.</p>';
  if (state.step === splitStep())
    html += '<div class="offer">A What-if was already recorded from this step. ' +
      '<button class="ctl" id="open-recorded">Open the recorded What-if</button></div>';
  html += '<p class="small" style="margin:0 0 6px">New instruction at step ' + state.step + ':</p>' +
    '<textarea id="try-text" rows="2" placeholder="Say what the assistant should do differently from this step on…"></textarea>' +
    '<div style="margin-top:8px"><button class="ctl" id="try-go">Make the What-if</button></div>' +
    '<div id="try-done"></div>';
  p.innerHTML = html;
  const openBtn = $('#open-recorded');
  if (openBtn) openBtn.onclick = () => { setVer('fork'); closePanels(); };
  $('#try-go').onclick = () => {
    const text = $('#try-text').value.trim();
    if (!text) return;
    state.notRun.push({ rec: state.rec, ver: state.ver, step: state.step, text: text });
    $('#try-done').innerHTML = '<div class="card pending" style="margin-left:0"><div class="hd">WHAT-IF — NOT RUN YET</div>' +
      esc(text) + '<div class="honest">Saved as the first step of a What-if. It runs when this recording is reopened in a live session. It is also pinned in the Steps list at step ' + state.step + '.</div></div>';
    renderBody();
  };
}
function buildChangePanel() {
  $('#panel-change').innerHTML = '<h3>Change this step</h3>' +
    '<p style="margin:0 0 8px">Like fixing a cell in a spreadsheet. The steps after it redo themselves. The original never changes.</p>' +
    '<p class="small" style="margin:0 0 8px">That works on a recording kept as values and formulas. This recording is a work session: its steps are the assistant working, not values in cells, so one step cannot be changed on its own here.</p>' +
    '<button class="ctl" id="change-to-try">Use “Try it differently from here” instead</button>';
  $('#change-to-try').onclick = () => { closePanels(); buildTryPanel(); openPanel('#panel-try'); };
}
function buildNotePanel() {
  $('#panel-note').innerHTML = '<h3>Note on step ' + state.step + '</h3>' +
    '<textarea id="note-text" rows="2" placeholder="A note pinned to this step…"></textarea>' +
    '<div style="margin-top:8px"><button class="ctl" id="note-go">Save note</button></div>';
  $('#note-go').onclick = () => {
    const text = $('#note-text').value.trim();
    if (!text) return;
    state.localNotes.push({ rec: state.rec, ver: state.ver, step: state.step, text: text });
    closePanels();
    if (state.tab !== 'steps') setTab('steps'); else renderBody();
    renderBar();
  };
}

// ---------- wiring ----------
$('#btn-first').onclick = () => { stopPlay(); gotoStep(1); };
$('#btn-back').onclick = () => { stopPlay(); gotoStep(state.step - 1); };
$('#btn-fwd').onclick = () => { stopPlay(); gotoStep(state.step + 1); };
$('#btn-play').onclick = () => {
  if (state.playing) { stopPlay(); return; }
  if (state.step >= maxStep()) gotoStep(1);
  state.playing = true;
  $('#btn-play').textContent = '⏸ Pause';
  tick();
};
$('#scrub').oninput = e => { stopPlay(); gotoStep(+e.target.value); };
$('#speed').onchange = e => { state.speed = +e.target.value; };
$('#notice-x').onclick = () => $('#notice').classList.remove('show');
document.querySelectorAll('.rtab').forEach(t => t.onclick = () => setTab(t.dataset.tab));
$('#btn-note').onclick = () => { buildNotePanel(); openPanel('#panel-note'); };
$('#btn-rules').onclick = () => setTab('where');
$('#btn-change').onclick = () => {
  if (state.rec === 'session') { buildChangePanel(); openPanel('#panel-change'); }
  else if (state.rec === 'desktop') showNotice('Steps cannot be changed in an outline recording: the words themselves were not kept.');
  else showNotice('Steps cannot be changed in a video-only recording: only pictures of the screen were kept.');
};
$('#btn-try').onclick = () => {
  if (!sealOk()) { showNotice('This recording does not check out, so nothing in it can be changed. You can watch it, but do not trust it.'); return; }
  if (can('fork')) { buildTryPanel(); openPanel('#panel-try'); }
  else if (state.rec === 'desktop') showNotice('You cannot try it differently from an outline recording: the words themselves were not kept, so there is no work session to give a new instruction to.');
  else showNotice('You cannot try it differently from a video-only recording: only pictures of the screen were kept.');
};
$('#btn-where').onclick = () => {
  if (!can('provenance')) {
    showNotice(state.rec === 'desktop'
      ? 'Words cannot be traced in an outline recording: the words themselves were not kept, only the parts of the screen.'
      : 'Words cannot be traced in a video-only recording: only pictures of the screen were kept.');
    return;
  }
  state.pick = !state.pick;
  $('#btn-where').classList.toggle('on', state.pick);
  if (state.pick) showNotice('Click any word or number on the screen. The answer appears under “Where it came from”.');
  renderStage();
};
document.addEventListener('keydown', e => {
  const tag = (e.target.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
  if (e.key === ' ') { e.preventDefault(); $('#btn-play').click(); }
  else if (e.key === 'ArrowLeft') { stopPlay(); gotoStep(state.step - 1); }
  else if (e.key === 'ArrowRight') { stopPlay(); gotoStep(state.step + 1); }
  else if (e.key === 'Escape') {
    closePanels();
    if (state.pick) { state.pick = false; $('#btn-where').classList.remove('on'); renderStage(); }
  }
});
renderAll();
</script>
</body></html>
"""

out = HTML.replace("__DATA__", data.replace("</script>", "<\\/script>"))
dest = Path.home() / "workspace/your_files/melange-player-v2"
dest.mkdir(parents=True, exist_ok=True)
(dest / "melange-player-v2.html").write_text(out)
print("wrote", dest / "melange-player-v2.html", len(out), "bytes")
