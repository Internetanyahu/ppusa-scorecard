#!/usr/bin/env python3
"""Scrape every politician's office(s) from their Power Play wiki profile page.

The national Politicians roster (window.politiciansData) has NO office data, so
offices must come from https://powerplayusa.net/wiki/politician/<user_id>
(see AGENTS.md section 4). That is one page per profile, so this runs as its own
workflow (.github/workflows/offices.yml) with 10 pages in parallel and writes:

  offices.json        {"profiles": {"<id>": {"offices": [...], "scraped_at": ...}}}
                      Read by scraper/main.py when it builds players.json.
  offices_debug.json  What the parser saw (label names, sample page text) so the
                      extraction can be calibrated against the real page.

Rules from AGENTS.md that this script follows:
  * A security-verification page is a hard failure: stop everything, exit 1.
  * A fetch that fails keeps the previous stored value; it never becomes empty.
  * Offices are never inferred from party, chamber, state, or is_main. Only
    labelled office/position fields on the profile page count.
"""
import asyncio
import collections
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
PLAYERS_FILE = ROOT / "players.json"
OFFICES_FILE = ROOT / "offices.json"
DEBUG_FILE = ROOT / "offices_debug.json"

BASE_URL = "https://powerplayusa.net"
CONCURRENCY = int(os.environ.get("SCRAPER_CONCURRENCY", "10"))
DELAY = 1.0
SAVE_EVERY = 40
USER_AGENT = (
    "Mozilla/5.0 (compatible; PPUSA-Scorecard-Bot/1.0; "
    "+https://github.com/SK64HD/ppusa-scorecard)"
)
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()

SECURITY_RE = re.compile(
    r"performing security verification|security service to protect against malicious bots", re.I
)
# A label (table header, <dt>, or "Label: value" line) that introduces an office.
LABEL_RE = re.compile(
    r"^(?:current |held |elected |appointed )?"
    r"(?:offices?|positions?|seats?|roles?|titles?|government (?:office|position))$", re.I
)
NO_OFFICE_RE = re.compile(r"^(?:none|n/?a|no office|no offices|-|—|–|not applicable)$", re.I)

EXTRACT_JS = r"""
() => {
  const clean = s => String(s ?? '').replace(/\s+/g, ' ').trim();
  const text = document.body ? document.body.innerText : '';
  const out = {
    security: /performing security verification|security service to protect against malicious bots/i.test(text),
    title: document.title, url: location.href, pairs: [], tagged: [], headings: [],
    snippet: clean(text).slice(0, 600),
  };
  for (const tr of document.querySelectorAll('tr')) {
    const cells = [...tr.children].map(c => clean(c.innerText));
    if (cells.length >= 2) out.pairs.push([cells[0], cells.slice(1).join(' ')]);
  }
  for (const dt of document.querySelectorAll('dt')) {
    const dd = dt.nextElementSibling;
    if (dd) out.pairs.push([clean(dt.innerText), clean(dd.innerText)]);
  }
  for (const line of text.split(/\n+/)) {
    const m = line.match(/^\s*([A-Za-z][A-Za-z ]{2,30}?)\s*[:：]\s*(.+)$/);
    if (m) out.pairs.push([clean(m[1]), clean(m[2])]);
  }
  // Label element followed by a value element (infobox / stat-card layouts)
  for (const el of document.querySelectorAll('[class*="label"], [class*="title"], small, .text-muted')) {
    const label = clean(el.innerText);
    const next = el.nextElementSibling;
    if (label && label.length <= 30 && next) out.pairs.push([label, clean(next.innerText)]);
  }
  // Elements explicitly marked as an office/position by their class name
  for (const el of document.querySelectorAll('[class*="office"], [class*="position"], [data-office]')) {
    const t = clean(el.innerText || el.getAttribute('data-office'));
    if (t) out.tagged.push(t);
  }
  out.headings = [...document.querySelectorAll('h1,h2,h3,h4')].map(h => clean(h.innerText)).filter(Boolean).slice(0, 20);
  return out;
}
"""


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_values(value):
    parts = re.split(r"\s*(?:\||;|•|·|\n|\s{2,})\s*", clean(value))
    return [p for p in (clean(x) for x in parts) if p]


def extract_offices(raw):
    """Offices from labelled fields only. Returns (offices, how)."""
    found, how = [], []

    def add(label, source):
        label = clean(label)[:140]
        if not label or NO_OFFICE_RE.match(label):
            return
        if label.lower() not in {x.lower() for x in found}:
            found.append(label)
            how.append(source)

    for key, value in raw.get("pairs", []):
        if LABEL_RE.match(clean(key)):
            for part in split_values(value):
                add(part, f"label:{clean(key).lower()}")
    for text in raw.get("tagged", []):
        for part in split_values(text):
            add(part, "class-tagged")
    return found, how


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SecurityBlock(RuntimeError):
    pass


async def scrape_profile(page, profile_id):
    await page.goto(f"{BASE_URL}/wiki/politician/{profile_id}", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1500)  # let client-side rendering finish
    raw = await page.evaluate(EXTRACT_JS)
    if raw.get("security"):
        raise SecurityBlock(f"profile {profile_id}: {raw.get('snippet', '')[:300]!r}")
    return raw


async def fetch(pool, profile_id, stop):
    if stop.is_set():
        return "SKIPPED"
    page = await pool.get()
    try:
        raw = await scrape_profile(page, profile_id)
        await asyncio.sleep(DELAY)
        return raw
    except SecurityBlock as error:
        stop.set()
        print(f"  SECURITY VERIFICATION on {error}")
        return "BLOCKED"
    except Exception as error:  # network/timeouts: keep the previous value
        print(f"  ERROR on {profile_id}: {error}")
        return "ERROR"
    finally:
        pool.put_nowait(page)


def chunks(items, size):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(offices, debug):
    OFFICES_FILE.write_text(json.dumps(offices, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    DEBUG_FILE.write_text(json.dumps(debug, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


async def main():
    players = load_json(PLAYERS_FILE, [])
    ids = sorted({str(p.get("powerplay_profile_id") or p.get("user_id")) for p in players if p.get("user_id") or p.get("powerplay_profile_id")}, key=int)
    only = [a for a in sys.argv[1:] if a.isdigit()]
    if only:
        ids = only
    if not ids:
        print("ERROR: players.json has no profiles; run scraper/main.py first.")
        sys.exit(1)

    offices = load_json(OFFICES_FILE, {"profiles": {}})
    offices.setdefault("profiles", {})
    key_counts, sample_snippets, empty_ids = collections.Counter(), [], []
    stats = {"ok": 0, "with_office": 0, "errors": 0, "skipped": 0}
    stop = asyncio.Event()
    print(f"Profiles to scrape: {len(ids)}  |  pages at once: {CONCURRENCY}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        if SCRAPER_TOKEN:
            async def add_token(route, request):
                if request.url.startswith(BASE_URL):
                    await route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
                else:
                    await route.continue_()
            await context.route("**/*", add_token)
        pool = asyncio.Queue()
        for _ in range(CONCURRENCY):
            pool.put_nowait(await context.new_page())

        try:
            for batch in chunks(ids, SAVE_EVERY):
                results = await asyncio.gather(*(fetch(pool, i, stop) for i in batch))
                for profile_id, raw in zip(batch, results):
                    if raw == "SKIPPED":
                        stats["skipped"] += 1
                        continue
                    if raw in ("ERROR", "BLOCKED"):
                        stats["errors"] += 1
                        continue
                    found, how = extract_offices(raw)
                    stats["ok"] += 1
                    for key, _value in raw.get("pairs", []):
                        if len(key) <= 30:
                            key_counts[key.lower()] += 1
                    if found:
                        stats["with_office"] += 1
                    else:
                        empty_ids.append(profile_id)
                        if len(sample_snippets) < 6:
                            sample_snippets.append({"profile_id": profile_id, "title": raw.get("title"),
                                                    "headings": raw.get("headings"), "snippet": raw.get("snippet")})
                    offices["profiles"][profile_id] = {"offices": found, "found_by": how, "scraped_at": utc_now()}
                    print(f"{profile_id}: {', '.join(found) if found else '(no office found)'}")
                offices["generated_at"] = utc_now()
                save(offices, {"generated_at": utc_now(), "stats": stats,
                               "top_labels_seen": key_counts.most_common(40),
                               "profiles_without_office": len(empty_ids),
                               "sample_pages_without_office": sample_snippets})
                if stop.is_set():
                    break
        finally:
            await browser.close()

    print()
    print(f"OK {stats['ok']}  |  with office {stats['with_office']}  |  errors {stats['errors']}  |  skipped {stats['skipped']}")
    if stop.is_set():
        print("#" * 70)
        print("# SECURITY VERIFICATION: Power Play blocked the office scraper.")
        print("# Stopped without retrying. Previously stored offices were kept.")
        print("#" * 70)
        sys.exit(1)
    if stats["ok"] == 0:
        print("ERROR: no profile pages could be read; offices.json was not updated.")
        sys.exit(1)
    if stats["with_office"] == 0:
        print("WARNING: pages loaded but no office field was recognised. Check offices_debug.json")
        print("(top_labels_seen and sample_pages_without_office) and adjust LABEL_RE.")


if __name__ == "__main__":
    asyncio.run(main())
