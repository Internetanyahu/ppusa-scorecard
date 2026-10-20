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

    response = page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    print("HTTP status:", response.status if response else "unknown")
    print("Page title:", page.title())

    page.wait_for_timeout(10000)

    html = page.content()

    print("HTML length:", len(html))

    if "Just a moment" in html:
        browser.close()
        raise RuntimeError(
            "Cloudflare challenge was not passed."
        )

    soup = BeautifulSoup(html, "html.parser")

    table = soup.find("table", id="politiciansTable")

    if table is None:
        browser.close()
        raise RuntimeError("Could not find politiciansTable")

    headers = [
        cell.get_text(" ", strip=True)
        for cell in table.find("thead").find_all(["th", "td"])
    ]

    players = []

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

        if profile_link:
            href = profile_link.get("href", "")
            player["powerplay_profile_id"] = (
                href.rstrip("/").split("/")[-1]
            )

        players.append(player)

    browser.close()

output = Path("players.json")

output.write_text(
    json.dumps(players, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print(f"Saved {len(players)} players to {output}")
