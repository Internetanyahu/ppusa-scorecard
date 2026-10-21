'use strict';

/* Static admin editor for scorecard_sets_config.json. */
const VERIFIER = {
  salt: 'f26d0b470221240e7dff7de5e56c581e',
  iterations: 600000,
  hash: '095031433fe8fbf8096a1ca8d815a4ede7d05dab03723278e8610b86a27f4505'
};
const REPO = { owner: 'SK64HD', repo: 'ppusa_conservative_scorecard', path: 'scorecard_sets_config.json' };
const CATS = ['social', 'economic', 'foreign'];
const DIRS = [1, 0, -1];
const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[c]));
const norm = s => String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
const clone = o => JSON.parse(JSON.stringify(o));

const S = { config: null, data: null, original: null, selected: null, provisions: [], q: '', token: '' };

async function verify(secret) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret.trim().toLowerCase()), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name:'PBKDF2', hash:'SHA-256', salt:Uint8Array.from(VERIFIER.salt.match(/../g),x=>parseInt(x,16)), iterations:VERIFIER.iterations }, key, 256);
  const got = Array.from(new Uint8Array(bits),x=>x.toString(16).padStart(2,'0')).join('');
  return got === VERIFIER.hash;
}

function slugify(value){return String(value||'').trim().toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,48)||`scorecard-${Date.now()}`;}
function setById(id){return S.config.sets.find(x=>x.id===id)}
function selectedSet(){return setById(S.selected)}
function ensureShape(set){
  set.id ||= slugify(set.name); set.name ||= set.id; set.description ||= ''; set.strategy ||= 'conservative'; set.owner_name ||= ''; set.owner_player_id ||= '';
  set.category_names ||= {}; CATS.forEach(c=>{set.category_names[c] ||= c[0].toUpperCase()+c.slice(1)});
  set.ideology_labels ||= {}; CATS.forEach(c=>{set.ideology_labels[c]=Array.isArray(set.ideology_labels[c])?set.ideology_labels[c]:[]});
  set.provision_overrides ||= {}; return set;
}
function defaultLabels(){return {social:['Left 1','Left 2','Left 3','Left 4','Center','Right 6','Right 7','Right 8','Right 9'],economic:['Left 1','Left 2','Left 3','Left 4','Center','Right 6','Right 7','Right 8','Right 9'],foreign:['Left 1','Left 2','Left 3','Left 4','Center','Right 6','Right 7','Right 8','Right 9']}}
function currentAssignment(set,name){
  const o=set.provision_overrides?.[norm(name)]||set.provision_overrides?.[name];
  if(o)return {direction:Number(o.direction),category:o.category||'',rationale:o.rationale||'',id:o.id||`SET-${slugify(name)}`};
  const generated=S.data?.sets?.find(x=>x.id===set.id);
  for(const bill of Object.values(generated?.bills||{})){const p=(bill.scorecard?.provisions||[]).find(x=>norm(x.name)===norm(name));if(p)return {direction:Number(p.direction),category:p.category||'',rationale:p.rationale||'',id:p.rule_id||''}}
  return {direction:0,category:'',rationale:'',id:''};
}
function buildProvisions(){
  const set=selectedSet(),generated=S.data?.sets?.find(x=>x.id===set?.id),map=new Map();
  Object.values(generated?.bills||{}).forEach(b=>(b.scorecard?.provisions||[]).forEach(p=>{if(!p.name)return;const k=norm(p.name);if(!map.has(k))map.set(k,{name:p.name,bills:new Set()});map.get(k).bills.add(b.number||String(b.resolution_id))}));
  Object.keys(set?.provision_overrides||{}).forEach(k=>{if(!map.has(norm(k)))map.set(norm(k),{name:k,bills:new Set()})});
  S.provisions=[...map.values()].map(x=>({...x,bills:[...x.bills]})).sort((a,b)=>a.name.localeCompare(b.name));
}
function changed(){return JSON.stringify(S.config)!==JSON.stringify(S.original)}

function render(){
  const root=$('app'),set=selectedSet();if(!set)return;ensureShape(set);buildProvisions();
  root.innerHTML=`<header class="adm-head"><div class="shell"><p class="eyebrow">PPUSA-SCORECARD ADMIN</p><h1>Scorecard sets</h1><p>Create, rename and configure independent scorecards. Set passwords are never stored in this public file.</p></div></header><main class="shell set-admin"><section class="set-manager panel"><div class="set-manager-head"><div><h2>Scorecard sets</h2><p class="note">Add a set; the master admin can generate its password.</p></div><button class="btn primary" id="addSet">Add scorecard set</button></div><div class="set-list">${S.config.sets.map(s=>`<button type="button" class="set-card ${s.id===S.selected?'active':''}" data-select-set="${esc(s.id)}"><strong>${esc(s.name)}</strong><span>${esc(s.strategy)}</span>${s.owner_name?`<small>Owner: ${esc(s.owner_name)}</small>`:'<small>No owner assigned</small>'}</button>`).join('')}</div></section><section class="panel set-editor"><div class="editor-head"><div><p class="eyebrow">SELECTED SET</p><h2>${esc(set.name)}</h2></div><div class="set-actions"><button class="btn danger" id="deleteSet">Delete set</button></div></div><div class="rrow-grid set-fields"><div><label>Set name</label><input id="setName" value="${esc(set.name)}"></div><div><label>Set ID</label><input id="setId" value="${esc(set.id)}" ${set.id==='conservative'||set.id==='states-rights'?'disabled':''}></div><div><label>Base strategy</label><select id="setStrategy"><option value="conservative" ${set.strategy==='conservative'?'selected':''}>Conservative</option><option value="states_rights" ${set.strategy==='states_rights'?'selected':''}>State's Rights</option></select></div><div><label>Owner / party leader</label><input id="setOwner" value="${esc(set.owner_name)}" placeholder="Future party leader"></div></div><div><label>Description</label><textarea id="setDescription">${esc(set.description)}</textarea></div><div class="rrow-grid category-fields">${CATS.map(c=>`<div><label>${esc(c)} category name</label><input data-cat-name="${c}" value="${esc(set.category_names[c])}"></div>`).join('')}</div><h3>Ideology labels</h3><p class="note">Enter exactly 9 labels per category, from 0–10 through 90–100.</p><div class="labels-grid">${CATS.map(c=>`<div><label>${esc(c)}</label><textarea data-labels="${c}">${esc((set.ideology_labels[c]||[]).join(', '))}</textarea></div>`).join('')}</div><div class="provision-editor"><div class="provision-head"><div><h3>Provision assignments</h3><p class="note">A set override replaces its base strategy. Neutral (0) is excluded from scoring.</p></div><input id="provisionSearch" type="search" placeholder="Search provisions or bill number"></div><div id="provisionList"></div></div></section></main><div class="actionbar"><div class="shell"><span class="muted">${changed()?'Unsaved changes':'No unsaved changes'}</span><div class="btns"><button class="btn" id="discard">Discard</button><button class="btn" id="download">Download JSON</button><button class="btn primary" id="publish">Publish to GitHub</button></div></div></div><dialog id="pubDlg" class="dialog"><button class="dialog-close" data-close aria-label="Close">×</button><div class="pad"><h2>Publish scorecard sets</h2><p class="note">Use a fine-grained GitHub token. It is kept only in this tab.</p><div class="row2"><div><label>Owner</label><input id="pOwner" value="${esc(REPO.owner)}"></div><div><label>Repository</label><input id="pRepo" value="${esc(REPO.repo)}"></div></div><div><label>GitHub token</label><input id="pTok" type="password" autocomplete="off"></div><div><label>Commit message</label><input id="pMsg" value="Update scorecard sets"></div><div id="pStatus" class="status"></div><button class="btn primary" id="pGo">Commit changes</button></div></dialog>`;
  wire();renderProvisions();
}
function renderProvisions(){
  const set=selectedSet(),q=String(S.q||'').trim().toLowerCase(),list=S.provisions.filter(p=>!q||norm(p.name).includes(q)||p.bills.some(b=>String(b).toLowerCase().includes(q)));
  $('provisionList').innerHTML=list.map(p=>{const a=currentAssignment(set,p.name),io=!!(set.provision_overrides?.[norm(p.name)]||set.provision_overrides?.[p.name]);return `<div class="prow ${io?'pending':'inherited'}" data-provision="${esc(p.name)}"><div class="prow-top"><div><div class="prow-name">${esc(p.name)}</div><div class="prow-meta">${esc(p.bills.join(', '))} · ${io?'Set override':'Inherited from strategy'}</div></div><span class="badge ${io?'ok':'todo'}">${io?'Override':'Inherited'}</span></div><div class="prow-controls"><div><label>Direction</label><div class="seg">${DIRS.map(d=>`<button type="button" data-dir="${d}" class="${a.direction===d?(d>0?'on pos':d<0?'on neg':'on neu'):''}">${d>0?'+1':d<0?'−1':'0'}</button>`).join('')}</div></div><div><label>Category</label><select data-field="category" ${a.direction===0?'disabled':''}>${CATS.map(c=>`<option value="${c}" ${a.category===c?'selected':''}>${esc(set.category_names[c])}</option>`).join('')}</select></div><div><label>Rationale</label><input data-field="rationale" value="${esc(a.rationale)}" placeholder="Why this position?"></div></div><div class="prow-foot"><button class="btn" type="button" data-clear>Clear override</button><span class="note">Rule: ${esc(a.id||'strategy')}</span></div></div>`}).join('')||'<div class="empty">No provisions match.</div>';
  $('provisionList').querySelectorAll('[data-provision]').forEach(row=>{const name=row.dataset.provision;row.querySelectorAll('[data-dir]').forEach(btn=>btn.addEventListener('click',()=>updateOverride(name,{direction:Number(btn.dataset.dir)})));row.querySelector('[data-field="category"]')?.addEventListener('change',e=>updateOverride(name,{category:e.target.value}));row.querySelector('[data-field="rationale"]')?.addEventListener('change',e=>updateOverride(name,{rationale:e.target.value}));row.querySelector('[data-clear]')?.addEventListener('click',()=>{delete selectedSet().provision_overrides[norm(name)];render()})});
}
function updateOverride(name,patch){const set=selectedSet(),key=norm(name),current=currentAssignment(set,name),next={id:current.id||`SET-${slugify(name)}`,name,direction:current.direction,category:current.category||'social',rationale:current.rationale||'',...patch};next.direction=Number(next.direction);if(![-1,0,1].includes(next.direction))next.direction=0;if(next.direction===0)next.category=null;set.provision_overrides[key]=next;render()}
function wire(){
  $('addSet').addEventListener('click',()=>{const base=defaultLabels(),name=`New Scorecard ${S.config.sets.length+1}`;let id=slugify(name);while(setById(id))id+='-2';S.config.sets.push(ensureShape({id,name,description:'',strategy:'conservative',owner_name:'',owner_player_id:'',category_names:{social:'Social',economic:'Economic',foreign:'Foreign'},ideology_labels:base,provision_overrides:{}}));S.selected=id;render()});
  document.querySelectorAll('[data-select-set]').forEach(btn=>btn.addEventListener('click',()=>{S.selected=btn.dataset.selectSet;render()}));
  $('deleteSet').addEventListener('click',()=>{if(S.config.sets.length<=1)return alert('At least one scorecard set must remain.');if(!confirm(`Delete "${selectedSet().name}"?`))return;const old=selectedSet().id;S.config.sets=S.config.sets.filter(x=>x.id!==old);if(S.config.default_set===old)S.config.default_set=S.config.sets[0].id;S.selected=S.config.sets[0].id;render()});
  $('setName').addEventListener('input',e=>{selectedSet().name=e.target.value;document.querySelector('.editor-head h2').textContent=e.target.value});$('setStrategy').addEventListener('change',e=>{selectedSet().strategy=e.target.value;render()});$('setOwner').addEventListener('input',e=>selectedSet().owner_name=e.target.value);$('setDescription').addEventListener('input',e=>selectedSet().description=e.target.value);document.querySelectorAll('[data-cat-name]').forEach(el=>el.addEventListener('input',e=>selectedSet().category_names[e.target.dataset.catName]=e.target.value));document.querySelectorAll('[data-labels]').forEach(el=>el.addEventListener('input',e=>selectedSet().ideology_labels[e.target.dataset.labels]=e.target.value.split(',').map(x=>x.trim()).filter(Boolean)));
  $('provisionSearch').addEventListener('input',e=>{S.q=e.target.value;renderProvisions()});$('discard').addEventListener('click',()=>{S.config=clone(S.original);S.selected=S.config.default_set;render()});$('download').addEventListener('click',()=>{const blob=new Blob([JSON.stringify(S.config,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='scorecard_sets_config.json';a.click();URL.revokeObjectURL(a.href)});
  $('publish').addEventListener('click',()=>{$('pubDlg').showModal()});document.querySelectorAll('[data-close]').forEach(x=>x.addEventListener('click',()=>x.closest('dialog').close()));$('pGo').addEventListener('click',publish);
}
async function publish(){
  const status=$('pStatus');status.className='status';status.textContent='Publishing…';
  try{const owner=$('pOwner').value.trim(),repo=$('pRepo').value.trim(),token=$('pTok').value.trim();if(!token)throw new Error('GitHub token required');const api=`https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${REPO.path}`;const get=await fetch(api,{headers:{Authorization:`Bearer ${token}`,Accept:'application/vnd.github+json'}});if(!get.ok)throw new Error(`GitHub read failed: HTTP ${get.status}`);const cur=await get.json();const content=btoa(unescape(encodeURIComponent(JSON.stringify(S.config,null,2)+'\n')));const put=await fetch(api,{method:'PUT',headers:{Authorization:`Bearer ${token}`,Accept:'application/vnd.github+json','Content-Type':'application/json'},body:JSON.stringify({message:$('pMsg').value.trim()||'Update scorecard sets',content,sha:cur.sha})});if(!put.ok)throw new Error(`GitHub write failed: HTTP ${put.status}`);S.original=clone(S.config);$('pTok').value='';$('pubDlg').close();render();alert('Published. Passwords are managed separately and are not included in the public scorecard configuration.')}catch(err){status.className='status fail';status.textContent=err.message}}

async function load(){
  try{const [cfg,data]=await Promise.all([fetch('../data/scorecard_sets_config.json').then(r=>r.json()),fetch('../data/conservative_scorecard.json').then(r=>r.json())]);S.config=cfg;S.data=data;S.original=clone(cfg);S.selected=cfg.default_set||cfg.sets[0]?.id;render()}catch(err){$('app').innerHTML=`<main class="shell pad"><h1>Unable to load admin</h1><p>${esc(err.message)}</p></main>`}}

load();
