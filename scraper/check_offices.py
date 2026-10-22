#!/usr/bin/env python3
"""Check office data only for main player profiles with no recent vote.

The normal player scraper derives legislative office from the most recent bill
vote. This script is the fallback for players who have not voted recently. It
reads only the main profile's wiki page and never scans the full roster of wiki
pages.
"""
import argparse
import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "https://powerplayusa.net"
PLAYERS_FILE = Path("players.json")
BILLS_FILE = Path("bills.json")
OFFICES_FILE = Path("offices.json")
DEBUG_FILE = Path("offices_debug.json")
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = __import__("os").environ.get("SCRAPER_TOKEN", "").strip()
CONCURRENCY = 8
USER_AGENT = (
    "Mozilla/5.0 (compatible; PPUSA-Scorecard-Bot/1.0; "
    "+https://github.com/SK64HD/ppusa-scorecard)"
)
SECURITY_RE = re.compile(
    r"performing security verification|security service to protect against malicious bots",
    re.I,
)

EXTRACT_JS = r"""
() => {
  const clean = s => String(s ?? '').replace(/\s+/g, ' ').trim();
  const body = clean(document.body?.innerText || '');
  const career = [...document.querySelectorAll('.wiki-career-office')].map(x => clean(x.innerText));
  const years = [...document.querySelectorAll('.wiki-career-years')].map(x => clean(x.innerText));
  const summary = clean(document.querySelector('.wiki-summary')?.innerText || '');
  const description = document.querySelector('meta[name="description"]')?.content || '';
  return {
    security: /performing security verification|security service to protect against malicious bots/i.test(body),
    title: document.title,
    summary,
    description,
    career,
    years,
    snippet: body.slice(0, 800),
  };
}
"""


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_time(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def normalize_office(text):
    text = clean(text)
    text = re.sub(r"\s+(?:from|of)\s+.+$", "", text, flags=re.I)
    replacements = [
        (r"^U\.S\. Senator$", "Senate"),
        (r"^U\.S\. Representative$", "House"),
        (r"^Congressman$", "House"),
        (r"^Congresswoman$", "House"),
        (r"^President of the United States$", "President"),
        (r"^President$", "President"),
        (r"^Vice President of the United States$", "Vice President"),
        (r"^Vice President$", "Vice President"),
    ]
    for pattern, replacement in replacements:
        if re.fullmatch(pattern, text, re.I):
            return replacement
    return text


def extract_offices(raw):
    offices = []
    # The wiki summary is the strongest current-office signal in the example
    # page. Prefer the phrase immediately following "currently serves as".
    for text in (raw.get("summary", ""), raw.get("description", "")):
        match = re.search(r"currently serves as\s+(.+?)(?:\.|$)", text, re.I)
        if match:
            office = normalize_office(match.group(1))
            if office and office.lower() not in {x.lower() for x in offices}:
                offices.append(office)

    # Fall back to the latest elected-office entry if the summary does not
    # state a current office. Party/appointed-role text is intentionally not
    # used as a substitute for an elected office.
    career = raw.get("career") or []
    years = raw.get("years") or []
    elected = []
    for idx, item in enumerate(career):
        if idx < len(years):
            period = years[idx]
        else:
            period = ""
        if "present" in period.lower() or not elected:
            office = normalize_office(item)
            if office and office.lower() not in {x.lower() for x in elected}:
                elected.append(office)
    if not offices and elected:
        offices.append(elected[0])
    return offices


async def scrape(page, profile_id):
    url = f"{BASE_URL}/wiki/politician/{profile_id}"
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(800)
    raw = await page.evaluate(EXTRACT_JS)
    if raw.get("security"):
        raise RuntimeError(f"profile {profile_id}: Power Play security verification page")
    return raw


async def main(days):
    players = load_json(PLAYERS_FILE, [])
    stored = load_json(OFFICES_FILE, {"profiles": {}})
    stored.setdefault("profiles", {})
    bills = load_json(BILLS_FILE, [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Use last_vote_at already derived from bills. If a player has no vote or
    # their latest vote is older than the threshold, and this is their main
    # profile, their wiki page is eligible for this fallback check.
    targets = []
    for player in players:
        if not player.get("is_main"):
            continue
        last_vote = parse_time(player.get("last_vote_at"))
        if last_vote is None or last_vote < cutoff:
            targets.append(player)

    # De-duplicate by main profile ID and never scrape a page outside this set.
    unique = {}
    for player in targets:
        pid = str(player.get("powerplay_profile_id") or player.get("user_id") or "")
        if pid:
            unique[pid] = player
    targets = list(unique.values())
    print(f"Inactive main profiles to check: {len(targets)} (threshold: {days} days)")

    debug = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "threshold_days": days, "checked": [], "skipped": [], "errors": []}
    stop = asyncio.Event()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        if SCRAPER_TOKEN:
            async def add_token(route, request):
                await route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
            await context.route("**/*", add_token)
            print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
        pool = asyncio.Queue()
        for _ in range(min(CONCURRENCY, max(1, len(targets)))):
            pool.put_nowait(await context.new_page())

        async def one(player):
            if stop.is_set():
                return player, "SKIPPED", None
            pid = str(player.get("powerplay_profile_id") or player.get("user_id"))
            page = await pool.get()
            try:
                raw = await scrape(page, pid)
                offices = extract_offices(raw)
                return player, "OK", {"raw": raw, "offices": offices}
            except RuntimeError as error:
                stop.set()
                return player, "BLOCKED", str(error)
            except Exception as error:
                return player, "ERROR", str(error)
            finally:
                pool.put_nowait(page)

        try:
            results = await asyncio.gather(*(one(player) for player in targets))
        finally:
            await browser.close()

    for player, status, payload in results:
        pid = str(player.get("powerplay_profile_id") or player.get("user_id"))
        if status == "OK":
            raw = payload["raw"]
            offices = payload["offices"]
            stored["profiles"][pid] = {
                "offices": offices,
                "found_by": ["wiki-summary-current-office"] if offices else [],
                "wiki_url": f"{BASE_URL}/wiki/politician/{pid}",
                "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "last_vote_at": player.get("last_vote_at", ""),
            }
            debug["checked"].append({"profile_id": pid, "name": player.get("name", ""), "offices": offices, "summary": raw.get("summary", ""), "career": raw.get("career", [])})
            print(f"{pid}: {player.get('name', '')}: {', '.join(offices) if offices else '(No office)'}")
        elif status == "ERROR":
            debug["errors"].append({"profile_id": pid, "error": payload})
        elif status == "BLOCKED":
            debug["errors"].append({"profile_id": pid, "error": payload})

    stored["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_json(OFFICES_FILE, stored)
    save_json(DEBUG_FILE, debug)

    if stop.is_set():
        print("ERROR: OFFICE CHECK STOPPED — POWER PLAY SECURITY VERIFICATION DETECTED.")
        raise SystemExit(2)
    print(f"Checked: {len(debug['checked'])} | errors: {len(debug['errors'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=5)
    args = parser.parse_args()
    asyncio.run(main(args.days))
