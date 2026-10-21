import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://powerplayusa.net"
BILLS_FILE = Path("bills.json")
# Ledger of finalized bills: {resolution_id: url}. A bill listed here is never
# visited again, and the scan for new bills starts after the highest known ID.
LINKS_FILE = Path("finalized_links.json")

START_ID = 1
MAX_MISSES = 40       # stop after this many consecutive misses when scanning from scratch
TAIL_MISSES = 10      # ...and after this many when scanning past the highest known bill
DELAY = 1.0           # seconds between requests (avoids being bounced to login)
HARD_CAP = 5000       # safety net so a bug can never loop forever
SAVE_EVERY = 25

# Identifies this scraper so the site owner can allow it. The "Mozilla/5.0
# (compatible; ...)" shape keeps simple browser-integrity checks happy.
USER_AGENT = (
    "Mozilla/5.0 (compatible; PPUSA-Scorecard-Bot/1.0; "
    "+https://github.com/SK64HD/ppusa_conservative_scorecard)"
)
# Shared secret sent only to powerplayusa.net (from the SCRAPER_TOKEN repo
# secret) so a firewall rule can allow exactly this scraper.
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()

# Runs inside the page. Returns raw data; Python does the cleanup.
EXTRACT_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const meta = n => {
    const m = document.querySelector(
      `meta[property="${n}"], meta[name="${n}"]`);
    return m ? m.content : '';
  };

  const isBill = [...document.querySelectorAll('h4')]
    .some(h => /about this bill/i.test(h.textContent));
  if (!isBill) return {
    found: false,
    h4s: [...document.querySelectorAll('h4')].map(h => clean(h.textContent)).slice(0, 8),
    snippet: clean(document.body ? document.body.innerText : '').slice(0, 160),
  };

  const userLinks = root => [...root.querySelectorAll('a[href*="/users/"]')]
    .map(a => userFromAnchor(a));

  const userFromAnchor = a => ({
    profile_id: ((a.getAttribute('href') || '').match(/\/users\/(\d+)/) || [])[1],
    name: clean(a.textContent),
    tail: clean(a.nextSibling && a.nextSibling.nodeType === 3
                ? a.nextSibling.textContent : ''),
  });

  // "About This Bill" key/value rows
  const about = {};
  for (const row of document.querySelectorAll('tr')) {
    const cells = row.children;
    if (cells.length < 2) continue;
    about[clean(cells[0].textContent).toLowerCase()] = {
      text: clean(cells[1].textContent),
      users: userLinks(cells[1]),
    };
  }

  // Votes: walk headings and user links in document order.
  // Group 1 (first "Aye") is the Senate, group 2 is the House.
  const groups = [];
  let current = null;
  let ayeSeen = 0;
  for (const el of document.querySelectorAll('h4, h6, a[href*="/users/"]')) {
    if (el.tagName === 'H4') { current = null; continue; }
    if (el.tagName === 'H6') {
      const m = clean(el.textContent).match(/^(Aye|Nay|Present)\s*\((\d+)\)$/i);
      if (!m) { current = null; continue; }
      const vote = m[1].toLowerCase();
      if (vote === 'aye') ayeSeen += 1;
      current = { chamber: ayeSeen <= 1 ? 'senate' : 'house',
                  vote, expected: parseInt(m[2], 10), voters: [] };
      groups.push(current);
      continue;
    }
    if (current) current.voters.push(userFromAnchor(el));
  }

  // "Provisions" table: label/text rows in page order
  const provisionRows = [];
  const ph = [...document.querySelectorAll('h4')]
    .find(h => /^provisions$/i.test(clean(h.textContent)));
  if (ph) {
    let el = ph.nextElementSibling;
    while (el && el.tagName !== 'H4' &&
           !(el.matches('table') || el.querySelector('table'))) {
      el = el.nextElementSibling;
    }
    const table = (el && el.tagName !== 'H4')
      ? (el.matches('table') ? el : el.querySelector('table')) : null;
    if (table) {
      for (const row of table.querySelectorAll('tr')) {
        const cells = row.children;
        if (cells.length >= 2) {
          provisionRows.push({ label: clean(cells[0].textContent),
                               text: clean(cells[1].textContent) });
        }
      }
    }
  }

  return {
    found: true,
    provisionRows,
    og_title: meta('og:title'),
    og_description: meta('og:description'),
    about,
    groups,
  };
}
"""

TAIL_RE = re.compile(
    r"\(\s*([A-Za-z]+)-([A-Za-z]{2})"      # party-state
    r"(?:\s*,\s*(\d+)\s+seats?)?"           # optional seats (House)
    r"(?:\s*,\s*([^)]+?))?\s*\)"            # optional role (Leader, Whip)
)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def about_text(about, label):
    return (about.get(label) or {}).get("text", "")


EFFECT_RE = re.compile(r"(.+?)\s*([+\-\u2212]\d+(?:\.\d+)?)(?=[\s,;]|$)")


def parse_effects(text):
    """'Civil Liberties+2 Gender Equality+1' -> [{'metric':..., 'change':2.0}, ...]"""
    effects = []
    for metric, change in EFFECT_RE.findall(text):
        effects.append(
            {
                "metric": metric.strip(" ,;"),
                "change": float(change.replace("\u2212", "-")),
            }
        )
    return effects


def parse_provisions(rows):
    """Group Provisions-table rows: each 'Provision' row starts a new provision."""
    provisions = []

    for row in rows:
        label = row["label"].strip()
        text = row["text"]

        if label.lower() == "provision":
            provisions.append({"name": text, "effects": [], "notes": {}})
            continue

        if not provisions:
            provisions.append({"name": "", "effects": [], "notes": {}})

        if label.lower() == "effects":
            provisions[-1]["effects"].extend(parse_effects(text))
        else:
            provisions[-1]["notes"][label] = text

    return provisions


def person(raw):
    """Turn a raw link + trailing '(D-WA, 31 seats, Leader)' into a record."""
    match = TAIL_RE.search(raw.get("tail", ""))
    party = state = role = None
    seats = None
    if match:
        party = match.group(1).upper()
        state = match.group(2).upper()
        seats = int(match.group(3)) if match.group(3) else None
        role = match.group(4).strip() if match.group(4) else None
    return {
        "profile_id": str(raw["profile_id"]),
        "name": raw.get("name", ""),
        "party": party,
        "state": state,
        "seats": seats,
        "role": role,
    }


def build_bill(raw, resolution_id):
    about = raw["about"]
    description = raw.get("og_description", "")
    number_match = re.match(r"^(.+?)\s+was sponsored by", description)

    time_left = about_text(about, "time left")
    sponsor = (about.get("sponsor") or {}).get("users", [])
    cosponsors = (about.get("cosponsors") or about.get("cosponsor") or {}).get("users", [])

    votes = {
        "senate": {"aye": [], "nay": [], "present": []},
        "house": {"aye": [], "nay": [], "present": []},
    }
    warnings = []

    for group in raw["groups"]:
        voters = [person(v) for v in group["voters"] if v.get("profile_id")]
        votes[group["chamber"]][group["vote"]] = voters
        if group["chamber"] == "house":
            seats = sum(v["seats"] or 0 for v in voters)
            if seats != group["expected"]:
                warnings.append(
                    f"house {group['vote']}: page says {group['expected']} seats, "
                    f"parsed {seats} seats from {len(voters)} members"
                )
        elif len(voters) != group["expected"]:
            warnings.append(
                f"{group['chamber']} {group['vote']}: page says "
                f"{group['expected']}, parsed {len(voters)}"
            )

    if len(raw["groups"]) != 6:
        warnings.append(f"expected 6 vote groups, found {len(raw['groups'])}")

    return {
        "resolution_id": resolution_id,
        "url": f"{BASE_URL}/resolutions/{resolution_id}",
        "number": number_match.group(1) if number_match else "",
        "title": raw.get("og_title", ""),
        "status": about_text(about, "status"),
        "time_left": time_left,
        "finalized": time_left.strip().lower() == "finalized",
        "type": about_text(about, "type"),
        "to_pass": about_text(about, "to pass"),
        "committee": about_text(about, "committee"),
        "introduced": about_text(about, "introduced"),
        "passed": about_text(about, "passed"),
        "sponsor": person(sponsor[0]) if sponsor else None,
        "cosponsors": [person(c) for c in cosponsors],
        "provisions": parse_provisions(raw.get("provisionRows", [])),
        "votes": votes,
        "warnings": warnings,
        "scraped_at": now_iso(),
    }


def scrape_bill(page, resolution_id):
    """Return a bill dict, or None if the page is the login page / missing."""
    page.goto(
        f"{BASE_URL}/resolutions/{resolution_id}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    try:
        page.wait_for_function(
            "() => [...document.querySelectorAll('h4')]"
            ".some(h => /about this bill/i.test(h.textContent))",
            timeout=15000,
        )
    except Exception:
        pass

    raw = None
    if "/login" not in page.url:
        raw = page.evaluate(EXTRACT_JS)

    if not raw or not raw.get("found"):
        print(f"  (url={page.url!r} title={page.title()!r})")
        if raw:
            print(f"  h4s={raw.get('h4s')} text={raw.get('snippet')!r}")
        return None

    return build_bill(raw, resolution_id)


def main():
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]  # e.g. python bills.py 2

    stored = load_json(BILLS_FILE, [])
    bills = {int(b["resolution_id"]): b for b in stored}

    # Finalized-bill ledger. Seeded from bills.json so the first run after this
    # change already knows every finalized bill.
    links = {str(k): v for k, v in load_json(LINKS_FILE, {}).items()}
    for rid, b in bills.items():
        if b.get("finalized") and "provisions" in b:
            links.setdefault(str(rid), b.get("url") or f"{BASE_URL}/resolutions/{rid}")

    max_known = max(bills) if bills else 0
    if only:
        ids = only
    else:
        # Known bills that are not finalized yet (their status can still change),
        # then anything newer than the highest ID we have ever seen.
        unfinished = sorted(r for r in bills if str(r) not in links)
        ids = unfinished + list(range(max_known + 1, HARD_CAP))
    print(f"Finalized links on file: {len(links)} (never revisited)")
    print(f"Unfinished bills to refresh: {sum(1 for r in ids if r <= max_known and str(r) not in links)}")

    scraped = skipped = 0
    misses = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)

        if SCRAPER_TOKEN:
            def add_token(route, request):
                if request.url.startswith(BASE_URL):
                    route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
                else:  # never leak the token to third-party hosts
                    route.continue_()
            page.route("**/*", add_token)
            print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
        else:
            print("SCRAPER_TOKEN is not set; sending no identification header")

        try:
            for resolution_id in ids:
                # Finalized: archived link, never rescraped.
                if str(resolution_id) in links:
                    skipped += 1
                    continue
                is_new = resolution_id > max_known

                try:
                    bill = scrape_bill(page, resolution_id)
                    if bill is None:  # one retry: a rate-limit bounce looks like a miss
                        time.sleep(3)
                        bill = scrape_bill(page, resolution_id)
                except Exception as error:
                    print(f"  ERROR on {resolution_id}: {error}")
                    continue  # network errors are not "end of bills"
                time.sleep(DELAY)

                if bill is None:
                    if not is_new:
                        # A known bill that did not load this time (rate limit or
                        # block page): keep the stored copy, do not end the scan.
                        print(f"Could not refresh {resolution_id}; keeping stored copy")
                        continue
                    misses += 1
                    limit = TAIL_MISSES if max_known else MAX_MISSES
                    print(f"No bill at {resolution_id} ({misses}/{limit})")
                    if not only and misses >= limit:
                        break
                    continue

                misses = 0
                bills[resolution_id] = bill
                scraped += 1
                if bill.get("finalized"):
                    links[str(resolution_id)] = bill.get("url") or f"{BASE_URL}/resolutions/{resolution_id}"

                tally = {
                    ch: {k: len(v) for k, v in bill["votes"][ch].items()}
                    for ch in ("senate", "house")
                }
                print(
                    f"{bill['number'] or resolution_id}: {bill['title']} "
                    f"[{bill['status']}] {tally}"
                )
                for warning in bill["warnings"]:
                    print(f"  WARNING: {warning}")

                if scraped % SAVE_EVERY == 0:
                    save_json(BILLS_FILE, [bills[k] for k in sorted(bills)])
                    save_json(LINKS_FILE, dict(sorted(links.items(), key=lambda kv: int(kv[0]))))
        finally:
            browser.close()

    if not bills:
        print()
        print("ERROR: no bills were found, so bills.json was NOT written.")
        print("Check the (url=..., title=...) lines above: a login or")
        print("block page means the site is rejecting the scraper.")
        sys.exit(1)

    save_json(BILLS_FILE, [bills[k] for k in sorted(bills)])
    save_json(LINKS_FILE, dict(sorted(links.items(), key=lambda kv: int(kv[0]))))

    print()
    print(f"Scraped: {scraped}")
    print(f"Skipped (finalized): {skipped}")
    print(f"Bills stored: {len(bills)}")
    print(f"Saved: {BILLS_FILE}")


if __name__ == "__main__":
    main()
