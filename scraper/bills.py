import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = "https://powerplayusa.net"
BILLS_FILE = Path("bills.json")

START_ID = 1
MAX_MISSES = 3        # stop after this many consecutive login/missing pages
HARD_CAP = 5000       # safety net so a bug can never loop forever
SAVE_EVERY = 25

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
  if (!isBill) return { found: false };

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

  return {
    found: true,
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
    cosponsors = (about.get("cosponsors") or {}).get("users", [])

    votes = {
        "senate": {"aye": [], "nay": [], "present": []},
        "house": {"aye": [], "nay": [], "present": []},
    }
    warnings = []

    for group in raw["groups"]:
        voters = [person(v) for v in group["voters"] if v.get("profile_id")]
        votes[group["chamber"]][group["vote"]] = voters
        if len(voters) != group["expected"]:
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
    page.wait_for_timeout(300)

    if "/login" in page.url:
        return None

    raw = page.evaluate(EXTRACT_JS)
    if not raw.get("found"):
        return None

    return build_bill(raw, resolution_id)


def main():
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]  # e.g. python bills.py 2

    stored = load_json(BILLS_FILE, [])
    bills = {int(b["resolution_id"]): b for b in stored}

    scraped = skipped = 0
    misses = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            ids = only or range(START_ID, HARD_CAP)

            for resolution_id in ids:
                existing = bills.get(resolution_id)

                # Law or failed: archived, never rescraped.
                if existing and existing.get("finalized"):
                    skipped += 1
                    misses = 0
                    continue

                try:
                    bill = scrape_bill(page, resolution_id)
                except Exception as error:
                    print(f"  ERROR on {resolution_id}: {error}")
                    continue  # network errors are not "end of bills"

                if bill is None:
                    misses += 1
                    print(f"No bill at {resolution_id} ({misses}/{MAX_MISSES})")
                    if not only and misses >= MAX_MISSES:
                        break
                    continue

                misses = 0
                bills[resolution_id] = bill
                scraped += 1

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
        finally:
            browser.close()

    save_json(BILLS_FILE, [bills[k] for k in sorted(bills)])

    print()
    print(f"Scraped: {scraped}")
    print(f"Skipped (finalized): {skipped}")
    print(f"Bills stored: {len(bills)}")
    print(f"Saved: {BILLS_FILE}")


if __name__ == "__main__":
    main()
