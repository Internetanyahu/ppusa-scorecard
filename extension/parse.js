// Turns the raw page data into the same bill shape used by bills.json.
const TAIL_RE = /\(\s*([A-Za-z]+)-([A-Za-z]{2})(?:\s*,\s*(\d+)\s+seats?)?(?:\s*,\s*([^)]+?))?\s*\)/;
const EFFECT_RE = /(.+?)\s*([+\-−]\d+(?:\.\d+)?)(?=[\s,;]|$)/g;
export function parseEffects(text) {
  const out = [];
  for (const m of text.matchAll(EFFECT_RE)) out.push({ metric: m[1].replace(/^[\s,;]+|[\s,;]+$/g, ""), change: parseFloat(m[2].replace("−", "-")) });
  return out;
}
export function parseProvisions(rows) {
  const provisions = [];
  for (const row of rows) {
    const label = row.label.trim();
    if (label.toLowerCase() === "provision") { provisions.push({ name: row.text, effects: [], notes: {} }); continue; }
    if (!provisions.length) provisions.push({ name: "", effects: [], notes: {} });
    const last = provisions[provisions.length - 1];
    if (label.toLowerCase() === "effects") last.effects.push(...parseEffects(row.text));
    else last.notes[label] = row.text;
  }
  return provisions;
}
export function person(raw) {
  const m = TAIL_RE.exec(raw.tail || "");
  let party = null, state = null, role = null, seats = null;
  if (m) { party = m[1].toUpperCase(); state = m[2].toUpperCase(); seats = m[3] ? parseInt(m[3], 10) : null; role = m[4] ? m[4].trim() : null; }
  if (seats === null) { const s = /(\d+)\s+seats?/i.exec(raw.tail || "") || /(\d+)\s+seats?/i.exec(raw.ptext || ""); if (s) seats = parseInt(s[1], 10); }
  return { profile_id: String(raw.profile_id), name: raw.name || "", party, state, seats, role };
}
export function buildBill(raw, id) {
  const about = raw.about || {};
  const aboutText = (k) => (about[k] || {}).text || "";
  const numMatch = /^(.+?)\s+was sponsored by/.exec(raw.og_description || "");
  const timeLeft = aboutText("time left");
  const sponsors = (about["sponsor"] || {}).users || [];
  const cosponsors = (about["cosponsors"] || about["cosponsor"] || {}).users || [];
  const votes = { senate: { aye: [], nay: [], present: [] }, house: { aye: [], nay: [], present: [] } };
  const warnings = [];
  for (const g of raw.groups) {
    const voters = g.voters.filter((v) => v.profile_id).map(person);
    if (votes[g.chamber]) votes[g.chamber][g.vote] = voters;
    if (g.chamber === "house") {
      const seats = voters.reduce((a, v) => a + (v.seats || 0), 0);
      if (seats !== g.expected) warnings.push(`house ${g.vote}: page says ${g.expected} seats, parsed ${seats} seats from ${voters.length} members`);
    } else if (voters.length !== g.expected) warnings.push(`${g.chamber} ${g.vote}: page says ${g.expected}, parsed ${voters.length}`);
  }
  if (raw.groups.length !== 6) warnings.push(`expected 6 vote groups, found ${raw.groups.length}`);
  const status = aboutText("status");
  const finalized = timeLeft.trim().toLowerCase() === "finalized" || /\b(pass|passed|fail|failed)\b/i.test(status);
  return {
    resolution_id: id,
    url: `${"https://powerplayusa.net"}/resolutions/${id}`,
    number: numMatch ? numMatch[1] : raw.number_fallback || "",
    title: raw.og_title || "",
    status,
    time_left: timeLeft,
    finalized,
    type: aboutText("type"),
    to_pass: aboutText("to pass"),
    committee: aboutText("committee"),
    introduced: aboutText("introduced"),
    passed: aboutText("passed"),
    sponsor: sponsors.length ? person(sponsors[0]) : null,
    cosponsors: cosponsors.map(person),
    provisions: parseProvisions(raw.provisionRows || []),
    votes,
    warnings,
    scraped_at: new Date().toISOString().replace(/\.\d+Z$/, "+00:00"),
  };
}
