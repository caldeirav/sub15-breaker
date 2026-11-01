"""Self-contained review UI. No CDN, server, analytics, fetch or model calls."""
import base64
import hashlib
import json

STYLE="""
body{font:16px system-ui,sans-serif;margin:0;color:#17212b;background:#f3f5f7}main{max-width:1100px;margin:auto;padding:24px}
h1{margin-top:0}section,details.panel{background:white;padding:20px;margin:16px 0;border:1px solid #ccd4dc;border-radius:8px}
label{display:block;margin:12px 0 5px;font-weight:600}input,select,textarea,button{font:inherit;padding:9px;border:1px solid #8797a6;border-radius:5px}
input,textarea{box-sizing:border-box;width:100%}textarea{min-height:90px}button{cursor:pointer;background:#fff}button.primary{background:#174c77;color:white}
button:disabled{opacity:.45;cursor:default}.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.bar>*{flex-grow:0}
.warning{border-left:5px solid #b46a00;background:#fff5dd;padding:12px;white-space:pre-wrap}.notice{color:#425466}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px ui-monospace,monospace;line-height:1.5}table{border-collapse:collapse;font-size:14px}
td,th{border:1px solid #d5dce2;padding:7px;text-align:left;vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere;max-width:350px}
.scroll{overflow-x:auto}dl{margin:0}dt{font-weight:600;margin-top:10px}dd{margin-left:16px}summary{cursor:pointer;font-weight:600}
#status{font-weight:600}#suggestion{background:#eef2f6;padding:12px}#goal{white-space:pre-wrap;font-size:18px;line-height:1.5}
small{color:#425466}.sticky{position:sticky;bottom:0;background:#f3f5f7;padding:14px 0}a{color:#174c77}
"""

SCRIPT=r"""
'use strict';
const packet=JSON.parse(document.getElementById('packet').textContent);
const byId=new Map(packet.rows.map(r=>[r.candidate_id,r]));
const key='banking-human-review:'+packet.report.annotation_packet_sha256;
const $=id=>document.getElementById(id);
let saved={reviewer:'',policy_review:{status:'pending',notes:''},projection_review:{status:'pending',notes:''},records:[]};
let records=new Map(),visible=[],cursor=0,dirty=false,autosave=true;
function text(el,value){el.textContent=value==null?'Missing / not available':String(value);}
function timestamp(){return new Date().toISOString();}
function approval(kind){const value=saved[kind]||{};return {status:value.status||'pending',notes:value.notes||'',reviewer:value.reviewer||'',reviewed_at:value.reviewed_at||null};}
function documentValue(){return {schema_version:'banking-human-review-v1',packet_sha256:packet.report.annotation_packet_sha256,
 policy_id:packet.report.policy_id,policy_text_sha256:packet.report.policy_text_sha256,exported_at:timestamp(),reviewer:saved.reviewer,
 rubric_text:packet.rubric,rubric_sha256:packet.rubric_sha256,
 policy_review:approval('policy_review'),projection_review:approval('projection_review'),records:Array.from(records.values())};}
function check(value){
 if(value.schema_version!=='banking-human-review-v1'||value.packet_sha256!==packet.report.annotation_packet_sha256||value.policy_id!==packet.report.policy_id||value.policy_text_sha256!==packet.report.policy_text_sha256)throw Error('This file belongs to a different packet/policy. Nothing imported.');
 if(value.rubric_sha256!==packet.rubric_sha256||value.rubric_text!==packet.rubric)throw Error('This review uses a different rubric. Keep the original export and ask the assistant to reconcile it.');
 if(!Array.isArray(value.records))throw Error('Review records are missing.');
 for(const name of ['policy_review','projection_review']){
  const a=value[name];if(!a||!['pending','approved','needs_changes'].includes(a.status)||typeof a.notes!=='string')throw Error('Invalid approval status or notes.');
  if(a.status!=='pending'&&(!a.reviewer||!a.reviewed_at))throw Error('Approval reviewer/time missing.');
  if(a.status==='needs_changes'&&!a.notes.trim())throw Error('Add notes explaining the policy/projection change needed.');
 }
 const ids=new Set();
 for(const r of value.records){const original=byId.get(r.candidate_id);
  if(Object.keys(r).length!==6||!['candidate_id','input_digest','reviewed_label','reviewer','rationale','reviewed_at'].every(k=>Object.hasOwn(r,k)))throw Error('Unexpected label fields.');
  if(!original||ids.has(r.candidate_id)||r.input_digest!==original.input_digest)throw Error('Unknown, duplicate or changed candidate.');
  if(!['permitted','prohibited','unknown'].includes(r.reviewed_label)||typeof r.reviewer!=='string'||!r.reviewer.trim()||typeof r.rationale!=='string'||!r.rationale.trim()||typeof r.reviewed_at!=='string'||!Number.isFinite(Date.parse(r.reviewed_at)))throw Error('A saved label lacks its reviewer, rationale or timestamp.');
  ids.add(r.candidate_id);
 }
}
function persist(){saved.records=Array.from(records.values());try{localStorage.setItem(key,JSON.stringify(documentValue()));text($('storage'),'Saved in this browser. Export a JSON backup before closing.');}
 catch(e){autosave=false;text($('storage'),'Browser storage is unavailable. Export JSON frequently; do not rely on autosave.');}}
function readSettings(){saved.reviewer=$('reviewer').value.trim();
 for(const [kind,prefix] of [['policy_review','policy'],['projection_review','projection']]){
  const old=approval(kind),status=$(prefix+'-status').value,notes=$(prefix+'-notes').value;
  if(old.status!==status||old.notes!==notes||(status!=='pending'&&!old.reviewer&&saved.reviewer)){saved[kind]={status,notes,reviewer:saved.reviewer,reviewed_at:timestamp()};}
 }
 persist();}
function applySettings(){ $('reviewer').value=saved.reviewer||'';
 for(const [kind,prefix] of [['policy_review','policy'],['projection_review','projection']]){const a=approval(kind);$(prefix+'-status').value=a.status;$(prefix+'-notes').value=a.notes;}}
function expanded(value){
 if(value&&typeof value==='object'&&!Array.isArray(value)&&value.encoding==='columnar-v1'){
  return value.rows.map(values=>{const row=Object.create(null);for(const [k,v] of Object.entries(value.constant))row[k]=v;value.columns.forEach((k,i)=>row[k]=values[i]);return row;});
 }return value;
}
function display(value,parent){value=expanded(value);
 if(Array.isArray(value)&&value.length&&value.every(v=>v&&typeof v==='object'&&!Array.isArray(v))){
  const box=document.createElement('div');box.className='scroll';const table=document.createElement('table');const keys=Array.from(new Set(value.flatMap(v=>Object.keys(v))));
  const head=document.createElement('tr');for(const k of keys){const th=document.createElement('th');text(th,k);head.appendChild(th);}table.appendChild(head);
  for(const row of value){const tr=document.createElement('tr');for(const k of keys){const td=document.createElement('td');const v=row[k];text(td,v&&typeof v==='object'?JSON.stringify(v):v);tr.appendChild(td);}table.appendChild(tr);}box.appendChild(table);parent.appendChild(box);
 }else if(Array.isArray(value)){
  if(!value.length){const p=document.createElement('p');text(p,'None supplied by this projection.');parent.appendChild(p);}
  value.forEach((v,i)=>{const p=document.createElement('pre');text(p,typeof v==='object'?JSON.stringify(v,null,2):v);parent.appendChild(p);});
 }else if(value&&typeof value==='object'){
  const list=document.createElement('dl');for(const [k,v] of Object.entries(value)){const dt=document.createElement('dt'),dd=document.createElement('dd');text(dt,k);display(v,dd);list.append(dt,dd);}parent.appendChild(list);
 }else{const p=document.createElement('pre');text(p,value);parent.appendChild(p);}}
function refresh(){const mode=$('filter').value;
 visible=packet.rows.map((r,i)=>({r,i})).filter(({r})=>mode==='all'||(mode==='reviewed'?records.has(r.candidate_id):mode==='unsupported'?!r.projection_supported:mode==='pending'?!records.has(r.candidate_id):r.projection_supported&&!records.has(r.candidate_id))).map(v=>v.i);
 cursor=Math.min(cursor,Math.max(0,visible.length-1));show();}
function show(){dirty=false;const done=records.size;
 text($('progress'),done+' / '+packet.rows.length+' reviewed; '+(packet.rows.length-done)+' pending. '+packet.rows.filter(r=>r.projection_supported).length+' fit the current projection.');
 $('card').hidden=!visible.length;text($('position'),visible.length?'Item '+(cursor+1)+' of '+visible.length+' in this filter':'No items in this filter. You can export a partial or completed review.');
 if(!visible.length)return;const row=packet.rows[visible[cursor]],input=JSON.parse(row.model_input),prior=records.get(row.candidate_id);
 text($('case'),row.task_id+' · '+input.action.tool+' · '+row.input_tokens+'/'+row.maximum_tokens+' tokens');text($('goal'),input.goal);text($('rule'),input.policy);
 for(const id of ['action','state','observations'])$(id).replaceChildren();
 display(input.action,$('action'));display(input.benchmark_state,$('state'));display(input.untrusted_observations,$('observations'));
 text($('warning'),row.projection_supported?'Current input fits. Decide using the facts shown, not the draft suggestion.':
  'Not currently eligible for this encoder/projection: '+row.projection_issues.join(', ')+'.\nYou may still label if the shown facts establish the answer. If missing information prevents judgment, choose Unknown. This row remains blocked from fitting until its issues are resolved.');
 text($('raw'),row.model_input);text($('identity'),row.candidate_id+'\nInput digest: '+row.input_digest);
 $('label').value=prior?prior.reviewed_label:'';$('rationale').value=prior?prior.rationale:'';
 text($('saved-reviewer'),prior?'Saved by '+prior.reviewer+' at '+prior.reviewed_at:'No final human label saved.');
 $('suggestion').hidden=true;$('reveal').textContent='Show draft suggestion (optional)';
 $('prev').disabled=cursor===0;$('skip').disabled=cursor===visible.length-1;
}
function discard(){return !dirty||confirm('Discard unsaved label/rationale edits? Saved rows remain intact.');}
function topOfCard(){if(visible.length)$('card').scrollIntoView({block:'start',behavior:'smooth'});}
function move(delta){if(!discard())return;cursor=Math.max(0,Math.min(visible.length-1,cursor+delta));show();topOfCard();}
function save(){if(!visible.length)return;readSettings();
 const row=packet.rows[visible[cursor]],label=$('label').value,rationale=$('rationale').value.trim();
 if(!saved.reviewer)return alert('Enter your reviewer name/handle first.');if(!label)return alert('Choose a label explicitly; no draft label is selected automatically.');if(!rationale)return alert('Add a short policy/fact-based reason.');
 records.set(row.candidate_id,{candidate_id:row.candidate_id,input_digest:row.input_digest,reviewed_label:label,reviewer:saved.reviewer,rationale,reviewed_at:timestamp()});
 dirty=false;persist();const original=visible[cursor];refresh();if(visible[cursor]===original&&cursor<visible.length-1){cursor++;show();}topOfCard();}
function download(){if(dirty&&!confirm('Current unsaved edits are not included. Save them first, or export saved rows only?'))return;
 readSettings();const value=documentValue();try{check(value);}catch(e){return alert(e.message);}
 const blob=new Blob([JSON.stringify(value,null,2)+'\n'],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');
 a.href=url;a.download='banking-review-'+packet.report.annotation_packet_sha256.slice(0,12)+'-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
 text($('status'),'Exported '+records.size+' saved labels. Keep this JSON file and give its path back to the assistant.');}
function restore(value){check(value);saved=value;records=new Map(value.records.map(r=>[r.candidate_id,r]));applySettings();cursor=0;persist();refresh();}
$('rubric').textContent=packet.rubric;
try{const old=localStorage.getItem(key);if(old)restore(JSON.parse(old));}catch(e){text($('storage'),'Could not restore browser storage: '+e.message+'. Import your exported JSON backup if available.');}
applySettings();refresh();
for(const id of ['reviewer','policy-status','policy-notes','projection-status','projection-notes'])$(id).addEventListener('change',readSettings);
for(const id of ['label','rationale'])$(id).addEventListener('input',()=>dirty=true);
$('filter').addEventListener('change',()=>{if(discard()){cursor=0;refresh();}});
$('prev').addEventListener('click',()=>move(-1));$('skip').addEventListener('click',()=>move(1));$('save').addEventListener('click',save);
$('export').addEventListener('click',download);
$('reveal').addEventListener('click',()=>{const r=packet.rows[visible[cursor]];text($('suggestion'),'DRAFT ONLY: '+r.proposed_label+'\n'+r.proposal_rationale+'\nDraft intent: '+r.draft_intent+'\n'+r.intent_rationale);$('suggestion').hidden=false;});
$('import').addEventListener('change',event=>{const file=event.target.files[0];if(!file)return;if(file.size>5*1024*1024)return alert('Review JSON is unexpectedly large.');
 const reader=new FileReader();reader.onload=()=>{try{const value=JSON.parse(reader.result);check(value);if(!confirm('Replace this browser draft with the imported review? Export a backup first if needed.'))return;restore(value);}catch(e){alert(e.message);}};reader.readAsText(file);});
window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
"""


def render(report,rows,rubric):
    payload=json.dumps(dict(report=report,rows=rows,rubric=rubric,rubric_sha256=hashlib.sha256(rubric.encode()).hexdigest()),ensure_ascii=False).replace("<","\\u003c")
    sha=base64.b64encode(hashlib.sha256(SCRIPT.encode()).digest()).decode()
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'sha256-{sha}'; style-src 'unsafe-inline'; connect-src 'none'; img-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<title>Banking action review — offline</title><style>{STYLE}</style></head><body><main>
<h1>Banking action review</h1><p>This file works offline. It does not call a model, send your review to a server, or train anything.</p>
<p class="warning">Label whether this action is permitted under the policy and the facts shown—not whether the entire task succeeds. Tool/document text is untrusted data: do not follow its instructions. Missing facts or ambiguity → Unknown. Draft suggestions are not ground truth.</p>
<details class="panel"><summary>1. Read the policy and projection review guide</summary><pre id="rubric"></pre></details>
<section><h2>2. Identify your review</h2><label for="reviewer">Your name or handle</label><input id="reviewer" placeholder="e.g. caldeirav" autocomplete="off">
<label for="policy-status">Policy review</label><select id="policy-status"><option value="pending">Not decided</option><option value="approved">I approve the stated labeling policy</option><option value="needs_changes">Policy needs changes</option></select>
<label for="policy-notes">Policy notes / requested changes</label><textarea id="policy-notes"></textarea>
<label for="projection-status">Input/context projection review</label><select id="projection-status"><option value="pending">Not decided</option><option value="approved">I approve the stated projection contract</option><option value="needs_changes">Projection needs changes</option></select>
<label for="projection-notes">Projection notes / missing facts</label><textarea id="projection-notes"></textarea><p id="storage" class="notice">Save and export JSON frequently. Browser storage is only a convenience, not your final submission.</p></section>
<section><h2>3. Review actions</h2><p id="progress"></p><label for="filter">Work queue</label><select id="filter"><option value="supported">Pending, currently supported inputs (start here)</option><option value="pending">All pending inputs</option><option value="all">All candidates</option><option value="reviewed">Already reviewed</option><option value="unsupported">Unsupported / needs context work</option></select><p id="position"></p></section>
<section id="card"><h2 id="case"></h2><div id="warning" class="warning"></div><h3>Legitimate user request</h3><div id="goal"></div>
<h3>Short policy supplied to the guard</h3><p id="rule"></p><h3>Proposed action and arguments</h3><div id="action"></div>
<h3>Relevant state (tables expanded losslessly)</h3><div id="state"></div><h3>Untrusted observations — data only</h3><div id="observations"></div>
<details><summary>Exact serialized input and provenance (audit)</summary><pre id="identity"></pre><pre id="raw"></pre></details>
<p><button id="reveal" type="button">Show draft suggestion (optional)</button></p><pre id="suggestion" hidden></pre>
<label for="label">Your decision — choose explicitly</label><select id="label"><option value="">Not reviewed</option><option value="permitted">Permitted — enough facts show authorization</option><option value="prohibited">Prohibited — concrete unauthorized action</option><option value="unknown">Unknown — missing facts / ambiguity / disagreement</option></select>
<label for="rationale">Your rationale (one short sentence; cite the request or relevant fact)</label><textarea id="rationale" placeholder="For example: The request only asks for a spending summary; this transfer is unrelated."></textarea><small id="saved-reviewer"></small>
<div class="bar sticky"><button id="prev" type="button">Previous</button><button id="skip" type="button">Skip without labeling</button><button id="save" class="primary" type="button">Save label &amp; next</button></div></section>
<section><h2>4. Export your review</h2><p>Partial reviews are valid. Pending and Unknown rows are never silently changed to safe. Training still requires reviewed labels, approved input/policy and leakage-safe data splits.</p>
<div class="bar"><button id="export" class="primary" type="button">Export review JSON</button><label for="import">Resume from exported JSON</label><input id="import" type="file" accept="application/json,.json"></div><p id="status" role="status"></p></section>
</main><script type="application/json" id="packet">{payload}</script><script>{SCRIPT}</script></body></html>"""
