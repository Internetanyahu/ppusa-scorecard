// Functions injected into powerplayusa.net pages. Keep them self-contained.

export function probe() {
  const title = document.title || "";
  const body = ((document.body && document.body.innerText) || "").slice(0, 1600).toLowerCase();
  const path = location.pathname;
  return {
    url: location.href,
    path,
    title,
    challenge: /just a moment|security verification|verify you are human|checking your browser|performing security/.test(body),
    notFound: /\b404\b|page not found|not found|does not exist/.test(`${title} ${body}`),
    isBill: [...document.querySelectorAll("h4")].some(h => /about this bill/i.test(h.textContent)),
    isWiki: /\/wiki\/politician\/\d+\/?$/.test(path),
  };
}

export function extractDiscovery() {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const source = document.documentElement?.outerHTML || "";
  const visible = clean(document.body?.innerText || "");
  const haystack = `${document.title || ""}\n${location.href}\n${visible}`.toLowerCase();
  const keywordGroups = {
    resolution: ["resolution", "resolution_id", "create-resolution", "resolution status"],
    bill: ["about this bill", "bill status", "bill number", "resolution_id", "s.j.res.", "h.j.res.", "h.r.", "s."],
    office: ["office", "currently serves as", "career office", "senator", "representative", "governor", "president", "vice president"],
    politician: ["politician", "caucus", "party", "district", "chamber", "/wiki/politician/"],
    vote: ["aye", "nay", "present", "vote", "voted", "yea"],
    data: ["data", "json", "api", "provision", "provisions", "scorecard"]
  };
  const hits = {};
  for (const [group, words] of Object.entries(keywordGroups)) {
    const found = words.filter(word => haystack.includes(word));
    if (found.length) hits[group] = found;
  }
  const keywordCount = Object.values(hits).reduce((n, words) => n + words.length, 0);
  if (!keywordCount) return { found: false, url: location.href, path: location.pathname, title: document.title || "" };

  const path = location.pathname;
  let pageType = "other";
  if (/\/resolutions\/\d+/.test(path) || hits.resolution || hits.bill) pageType = "bill-or-resolution";
  if (/\/wiki\/politician\/\d+/.test(path) || hits.office || hits.politician) pageType = "politician";
  if (/\/national\/politicians/.test(path)) pageType = "politicians-roster";
  if (/create-resolution/.test(path)) pageType = "resolution-builder";

  return {
    found: true,
    url: location.href,
    path,
    title: document.title || "",
    pageType,
    hits,
    keywordCount,
    source,
    capturedAt: new Date().toISOString()
  };
}

export function extractBill() {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const meta = n => document.querySelector(`meta[property="${n}"], meta[name="${n}"]`)?.content || "";
  const h4s = [...document.querySelectorAll("h4")];
  const aboutH = h4s.find(h => /about this bill/i.test(h.textContent));
  if (!aboutH) return { found: false };

  const tailOf = a => {
    const n = a.nextSibling;
    let t = n && n.nodeType === 3 ? clean(n.textContent) : "";
    if (!/\(\s*[A-Za-z]+-[A-Z]{2}/.test(t)) {
      const p = a.parentElement;
      if (p && p.querySelectorAll('a[href*="/users/"]').length === 1) {
        const full = clean(p.textContent);
        const name = clean(a.textContent);
        const i = full.indexOf(name);
        t = i >= 0 ? full.slice(i + name.length) : full;
      }
    }
    return t;
  };
  const userFromAnchor = a => ({
    profile_id: ((a.getAttribute("href") || "").match(/\/users\/(\d+)/) || [])[1],
    name: clean(a.textContent),
    tail: tailOf(a),
    ptext: a.parentElement ? clean(a.parentElement.textContent).slice(0, 200) : "",
  });
  const userLinks = root => [...root.querySelectorAll('a[href*="/users/"]')].map(userFromAnchor);
  const tableAfter = h => {
    const next = h4s[h4s.indexOf(h) + 1];
    for (const t of document.querySelectorAll("table")) {
      if (h.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) {
        if (next && next.compareDocumentPosition(t) & Node.DOCUMENT_POSITION_FOLLOWING) return null;
        return t;
      }
    }
    return null;
  };

  const about = {};
  const aboutTable = tableAfter(aboutH);
  if (aboutTable) for (const row of aboutTable.querySelectorAll("tr")) {
    const cells = row.children;
    if (cells.length >= 2) about[clean(cells[0].textContent).toLowerCase()] = { text: clean(cells[1].textContent), users: userLinks(cells[1]) };
  }

  const groups = [];
  let current = null;
  let ayeSeen = 0;
  for (const el of document.querySelectorAll('h4, h6, a[href*="/users/"]')) {
    if (el.tagName === "H4") { current = null; continue; }
    if (el.tagName === "H6") {
      const m = clean(el.textContent).match(/^(Aye|Nay|Present)\s*\((\d+)\)$/i);
      if (!m) { current = null; continue; }
      const vote = m[1].toLowerCase();
      if (vote === "aye") ayeSeen += 1;
      current = { chamber: ayeSeen <= 1 ? "senate" : "house", vote, expected: parseInt(m[2], 10), voters: [] };
      groups.push(current);
      continue;
    }
    if (current) current.voters.push(userFromAnchor(el));
  }

  const provisionRows = [];
  const provH = h4s.find(h => /^provisions$/i.test(clean(h.textContent)));
  const provTable = provH ? tableAfter(provH) : null;
  if (provTable) for (const row of provTable.querySelectorAll("tr")) {
    const cells = row.children;
    if (cells.length >= 2) provisionRows.push({ label: clean(cells[0].textContent), text: clean(cells[1].textContent) });
  }
  const numMatch = clean(document.body.innerText).match(/\b(S\.J\.Res\.|H\.J\.Res\.|S\.|H\.R\.)\s*\d+\b/);
  return { found: true, provisionRows, og_title: meta("og:title"), og_description: meta("og:description"), number_fallback: numMatch ? numMatch[0] : "", about, groups };
}

export function extractOffice() {
  const clean = s => (s || "").replace(/\s+/g, " ").trim();
  const summary = clean(document.querySelector(".wiki-summary")?.innerText || "");
  const description = clean(document.querySelector('meta[name="description"]')?.content || "");
  const career = [...document.querySelectorAll(".wiki-career-office")].map(x => clean(x.innerText));
  const years = [...document.querySelectorAll(".wiki-career-years")].map(x => clean(x.innerText));
  const normalize = value => {
    let text = clean(value).replace(/\s+(?:from|of)\s+.+$/i, "");
    text = text.replace(/^U\.S\. Senator$/i, "Senate").replace(/^U\.S\. Representative$/i, "House").replace(/^Congress(?:man|woman)$/i, "House");
    return text;
  };
  const offices = [];
  for (const text of [summary, description]) {
    const m = text.match(/currently serves as\s+(.+?)(?:\.|$)/i);
    if (m) { const office = normalize(m[1]); if (office && !offices.some(x => x.toLowerCase() === office.toLowerCase())) offices.push(office); }
  }
  if (!offices.length) {
    for (let i = 0; i < career.length; i++) {
      const period = years[i] || "";
      if (i === 0 || /present/i.test(period)) {
        const office = normalize(career[i]);
        if (office && !offices.some(x => x.toLowerCase() === office.toLowerCase())) offices.push(office);
      }
    }
  }
  return { offices, found_by: offices.length ? ["wiki-summary-current-office"] : [], wiki_url: location.href, scraped_at: new Date().toISOString() };
}
