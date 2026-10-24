import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"
BASE_URL = "https://powerplayusa.net"
SOURCE_ENV = "PPUSA_POLITICIANS_SOURCE"
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()

SECURITY_RE = re.compile(r"performing security verification|security service to protect against malicious bots", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def party_label(value):
    value = clean(value)
    return "Independent" if value.lower() == "ind" else value


def parse_iso(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return datetime.min.replace(tzinfo=timezone.utc)


def voter_office(voter, chamber):
    chamber = clean(chamber).lower()
    if chamber == "senate":
        return "Senate"
    if chamber == "house":
        return "House"
    role = clean(voter.get("role"))
    return role if role else ""


def latest_bill_vote(profile_id, bills):
    best = None
    pid = str(profile_id)
    for bill in bills:
        for chamber, groups in (bill.get("votes") or {}).items():
            for vote, voters in (groups or {}).items():
                for voter in voters or []:
                    if str(voter.get("profile_id")) != pid:
                        continue
                    candidate = {
                        "office": voter_office(voter, chamber),
                        "chamber": clean(chamber).title(),
                        "vote": vote,
                        "resolution_id": bill.get("resolution_id"),
                        "bill_number": bill.get("number", ""),
                        "bill_title": bill.get("title", ""),
                        "voted_at": bill.get("scraped_at", ""),
                    }
                    if best is None or (parse_iso(candidate["voted_at"]), int(candidate["resolution_id"] or 0)) > (parse_iso(best["voted_at"]), int(best["resolution_id"] or 0)):
                        best = candidate
    return best


def fallback_office(profile_id, office_records):
    record = office_records.get(str(profile_id)) or {}
    return [clean(x) for x in (record.get("offices") or []) if clean(x)]


def parse_source_html(source):
    if SECURITY_RE.search(source):
        raise RuntimeError("PLAYER SCRAPER STOPPED: saved source is a Power Play security verification page")
    match = re.search(r"window\.politiciansData\s*=\s*(\[.*?\])\s*;</script>", source, re.S)
    if not match:
        raise RuntimeError("Could not find window.politiciansData in saved Power Play source")
    politicians = json.loads(match.group(1))
    title_match = re.search(r"<title>(.*?)</title>", source, re.I | re.S)
    title = clean(re.sub(r"<[^>]+>", " ", title_match.group(1))) if title_match else ""
    meta = {}
    for key, value in re.findall(r'<meta\s+(?:name|property)=["\']([^"\']+)["\'][^>]*content=["\']([^"\']*)["\']', source, re.I):
        meta[key] = value
    return politicians, title, meta, source


def load_page_data(page):
    return page.evaluate(r"""
() => {
  const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const bodyText = clean(document.body?.innerText || '');
  const security = /performing security verification|security service to protect against malicious bots/i.test(bodyText);
  const meta = {};
  for (const el of document.querySelectorAll('meta[name], meta[property]')) {
    const key = el.getAttribute('name') || el.getAttribute('property');
    if (key) meta[key] = el.content || '';
  }
  const table = document.querySelector('#politiciansTable');
  const tableHeaders = table ? [...table.querySelectorAll('thead th')].map(x => clean(x.textContent)) : [];
  const tableRows = table ? [...table.querySelectorAll('tbody tr')].map(tr => ({
    text: clean(tr.innerText),
    cells: [...tr.querySelectorAll('td')].map(td => clean(td.innerText)),
    ids: [...tr.querySelectorAll('[data-user-id], [data-profile-id], [data-id]')]
      .flatMap(el => [el.getAttribute('data-user-id'), el.getAttribute('data-profile-id'), el.getAttribute('data-id')])
      .filter(Boolean),
    hrefs: [...tr.querySelectorAll('a[href]')].map(a => a.href),
  })) : [];
  return { security, title: document.title, url: location.href, text: bodyText, meta, tableHeaders, tableRows };
}
""")


def scrape_live():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        ))
        if SCRAPER_TOKEN:
            def add_token(route, request):
                route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
            context.route("**/*", add_token)
            print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
        page = context.new_page()
        print("Opening Power Play...")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        page_data = load_page_data(page)
        print("Page title:", page_data.get("title", ""))
        if page_data.get("security"):
            browser.close()
            raise RuntimeError(
                "PLAYER SCRAPER STOPPED: Power Play returned a security verification page; "
                f"text={page_data.get('text', '')[:500]!r}"
            )
        politicians = page.evaluate("() => window.politiciansData")
        browser.close()
    if not politicians:
        raise RuntimeError("Could not find window.politiciansData")
    return politicians, page_data


def build_player(politician, page_data, latest_vote, fallback_offices):
    profile_id = str(politician.get("user_id", ""))
    party = party_label(politician.get("partyAbbreviation2", politician.get("party", "")))
    offices = [latest_vote["office"]] if latest_vote and latest_vote.get("office") else fallback_offices
    return {
        **politician,
        "powerplay_profile_id": profile_id,
        "name": politician.get("name", ""),
        "discord": politician.get("discord_user", "") or "",
        "party": party,
        "state": politician.get("stateName", politician.get("state", "")),
        "caucus": politician.get("caucus", 0),
        "caucus_url": politician.get("caucusUrl", "") or "",
        "offices": offices,
        "office": offices[0] if offices else "",
        "office_count": len(offices),
        "has_office": bool(offices),
        "last_vote_at": latest_vote.get("voted_at", "") if latest_vote else "",
        "last_vote_resolution_id": latest_vote.get("resolution_id") if latest_vote else None,
        "last_vote_bill": latest_vote.get("bill_number", "") if latest_vote else "",
        "last_vote_title": latest_vote.get("bill_title", "") if latest_vote else "",
        "last_vote_chamber": latest_vote.get("chamber", "") if latest_vote else "",
        "source_page": URL,
        "source_page_title": page_data.get("title", ""),
        "page_metadata": page_data.get("meta", {}),
        "page_elements": [],
    }


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", default=None, help="Use a saved Power Play HTML source instead of the live site")
    parser.add_argument("--skip-profile-pages", action="store_true", help="Deprecated compatibility flag; profile pages are never scraped")
    args = parser.parse_args()

    source_file = args.source_file or os.environ.get(SOURCE_ENV, "")
    if source_file:
        source = Path(source_file).read_text(encoding="utf-8")
        politicians, title, meta, raw_source = parse_source_html(source)
        page_data = {"title": title, "meta": meta, "table_headers": [], "table_rows": [], "text": clean(raw_source)}
        print(f"Using saved Power Play source: {source_file}")
    else:
        politicians, page_data = scrape_live()

    bills = load_json(Path("bills.json"), [])
    office_records = load_json(Path("offices.json"), {}).get("profiles", {})
    print(f"Players found: {len(politicians)}")
    print(f"Bills available for office derivation: {len(bills)}")
    print(f"Fallback office records on file: {len(office_records)}")

    players = []
    for politician in politicians:
        pid = str(politician.get("user_id", ""))
        latest_vote = latest_bill_vote(pid, bills)
        fallback = fallback_office(pid, office_records)
        players.append(build_player(politician, page_data, latest_vote, fallback))

    output = Path("players.json")
    output.write_text(json.dumps(players, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"FINAL PLAYER COUNT: {len(players)}")
    print(f"PLAYERS WITH OFFICE DATA: {sum(bool(p['offices']) for p in players)}")
    print(f"PLAYERS WITH NO OFFICE: {sum(not p['offices'] for p in players)}")
    print(f"TOTAL OFFICES RECORDED: {sum(len(p['offices']) for p in players)}")
    print(f"Saved players to {output}")


if __name__ == "__main__":
    main()
