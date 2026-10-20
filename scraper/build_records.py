import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PLAYERS_FILE = Path("players.json")
INDEX_FILE = Path("player_index.json")
HISTORY_FILE = Path("legislative_history.json")
BILLS_FILE = Path("bills.json")
OUT_FILE = Path("voting_records.json")


def load_json(path, default):
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path, data):
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    tmp.replace(path)


def summarize(bill_rows):
    counts = {
        "bills": len(bill_rows),
        "sponsored": 0,
        "cosponsored": 0,
        "senate": {"aye": 0, "nay": 0, "present": 0},
        "house": {"aye": 0, "nay": 0, "present": 0},
    }

    for row in bill_rows:
        if row.get("sponsored"):
            counts["sponsored"] += 1
        if row.get("cosponsored"):
            counts["cosponsored"] += 1
        for chamber in ("senate", "house"):
            vote = row.get(f"{chamber}_vote")
            if vote in counts[chamber]:
                counts[chamber][vote] += 1

    return counts


def label_for(discord, name):
    if discord and name:
        return f"{discord} ({name})"
    return discord or name or "Unknown"


def main():
    index = load_json(INDEX_FILE, {})
    history = load_json(HISTORY_FILE, [])
    bills = load_json(BILLS_FILE, [])
    players = load_json(PLAYERS_FILE, [])

    if not index:
        raise RuntimeError("player_index.json is missing; run build_history.py first.")

    is_main = {
        str(p["powerplay_profile_id"]): bool(p.get("is_main")) for p in players
    }

    # One lookup for bill details + provisions; vote rows point at it by ID.
    bill_lookup = {}
    for bill in bills:
        bill_lookup[str(bill["resolution_id"])] = {
            "resolution_id": bill["resolution_id"],
            "number": bill.get("number", ""),
            "title": bill.get("title", ""),
            "status": bill.get("status", ""),
            "finalized": bill.get("finalized", False),
            "type": bill.get("type", ""),
            "to_pass": bill.get("to_pass", ""),
            "committee": bill.get("committee", ""),
            "introduced": bill.get("introduced", ""),
            "passed": bill.get("passed", ""),
            "sponsor_profile_id": (bill.get("sponsor") or {}).get("profile_id"),
            "provisions": bill.get("provisions", []),
        }

    bill_rows_by_profile = defaultdict(list)
    for person in history:
        for row in person["bills"]:
            bill_rows_by_profile[str(row["profile_id"])].append(row)

    # ---- profile records ------------------------------------------------
    profiles = []
    profile_ids_by_player = defaultdict(list)

    for profile_id, info in index.items():
        bill_rows = sorted(
            bill_rows_by_profile.get(profile_id, []),
            key=lambda r: r["resolution_id"],
        )

        player_id = info["player_id"]
        profile_ids_by_player[player_id].append(profile_id)

        profiles.append(
            {
                "profile_id": profile_id,
                "player_id": player_id,
                "name": info.get("name", ""),
                "discord": info.get("discord", ""),
                "discord_id": info.get("discord_id", ""),
                "discord_history": info.get("discord_history", []),
                "party": info.get("party", ""),
                "state": info.get("state", ""),
                "is_main": is_main.get(profile_id, False),
                "on_site": info.get("on_site", False),
                "counts": summarize(bill_rows),
                "bill_votes": bill_rows,
            }
        )

    profiles.sort(key=lambda p: int(p["profile_id"]))
    profile_by_id = {p["profile_id"]: p for p in profiles}

    # ---- player records (all of a player's profiles combined) ------------
    player_records = []

    for player_id, profile_ids in profile_ids_by_player.items():
        members = [profile_by_id[pid] for pid in sorted(profile_ids, key=int)]
        main = next((m for m in members if m["is_main"]), members[0])

        bill_rows = sorted(
            (row for m in members for row in m["bill_votes"]),
            key=lambda r: (r["resolution_id"], r["profile_id"]),
        )

        aliases = []
        discord_ids = []
        for m in members:
            for h in m["discord_history"]:
                if h.get("discord") and h["discord"] not in aliases:
                    aliases.append(h["discord"])
                if h.get("discord_id") and h["discord_id"] not in discord_ids:
                    discord_ids.append(h["discord_id"])

        # Current Discord if anyone has one, else the last one ever used.
        current = next(
            (m["discord"] for m in [main] + members if m["discord"]), ""
        )
        display_discord = current or (aliases[-1] if aliases else "")

        player_records.append(
            {
                "player_id": player_id,
                "discord": display_discord,
                "discord_current": bool(current),
                "discord_aliases": aliases,
                "discord_ids": discord_ids,
                "name": main["name"],
                "profile_ids": [m["profile_id"] for m in members],
                "profiles": [
                    {
                        "profile_id": m["profile_id"],
                        "name": m["name"],
                        "party": m["party"],
                        "state": m["state"],
                        "is_main": m["is_main"],
                        "on_site": m["on_site"],
                    }
                    for m in members
                ],
                "counts": summarize(bill_rows),
                "bill_votes": bill_rows,
            }
        )

    player_records.sort(key=lambda p: label_for(p["discord"], p["name"]).lower())

    # ---- "Filter by Player (Discord) / Profile" options ------------------
    filter_options = []

    for player in player_records:
        filter_options.append(
            {
                "type": "player",
                "id": player["player_id"],
                "label": label_for(player["discord"], player["name"]),
                "aliases": player["discord_aliases"],
                "profile_ids": player["profile_ids"],
            }
        )

    for profile in profiles:
        filter_options.append(
            {
                "type": "profile",
                "id": profile["profile_id"],
                "label": f"{profile['name'] or 'Unknown'} ({profile['profile_id']})",
                "player_id": profile["player_id"],
            }
        )

    filter_options.sort(key=lambda o: (o["type"], o["label"].lower()))

    save_json(
        OUT_FILE,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "filter_options": filter_options,
            "bills": bill_lookup,
            "players": player_records,
            "profiles": profiles,
        },
    )

    print(f"Players: {len(player_records)}")
    print(f"Profiles: {len(profiles)}")
    print(f"Bills: {len(bill_lookup)}")
    print(f"Filter options: {len(filter_options)}")
    print(f"Saved: {OUT_FILE}")


if __name__ == "__main__":
    main()
