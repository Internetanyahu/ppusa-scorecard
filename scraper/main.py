import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"
SOURCE_ENV = "PPUSA_POLITICIANS_SOURCE"

# The national Politicians page is the authoritative roster source.
# Individual politician pages are never scraped by this workflow.
OFFICE_KEY_RE = re.compile(
    r"(?:^|_)(?:office|offices|position|positions|appointment|appointments|"
    r"governorship|governor|president|vice.?president|senator|representative|"
    r"cabinet|secretary|mayor|judge|justice|attorney.?general)(?:$|_)", re.I,
)
OFFICE_LIST_KEYS = {
    "offices", "held_offices", "heldOffices", "office_history", "officeHistory",
    "positions", "position_history", "positionHistory", "officeHistoryEntries",
}
OFFICE_TEXT_RE = re.compile(
    r"\b(?:President|Vice President|Governor|Lieutenant Governor|U\.S\. Senator|"
    r"Senator|U\.S\. Representative|Representative|Congressman|Congresswoman|"
    r"Cabinet Secretary|Secretary of State|Attorney General|Mayor|Chief Justice|"
    r"Justice|Judge)\b(?:[^\n|;,]{0,100})", re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def office_label(value, key_name=""):
    if isinstance(value, str):
        value = clean(value)
        return value if value else ""
    if value is True and OFFICE_KEY_RE.search(str(key_name)):
        return re.sub(r"[_-]+", " ", str(key_name)).strip().title()
    if isinstance(value, dict):
        for key in ("office", "name", "title", "label", "position", "role"):
            label = office_label(value.get(key), key)
            if label:
                return label
    return ""


def collect_office_values(value, key_name="", found=None):
    """Collect office values exposed in the national page's player data."""
    found = found if found is not None else []
    key = str(key_name)
    if OFFICE_KEY_RE.search(key) or key in OFFICE_LIST_KEYS:
        values = value if isinstance(value, list) else [value]
        for item in values:
            label = office_label(item, key)
            if label and label.lower() not in {x.lower() for x in found}:
                found.append(label)
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            collect_office_values(child_value, child_key, found)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                collect_office_values(item, key, found)
    return found


def extract_offices_from_page_rows(politician, page_data):
    """Extract office labels from the rendered national roster rows only."""
    profile_id = str(politician.get("user_id", ""))
    if not profile_id:
        return []
    labels = []
    for row in page_data.get("rows", []):
        attrs = row.get("attrs", {}) or {}
        identifiers = {
            str(attrs.get("data-user-id", "")),
            str(attrs.get("data-profile-id", "")),
            str(attrs.get("data-id", "")),
        }
        href = str(row.get("href", ""))
        if profile_id not in identifiers and f"/users/{profile_id}" not in href and f"/wiki/politician/{profile_id}" not in href:
            continue
        for match in OFFICE_TEXT_RE.findall(clean(row.get("text", ""))):
            label = clean(match).strip(" .:|-—")
            if label and label.lower() not in {x.lower() for x in labels}:
                labels.append(label)
    return labels


def parse_source_html(source):
    """Parse a saved Power Play politicians HTML source for CI tests."""
    if re.search(r"performing security verification|security service to protect against malicious bots", source, re.I):
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
  const elements = [...document.querySelectorAll('a, img, [data-user-id], [data-profile-id], [data-id]')];
  const rows = elements.map(el => {
    const attrs = {};
    for (const attr of el.attributes || []) attrs[attr.name] = attr.value;
    return { tag: el.tagName.toLowerCase(), text: clean(el.textContent), href: el.href || '', src: el.src || '', attrs };
  });
  const meta = {};
  for (const el of document.querySelectorAll('meta[name], meta[property]')) {
    const key = el.getAttribute('name') || el.getAttribute('property');
    if (key) meta[key] = el.content || '';
  }
  return { security, title: document.title, url: location.href, text: bodyText, meta, rows };
}
""")


def scrape_live():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
        ))
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


def build_player(politician, page_data, offices):
    profile_id = str(politician.get("user_id", ""))
    return {
        **politician,
        "powerplay_profile_id": profile_id,
        "name": politician.get("name", ""),
        "party": politician.get("partyAbbreviation2", politician.get("party", "")),
        "state": politician.get("stateName", politician.get("state", "")),
        "offices": offices,
        "office": offices[0] if offices else "",
        "office_count": len(offices),
        "has_office": bool(offices),
        "source_page": URL,
        "source_page_title": page_data.get("title", ""),
        "page_metadata": page_data.get("meta", {}),
        "page_elements": [],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", default=None, help="Use a saved Power Play HTML source instead of the live site")
    parser.add_argument("--skip-profile-pages", action="store_true", help="Deprecated compatibility flag; profile pages are never scraped")
    args = parser.parse_args()

    source_file = args.source_file or __import__("os").environ.get(SOURCE_ENV, "")
    if source_file:
        source = Path(source_file).read_text(encoding="utf-8")
        politicians, title, meta, raw_source = parse_source_html(source)
        page_data = {"title": title, "meta": meta, "rows": [], "text": clean(raw_source)}
        print(f"Using saved Power Play source: {source_file}")
    else:
        politicians, page_data = scrape_live()

    print(f"Players found: {len(politicians)}")
    players = []
    for politician in politicians:
        offices = collect_office_values(politician)
        for label in extract_offices_from_page_rows(politician, page_data):
            if label.lower() not in {x.lower() for x in offices}:
                offices.append(label)
        players.append(build_player(politician, page_data, offices))

    output = Path("players.json")
    output.write_text(json.dumps(players, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"FINAL PLAYER COUNT: {len(players)}")
    print(f"PLAYERS WITH OFFICE DATA: {sum(bool(p['offices']) for p in players)}")
    print(f"PLAYERS WITH NO OFFICE: {sum(not p['offices'] for p in players)}")
    print(f"TOTAL OFFICES RECORDED: {sum(len(p['offices']) for p in players)}")
    print(f"Saved players to {output}")


if __name__ == "__main__":
    main()
