import json
from pathlib import Path

import requests
from bs4 import BeautifulSoup

URL = "https://powerplayusa.net/national/politicians"

response = requests.get(
    URL,
    headers={"User-Agent": "Mozilla/5.0"},
    timeout=30,
)
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
