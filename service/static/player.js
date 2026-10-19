'use strict';
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kindNames = {native:'Full recording', structure:'Outline recording', 'screen-only':'Video-only recording'};
const stepNames = {tool_call:'Work was done', model_call:'Figures were calculated', terminal_chunk:'The screen changed', grid_keyframe:'The screen was saved', workspace_snapshot:'A checkpoint was saved', context_note:'An instruction was saved', annotation:'A note was added', fork:'A What-if began', edit:'A value was changed', ax_keyframe:'The screen outline was saved', ax_delta:'The screen outline changed', input_event:'An action was recorded', cell_frame:'The workbook changed', screen_frame:'The screen was recorded', generic_event:'An update was recorded', shelf:'A version was kept', narration:'The story was saved'};
const titles = {steps:'Steps', inspect:'Look inside', note:'Note', change:'Change this step', instruction:'Try it differently'};
const labels = {wages:'Wages', withholding:'Federal withholding', otherIncome:'Other income', standardDeduction:'Standard deduction', stateWages:'State wages', stateWithholding:'State withholding', dependents:'Dependents', agi:'Adjusted gross income', taxableIncome:'Taxable income', totalTax:'Total tax', refund:'Refund', taxBeforeCredits:'Tax before credits', childCredit:'Child credit', credit:'Credit', stateTaxable:'State taxable income', stateTax:'State tax', stateRefund:'State refund'};
const state = {stores:[], id:null, branch:null, detail:null, step:0, payload:null, cache:new Map(), generation:0, request:0, playing:false, timer:null, panel:null, loading:false, saving:false, speed:1};
Object.assign(labels,{retryBudget:'Retry budget',testsPassed:'Passed',testsFailed:'Failed',testsRun:'Tests run'});
function isCoding() { return state.detail?.computation?.profile==='coding-retry-v1'; }
function label(key) { const name = key.split('/').pop(); return labels[name] || name.replace(/_/g,' ').replace(/([a-z])([A-Z])/g,'$1 $2').replace(/^./,c=>c.toUpperCase()); }
function number(value) { return typeof value === 'number' ? value.toLocaleString(undefined,{maximumFractionDigits:2}) : String(value ?? '—'); }
function url(suffix='') { return '/api/store/'+encodeURIComponent(state.id)+'/branch/'+encodeURIComponent(state.branch)+suffix; }
async function api(path, body) {
  const response = await fetch(path, {cache:'no-store', ...(body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) throw new Error(data.reason || data.error || 'The recording could not be opened.');
  return data;
}
function status(text, error=false) { const out=$('#status'); out.textContent=text; out.hidden=!text; out.className=error?'error':''; }
function original(store) { return store.branches.find(b=>!b.fork && b.steps) || store.branches.find(b=>b.steps) || store.branches[0]; }
function versionName(branch) {
  if(!branch.fork) return 'Original';
  const name=branch.name.replace(/^whatif-clamp-/, '').replace(/^ghost-/, '').replace(/^whatif-/, 'instruction-');
  return 'What-if · '+label(name.replace(/[-_]/g,' '));
}
function renderLibrary() {
  $('#recordings').innerHTML=state.stores.map(s=>'<button class="recording" data-store="'+esc(s.id)+'" aria-current="'+(s.id===state.id)+'"><strong>'+esc(s.label)+'</strong><small>'+s.branches.length+' version'+(s.branches.length===1?'':'s')+' · '+(original(s)?.steps||0)+' steps</small></button>').join('');
  for(const button of document.querySelectorAll('[data-store]')) button.onclick=()=>{if(!state.saving) openRecording(button.dataset.store, original(state.stores.find(s=>s.id===button.dataset.store))?.name);};
}
async function boot(remember=true) {
  if(state.saving) return;
  const generation=++state.generation; ++state.request;
  stop(); state.loading=true; controls();
  closePanel(false);
  $('#connection-error').hidden=true;
  try {
    const stores=await api('/api/stores');
    if(generation!==state.generation) return;
    state.stores=stores;
    const hash=new URLSearchParams(location.hash.slice(1));
    const preferred=remember ? (state.id||hash.get('recording')) : null;
    const store=state.stores.find(s=>s.id===preferred)||state.stores.find(s=>s.branches.some(b=>b.steps))||state.stores[0];
    renderLibrary();
    $('#empty-library').hidden=!!store;
    if (!store) { state.detail=null; state.loading=false; $('#player').hidden=true; controls(); return; }
    const requested=remember ? (state.branch||hash.get('version')) : null;
    const branch=store.branches.find(b=>b.name===requested)||original(store);
    await openRecording(store.id,branch?.name,remember?(state.step||Number(hash.get('step'))||1):1);
  } catch(error) {
    if(generation!==state.generation) return;
    state.generation++; state.request++; state.loading=false; state.detail=null;
    $('#player').hidden=true; $('#connection-error').hidden=false;
    $('#connection-message').textContent='The recordings service is not answering correctly. '+error.message;
    controls();
  }
}
async function openRecording(id, branch, step=1, internal=false) {
  if(state.saving&&!internal) return;
  stop();
  const generation=++state.generation; ++state.request;
  state.id=id; state.branch=branch; state.detail=null; state.payload=null; state.cache=new Map(); state.loading=true;
  state.step=0; state.panel=null; closePanel(false); status(''); controls(); renderLibrary();
  const store=state.stores.find(s=>s.id===id);
  $('#title').textContent=store.label;
  $('#player').hidden=false; $('#kind').textContent='Opening recording…'; $('#seal').textContent='';
  $('#version-context').textContent=''; $('#integrity-warning').hidden=true;
  $('#version').innerHTML=[...store.branches].sort((a,b)=>Number(!!a.fork)-Number(!!b.fork)).map(b=>'<option value="'+esc(b.name)+'">'+esc(versionName(b))+'</option>').join('');
  $('#version').value=branch||'';
  $('#frame').innerHTML='<p class="busy-message">Opening recording…</p>';
  $('#step-title').textContent='Opening recording…'; $('#screen-label').textContent=''; $('#note-markers').replaceChildren(); $('#hint').textContent='';
  if(!branch) { state.loading=false; $('#kind').textContent='No steps yet'; $('#step-title').textContent='No steps yet'; $('#frame').innerHTML='<p class="busy-message">This recording has no steps yet.</p>'; controls(); return; }
  try {
    const detail=await api(url());
    if(generation!==state.generation) return;
    state.detail=detail; state.loading=false;
    $('#kind').textContent=kindNames[detail.fidelity]||'Recording';
    $('#seal').textContent=detail.seal?'✓ Recording checked':'Recording does not check out';
    $('#seal').className='badge '+(detail.seal?'good':'bad');
    $('#integrity-warning').hidden=detail.seal;
    $('#version-context').textContent=detail.fork?'What-if · from step '+detail.fork.split_step:'Original';
    $('#scrub').max=Math.max(1,detail.steps);
    renderMarkers();
    if(!detail.steps) { $('#frame').innerHTML='<p class="busy-message">This recording has no steps yet.</p>'; $('#step-title').textContent='No steps yet'; controls(); return; }
    await go(step===Infinity ? detail.steps : step, internal);
  } catch(error) {
    if(generation!==state.generation) return;
    state.loading=false; state.detail=null; controls();
    $('#frame').innerHTML='<p class="busy-message">This recording could not be opened. Use Refresh recordings to try again.</p>';
    status(error.message,true);
  }
}
function controls() {
  const d=state.detail, blocked=state.loading||state.saving||!d?.steps;
  $('#version').disabled=state.loading||state.saving;
  for(const id of ['play','scrub','speed']) $('#'+id).disabled=blocked;
  $('#back').disabled=blocked||state.step<=1;
  $('#forward').disabled=blocked||state.step>=d.steps;
  for(const b of document.querySelectorAll('[data-panel]')) { b.disabled=blocked; b.setAttribute('aria-pressed',String(b.dataset.panel===state.panel)); }
  $('#readout').textContent=d?.steps?'Step '+state.step+' of '+d.steps:'Step 0 of 0';
  for(const panel of ['inspect','change','instruction']) {
    const reason=locked(panel);
    const button=$('[data-panel="'+panel+'"]');
    button.textContent=(reason?'🔒 ':'')+titles[panel];
    // The action still opens its explanation, so it remains an operable button.
    button.title=reason||'';
  }
}
function locked(panel) {
  const d=state.detail; if(!d) return '';
  if(['note','change','instruction'].includes(panel)&&!d.seal) return 'This recording does not check out. You can watch it, but changes are unavailable.';
  if(panel==='inspect'&&!d.caps.includes('dive')) return 'Only the visible output was kept. This recording cannot show the parts inside it.';
  if(panel==='change' && (!d.caps.includes('clamp')||!d.computation)) return d.kind==='workbook'?'Workbook changes are available in Advanced view.':'This recording can be played back, but it does not contain a calculation that can be rerun here.';
  if(panel==='instruction'&&!d.caps.includes('fork')) return 'This recording can be played back, but it cannot start a new work session from this step.';
  return '';
}
async function go(step, internal=false) {
  const d=state.detail; if(!d?.steps||(state.saving&&!internal)) return false;
  const n=Math.max(1,Math.min(d.steps,Math.round(step)));
  const request=++state.request, generation=state.generation, endpoint=url('/step/'+n);
  $('#frame').setAttribute('aria-busy','true');
  try {
    let payload=state.cache.get(n);
    if(!payload) {
      payload=await api(endpoint+(d.kind==='video'?'?meta=1':''));
      if(request!==state.request||generation!==state.generation) return false;
      state.cache.set(n,payload);
    }
    if(request!==state.request||generation!==state.generation) return false;
    // Commit the picture and its label together. Late responses cannot repaint a newer selection.
    state.step=n; state.payload=payload;
    $('#scrub').value=n;
    renderFrame(payload,endpoint); controls();
    if(state.panel) renderPanel();
    history.replaceState(null,'','#'+new URLSearchParams({recording:state.id,version:state.branch,step:String(n)}));
    $('#hint').textContent='Space to play or pause · Arrow keys to step';
    if(d.computation_step&&n!==d.computation_step) {
      const button=document.createElement('button'); button.textContent=isCoding()?'Go to test run':'Go to calculation'; button.onclick=()=>{stop();go(d.computation_step);};
      $('#hint').append(' · ',button);
    }
    return true;
  } catch(error) {
    if(request===state.request&&generation===state.generation) { stop(); $('#scrub').value=state.step||1; status('Could not load that step. '+error.message,true); }
    return false;
  } finally { if(request===state.request&&generation===state.generation) $('#frame').setAttribute('aria-busy','false'); }
}
function valueTable(values,editable=false) {
  return '<table class="values"><tbody>'+Object.entries(values||{}).map(([key,value])=>'<tr><th scope="row">'+esc(label(key))+'</th><td>'+(editable?'<button class="value-edit" data-edit="'+esc(key)+'" aria-label="Change '+esc(label(key))+'">'+esc(number(value))+'</button>':esc(number(value)))+'</td></tr>').join('')+'</tbody></table>';
}
function bindValues() {
  for(const button of document.querySelectorAll('[data-edit]')) button.onclick=()=>{openPanel('change'); const field=$('#change-field'); if(field){field.value=button.dataset.edit;field.onchange();$('#change-value').focus();}};
}
function renderFrame(p, endpoint) {
  const d=state.detail, frame=$('#frame'), event=p.payload||{};
  frame.classList.toggle('code-run',event.profile==='coding-retry-v1');
  $('#step-title').textContent=stepNames[p.event_kind]||(d.kind==='workbook'?'The workbook at this step':'The screen at this step');
  $('#screen-label').textContent=d.kind==='video'?'Recorded picture':d.kind==='structure'?'Recorded screen outline':'Re-drawn from the recording';
  if(d.kind==='video') {
    frame.replaceChildren();const img=new Image();img.alt='Recorded screen, step '+state.step;img.src=endpoint;
    img.onerror=()=>{if(img.isConnected)status('The picture for this step could not be loaded.',true);};frame.append(img);return;
  }
  if(d.kind==='structure') { frame.innerHTML=outline(p.parts);return; }
  if(d.kind==='workbook') { frame.innerHTML='<h3>'+esc(p.label||'Recorded workbook')+'</h3>'+valueTable(p.values);return; }
  if(event.profile==='coding-retry-v1' && event.figures && event.execution) {
    const f=event.figures, run=event.execution, failed=f['/testsFailed'];
    $('#step-title').textContent=(event.clamped?'Tests rerun':'Recorded test run')+' · '+(failed?failed+' failing':'all '+f['/testsRun']+' pass');
    $('#screen-label').textContent='Python · actual process output';
    const editable=state.step===d.computation_step && !locked('change');
    const cases=String(run.output||'').split('\n').filter(line=>/^test_\d+_/.test(line));
    frame.innerHTML='<div class="figure-grid test-summary">'+['/testsPassed','/testsFailed','/testsRun'].map(key=>'<div class="figure '+(key==='/testsPassed'?'pass':key==='/testsFailed'?(failed?'fail':'clear'):'')+'"><span>'+esc(label(key))+'</span><strong>'+esc(number(f[key]))+'</strong></div>').join('')+'</div><div class="run-input"><span>Retry budget</span>'+(editable?'<button class="value-edit" data-edit="/retryBudget" aria-label="Change Retry budget">'+esc(event.inputs?.['/retryBudget'])+'</button>':'<strong>'+esc(event.inputs?.['/retryBudget'])+'</strong>')+'</div><pre class="test-output">'+cases.map(line=>'<span class="'+(/ERROR|FAIL/.test(line)?'failed':'')+'">'+esc(line.replace(/ \(__main__.*?\)/,''))+'</span>').join('\n')+'</pre><div class="run-footer"><span>Exit code '+esc(run.exit_code)+'</span><span>Synthetic coding task · real test execution</span></div><details class="code-evidence"><summary>View code · retry.py</summary><pre class="source-code">'+esc(run.source)+'</pre></details><details class="code-evidence"><summary>Full test output</summary><pre class="test-output">'+esc(run.output)+'</pre></details>';
    bindValues();return;
  }
  if(event.figures) {
    const figures=event.figures;
    const featured=['/totalTax','/refund','/agi'].filter(key=>key in figures);
    frame.innerHTML='<p class="eyebrow">'+(event.clamped?'RECALCULATED RESULT':'RECORDED CALCULATION')+'</p><h3>'+(event.clamped?'Here is what changed.':'The figures at this step.')+'</h3><div class="figure-grid">'+featured.map(key=>'<div class="figure"><span>'+esc(label(key))+'</span><strong>'+esc(number(figures[key]))+'</strong></div>').join('')+'</div>';
    if(state.step===d.computation_step && d.computation) frame.innerHTML+='<p class="muted">Select an input to try a different value.</p>'+valueTable(d.computation.inputs,!locked('change'));
    else frame.innerHTML+=valueTable(figures);
    bindValues();return;
  }
  if(p.event_kind==='tool_call' && event.output) { frame.innerHTML='<h3>'+esc(event.name||'Recorded work')+'</h3><pre class="document">'+esc(typeof event.output==='string'?event.output:JSON.stringify(event.output,null,2))+'</pre>';return; }
  if(p.event_kind==='context_note') {frame.innerHTML='<h3>Instruction saved</h3><p class="frame-note">'+esc(event.text||'')+'</p><p class="muted">This records an instruction. It has not been run by this player.</p>';return;}
  if(p.event_kind==='annotation') {frame.innerHTML='<h3>Note</h3><p class="frame-note">'+esc(event.text||'')+'</p>';return;}
  if(p.screen?.trim()) {frame.innerHTML='<pre class="transcript">'+esc(p.screen.trimEnd())+'</pre>';return;}
  frame.innerHTML='<h3>'+esc(stepNames[p.event_kind]||'Recorded step')+'</h3><p class="frame-note">'+(p.event_kind==='workspace_snapshot'?'The work was saved here so another version can start from it.':'This step did not add anything to the visible screen.')+'</p>';
}
function outline(parts) {
  if(!parts || !Object.keys(parts).length) return '<p class="frame-note">No screen outline was kept at this step.</p>';
  const nodes=Object.values(parts).filter(v=>v&&typeof v==='object'&&('role' in v||'name' in v));
  if(nodes.length) return '<h3>Parts of the recorded screen</h3><p class="frame-note">The words and controls kept at this step.</p>'+nodes.filter(n=>n.name||n.desc||!['none','generic'].includes(n.role)).map(n=>'<div class="outline-part"><small>'+esc(n.role||'Part')+'</small><p>'+esc(n.name||n.desc||'Unnamed part')+'</p></div>').join('');
  return '<h3>Recorded details</h3>'+valueTable(Object.fromEntries(Object.entries(parts).map(([k,v])=>[k,typeof v==='object'?JSON.stringify(v):v])));
}
function renderMarkers() {
  const d=state.detail, events=new Map((d.timeline||[]).map(e=>[e.event_id,e.step]));
  $('#scrub').max=Math.max(1,d.steps);
  const steps=[...new Set((d.notes||[]).map(n=>events.get(n.at_event)).filter(Boolean))];
  $('#note-markers').innerHTML=steps.map(n=>'<button style="left:'+((n-1)/Math.max(1,d.steps-1)*100)+'%" data-note-step="'+n+'" aria-label="Note at step '+n+'" title="Note at step '+n+'"></button>').join('');
  for(const b of document.querySelectorAll('[data-note-step]')) b.onclick=async()=>{stop();await go(Number(b.dataset.noteStep));openPanel('note');};
}
function stop() {state.playing=false;clearTimeout(state.timer);$('#play').innerHTML='▶ <span>Play</span>';$('#play').setAttribute('aria-label','Play');}
function schedule() {
  if(!state.playing)return;
  if(state.step>=state.detail.steps){stop();return;}
  const line=state.detail.timeline||[], a=line[state.step-1],b=line[state.step];
  const gap=a&&b&&Number.isFinite(a.ts)&&Number.isFinite(b.ts)?b.ts-a.ts:.9;
  const generation=state.generation;
  state.timer=setTimeout(async()=>{if(!state.playing||generation!==state.generation)return;const ok=await go(state.step+1);if(ok&&state.playing&&generation===state.generation)schedule();},Math.max(.25,Math.min(3,gap))*1000/state.speed);
}
$('#play').onclick=async()=>{if(state.playing){stop();return;}if(!state.detail?.steps)return;const generation=state.generation;if(state.step>=state.detail.steps&&!await go(1))return;if(generation!==state.generation)return;state.playing=true;$('#play').innerHTML='Ⅱ <span>Pause</span>';$('#play').setAttribute('aria-label','Pause');schedule();};
$('#back').onclick=()=>{stop();go(state.step-1);};$('#forward').onclick=()=>{stop();go(state.step+1);};
$('#scrub').oninput=e=>{stop();go(Number(e.target.value));};
$('#speed').onchange=e=>{state.speed=Number(e.target.value);if(state.playing){clearTimeout(state.timer);schedule();}};
$('#version').onchange=e=>openRecording(state.id,e.target.value,state.step);
for(const b of document.querySelectorAll('[data-panel]'))b.onclick=()=>state.panel===b.dataset.panel?closePanel():openPanel(b.dataset.panel);
function openPanel(name) {if(!state.detail||state.saving)return;stop();state.panel=name;$('#inspector').hidden=false;$('#workspace').classList.add('with-panel');renderPanel();controls();}
function closePanel(focus=true) {const old=state.panel;state.panel=null;$('#inspector').hidden=true;$('#workspace').classList.remove('with-panel');controls();if(focus&&old)$('[data-panel="'+old+'"]').focus();}
$('#close-panel').onclick=()=>closePanel();
function renderPanel() {
  const name=state.panel,d=state.detail,p=state.payload;if(!name||!d)return;
  const box=$('#panel-content');$('#panel-title').textContent=titles[name];
  const reason=locked(name);if(reason){box.innerHTML='<p>'+esc(reason)+'</p>';return;}
  if(name==='steps') {
    box.innerHTML='<ol class="step-list">'+(d.timeline||[]).map(e=>'<li><button data-step="'+e.step+'"'+(e.step===state.step?' aria-current="step"':'')+'><span class="step-number">'+e.step+'</span>'+esc(stepNames[e.kind]||'Recorded update')+'</button></li>').join('')+'</ol>';
    for(const b of box.querySelectorAll('[data-step]'))b.onclick=()=>go(Number(b.dataset.step));return;
  }
  if(name==='inspect') {
    if(p?.payload?.figures) box.innerHTML='<p>Figures kept at step '+state.step+'.</p>'+valueTable(p.payload.figures);
    else if(d.kind==='structure')box.innerHTML=outline(p.parts);
    else if(d.kind==='workbook')box.innerHTML=valueTable(p.values);
    else box.innerHTML='<p>'+esc(stepNames[p?.event_kind]||'Recorded step')+'.</p><p>'+(p?.payload?.name?'Recorded action: '+esc(p.payload.name):'This step has no calculated figures to look inside. Use Steps to move to a calculation.')+'</p>';
    return;
  }
  if(name==='note') {
    const at=p.event_id,notes=(d.notes||[]).filter(n=>n.at_event===at);
    box.innerHTML='<p>Notes on step '+state.step+' stay with the recording.</p>'+notes.map(n=>'<div class="note"><small>Step '+state.step+'</small>'+esc(n.text)+'</div>').join('')+'<form id="note-form"><label for="note-text">Your note</label><textarea id="note-text" rows="4" required placeholder="What should you remember here?"></textarea><button class="primary" type="submit">Save note</button><p class="panel-error" id="form-error" role="alert"></p></form>';
    const step=state.step;
    $('#note-form').onsubmit=e=>{e.preventDefault();save(async()=>{await api(url('/note'),{step,text:$('#note-text').value.trim()});const detail=await api(url());state.detail=detail;renderMarkers();renderPanel();status('Note saved at step '+step+'.');});};return;
  }
  if(name==='change') {
    if(state.step!==d.computation_step){box.innerHTML='<p>Go to the recorded run to choose an input and try another outcome.</p><button id="to-calculation" class="primary">'+(isCoding()?'Go to test run':'Go to calculation')+'</button>';$('#to-calculation').onclick=()=>go(d.computation_step);return;}
    box.innerHTML='<p>'+(isCoding()?'Change the retry budget and rerun the Python tests in a What-if. The Original stays unchanged.':'Change a recorded input and rerun its calculation in a What-if. The Original stays unchanged.')+'</p><form id="change-form"><label for="change-field">Input to change</label><select id="change-field">'+Object.keys(d.computation.inputs).map(key=>'<option value="'+esc(key)+'">'+esc(label(key))+'</option>').join('')+'</select><p id="current-value" class="note-tip"></p><label for="change-value">New value</label><input id="change-value" type="number" '+(isCoding()?'step="1" min="0" max="8"':'step="any"')+' required><button class="primary" type="submit">Make the What-if</button><p id="form-error" class="panel-error" role="alert"></p></form>';
    $('#change-field').onchange=()=>{const current=d.computation.inputs[$('#change-field').value];$('#current-value').textContent='Current value: '+number(current);$('#change-value').value=current;};$('#change-field').onchange();
    $('#change-form').onsubmit=e=>{e.preventDefault();const key=$('#change-field').value,value=Number($('#change-value').value),before=d.computation.inputs[key],storeId=state.id;if(!Number.isFinite(value))return;if(value===before){$('#form-error').textContent='Enter a different value to make a What-if.';return;}save(async()=>{const result=await api(url('/fork'),{clamp:{cell:key,value}});state.stores=await api('/api/stores');await openRecording(storeId,result.branch,Infinity,true);if(!state.payload)return;status(label(key)+' changed from '+number(before)+' to '+number(value)+'. The result below was recalculated.');const parent=d.branch;const back=document.createElement('button');back.textContent=d.fork?'Compare previous version':'Compare Original';back.onclick=()=>openRecording(storeId,parent,d.computation_step);$('#status').append(back);});};return;
  }
  if(name==='instruction') {
    box.innerHTML='<p>This makes a What-if copy and saves your instruction. It runs when the recording is reopened in a live session.</p><form id="instruction-form"><label for="instruction-text">New instruction at step '+state.step+'</label><textarea id="instruction-text" rows="4" required></textarea><button class="primary" type="submit">Save instruction in a What-if</button><p id="form-error" class="panel-error" role="alert"></p></form>';
    const step=state.step;
    $('#instruction-form').onsubmit=e=>{e.preventDefault();save(async()=>{const storeId=state.id;const result=await api(url('/fork'),{step,note:$('#instruction-text').value.trim()});state.stores=await api('/api/stores');await openRecording(storeId,result.branch,Infinity,true);if(state.payload)status('Instruction saved in a What-if. It has not run; it needs a live session.');});};
  }
}
async function save(action) {
  if(state.saving||state.loading)return;state.saving=true;stop();controls();
  const button=$('#panel-content button[type=submit]');if(button)button.disabled=true;
  const error=$('#form-error');if(error)error.textContent='';
  try{await action();}catch(e){if(error?.isConnected)error.textContent=e.message;else status(e.message,true);}finally{state.saving=false;controls();if(button?.isConnected)button.disabled=false;}
}
document.addEventListener('keydown',e=>{if(e.target.closest('input,textarea,select,button,a')||e.altKey||e.ctrlKey||e.metaKey)return;if(e.code==='Space'){e.preventDefault();$('#play').click();}if(e.code==='ArrowLeft'){e.preventDefault();$('#back').click();}if(e.code==='ArrowRight'){e.preventDefault();$('#forward').click();}if(e.code==='Escape')closePanel();});
for(const id of ['refresh','retry','empty-refresh'])$('#'+id).onclick=()=>{if(!state.saving)boot();};
boot();
