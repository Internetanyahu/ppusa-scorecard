import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "https://powerplayusa.net"
BILLS_FILE = Path("bills.json")
LINKS_FILE = Path("finalized_links.json")

START_ID = 1
MAX_MISSES = 40
TAIL_MISSES = 10
DELAY = 1.0
HARD_CAP = 5000
SAVE_EVERY = 25
CONCURRENCY = int(os.environ.get("SCRAPER_CONCURRENCY", "10"))

USER_AGENT = (
    "Mozilla/5.0 (compatible; PPUSA-Scorecard-Bot/1.0; "
    "+https://github.com/SK64HD/ppusa-scorecard)"
)
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()

SECURITY_VERIFICATION_RE = re.compile(
    r"performing security verification|security service to protect against malicious bots",
    re.I,
)

EXTRACT_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const meta = n => {
    const m = document.querySelector(`meta[property="${n}"], meta[name="${n}"]`);
    return m ? m.content : '';
  };
  const bodyText = clean(document.body ? document.body.innerText : '');
  const security = /performing security verification|security service to protect against malicious bots/i.test(bodyText);
  const h4s = [...document.querySelectorAll('h4')].map(h => clean(h.textContent)).slice(0, 8);
  if (security) return { found: false, security: true, h4s, snippet: bodyText.slice(0, 500) };

  const isBill = [...document.querySelectorAll('h4')].some(h => /about this bill/i.test(h.textContent));
  if (!isBill) return { found: false, security: false, h4s, snippet: bodyText.slice(0, 500) };

  const userFromAnchor = a => ({
    profile_id: ((a.getAttribute('href') || '').match(/\/users\/(\d+)/) || [])[1],
    name: clean(a.textContent),
    tail: clean(a.nextSibling && a.nextSibling.nodeType === 3 ? a.nextSibling.textContent : ''),
  });
  const userLinks = root => [...root.querySelectorAll('a[href*="/users/"]')].map(userFromAnchor);

  const about = {};
  for (const row of document.querySelectorAll('tr')) {
    const cells = row.children;
    if (cells.length < 2) continue;
    about[clean(cells[0].textContent).toLowerCase()] = {
      text: clean(cells[1].textContent),
      users: userLinks(cells[1]),
    };
  }

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
      current = { chamber: ayeSeen <= 1 ? 'senate' : 'house', vote, expected: parseInt(m[2], 10), voters: [] };
      groups.push(current);
      continue;
    }
    if (current) current.voters.push(userFromAnchor(el));
  }

  const provisionRows = [];
  const ph = [...document.querySelectorAll('h4')].find(h => /^provisions$/i.test(clean(h.textContent)));
  if (ph) {
    let el = ph.nextElementSibling;
    while (el && el.tagName !== 'H4' && !(el.matches('table') || el.querySelector('table'))) el = el.nextElementSibling;
    const table = (el && el.tagName !== 'H4') ? (el.matches('table') ? el : el.querySelector('table')) : null;
    if (table) {
      for (const row of table.querySelectorAll('tr')) {
        const cells = row.children;
        if (cells.length >= 2) provisionRows.push({ label: clean(cells[0].textContent), text: clean(cells[1].textContent) });
      }
    }
  }

  return { found: true, security: false, provisionRows, og_title: meta('og:title'), og_description: meta('og:description'), about, groups };
}
"""

TAIL_RE = re.compile(
    r"\(\s*([A-Za-z]+)-([A-Za-z]{2})"
    r"(?:\s*,\s*(\d+)\s+seats?)?"
    r"(?:\s*,\s*([^)]+?))?\s*\)"
)
EFFECT_RE = re.compile(r"(.+?)\s*([+\-\u2212]\d+(?:\.\d+)?)(?=[\s,;]|$)")


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path, default):
    if not path.exists(): return default
    try:
        with path.open("r", encoding="utf-8") as f: return json.load(f)
    except (json.JSONDecodeError, OSError): return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def about_text(about, label):
    return (about.get(label) or {}).get("text", "")


def parse_effects(text):
    return [{"metric": metric.strip(" ,;"), "change": float(change.replace("\u2212", "-"))} for metric, change in EFFECT_RE.findall(text)]


def parse_provisions(rows):
    provisions = []
    for row in rows:
        label, text = row["label"].strip(), row["text"]
        if label.lower() == "provision": provisions.append({"name": text, "effects": [], "notes": {}}); continue
        if not provisions: provisions.append({"name": "", "effects": [], "notes": {}})
        if label.lower() == "effects": provisions[-1]["effects"].extend(parse_effects(text))
        else: provisions[-1]["notes"][label] = text
    return provisions


def person(raw):
    match = TAIL_RE.search(raw.get("tail", ""))
    party = state = role = None; seats = None
    if match:
        party, state = match.group(1).upper(), match.group(2).upper()
        seats = int(match.group(3)) if match.group(3) else None
        role = match.group(4).strip() if match.group(4) else None
    return {"profile_id": str(raw["profile_id"]), "name": raw.get("name", ""), "party": party, "state": state, "seats": seats, "role": role}


def build_bill(raw, resolution_id):
    about = raw["about"]
    number_match = re.match(r"^(.+?)\s+was sponsored by", raw.get("og_description", ""))
    time_left = about_text(about, "time left")
    sponsor = (about.get("sponsor") or {}).get("users", [])
    cosponsors = (about.get("cosponsors") or about.get("cosponsor") or {}).get("users", [])
    votes = {"senate": {"aye": [], "nay": [], "present": []}, "house": {"aye": [], "nay": [], "present": []}}
    warnings = []
    for group in raw["groups"]:
        voters = [person(v) for v in group["voters"] if v.get("profile_id")]
        votes[group["chamber"]][group["vote"]] = voters
        if group["chamber"] == "house":
            seats = sum(v["seats"] or 0 for v in voters)
            if seats != group["expected"]: warnings.append(f"house {group['vote']}: page says {group['expected']} seats, parsed {seats} seats from {len(voters)} members")
        elif len(voters) != group["expected"]:
            warnings.append(f"{group['chamber']} {group['vote']}: page says {group['expected']}, parsed {len(voters)}")
    if len(raw["groups"]) != 6: warnings.append(f"expected 6 vote groups, found {len(raw['groups'])}")
    return {
        "resolution_id": resolution_id, "url": f"{BASE_URL}/resolutions/{resolution_id}",
        "number": number_match.group(1) if number_match else "", "title": raw.get("og_title", ""),
        "status": about_text(about, "status"), "time_left": time_left,
        "finalized": time_left.strip().lower() == "finalized", "type": about_text(about, "type"),
        "to_pass": about_text(about, "to pass"), "committee": about_text(about, "committee"),
        "introduced": about_text(about, "introduced"), "passed": about_text(about, "passed"),
        "sponsor": person(sponsor[0]) if sponsor else None, "cosponsors": [person(c) for c in cosponsors],
        "provisions": parse_provisions(raw.get("provisionRows", [])), "votes": votes,
        "warnings": warnings, "scraped_at": now_iso(),
    }


ERROR = object()


class SecurityVerificationError(RuntimeError):
    pass


async def scrape_bill(page, resolution_id):
    await page.goto(f"{BASE_URL}/resolutions/{resolution_id}", wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_function("() => [...document.querySelectorAll('h4')].some(h => /about this bill/i.test(h.textContent))", timeout=15000)
    except Exception:
        pass

    raw = None if "/login" in page.url else await page.evaluate(EXTRACT_JS)
    if raw and raw.get("security"):
        raise SecurityVerificationError(
            f"[{resolution_id}] Power Play returned a security verification page; refusing to scrape or treat it as a missing bill. "
            f"h4s={raw.get('h4s')!r} text={raw.get('snippet')!r}"
        )

    if not raw or not raw.get("found"):
        print(f"  [{resolution_id}] (url={page.url!r} title={await page.title()!r})")
        if raw: print(f"  [{resolution_id}] h4s={raw.get('h4s')} text={raw.get('snippet')!r}")
        return None
    return build_bill(raw, resolution_id)


async def fetch(pool, resolution_id):
    page = await pool.get()
    try:
        return await scrape_bill(page, resolution_id)
    except SecurityVerificationError:
        raise
    except Exception as error:
        print(f"  ERROR on {resolution_id}: {error}")
        return ERROR
    finally:
        pool.put_nowait(page)


def chunks(items, size):
    items = list(items)
    for start in range(0, len(items), size): yield items[start:start + size]


def save_all(bills, links):
    save_json(BILLS_FILE, [bills[k] for k in sorted(bills)])
    save_json(LINKS_FILE, dict(sorted(links.items(), key=lambda kv: int(kv[0]))))


async def main():
    only = [int(a) for a in sys.argv[1:] if a.isdigit()]
    stored = load_json(BILLS_FILE, [])
    bills = {int(b["resolution_id"]): b for b in stored}
    links = {str(k): v for k, v in load_json(LINKS_FILE, {}).items()}
    for rid, b in bills.items():
        if b.get("finalized") and "provisions" in b: links.setdefault(str(rid), b.get("url") or f"{BASE_URL}/resolutions/{rid}")

    max_known = max(bills) if bills else 0
    refresh = ([r for r in only if str(r) not in links and not bills.get(r, {}).get("finalized")] if only else sorted(r for r in bills if str(r) not in links and not bills.get(r, {}).get("finalized")))
    skipped = len(links) if not only else len(only) - len(refresh)
    print(f"Finalized links on file: {len(links)} (never revisited)")
    print(f"Bills to refresh: {len(refresh)}  |  pages at once: {CONCURRENCY}")
    scraped = 0

    def keep(resolution_id, bill):
        nonlocal scraped
        bills[resolution_id] = bill; scraped += 1
        if bill.get("finalized"): links[str(resolution_id)] = bill.get("url") or f"{BASE_URL}/resolutions/{resolution_id}"
        tally = {ch: {k: len(v) for k, v in bill["votes"][ch].items()} for ch in ("senate", "house")}
        print(f"{bill['number'] or resolution_id}: {bill['title']} [{bill['status']}] {tally}")
        for warning in bill["warnings"]: print(f"  WARNING: {warning}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        if SCRAPER_TOKEN:
            async def add_token(route, request):
                if request.url.startswith(BASE_URL): await route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
                else: await route.continue_()
            await context.route("**/*", add_token)
            print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
        else: print("SCRAPER_TOKEN is not set; sending no identification header")

        pool = asyncio.Queue()
        for _ in range(CONCURRENCY): pool.put_nowait(await context.new_page())
        async def run(batch): return dict(zip(batch, await asyncio.gather(*(fetch(pool, r) for r in batch))))

        try:
            for batch in chunks(refresh, SAVE_EVERY):
                results = await run(batch)
                for rid in batch:
                    bill = results[rid]
                    if bill is ERROR: continue
                    if bill is None: print(f"Could not refresh {rid}; keeping stored copy"); continue
                    keep(rid, bill)
                save_all(bills, links)

            if not only:
                limit = TAIL_MISSES if max_known else MAX_MISSES
                next_id, misses, done = max_known + 1, 0, False
                while not done and next_id < HARD_CAP:
                    batch = list(range(next_id, min(next_id + CONCURRENCY, HARD_CAP))); next_id += len(batch)
                    results = await run(batch)
                    for rid in batch:
                        bill = results[rid]
                        if bill is ERROR: continue
                        if bill is None:
                            misses += 1; print(f"No bill at {rid} ({misses}/{limit})")
                        else:
                            misses = 0; keep(rid, bill)
                    done = misses >= limit
                    save_all(bills, links)
        except SecurityVerificationError as error:
            print()
            print("ERROR: BILL SCRAPER STOPPED — POWER PLAY SECURITY VERIFICATION DETECTED.")
            print(str(error))
            print("No retry was attempted, and the verification page was not treated as a missing bill.")
            raise SystemExit(2)
        finally:
            await browser.close()

    if not bills:
        print("ERROR: no bills were found, so bills.json was NOT written.")
        sys.exit(1)
    save_all(bills, links)
    print(f"Scraped: {scraped}")
    print(f"Skipped (finalized): {skipped}")
    print(f"Bills stored: {len(bills)}")
    print(f"Saved: {BILLS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
