"""Add normalized office metadata to compiled scorecard player profiles."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYERS_FILE = ROOT / "players.json"
SCORECARD_FILE = ROOT / "conservative_scorecard.json"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_offices(value):
    if isinstance(value, list):
        values = value
    elif value:
        values = [value]
    else:
        values = []

    result = []
    for item in values:
        if isinstance(item, dict):
            item = (
                item.get("office")
                or item.get("name")
                or item.get("title")
                or item.get("label")
                or item.get("position")
                or ""
            )
        item = str(item).strip()
        if item and item not in result:
            result.append(item)
    return result


players = load(PLAYERS_FILE)
scorecard = load(SCORECARD_FILE)

by_profile_id = {
    str(player.get("powerplay_profile_id")): player
    for player in players
    if player.get("powerplay_profile_id") is not None
}

updated_profiles = 0
updated_players = 0

for player in scorecard.get("players", []):
    profile_rows = player.get("profiles", [])
    total_offices = 0

    for profile in profile_rows:
        source = by_profile_id.get(str(profile.get("profile_id")), {})
        offices = normalize_offices(source.get("offices"))

        # A singular office field is retained as a fallback for older/source
        # records that do not expose an office list.
        if not offices:
            offices = normalize_offices(source.get("office"))

        profile["offices"] = offices
        profile["office"] = offices[0] if offices else ""
        profile["office_count"] = len(offices)
        updated_profiles += 1
        total_offices += len(offices)

    player["offices_held"] = total_offices
    player["office_count"] = total_offices
    player["has_office"] = total_offices > 0
    updated_players += 1

scorecard["office_metadata"] = {
    "definition": "Count of normalized offices attached to each Power Play profile; POTUS, Vice President, Governor, legislative and other offices are all counted when supplied by the source.",
    "no_office_label": "No office",
    "updated_profiles": updated_profiles,
    "updated_players": updated_players,
}

SCORECARD_FILE.write_text(
    json.dumps(scorecard, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

print(f"Office metadata updated for {updated_players} players and {updated_profiles} profiles.")