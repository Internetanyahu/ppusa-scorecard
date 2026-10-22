import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"

SECURITY_RE = re.compile(r"performing security verification|security service to protect against malicious bots", re.I)
OFFICE_KEY_RE = re.compile(r"(?:^|_)(?:office|offices|position|positions|appointment|appointments|governorship|governor|president|vice.?president)(?:$|_)", re.I)
OFFICE_LIST_KEYS = {"offices", "held_offices", "heldOffices", "office_history", "officeHistory", "positions", "position_history", "positionHistory"}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def office_label(value):
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, dict):
        for key in ("office", "name", "title", "label", "position", "role"):
            label = office_label(value.get(key))
            if label:
                return label
    return ""


def collect_office_values(value, key_name="", found=None):
    """Walk arbitrary embedded player data and collect values from office-like keys."""
    found = found if found is not None else []
    key = str(key_name)

    if OFFICE_KEY_RE.search(key) or key in OFFICE_LIST_KEYS:
        if isinstance(value, list):
            for item in value:
                label = office_label(item)
                if label and label not in found:
                    found.append(label)
        else:
            label = office_label(value)
            if label and label not in found:
                found.append(label)

    if isinstance(value, dict):
        for child_key, child_value in value.items():
            collect_office_values(child_value, child_key, found)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                collect_office_values(item, key, found)

    return found


PAGE_EXTRACT_JS = r"""
() => {
  const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim();
  const bodyText = clean(document.body?.innerText || '');
  const security = /performing security verification|security service to protect against malicious bots/i.test(bodyText);

  const elements = [...document.querySelectorAll('a, img, [data-user-id], [data-profile-id], [data-id]')];
  const rows = elements.map(el => {
    const attrs = {};
    for (const attr of el.attributes || []) attrs[attr.name] = attr.value;
    return {
      tag: el.tagName.toLowerCase(),
      text: clean(el.textContent),
      href: el.href || '',
      src: el.src || '',
      attrs,
    };
  });

  const meta = {};
  for (const el of document.querySelectorAll('meta[name], meta[property]')) {
    const key = el.getAttribute('name') || el.getAttribute('property');
    if (key) meta[key] = el.content || '';
  }

  return {
    security,
    title: document.title,
    url: location.href,
    text: bodyText,
    meta,
    rows,
    jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(x => x.textContent || ''),
  };
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        )
    )

    print("Opening Power Play...")
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    print("Page title:", page.title())

    page_data = page.evaluate(PAGE_EXTRACT_JS)
    if page_data.get("security"):
        raise RuntimeError(
            "PLAYER SCRAPER STOPPED: Power Play returned a security verification page; "
            f"text={page_data.get('text', '')[:500]!r}"
        )

    politicians = page.evaluate("() => window.politiciansData")
    browser.close()

if not politicians:
    raise RuntimeError("Could not find window.politiciansData")

print(f"Players found: {len(politicians)}")

players = []
for politician in politicians:
    profile_id = str(politician.get("user_id", ""))
    offices = collect_office_values(politician)

    # Preserve the complete embedded player object rather than throwing away
    # fields that the page adds later. This makes the scraper future-proof and
    # gives the scorecard access to every field supplied by the roster page.
    player = dict(politician)
    player.update({
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
    })
    players.append(player)

output = Path("players.json")
output.write_text(json.dumps(players, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

print(f"FINAL PLAYER COUNT: {len(players)}")
print(f"PLAYERS WITH OFFICE DATA: {sum(bool(p['offices']) for p in players)}")
print(f"PLAYERS WITH NO OFFICE: {sum(not p['offices'] for p in players)}")
print(f"TOTAL OFFICES RECORDED: {sum(len(p['offices']) for p in players)}")
print(f"Saved players to {output}")