import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://powerplayusa.net/national/politicians"

response = requests.get(
    URL,
    headers={
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/154.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    },
    timeout=30,
)

print("HTTP status:", response.status_code)
print("Content type:", response.headers.get("content-type"))
print("First 500 characters:")
print(response.text[:500])

response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

table = soup.find("table", id="politiciansTable")

if table is None:
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

    profile_link = row.find("a", href=lambda href: href and "/users/" in href)

    if profile_link:
        href = profile_link.get("href", "")
        player["powerplay_profile_id"] = href.rstrip("/").split("/")[-1]

    players.append(player)

output = Path("players.json")

output.write_text(
    json.dumps(players, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print(f"Saved {len(players)} players to {output}")
