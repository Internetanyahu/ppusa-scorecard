// Functions injected into powerplayusa.net pages. Keep them self-contained.

export function probe() {
  const title = document.title || "";
  const body = ((document.body && document.body.innerText) || "").slice(0, 1200).toLowerCase();
  return {
    url: location.href,
    path: location.pathname,
    title,
    challenge:
      /just a moment/i.test(title) ||
      /security verification|verify you are human|checking your browser|performing security/.test(body),
    isBill: [...document.querySelectorAll("h4")].some((h) => /about this bill/i.test(h.textContent)),
    isPlayer: /\/users\/\d+\/?$/.test(location.pathname),
  };
}

export function extractBill() {
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const meta = (n) => {
    const m = document.querySelector(`meta[property="${n}"], meta[name="${n}"]`);
    return m ? m.content : "";
  };

  const h4s = [...document.querySelectorAll("h4")];
  const aboutH = h4s.find((h) => /about this bill/i.test(h.textContent));
  if (!aboutH) return { found: false };

  const tailOf = (a) => {
    const n = a.nextSibling;
    let t = n && n.nodeType === 3 ? clean(n.textContent) : "";
    if (!/\(\s*[A-Za-z]+-[A-Za-z]{2}/.test(t)) {
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
  const userFromAnchor = (a) => ({
    profile_id: ((a.getAttribute("href") || "").match(/\/users\/(\d+)/) || [])[1],
    name: clean(a.textContent),
    tail: tailOf(a),
    ptext: a.parentElement ? clean(a.parentElement.textContent).slice(0, 200) : "",
  });
  const userLinks = (root) => [...root.querySelectorAll('a[href*="/users/"]')].map(userFromAnchor);
  const tableAfter = (h) => {
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
  if (aboutTable) {
    for (const row of aboutTable.querySelectorAll("tr")) {
      const cells = row.children;
      if (cells.length < 2) continue;
      about[clean(cells[0].textContent).toLowerCase()] = {
        text: clean(cells[1].textContent),
        users: userLinks(cells[1]),
      };
    }
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
  const provH = h4s.find((h) => /^provisions$/i.test(clean(h.textContent)));
  const provTable = provH ? tableAfter(provH) : null;
  if (provTable) {
    for (const row of provTable.querySelectorAll("tr")) {
      const cells = row.children;
      if (cells.length >= 2) provisionRows.push({ label: clean(cells[0].textContent), text: clean(cells[1].textContent) });
    }
  }

  const h2 = document.querySelector("h2");
  const numMatch = clean(document.body.innerText).match(/\b(S\.J\.Res\.|H\.J\.Res\.|S\.|H\.R\.)\s*\d+\b/);
  return {
    found: true,
    provisionRows,
    og_title: meta("og:title") || (h2 ? clean(h2.textContent) : ""),
    og_description: meta("og:description"),
    number_fallback: numMatch ? numMatch[0] : "",
    about,
    groups,
  };
}

export function extractPlayerBillLinks() {
  return [...document.querySelectorAll('a[href*="/resolutions/"]')]
    .map((a) => {
      const m = (a.href || "").match(/\/resolutions\/(\d+)(?:[/?#]|$)/);
      return m ? Number(m[1]) : null;
    })
    .filter((x) => Number.isInteger(x));
}
