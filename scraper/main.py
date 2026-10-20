import json
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"

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

    page.wait_for_timeout(10000)

    html = page.content()

    print("HTML length:", len(html))

    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="politiciansTable")

    if table is None:
        browser.close()
        raise RuntimeError("Could not find politiciansTable")

    headers = [
        cell.get_text(" ", strip=True)
        for cell in table.find("thead").find_all(["th", "td"])
    ]

    print("Columns found:", headers)

    players = {}

    # Find every player link in the entire page.
    profile_links = soup.find_all(
        "a",
        href=lambda href: href and "/users/" in href
    )

    print("Player profile links found:", len(profile_links))

    for profile_link in profile_links:
        href = profile_link.get("href", "")
        profile_id = href.rstrip("/").split("/")[-1]

        if not profile_id.isdigit():
            continue

        row = profile_link.find_parent("tr")

        if row is None:
            continue

        cells = row.find_all("td")

        if not cells:
            continue

        values = [
            cell.get_text(" ", strip=True)
            for cell in cells
        ]

        if len(values) != len(headers):
            continue

        player = dict(zip(headers, values))

        player["powerplay_profile_id"] = profile_id

        players[profile_id] = player

    browser.close()

print("TOTAL PROFILE LINKS:", len(profile_links))

print("FIRST 10 PROFILE IDS:")
for profile_id in list(players.keys())[:10]:
    print(profile_id)

print("LAST 10 PROFILE IDS:")
for profile_id in list(players.keys())[-10:]:
    print(profile_id)

players_list = list(players.values())

output = Path("players.json")

output.write_text(
    json.dumps(
        players_list,
        indent=2,
        ensure_ascii=False,
    ),
    encoding="utf-8",
)

print()
print(f"FINAL PLAYER COUNT: {len(players_list)}")
print(f"Saved players to {output}")
