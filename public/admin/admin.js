'use strict';
/* ---------------------------------------------------------------------------
   Admin console. The access key is NOT stored here: only a salted PBKDF2-SHA256
   verifier. To rotate the key run tools/make_admin_verifier.py and paste its
   output over VERIFIER.
   Note: this page is static, so the lock is a convenience gate. Changes only
   take effect if you also hold a GitHub token with write access to the repo.
--------------------------------------------------------------------------- */
const VERIFIER = {"salt":"f26d0b470221240e7dff7de5e56c581e","iterations":600000,"hash":"095031433fe8fbf8096a1ca8d815a4ede7d05dab03723278e8610b86a27f4505"};
const REPO = {owner:'SK64HD', repo:'ppusa_conservative_scorecard', path:'scorecard_rules.json'};
const CATS = ['social','economic','foreign'];

const $ = id => document.getElementById(id);
const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const norm = s => String(s || '').trim().toLowerCase().replace(/\s+/g, ' ');
const hexToBytes = h => Uint8Array.from(h.match(/../g) || [], b => parseInt(b, 16));
const bytesToHex = b => Array.from(b, x => x.toString(16).padStart(2, '0')).join('');
const clone = o => JSON.parse(JSON.stringify(o));

/* ------------------------------- lock screen ------------------------------ */
async function verify(secret) {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret.trim().toLowerCase()), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({name:'PBKDF2', hash:'SHA-256', salt:hexToBytes(VERIFIER.salt), iterations:VERIFIER.iterations}, key, 256);
  return bytesToHex(new Uint8Array(bits)) === VERIFIER.hash;
}

let fails = 0, coolUntil = 0;
function initLock() {
  const form = $('lockForm'), msg = $('lockMsg'), btn = $('unlockBtn'), input = $('secret');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (Date.now() < coolUntil || !input.value) return;
    btn.disabled = true; msg.textContent = '';
    let ok = false;
    try { ok = await verify(input.value); }
    catch (err) { msg.textContent = 'This page needs a secure (https) connection.'; btn.disabled = false; return; }
    input.value = '';
    if (ok) { fails = 0; startAdmin(); return; }
    fails++;
    const wait = Math.min(30000, 1000 * 2 ** (fails - 1));
    coolUntil = Date.now() + wait;
    const tick = () => {
      const left = Math.ceil((coolUntil - Date.now()) / 1000);
      if (left > 0) { msg.textContent = `Incorrect key. Try again in ${left}s.`; setTimeout(tick, 250); }
      else { msg.textContent = 'Incorrect key.'; btn.disabled = false; input.focus(); }
    };
    tick();
  });
}

/* --------------------------------- state ---------------------------------- */
const S = {data:null, base:null, rules:null, baseCanon:'', provisions:[], ex:new Map(), baseEx:new Map(),
           tab:'provisions', filter:'all', cat:'all', q:'', limit:300, token:''};

function canon(rules) { const r = clone(rules); r.provision_rules = (r.provision_rules || []).slice().sort((a,b)=>norm(a.name)<norm(b.name)?-1:1); return JSON.stringify(r); }
function serialize() {
  const r = clone(S.rules);
  r.provision_rules = [...S.ex.values()].sort((a,b)=>norm(a.name)<norm(b.name)?-1:1).map(x => ({id:x.id, name:x.name, direction:x.direction, category:x.direction===0?null:x.category, rationale:x.rationale||'', ...(x.confidence ? {confidence:x.confidence} : {})}));
  return JSON.stringify(r, null, 2) + '\n';
}
function mapFrom(rules) { const m = new Map(); (rules.provision_rules || []).forEach(r => m.set(norm(r.name), {...r})); return m; }

async function startAdmin() {
  document.title = 'Scorecard rules';
  $('app').innerHTML = '<main class="shell" style="padding:40px 0"><p class="muted">Loading rules and provisions…</p></main>';
  try {
    const [d, r] = await Promise.all(['../data/conservative_scorecard.json', '../data/scorecard_rules.json'].map(u => fetch(u, {cache:'no-store'}).then(x => { if (!x.ok) throw new Error(`${u}: HTTP ${x.status}`); return x.json(); })));
    S.data = d; S.rules = r; S.rules.calibrated_rules ||= []; S.rules.general_rules ||= []; S.rules.provision_rules ||= [];
    S.base = clone(S.rules); S.baseCanon = canon(S.rules);
    S.ex = mapFrom(S.rules); S.baseEx = mapFrom(S.rules);
    buildProvisions(); renderShell();
  } catch (err) {
    $('app').innerHTML = `<main class="shell" style="padding:40px 0"><div class="empty">Could not load data: ${esc(err.message)}</div></main>`;
  }
}

function buildProvisions() {
  const map = new Map();
  Object.values(S.data.bills || {}).forEach(b => {
    const raw = b.provisions || [];
    (b.scorecard?.provisions || []).forEach((p, i) => {
      const name = String(p.name || '').trim(); if (!name) return;
      const key = norm(name);
      let e = map.get(key);
      if (!e) { e = {key, name, bills:[], eff:p, sigs:new Set(), notes:null}; map.set(key, e); }
      if (!e.bills.some(x => x.number === b.number)) e.bills.push({number:b.number, title:b.title});
      e.sigs.add(`${p.scorable === false ? 0 : p.direction}|${p.category}`);
      if (!e.notes && raw[i] && raw[i].name === p.name) e.notes = {notes:raw[i].notes, effects:raw[i].effects};
    });
  });
  (S.rules.provision_rules || []).forEach(r => {
    const key = norm(r.name); if (!key || map.has(key)) return;
    const dir = Number(r.direction);
    map.set(key, {key, name:r.name, bills:[], conf:r.confidence || '', sigs:new Set(), notes:null,
      eff:{direction:dir, category:r.category, rationale:r.rationale || '', rule_id:r.id, source:'explicit', scorable:dir !== 0}});
  });
  S.provisions = [...map.values()].sort((a,b) => a.key < b.key ? -1 : 1);
  S.provisions.forEach((e, i) => e.idx = i);
}

/* ------------------------------ provision rules --------------------------- */
function view(e) {
  const r = S.ex.get(e.key);
  if (r) return {state:'explicit', direction:Number(r.direction), category:r.category, rationale:r.rationale || '', id:r.id};
  const p = e.eff, dir = p.scorable === false ? 0 : Number(p.direction);
  return {state:p.source === 'explicit' ? 'removed' : 'inherited', direction:dir, category:p.category, rationale:p.rationale || '', id:p.rule_id, source:p.source};
}
function newId(e) {
  let h = 2166136261; for (const c of e.key) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619) >>> 0; }
  return 'EXP-' + e.key.replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 48) + '-' + h.toString(16).slice(0, 6);
}
function materialize(e) {
  let r = S.ex.get(e.key); if (r) return r;
  const v = view(e);
  r = {id:newId(e), name:e.name, direction:v.direction, category:v.direction === 0 ? null : (v.category || 'social'), rationale:v.rationale};
  S.ex.set(e.key, r); return r;
}
function setField(e, patch) {
  const r = materialize(e);
  Object.assign(r, patch);
  if (r.direction === 0) r.category = null; else if (!CATS.includes(r.category)) r.category = 'social';
}
const isChanged = key => JSON.stringify(S.ex.get(key) || null) !== JSON.stringify(S.baseEx.get(key) || null);

function rowHTML(e) {
  const v = view(e), changed = isChanged(e.key);
  const badge = v.state === 'explicit' ? '<span class="badge ok">Explicit rule</span>'
    : v.state === 'removed' ? '<span class="badge warn">Rule removed · reverts on rebuild</span>'
    : `<span class="badge todo">No explicit rule · ${esc(v.source || 'inherited')}${v.id ? ' · ' + esc(v.id) : ''}</span>`;
  const d = v.direction;
  const ctx = e.notes ? JSON.stringify(e.notes, null, 2) : '';
  return `<div class="prow ${v.state === 'explicit' ? '' : 'inherited'} ${changed ? 'pending' : ''}" data-i="${e.idx}">
    <div class="prow-top"><div><div class="prow-name">${esc(e.name)}</div>
      <div class="prow-meta">${e.bills.length ? esc(e.bills.map(b => b.number).join(', ')) : 'Law on the books · no finalized bill uses this yet'}${e.conf === 'low' ? ' · <span class="err">low confidence — review</span>' : ''}${e.sigs.size > 1 ? ' · <span class="err">classified differently across bills</span>' : ''}${changed ? ' · <strong>unsaved change</strong>' : ''}</div></div>${badge}</div>
    <div class="prow-controls">
      <div><label>Conservative position</label><div class="seg" role="group">
        <button type="button" data-act="dir" data-v="1" class="${d === 1 ? 'on pos' : ''}">+1 · Aye</button>
        <button type="button" data-act="dir" data-v="-1" class="${d === -1 ? 'on neg' : ''}">−1 · Nay</button>
        <button type="button" data-act="dir" data-v="0" class="${d === 0 ? 'on neu' : ''}">Neutral</button></div></div>
      <div><label>Category</label><select data-act="cat" ${d === 0 ? 'disabled' : ''}>${CATS.map(c => `<option value="${c}" ${v.category === c ? 'selected' : ''}>${c[0].toUpperCase() + c.slice(1)}</option>`).join('')}</select></div>
      <div><label>Rationale</label><input data-act="rat" type="text" value="${esc(v.rationale)}" placeholder="Why this position?"></div>
    </div>
    <div class="prow-foot">
      ${v.state === 'explicit' ? '<button type="button" class="btn" data-act="reset">Remove explicit rule</button>' : '<button type="button" class="btn" data-act="lock">Make explicit</button>'}
      ${ctx ? `<details class="ctx"><summary>Provision details</summary><pre>${esc(ctx)}</pre></details>` : ''}
    </div></div>`;
}

function filtered() {
  const q = S.q.trim().toLowerCase();
  return S.provisions.filter(e => {
    const v = view(e);
    if (q && !(e.key.includes(q) || e.bills.some(b => String(b.number).toLowerCase().includes(q)))) return false;
    if (S.cat !== 'all' && (v.direction === 0 ? 'neutral' : v.category) !== S.cat) return false;
    if (S.filter === 'uncovered') return v.state !== 'explicit';
    if (S.filter === 'explicit') return v.state === 'explicit';
    if (S.filter === 'neutral') return v.direction === 0;
    if (S.filter === 'pending') return isChanged(e.key);
    return true;
  });
}

/* -------------------------------- pattern rules --------------------------- */
function validRegex(p) { try { new RegExp(p, 'i'); return true; } catch { return false; } }
function patternRows(group) {
  return S.rules[group].map((r, i) => {
    const b = S.base[group][i], changed = JSON.stringify(r) !== JSON.stringify(b);
    const bad = changed && !validRegex(r.pattern);
    const dir = Number(r.direction), cat = String(r.category || '').toLowerCase();
    return `<div class="rrow ${changed ? 'pending' : ''}" data-g="${group}" data-i="${i}">
      <h3>${esc(r.id)}${changed ? ' · <span class="muted">unsaved change</span>' : ''}</h3>
      <div class="rrow-grid">
        <div><label>Pattern (regex)</label><input data-f="pattern" class="${bad ? 'bad' : ''}" value="${esc(r.pattern)}">${bad ? '<div class="err">Invalid regular expression</div>' : ''}</div>
        <div><label>Direction</label><select data-f="direction">${[1, -1, 0].map(d => `<option value="${d}" ${dir === d ? 'selected' : ''}>${d > 0 ? '+1' : d < 0 ? '−1' : '0'}</option>`).join('')}</select></div>
        <div><label>Category</label><select data-f="category">${CATS.map(c => `<option value="${c}" ${cat === c ? 'selected' : ''}>${c[0].toUpperCase() + c.slice(1)}</option>`).join('')}</select></div>
        <div><label>Rationale</label><input data-f="rationale" value="${esc(r.rationale || '')}"></div>
      </div></div>`;
  }).join('') || '<div class="empty">No rules in this group.</div>';
}

/* ------------------------------- diff + chrome ---------------------------- */
function diff() {
  const keys = new Set([...S.ex.keys(), ...S.baseEx.keys()]);
  let added = 0, changed = 0, removed = 0;
  keys.forEach(k => { const a = S.ex.get(k), b = S.baseEx.get(k); if (JSON.stringify(a || null) === JSON.stringify(b || null)) return; if (!b) added++; else if (!a) removed++; else changed++; });
  let pattern = 0;
  ['calibrated_rules', 'general_rules'].forEach(g => S.rules[g].forEach((r, i) => { if (JSON.stringify(r) !== JSON.stringify(S.base[g][i])) pattern++; }));
  return {added, changed, removed, pattern, total:added + changed + removed + pattern};
}
function hasInvalid() { return ['calibrated_rules', 'general_rules'].some(g => S.rules[g].some((r, i) => JSON.stringify(r) !== JSON.stringify(S.base[g][i]) && !validRegex(r.pattern))); }
function updateChrome() {
  const covered = S.provisions.filter(e => S.ex.has(e.key)).length, d = diff();
  $('stTotal').textContent = S.provisions.length; $('stCov').textContent = covered; $('stUn').textContent = S.provisions.length - covered; $('stPend').textContent = d.total;
  $('pendText').textContent = d.total ? `${d.total} unsaved change${d.total === 1 ? '' : 's'} — ${d.added} new, ${d.changed} edited, ${d.removed} removed provision rules; ${d.pattern} pattern rule${d.pattern === 1 ? '' : 's'} edited` : 'No unsaved changes';
  const dis = !d.total || hasInvalid();
  ['dlBtn', 'pubBtn', 'discardBtn'].forEach(id => $(id).disabled = id === 'discardBtn' ? !d.total : dis);
  document.querySelectorAll('[data-filter]').forEach(b => {
    const f = b.dataset.filter, n = f === 'all' ? S.provisions.length : f === 'uncovered' ? S.provisions.length - covered : f === 'explicit' ? covered : f === 'neutral' ? S.provisions.filter(e => view(e).direction === 0).length : S.provisions.filter(e => isChanged(e.key)).length;
    b.textContent = `${b.dataset.label} (${n})`;
  });
}

/* --------------------------------- shell ---------------------------------- */
function renderShell() {
  $('app').innerHTML = `
  <header class="adm-head"><div class="shell"><p class="eyebrow">ADMIN</p><h1>Scorecard rules</h1>
    <p>Every provision on a finalized bill, plus every law and amendment in the game's code, is listed below with its own rule. An explicit rule always overrides pattern rules and fallbacks. Changes are saved to <code>${esc(REPO.path)}</code> and the scorecard rebuilds automatically.</p></div></header>
  <main class="shell">
    <section class="adm-stats">
      <div class="hero-card"><span class="hero-label">Provisions</span><strong id="stTotal">—</strong></div>
      <div class="hero-card"><span class="hero-label">With explicit rule</span><strong id="stCov">—</strong></div>
      <div class="hero-card"><span class="hero-label">Without explicit rule</span><strong id="stUn">—</strong></div>
      <div class="hero-card"><span class="hero-label">Unsaved changes</span><strong id="stPend">—</strong></div>
    </section>
    <div class="adm-tabs"><button class="toggle" data-tab="provisions">Provisions</button><button class="toggle" data-tab="patterns">Pattern rules</button></div>
    <div id="tabProv">
      <section class="adm-filters panel">
        <div><label for="q">Search provision or bill</label><input id="q" type="search" placeholder="e.g. H-1B, HR 12…"></div>
        <div><label for="catF">Category</label><select id="catF"><option value="all">All</option><option value="social">Social</option><option value="economic">Economic</option><option value="foreign">Foreign</option><option value="neutral">Neutral</option></select></div>
        <div style="align-self:end"><button class="btn" id="bulkBtn" type="button" style="width:100%">Make every provision explicit</button></div>
      </section>
      <div class="chips-row">${[['all','All'],['uncovered','No explicit rule'],['explicit','Explicit'],['neutral','Neutral'],['pending','Unsaved']].map(([f, l]) => `<button class="toggle" data-filter="${f}" data-label="${l}"></button>`).join('')}</div>
      <div id="plist"></div>
    </div>
    <div id="tabPat" hidden>
      <p class="note" style="margin-bottom:14px">Pattern rules apply to provisions that have no explicit rule. Calibrated rules match the provision name; general rules match name, notes and effect metrics. Direction 0 on a calibrated rule means “use the fallback classifier”. Use Neutral on a provision to exclude it from scoring.</p>
      <h2 style="font-size:20px;margin:0 0 10px">Calibrated rules</h2><div id="pCal"></div>
      <h2 style="font-size:20px;margin:22px 0 10px">General rules</h2><div id="pGen"></div>
    </div>
  </main>
  <div class="actionbar"><div class="shell"><span id="pendText" class="muted"></span>
    <div class="btns"><button class="btn danger" id="discardBtn">Discard changes</button><button class="btn" id="dlBtn">Download JSON</button><button class="btn primary" id="pubBtn">Publish to GitHub</button></div></div></div>
  <dialog id="pubDlg" class="dialog"><button class="dialog-close" data-close aria-label="Close">×</button>
    <div class="pad"><h2 style="font-size:22px">Publish rules</h2>
      <p class="note">Commits <code>${esc(REPO.path)}</code> directly to the repository. The token stays in this tab’s memory only and is discarded when you close or reload the page. Use a fine-grained token limited to this repository with <strong>Contents: Read and write</strong>.</p>
      <div class="row2"><div><label for="pOwner">Owner</label><input id="pOwner"></div><div><label for="pRepo">Repository</label><input id="pRepo"></div></div>
      <div><label for="pTok">GitHub token</label><input id="pTok" type="password" autocomplete="off" spellcheck="false"></div>
      <div><label for="pMsg">Commit message</label><input id="pMsg" value="Update scorecard rules (admin)"></div>
      <div id="pStatus" class="status" role="status"></div>
      <div><button class="btn primary" id="pGo">Commit changes</button></div></div></dialog>`;
  $('pOwner').value = REPO.owner; $('pRepo').value = REPO.repo;
  wire(); showTab('provisions'); renderList(); renderPatterns(); updateChrome();
  window.addEventListener('beforeunload', ev => { if (diff().total) { ev.preventDefault(); ev.returnValue = ''; } });
}

function showTab(t) {
  S.tab = t; $('tabProv').hidden = t !== 'provisions'; $('tabPat').hidden = t !== 'patterns';
  document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === t));
}
function renderList() {
  const list = filtered(), shown = list.slice(0, S.limit);
  $('plist').innerHTML = (shown.map(rowHTML).join('') || '<div class="empty">Nothing matches the current filters.</div>')
    + (list.length > shown.length ? `<div style="text-align:center"><button class="btn" id="moreBtn">Show ${list.length - shown.length} more</button></div>` : '');
  document.querySelectorAll('[data-filter]').forEach(b => b.classList.toggle('active', b.dataset.filter === S.filter));
}
function renderPatterns() { $('pCal').innerHTML = patternRows('calibrated_rules'); $('pGen').innerHTML = patternRows('general_rules'); }

function wire() {
  document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => showTab(b.dataset.tab)));
  document.querySelectorAll('[data-filter]').forEach(b => b.addEventListener('click', () => { S.filter = b.dataset.filter; S.limit = 300; renderList(); }));
  $('q').addEventListener('input', e => { S.q = e.target.value; S.limit = 300; renderList(); });
  $('catF').addEventListener('change', e => { S.cat = e.target.value; S.limit = 300; renderList(); });
  $('bulkBtn').addEventListener('click', () => {
    const todo = S.provisions.filter(e => !S.ex.has(e.key));
    if (!todo.length) { alert('Every provision already has an explicit rule.'); return; }
    if (!confirm(`Create an explicit rule for ${todo.length} provision${todo.length === 1 ? '' : 's'}, locking in how each is classified today?`)) return;
    todo.forEach(materialize); renderList(); updateChrome();
  });
  const plist = $('plist');
  plist.addEventListener('click', ev => {
    if (ev.target.id === 'moreBtn') { S.limit += 300; renderList(); return; }
    const btn = ev.target.closest('[data-act]'); if (!btn) return;
    const row = btn.closest('.prow'), e = S.provisions[Number(row.dataset.i)];
    if (btn.dataset.act === 'dir') setField(e, {direction:Number(btn.dataset.v)});
    else if (btn.dataset.act === 'lock') materialize(e);
    else if (btn.dataset.act === 'reset') S.ex.delete(e.key);
    else return;
    row.outerHTML = rowHTML(e); updateChrome();
  });
  plist.addEventListener('change', ev => {
    const t = ev.target, act = t.dataset.act; if (act !== 'cat' && act !== 'rat') return;
    const row = t.closest('.prow'), e = S.provisions[Number(row.dataset.i)];
    setField(e, act === 'cat' ? {category:t.value} : {rationale:t.value});
    row.outerHTML = rowHTML(e); updateChrome();
  });
  $('tabPat').addEventListener('change', ev => {
    const t = ev.target, f = t.dataset.f; if (!f) return;
    const row = t.closest('.rrow'), r = S.rules[row.dataset.g][Number(row.dataset.i)];
    r[f] = f === 'direction' ? Number(t.value) : t.value;
    renderPatterns(); updateChrome();
  });
  $('discardBtn').addEventListener('click', () => {
    if (!confirm('Discard all unsaved changes?')) return;
    S.rules = clone(S.base); S.ex = mapFrom(S.base); renderList(); renderPatterns(); updateChrome();
  });
  $('dlBtn').addEventListener('click', () => {
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([serialize()], {type:'application/json'}));
    a.download = 'scorecard_rules.json'; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  });
  $('pubBtn').addEventListener('click', () => { $('pStatus').textContent = ''; $('pStatus').className = 'status'; $('pubDlg').showModal(); });
  $('pubDlg').querySelector('[data-close]').addEventListener('click', () => $('pubDlg').close());
  $('pGo').addEventListener('click', publish);
}

/* -------------------------------- publishing ------------------------------ */
const b64enc = text => { const bytes = new TextEncoder().encode(text); let s = ''; for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(s); };
const b64dec = b64 => new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, '')), c => c.charCodeAt(0)));

async function publish() {
  const st = $('pStatus'), go = $('pGo'), owner = $('pOwner').value.trim(), repo = $('pRepo').value.trim(), token = $('pTok').value.trim();
  const say = (t, cls = '') => { st.textContent = t; st.className = 'status ' + cls; };
  if (!owner || !repo || !token) { say('Owner, repository and token are required.', 'fail'); return; }
  go.disabled = true; say('Checking the repository…');
  const api = `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/contents/${REPO.path}`;
  const h = {Authorization:`Bearer ${token}`, Accept:'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28'};
  try {
    const cur = await fetch(api, {headers:h, cache:'no-store'});
    if (cur.status === 401 || cur.status === 403) throw new Error('GitHub rejected the token (needs Contents: Read and write on this repository).');
    if (!cur.ok) throw new Error(`Could not read ${REPO.path} (HTTP ${cur.status}).`);
    const meta = await cur.json();
    if (!meta.content) throw new Error('GitHub did not return the file contents.');
    const remote = JSON.parse(b64dec(meta.content)); remote.provision_rules ||= [];
    if (canon(remote) !== S.baseCanon) throw new Error('The rules file on GitHub changed since you opened this page. Reload the page and redo your edits so nothing is overwritten.');
    say('Committing…');
    const put = await fetch(api, {method:'PUT', headers:{...h, 'Content-Type':'application/json'}, body:JSON.stringify({message:$('pMsg').value.trim() || 'Update scorecard rules (admin)', content:b64enc(serialize()), sha:meta.sha})});
    if (put.status === 409) throw new Error('Conflict: the file changed while saving. Reload and try again.');
    if (!put.ok) throw new Error(`Commit failed (HTTP ${put.status}): ${(await put.json().catch(() => ({}))).message || ''}`);
    const res = await put.json();
    S.base = clone(S.rules); S.base.provision_rules = [...S.ex.values()].map(x => ({...x})); S.rules.provision_rules = clone(S.base.provision_rules);
    S.baseEx = new Map([...S.ex].map(([k, v]) => [k, {...v}])); S.baseCanon = canon(JSON.parse(serialize()));
    $('pTok').value = ''; renderList(); renderPatterns(); updateChrome();
    say(`Saved. Commit ${String(res.commit?.sha || '').slice(0, 7)}: ${res.commit?.html_url || ''}\nThe scorecard rebuild starts automatically; updated scores appear on the site in a few minutes.`, 'ok');
  } catch (err) { say(err.message, 'fail'); }
  finally { go.disabled = false; }
}

initLock();
