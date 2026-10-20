import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "https://powerplayusa.net"
PLAYERS_FILE = Path("players.json")
VOTES_FILE = Path("votes.json")


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


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_action_and_bill(text):
    """
    Convert Power Play's 'What happened' text into a rough structured form.

    Examples:
      Voted for Tax Cuts Act, as the state wanted
      Voted against Medicare for All: it improves the healthcare affordability index
      Voted on Tax Cuts Act on the floor
      Cosponsored Some Bill: it improves public trust
      Sponsored Some Bill: it improves small business formation
    """

    original = clean_text(text)

    patterns = [
        ("voted_for", r"^Voted for\s+(.+)$"),
        ("voted_against", r"^Voted against\s+(.+)$"),
        ("voted_on", r"^Voted on\s+(.+)$"),
        ("cosponsored", r"^Cosponsored\s+(.+)$"),
        ("sponsored", r"^Sponsored\s+(.+)$"),
    ]

    action = "other"
    remainder = original

    for candidate_action, pattern in patterns:
        match = re.match(pattern, original, re.IGNORECASE)
        if match:
            action = candidate_action
            remainder = clean_text(match.group(1))
            break

    # Remove Power Play's explanatory suffix from the bill name.
    bill_name = remainder
    context = ""

    if ":" in remainder:
        bill_name, context = remainder.split(":", 1)
        bill_name = clean_text(bill_name)
        context = clean_text(context)

    # Remove common trailing state/representation explanations
    # from the bill name while preserving the original text separately.
    bill_name = re.sub(
        r",?\s+(?:as the state wanted|against what the state wanted)\s*$",
        "",
        bill_name,
        flags=re.IGNORECASE,
    ).strip()

    # Remove common floor/committee suffixes.
    bill_name = re.sub(
        r"\s+on the floor\s*$",
        "",
        bill_name,
        flags=re.IGNORECASE,
    ).strip()

    bill_name = re.sub(
        r"\s+in committee\s*$",
        "",
        bill_name,
        flags=re.IGNORECASE,
    ).strip()

    return {
        "action": action,
        "bill_name": bill_name,
        "context": context,
    }


def get_players(page):
    page.goto(
        f"{BASE_URL}/national/politicians",
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_function(
        "() => Array.isArray(window.politiciansData)",
        timeout=30000,
    )

    players = page.evaluate("() => window.politiciansData")

    if not players:
        raise RuntimeError("No players were found on the politicians page.")

    return players


def scrape_player(page, player):
    profile_id = player.get("user_id")

    if not profile_id:
        return []

    url = f"{BASE_URL}/users/{profile_id}"

    print(f"Scraping {player.get('name', 'Unknown')} ({profile_id})")

    page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    # The record table is server-rendered HTML, so give it a short
    # opportunity to appear before parsing it.
    page.wait_for_timeout(500)

    rows = page.locator("table tbody tr")

    records = []

    for i in range(rows.count()):
        row = rows.nth(i)
        cells = row.locator("td")

        if cells.count() < 5:
            continue

        when = clean_text(cells.nth(0).inner_text())
        part = clean_text(cells.nth(1).inner_text())
        what_happened = clean_text(cells.nth(2).inner_text())
        at_the_time_text = clean_text(cells.nth(3).inner_text())
        now_text = clean_text(cells.nth(4).inner_text())

        # Only process the record table. Other tables on the profile
        # can also contain tbody/tr elements.
        if not re.match(r"^Week\s+\d+,\s+\d{4}$", when):
            continue

        year_match = re.search(r"(\d{4})$", when)
        week_match = re.search(r"Week\s+(\d+)", when)

        if not year_match or not week_match:
            continue

        year = int(year_match.group(1))
        week = int(week_match.group(1))

        parsed = parse_action_and_bill(what_happened)

        try:
            at_the_time = float(at_the_time_text.replace("+", ""))
        except ValueError:
            at_the_time = None

        try:
            now = float(now_text.replace("+", ""))
        except ValueError:
            now = None

        record = {
            "player_id": player.get("discord") or str(profile_id),
            "powerplay_profile_id": profile_id,
            "player_name": player.get("name"),
            "discord": player.get("discord"),
            "state": player.get("stateName"),
            "term": "current",
            "week": week,
            "year": year,
            "when": when,
            "part": part,
            "action": parsed["action"],
            "bill_name": parsed["bill_name"],
            "context": parsed["context"],
            "what_happened": what_happened,
            "at_the_time": at_the_time,
            "now": now,
            "source_url": url,
        }

        records.append(record)

    return records


def record_key(record):
    """
    Stable identity for a record.

    The raw text is included because several Power Play entries can occur
    in the same week for the same bill but represent different events.
    """

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
    """
    Add new records without deleting historical terms.

    If Power Play later exposes multiple terms, records from older terms
    remain in votes.json.
    """

    merged = {}

    for record in existing:
        merged[record_key(record)] = record

    for record in new_records:
        key = record_key(record)

        # Current scrape wins if the same record changed.
        merged[key] = record

    records = list(merged.values())

    records.sort(
        key=lambda r: (
            str(r.get("player_id", "")),
            str(r.get("term", "")),
            int(r.get("year", 0)),
            int(r.get("week", 0)),
            str(r.get("part", "")),
            str(r.get("what_happened", "")),
        ),
        reverse=True,
    )

    return records


def main():
    players = load_json(PLAYERS_FILE, [])

    if not players:
        raise RuntimeError(
            "players.json is empty or missing. Run the player scraper first."
        )

    existing_votes = load_json(VOTES_FILE, [])

    # Make sure old formats don't break the scraper.
    if not isinstance(existing_votes, list):
        existing_votes = []

    all_new_records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True
        )

        page = browser.new_page()

        try:
            for player in players:
                try:
                    records = scrape_player(page, player)
                    all_new_records.extend(records)

                    print(
                        f"  Found {len(records)} record entries"
                    )

                except Exception as e:
                    print(
                        f"  ERROR scraping "
                        f"{player.get('name', 'Unknown')} "
                        f"({player.get('user_id')}): {e}"
                    )

        finally:
            browser.close()

    merged = merge_records(existing_votes, all_new_records)

    save_json(VOTES_FILE, merged)

    print()
    print(f"Players checked: {len(players)}")
    print(f"New/current records scraped: {len(all_new_records)}")
    print(f"Total records stored: {len(merged)}")
    print(f"Saved to: {VOTES_FILE}")


if __name__ == "__main__":
    main()
