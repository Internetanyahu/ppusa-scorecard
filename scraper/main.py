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

    print("Page title:", page.title())

    players = {}

    while True:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table", id="politiciansTable")

        if table is None:
            browser.close()
            raise RuntimeError("Could not find politiciansTable")

        headers = [
            cell.get_text(" ", strip=True)
            for cell in table.find("thead").find_all(["th", "td"])
        ]

        rows_found = 0

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
            rows_found += 1

        print(f"Collected {rows_found} players on current page")
        print(f"Total unique players: {len(players)}")

        next_button = page.locator(
            "#politiciansTable_next"
        )

        if not next_button.count():
            break

        classes = next_button.get_attribute("class") or ""

        if "disabled" in classes:
            break

        next_button.click()

        page.wait_for_timeout(1000)

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

print(f"FINAL PLAYER COUNT: {len(players_list)}")
print(f"Saved players to {output}")
