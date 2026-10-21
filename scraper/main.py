import json
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"

# Power Play's embedded politician objects have changed shape over time. Keep
# the office extraction deliberately tolerant so executive offices (including
# President, Vice President, and Governor) are captured without assuming one
# exact source key.
OFFICE_KEYS = (
    "office",
    "office_name",
    "officeName",
    "office_title",
    "officeTitle",
    "position",
    "position_name",
    "positionName",
    "current_office",
    "currentOffice",
    "current_position",
    "currentPosition",
    "title",
)
OFFICE_LIST_KEYS = (
    "offices",
    "held_offices",
    "heldOffices",
    "office_history",
    "officeHistory",
)


def office_label(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("office", "name", "title", "label", "position", "role"):
            label = office_label(value.get(key))
            if label:
                return label
    return ""


def extract_offices(politician):
    offices = []

    for key in OFFICE_LIST_KEYS:
        value = politician.get(key)
        if isinstance(value, list):
            for item in value:
                label = office_label(item)
                if label and label not in offices:
                    offices.append(label)

    for key in OFFICE_KEYS:
        label = office_label(politician.get(key))
        if label and label not in offices:
            offices.append(label)

    return offices


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

    page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(5000)

    print("Page title:", page.title())

    # Read the complete dataset embedded in the page.
    politicians = page.evaluate(
        "() => window.politiciansData"
    )

    browser.close()

if not politicians:
    raise RuntimeError(
        "Could not find window.politiciansData"
    )

print(f"Players found: {len(politicians)}")

players = []

for politician in politicians:
    offices = extract_offices(politician)

    player = {
        "powerplay_profile_id": str(politician["user_id"]),
        "name": politician.get("name", ""),
        "party": politician.get("partyAbbreviation2", ""),
        "caucus": politician.get("caucus", 0),
        "state": politician.get("stateName", ""),
        "money": politician.get("money", 0),
        "liquid_capital": politician.get("liquid_capital", 0),
        "stamina": politician.get("stamina", 0),
        "legacy_points": politician.get("legacy_points", 0),
        "created_at": politician.get("createdAt", ""),
        "has_discord": politician.get("has_discord", 0),
        "discord": politician.get("discord_user", ""),
        "discord_avatar": politician.get("discord_avatar", ""),
        "is_main": politician.get("is_main", 0),
        "union_role": politician.get("union_role", ""),
        "offices": offices,
        "office": offices[0] if offices else "",
    }

    players.append(player)

output = Path("players.json")

output.write_text(
    json.dumps(
        players,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

print(f"FINAL PLAYER COUNT: {len(players)}")
print(f"PLAYERS WITH OFFICE DATA: {sum(bool(p['offices']) for p in players)}")
print(f"Saved players to {output}")