import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "https://powerplayusa.net"
PLAYERS_FILE = Path("players.json")
VOTES_FILE = Path("votes.json")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def load_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def parse_action(text):
    text = clean_text(text)

    patterns = [
        ("voted_for", r"^Voted for\s+"),
        ("voted_against", r"^Voted against\s+"),
        ("voted_on", r"^Voted on\s+"),
        ("cosponsored", r"^Cosponsored\s+"),
        ("sponsored", r"^Sponsored\s+"),
    ]

    for action, pattern in patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return action

    return "other"


def parse_bill_name(text):
    text = clean_text(text)

    text = re.sub(
        r"^(Voted for|Voted against|Voted on|Cosponsored|Sponsored)\s+",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove explanatory text after a colon.
    if ":" in text:
        text = text.split(":", 1)[0]

    # Remove representation explanations.
    text = re.sub(
        r",?\s+(?:as the state wanted|against what the state wanted)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    # Remove floor/committee wording.
    text = re.sub(
        r"\s+on the floor\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s+in committee\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return clean_text(text)


def parse_number(text):
    text = clean_text(text)

    try:
        return float(text.replace("+", ""))
    except ValueError:
        return None


def scrape_player(page, player):
    profile_id = player.get("powerplay_profile_id") or player.get("user_id")

    if not profile_id:
        return []

    url = f"{BASE_URL}/users/{profile_id}"

    print(f"Scraping votes: {player.get('name', 'Unknown')} ({profile_id})")

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(500)

    # Find the table whose header is:
    # When | Part | What happened | At the time | Now
    tables = page.locator("table")

    records = []

    for table_index in range(tables.count()):
        table = tables.nth(table_index)

        headers = [
            clean_text(table.locator("thead th").nth(i).inner_text())
            for i in range(table.locator("thead th").count())
        ]

        if headers[:5] != [
            "When",
            "Part",
            "What happened",
            "At the time",
            "Now",
        ]:
            continue

        rows = table.locator("tbody tr")

        for row_index in range(rows.count()):
            cells = rows.nth(row_index).locator("td")

            if cells.count() < 5:
                continue

            when = clean_text(cells.nth(0).inner_text())
            part = clean_text(cells.nth(1).inner_text())
            what_happened = clean_text(cells.nth(2).inner_text())
            at_the_time = parse_number(cells.nth(3).inner_text())
            now = parse_number(cells.nth(4).inner_text())

            match = re.match(
                r"^Week\s+(\d+),\s+(\d{4})$",
                when,
            )

            if not match:
                continue

            week = int(match.group(1))
            year = int(match.group(2))

            records.append(
                {
                    "player_id": player.get("discord")
                    or str(profile_id),
                    "powerplay_profile_id": profile_id,
                    "player_name": player.get("name"),
                    "discord": player.get("discord"),
                    "state": player.get("stateName"),
                    "term": "current",
                    "week": week,
                    "year": year,
                    "when": when,
                    "part": part,
                    "action": parse_action(what_happened),
                    "bill_name": parse_bill_name(what_happened),
                    "what_happened": what_happened,
                    "at_the_time": at_the_time,
                    "now": now,
                    "source_url": url,
                }
            )

        # We found the record table. Stop looking at other tables.
        break

    return records


def record_key(record):
    return (
        str(record.get("player_id", "")),
        str(record.get("powerplay_profile_id", "")),
        str(record.get("term", "")),
        str(record.get("year", "")),
        str(record.get("week", "")),
        str(record.get("part", "")),
        str(record.get("what_happened", "")),
    )


def merge_records(existing, new_records):
    records = {}

    for record in existing:
        records[record_key(record)] = record

    for record in new_records:
        records[record_key(record)] = record

    result = list(records.values())

    result.sort(
        key=lambda r: (
            str(r.get("player_id", "")),
            str(r.get("term", "")),
            int(r.get("year", 0)),
            int(r.get("week", 0)),
        ),
        reverse=True,
    )

    return result


def main():
    players = load_json(PLAYERS_FILE, [])

    if not players:
        raise RuntimeError(
            "players.json is empty or missing."
        )

    existing_votes = load_json(VOTES_FILE, [])

    if not isinstance(existing_votes, list):
        existing_votes = []

    new_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    )
)

        try:
            for player in players:
                try:
                    records = scrape_player(page, player)
                    new_records.extend(records)

                    print(
                        f"  Found {len(records)} record entries"
                    )

                except Exception as error:
                    print(
                        f"  ERROR: "
                        f"{player.get('name', 'Unknown')} "
                        f"({player.get('powerplay_profile_id')}): "
                        f"{error}"
                    )

        finally:
            browser.close()

    merged = merge_records(
        existing_votes,
        new_records,
    )

    save_json(VOTES_FILE, merged)

    print()
    print(f"Players checked: {len(players)}")
    print(f"Records scraped: {len(new_records)}")
    print(f"Records stored: {len(merged)}")
    print(f"Saved: {VOTES_FILE}")


if __name__ == "__main__":
    main()
