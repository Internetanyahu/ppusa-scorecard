const state = {
  data: null,
  players: [],
  bills: [],
  pending: [],
  filtered: [],
  problemsOnly: false,
  rules: null,
  baseData: null,
  adminUnlocked: false,
  adminOverrides: {}
};

const $ = id => document.getElementById(id);

const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  "'": '&#39;',
  '"': '&quot;'
}[c]));

const num = v =>
  v === null || v === undefined || v === '' || !Number.isFinite(Number(v))
    ? null
    : Number(v);

const fmt = v =>
  num(v) === null ? 'N/A' : Number(v).toFixed(Number(v) % 1 ? 2 : 0);

const capitalizeLabel = v =>
  v ? v.charAt(0).toUpperCase() + v.slice(1) : 'Unknown';

const IDEOLOGY = {
  social: ['Mega Woke', 'Woke', 'Wokelite', 'Left-Leaning', 'Moderate', 'Right-Leaning', 'Chudlite', 'Chud', 'Giga Chud'],
  economic: ['Communist', 'Socialist', 'Progressive', 'Social Democrat', 'Mixed-Market', 'Center-Right', 'Conservative', 'Lite-Libertarian', 'True Libertarian'],
  foreign: ['Warhawk', 'Neocon', 'Lite Neocon', 'Interventionist', 'Moderate', 'Hemispherist', 'Contra', 'Patriot', 'Gigapatriot']
};

function ideology(cat, v) {
  const n = num(v);
  if (n === null || !IDEOLOGY[cat]) return 'N/A';
  return IDEOLOGY[cat][Math.max(0, Math.min(8, Math.floor(n / 10) - 1))];
}

const partyLabel = v => ({
  gop: 'GOP', dem: 'Dem', grn: 'Green', cst: 'Constitutional'
})[String(v || '').toLowerCase()] || String(v || 'Other');

const initials = v => String(v || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join('').toUpperCase();

function avatar(p) {
  return p.avatar ? `<img class="avatar" src="${esc(p.avatar)}" alt="">` : `<div class="avatar-fallback">${esc(initials(p.name))}</div>`;
}

function billTotal(b) {
  return (b.scorecard?.provisions || []).reduce((sum, p) => sum + (p.scorable === false ? 0 : (p.direction || 0)), 0);
}

function siteUrl(path = '') { return new URL(path, window.location.href).href; }

function profileUrl(profileId) {
  return profileId ? `https://powerplayusa.net/wiki/politician/${encodeURIComponent(profileId)}` : null;
}

function shareUrl(player) { return siteUrl(`share/${encodeURIComponent(player.user_id || player.player_id)}/`); }

function billUrl(resolutionId) {
  const bill = state.data?.bills?.[String(resolutionId)];
  return bill?.url || siteUrl(`?bill=${encodeURIComponent(resolutionId)}`);
}

function voteTotals(bill) {
  const status = String(bill?.status || '').toLowerCase();
  let chamber = status.includes('house') ? bill?.votes?.house : status.includes('senate') ? bill?.votes?.senate : null;
  if (!chamber) {
    const house = bill?.votes?.house;
    const senate = bill?.votes?.senate;
    const houseCount = (house?.aye?.length || 0) + (house?.nay?.length || 0);
    const senateCount = (senate?.aye?.length || 0) + (senate?.nay?.length || 0);
    chamber = houseCount >= senateCount ? house : senate;
  }
  return { yeas: chamber?.aye?.length || 0, nays: chamber?.nay?.length || 0 };
}

function alignmentClass(alignment) { return alignment === 'Conservative' ? 'positive' : alignment === 'Liberal' ? 'negative' : 'neutral'; }

function normalizeOffices(profile) {
  const values = Array.isArray(profile?.offices) ? profile.offices : profile?.office ? [profile.office] : [];
  return [...new Set(values.map(x => typeof x === 'object' ? (x.office || x.name || x.title || x.label || x.position || '') : String(x)).map(x => String(x || '').trim()).filter(Boolean))];
}

function officeCount(player) {
  const explicit = Number(player?.office_count ?? player?.offices_held);
  if (Number.isFinite(explicit) && explicit >= 0) return explicit;
  return (player?.profiles || []).reduce((sum, profile) => sum + normalizeOffices(profile).length, 0);
}

function officeText(profile) {
  const offices = normalizeOffices(profile);
  return offices.length ? offices.join(', ') : 'No office';
}

async function loadData() {
  const [scorecardResponse, rulesResponse] = await Promise.all([
    fetch('data/conservative_scorecard.json'),
    fetch('data/scorecard_rules.json')
  ]);
  if (!scorecardResponse.ok || !rulesResponse.ok) throw new Error('Unable to load scorecard data or scoring rules.');
  const [scorecard, rules] = await Promise.all([scorecardResponse.json(), rulesResponse.json()]);
  state.baseData = structuredClone(scorecard);
  state.rules = rules;
  const stored = localStorage.getItem('ppusa_admin_policy_v1');
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      if (parsed && parsed.provision_overrides) state.adminOverrides = parsed.provision_overrides;
    } catch (_) { localStorage.removeItem('ppusa_admin_policy_v1'); }
  }
  applyAdminPolicy(true);
}

const ADMIN_SECRET_HASH = '4fed7d100abaeae41e5f614b747bf78f9047b5cc055e521eec3de0cadbe4cc0d';
const ADMIN_DIRECTION_OPTIONS = '<option value="1">+1 — Conservative</option><option value="0">0 — Neutral</option><option value="-1">−1 — Liberal</option>';
function directionLabel(v) { const n = Number(v); return n === 1 ? 'Conservative (+1)' : n === -1 ? 'Liberal (−1)' : 'Neutral (0)'; }
function normalizeAdminOverride(name, value, fallback) {
  const base = fallback || {};
  const direction = Number(value?.direction);
  return { direction: [-1, 0, 1].includes(direction) ? direction : Number(base.direction ?? 0), category: value?.category ?? base.category ?? null, rationale: value?.rationale || base.rationale || 'Assigned by the site policy editor.', group: value?.group ?? base.group ?? null };
}
function provisionAssignment(name) {
  const overrides = state.adminOverrides || {};
  const configured = overrides[name];
  if (configured) return normalizeAdminOverride(name, configured, configured);
  const base = state.rules?.admin_policy?.provision_overrides?.[name];
  if (base) return normalizeAdminOverride(name, base, base);
  const bill = state.bills.find(b => (b.scorecard?.provisions || []).some(p => p.name === name));
  const provision = bill?.scorecard?.provisions?.find(p => p.name === name);
  return normalizeAdminOverride(name, provision || {}, provision || {});
}
function allProvisionNames() {
  const names = new Set();
  Object.values(state.baseData?.bills || {}).forEach(b => (b.scorecard?.provisions || []).forEach(p => { if (p.name) names.add(p.name); }));
  return [...names].sort((a, b) => a.localeCompare(b));
}
function cloneBase() { return structuredClone(state.baseData); }

function recalculatePlayer(player, bills) {
  const details = (player.bill_details || []).map(detail => {
    const bill = bills[String(detail.resolution_id)];
    const provision = bill?.scorecard?.provisions?.find(p => p.name === detail.provision);
    if (!provision) return { ...detail, direction: 0, category: null, scorable: false, aligned: false };
    const direction = Number(provision.direction);
    const vote = String(detail.vote || '').toLowerCase();
    return { ...detail, direction, category: provision.category ?? null, scorable: provision.scorable !== false && [-1, 1].includes(direction), aligned: direction === 1 ? vote === 'aye' : direction === -1 ? vote === 'nay' : false, weight: bill.scorecard?.weight ?? detail.weight ?? 1 };
  });
  const scored = details.filter(x => x.scorable !== false && [-1, 1].includes(Number(x.direction)));
  const counts = {};
  ['social', 'economic', 'foreign'].forEach(cat => { counts[cat] = scored.filter(x => x.category === cat).length; });
  const categoryScores = {};
  ['social', 'economic', 'foreign'].forEach(cat => {
    const rows = scored.filter(x => x.category === cat);
    if (rows.length < 3) { categoryScores[cat] = null; return; }
    const denominator = rows.reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
    const aligned = rows.filter(x => x.aligned).reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
    categoryScores[cat] = denominator ? 100 * aligned / denominator : null;
  });
  const eligible = Object.values(counts).some(n => n >= 3);
  const denominator = scored.reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
  const aligned = scored.filter(x => x.aligned).reduce((sum, x) => sum + Number(x.weight ?? 1), 0);
  const overall = eligible && denominator ? 100 * aligned / denominator : null;
  return { ...player, bill_details: details, scores: { ...categoryScores, overall, tier: overall === null ? 'N/A' : overall >= 90 ? 'A+' : overall >= 80 ? 'A' : overall >= 70 ? 'B' : overall >= 60 ? 'C' : overall >= 50 ? 'D' : 'F' }, sample_size: { ...counts, overall: scored.length }, provisions_scored: scored.length, aligned_provisions: scored.filter(x => x.aligned).length, aligned_votes: scored.filter(x => x.aligned).length, eligible_for_grade: eligible };
}

function applyAdminPolicy(render = true) {
  const data = cloneBase();
  const overrides = state.adminOverrides || {};
  Object.values(data.bills || {}).forEach(bill => {
    const provisions = bill.scorecard?.provisions || [];
    provisions.forEach(provision => {
      const assignment = overrides[provision.name] || state.rules?.admin_policy?.provision_overrides?.[provision.name];
      if (!assignment) return;
      const direction = Number(assignment.direction);
      provision.direction = direction;
      provision.category = assignment.category ?? null;
      provision.scorable = direction !== 0;
      provision.source = 'admin';
      provision.rule_id = `ADMIN-${assignment.group || 'EXACT'}`;
      provision.rationale = assignment.rationale || 'Assigned by the site policy editor.';
    });
    const scored = provisions.filter(p => p.scorable !== false && [-1, 1].includes(Number(p.direction)));
    const total = scored.reduce((sum, p) => sum + Number(p.direction), 0);
    bill.scorecard.total = total;
    bill.scorecard.scored_provisions = scored.length;
    bill.scorecard.alignment = total > 0 ? 'Conservative' : total < 0 ? 'Liberal' : 'Neutral / mixed';
  });
  data.players = (data.players || []).map(player => recalculatePlayer(player, data.bills));
  state.data = data;
  state.players = data.players || [];
  state.bills = Object.values(data.bills || {}).sort((a, b) => Number(a.resolution_id) - Number(b.resolution_id));
  state.pending = data.pending_bills || [];
  if (render) { renderSummary(); renderPending(); applyFilters(); renderAdminPanel(); }
}

function persistAdminPolicy() { localStorage.setItem('ppusa_admin_policy_v1', JSON.stringify({ version: 1, provision_overrides: state.adminOverrides })); }
function setAdminAssignment(name, direction) {
  const base = state.rules.admin_policy.provision_overrides[name];
  if (!base) return;
  state.adminOverrides[name] = normalizeAdminOverride(name, { ...base, direction: Number(direction) }, base);
  persistAdminPolicy(); applyAdminPolicy();
}
function setAdminGroup(groupId, direction) {
  const group = (state.rules?.admin_policy?.groups || []).find(x => x.id === groupId);
  if (!group) return;
  group.provisions.forEach(name => setAdminAssignmentWithoutRender(name, Number(direction)));
  persistAdminPolicy(); applyAdminPolicy();
}
function setAdminAssignmentWithoutRender(name, direction) {
  const base = state.rules.admin_policy.provision_overrides[name];
  if (!base) return;
  state.adminOverrides[name] = normalizeAdminOverride(name, { ...base, direction }, base);
}
function resetAdminPolicy() { state.adminOverrides = {}; localStorage.removeItem('ppusa_admin_policy_v1'); applyAdminPolicy(); }
function downloadAdminRules() {
  const rules = structuredClone(state.rules);
  rules.admin_policy.provision_overrides = { ...(state.rules.admin_policy.provision_overrides || {}), ...(structuredClone(state.adminOverrides) || {}) };
  const blob = new Blob([JSON.stringify(rules, null, 2) + '\n'], { type: 'application/json' });
  const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = 'scorecard_rules.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function sha256(value) {
  const bytes = new TextEncoder().encode(value);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map(x => x.toString(16).padStart(2, '0')).join('');
}
async function unlockAdmin() {
  if (state.adminUnlocked) { renderAdminPanel(); $('adminDialog').showModal(); return; }
  if (!state.rules || !state.baseData) { window.alert('Please wait for the scorecard to finish loading, then try again.'); return; }
  const secret = window.prompt('Paste the PPUSA admin secret key below.\n\nPress OK after pasting it.');
  if (secret === null) return;
  const trimmed = secret.trim();
  if (!trimmed) { window.alert('Admin secret cannot be empty.'); return; }
  try {
    if ((await sha256(trimmed)) !== ADMIN_SECRET_HASH) { window.alert('Invalid admin secret.\n\nMake sure you pasted the complete key with no extra characters.'); return; }
    state.adminUnlocked = true; renderAdminPanel(); const dialog = $('adminDialog'); if (dialog && typeof dialog.showModal === 'function') dialog.showModal();
  } catch (error) { console.error('Admin unlock error:', error); window.alert('Could not verify the admin secret. Please reload the page and try again.'); }
}
function renderAdminPanel() {
  const root = $('adminPanel');
  if (!root || !state.rules?.admin_policy) return;
  const policy = state.rules.admin_policy; const names = allProvisionNames(); const groups = policy.groups || [];
  const groupRows = groups.map(group => {
    const assigned = group.provisions.map(name => provisionAssignment(name).direction); const mixed = new Set(assigned).size > 1;
    return `<div class="admin-group"><div><strong>${esc(group.label)}</strong><span>${group.provisions.length} provision${group.provisions.length === 1 ? '' : 's'}</span><small>${mixed ? 'Current assignments are mixed.' : `Current: ${directionLabel(assigned[0])}`}</small></div><select data-admin-group="${esc(group.id)}"><option value="">Bulk assign…</option>${ADMIN_DIRECTION_OPTIONS}</select></div>`;
  }).join('');
  const options = names.map(name => { const a = provisionAssignment(name); return `<option value="${esc(name)}">${esc(name)} — ${directionLabel(a.direction)}</option>`; }).join('');
  root.innerHTML = `<div class="detail-header"><p class="eyebrow">PRIVATE POLICY EDITOR</p><h2>Conservative-policy assignments</h2><p class="detail-sub">Group controls apply to every provision in the group. Advanced controls let you change one provision at a time. Changes are saved only in this browser until you export the rules file.</p></div><div class="admin-warning">This is a static GitHub Pages site. The secret hides the editor, but it is not server-side authentication. For real access control, the admin UI would need a server-side identity provider.</div><div class="admin-actions"><button class="toggle" id="exportRules">Export updated rules</button><button class="toggle" id="resetRules">Reset local assignments</button></div><p class="eyebrow admin-advanced-label">GROUP ASSIGNMENTS</p><div class="admin-groups">${groupRows}</div><p class="eyebrow admin-advanced-label">ADVANCED</p><div class="admin-advanced"><label for="adminProvision">Provision</label><select id="adminProvision"><option value="">Select a provision…</option>${options}</select><label for="adminDirection">Assignment</label><select id="adminDirection" disabled><option value="">Select a provision first…</option>${ADMIN_DIRECTION_OPTIONS}</select></div><div class="admin-coverage">${names.length} named provisions currently have explicit assignments.</div>`;
  root.querySelectorAll('[data-admin-group]').forEach(select => select.addEventListener('change', e => { if (!e.target.value) return; setAdminGroup(e.target.dataset.adminGroup, e.target.value); e.target.value = ''; }));
  const provisionSelect = $('adminProvision'); const directionSelect = $('adminDirection');
  provisionSelect.addEventListener('change', () => { const name = provisionSelect.value; directionSelect.disabled = !name; if (!name) return; directionSelect.value = String(provisionAssignment(name).direction); });
  directionSelect.addEventListener('change', () => { if (!provisionSelect.value) return; setAdminAssignment(provisionSelect.value, directionSelect.value); });
  $('exportRules').addEventListener('click', downloadAdminRules);
  $('resetRules').addEventListener('click', () => { if (window.confirm('Reset all browser-local policy assignments?')) resetAdminPolicy(); });
}

function renderSummary() {
  const n = state.bills.reduce((sum, b) => sum + (b.scorecard?.provisions || []).filter(p => p.scorable !== false).length, 0);
  $('playerCount').textContent = state.players.length;
  $('billCount').textContent = state.bills.length;
  $('provisionCount').textContent = n;
  $('generatedAt').textContent = `Data generated ${new Date(state.data.generated_at).toLocaleString()}`;
}

function applyFilters() {
  const q = $('search').value.trim().toLowerCase(); const party = $('party').value; const chamber = $('chamber').value; const sort = $('sort').value; const dir = $('direction').value === 'asc' ? 1 : -1;
  state.filtered = state.players.filter(p => {
    const profiles = p.profiles || [];
    const hay = [p.name, p.discord, ...profiles.map(x => x.name), ...profiles.map(x => x.state)].join(' ').toLowerCase();
    const parties = profiles.map(x => x.party); const chambers = profiles.map(x => x.chamber);
    return (!q || hay.includes(q)) && (party === 'all' || parties.includes(party)) && (chamber === 'all' || chambers.includes(chamber));
  }).sort((a, b) => {
    let av, bv;
    if (sort === 'score') { av = num(a.scores?.overall); bv = num(b.scores?.overall); }
    else if (['social', 'economic', 'foreign'].includes(sort)) { av = num(a.scores?.[sort]); bv = num(b.scores?.[sort]); }
    else if (sort === 'state') { av = (a.state || '').toLowerCase(); bv = (b.state || '').toLowerCase(); }
    else if (sort === 'profile') { av = (a.discord || '').toLowerCase(); bv = (b.discord || '').toLowerCase(); }
    else { av = (a.name || '').toLowerCase(); bv = (b.name || '').toLowerCase(); }
    if (av === bv) return 0;
    if (av === null || av === undefined || av === '') return 1;
    if (bv === null || bv === undefined || bv === '') return -1;
    return (av > bv ? 1 : -1) * dir;
  });
  renderPlayers(); renderBills();
}

function renderPlayers() {
  $('resultCount').textContent = `${state.filtered.length} scorecard${state.filtered.length === 1 ? '' : 's'}`;
  const root = $('scorecards');
  if (!state.filtered.length) { root.innerHTML = '<div class="empty">No scorecards match the current filters.</div>'; return; }
  root.innerHTML = state.filtered.map((p, i) => {
    const s = p.scores || {}; const profiles = p.profiles || []; const playerId = p.user_id || p.player_id;
    const mainProfileId = p.profile_id || profiles[0]?.profile_id || profiles[0]?.id;
    const playerLink = profileUrl(mainProfileId);
    const count = officeCount(p);
    const officeLabel = count === 0 ? 'No office' : `${count} office${count === 1 ? '' : 's'} held`;
    return `<article class="scorecard" tabindex="0" role="button" data-player-index="${i}">
      <div class="card-main"><div class="identity">${avatar({ name: p.name, avatar: p.avatar })}<div><h3>${playerLink ? `<a class="main-profile-link" href="${esc(playerLink)}" target="_blank" rel="noopener">${esc(p.name)}</a>` : esc(p.name)}</h3><div class="handle">${esc(p.discord || 'No Discord handle')}</div><div class="chips"><span class="party-chip">${esc(partyLabel(p.party))}</span>${(p.chambers || []).map(c => `<span class="chamber-chip">${esc(c)}</span>`).join('')}</div></div></div>
      <div class="score-row"><div class="score-main"><strong>${fmt(s.overall)}</strong><span>/ 100</span></div><div class="tier tier-${esc(s.tier || 'N/A')}">${esc(s.tier || 'N/A')}</div></div>
      <div class="mini-bars">${['social', 'economic', 'foreign'].map(cat => { const v = num(s[cat]); const w = v === null ? 0 : Math.max(0, Math.min(100, v)); return `<div class="mini-row"><span>${capitalizeLabel(cat)}</span><div class="bar"><span style="width:${w}%"></span></div><span class="mini-value">${fmt(v)}</span>${ideology(cat, v) ? `<span class="mini-tag">${esc(ideology(cat, v))}</span>` : ''}</div>`; }).join('')}</div></div>
      <div class="profile-strip"><strong>${esc(officeLabel)}</strong><div class="profile-list">${profiles.map(x => { const url = profileUrl(x.profile_id || x.id); const location = [x.chamber, x.state].filter(Boolean).join(' · '); const text = `${x.name} · ${officeText(x)} · ${x.state || ''}`; return url ? `<a class="profile-chip profile-link" href="${esc(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : `<span class="profile-chip">${esc(text)}</span>`; }).join('')}</div></div>
    </article>`;
  }).join('');
  root.querySelectorAll('.scorecard').forEach((card, i) => { card.addEventListener('click', e => { if (e.target.closest('a')) return; openPlayer(state.filtered[i]); }); card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openPlayer(state.filtered[i]); } }); });
}

function renderPending() {
  const floor = $('floorBills'); const committee = $('committeeBills');
  const floorRows = state.pending.filter(b => /floor|calendar|house|senate/i.test(String(b.status || ''))).map(b => `<button class="bill-card" data-bill-id="${esc(b.resolution_id)}"><strong>${esc(b.title || `Resolution ${b.resolution_id}`)}</strong><span>${esc(b.status || 'Pending')}</span></button>`).join('');
  const committeeRows = state.pending.filter(b => !/floor|calendar|house|senate/i.test(String(b.status || ''))).map(b => `<button class="bill-card" data-bill-id="${esc(b.resolution_id)}"><strong>${esc(b.title || `Resolution ${b.resolution_id}`)}</strong><span>${esc(b.status || 'Committee')}</span></button>`).join('');
  floor.innerHTML = floorRows || '<div class="empty">No floor bills awaiting action.</div>'; committee.innerHTML = committeeRows || '<div class="empty">No committee bills awaiting action.</div>';
  document.querySelectorAll('[data-bill-id]').forEach(el => el.addEventListener('click', () => openBill(el.dataset.billId)));
}

function renderBills() {
  const root = $('bills');
  root.innerHTML = state.bills.map(b => { const alignment = b.scorecard?.alignment || 'Neutral / mixed'; const votes = voteTotals(b); const total = billTotal(b); const score = total > 0 ? `+${total}` : String(total); return `<button class="bill-card" data-bill-id="${esc(b.resolution_id)}"><strong>${esc(b.title || `Resolution ${b.resolution_id}`)}</strong><span>Score ${esc(score)} · ${esc(alignment)} · ${votes.yeas}–${votes.nays}</span></button>`; }).join('');
  root.querySelectorAll('[data-bill-id]').forEach(el => el.addEventListener('click', () => openBill(el.dataset.billId)));
}

function openPlayer(player) {
  const dialog = $('scorecardDialog'); const detail = $('scorecardDetail'); const profiles = player.profiles || [];
  detail.innerHTML = `<div class="detail-header"><p class="eyebrow">PLAYER PROFILE</p><h2>${esc(player.name)}</h2><p class="detail-sub">${esc(player.party || 'Other')} · ${esc(player.state || '')}</p></div><div class="detail-section"><h3>Profiles</h3>${profiles.map(p => `<div class="account"><strong>${esc(p.name || 'Unknown')}</strong><span>${esc([officeText(p), p.state].filter(Boolean).join(' · '))}</span></div>`).join('')}</div>`;
  if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
}

async function init() {
  try { await loadData(); } catch (error) { console.error(error); $('scorecards').innerHTML = `<div class="empty">${esc(error.message)}</div>`; return; }
  $('search').addEventListener('input', applyFilters); $('party').addEventListener('change', applyFilters); $('chamber').addEventListener('change', applyFilters); $('sort').addEventListener('change', applyFilters); $('direction').addEventListener('change', applyFilters);
  document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog')?.close()));
  const adminButton = $('adminButton'); if (adminButton) adminButton.addEventListener('click', unlockAdmin);
}

init();
