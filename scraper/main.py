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
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(10000)

    players = {}

    def collect_players():
        soup = BeautifulSoup(page.content(), "html.parser")

        table = soup.find("table", id="politiciansTable")

        if table is None:
            raise RuntimeError("Could not find politiciansTable")

        headers = [
            cell.get_text(" ", strip=True)
            for cell in table.find("thead").find_all(["th", "td"])
        ]

        before = len(players)

        for row in table.find("tbody").find_all("tr"):
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

            profile_link = row.find(
                "a",
                href=lambda href: href and "/users/" in href
            )

            if not profile_link:
                continue

            href = profile_link.get("href", "")
            profile_id = href.rstrip("/").split("/")[-1]

            player["powerplay_profile_id"] = profile_id

            players[profile_id] = player

        added = len(players) - before

        print(
            f"Collected {added} new players. "
            f"Total: {len(players)}"
        )


    # Collect page 1.
    collect_players()

    # Find pagination buttons.
    pagination = page.locator(
        "#politiciansTable_paginate"
    )

    if pagination.count() == 0:
        browser.close()
        raise RuntimeError(
            "Could not find politicians pagination controls"
        )

    # Click numbered pages one at a time.
    page_number = 2

    while True:
        button = page.locator(
            f"#politiciansTable_paginate "
            f"span a:has-text('{page_number}')"
        )

        if button.count() == 0:
            break

        if not button.is_visible():
            break

        print(f"Opening page {page_number}...")

        button.click()

        page.wait_for_timeout(1000)

        collect_players()

        page_number += 1

    browser.close()


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
