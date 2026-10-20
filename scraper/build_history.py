import json
from datetime import date
from pathlib import Path

PLAYERS_FILE = Path("players.json")
BILLS_FILE = Path("bills.json")
INDEX_FILE = Path("player_index.json")          # append-only: never loses anyone
HISTORY_FILE = Path("legislative_history.json")  # derived: rebuilt every run


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


def player_id_for(profile_id, discord):
    # Discord is the identity; fall back to the profile ID if there is none.
    return discord or str(profile_id)


def update_index(index, players, bills, today):
    """Merge current players and bill voters into the index. Never deletes."""

    # 1. Everyone currently listed on the site.
    for player in players:
        pid = str(player["powerplay_profile_id"])
        entry = index.get(pid, {"first_seen": today})
        discord = player.get("discord") or entry.get("discord") or ""
        entry.update(
            {
                "profile_id": pid,
                "player_id": player_id_for(pid, discord),
                "name": player.get("name") or entry.get("name", ""),
                "discord": discord,
                "party": player.get("party") or entry.get("party", ""),
                "state": player.get("state") or entry.get("state", ""),
                "last_seen": today,
                "on_site": True,
            }
        )
        index[pid] = entry

    current_ids = {str(p["powerplay_profile_id"]) for p in players}
    for pid, entry in index.items():
        if pid not in current_ids:
            entry["on_site"] = False

    # 2. Anyone who appears in a bill but is not (or no longer) in players.json.
    for bill in bills:
        people = []
        if bill.get("sponsor"):
            people.append(bill["sponsor"])
        people.extend(bill.get("cosponsors", []))
        for chamber in bill["votes"].values():
            for group in chamber.values():
                people.extend(group)

        for person in people:
            pid = str(person["profile_id"])
            if pid in index:
                continue
            index[pid] = {
                "profile_id": pid,
                "player_id": pid,  # no Discord known for departed players
                "name": person.get("name", ""),
                "discord": "",
                "party": person.get("party") or "",
                "state": person.get("state") or "",
                "first_seen": today,
                "last_seen": None,
                "on_site": False,
            }

    return index


def build_history(index, bills):
    history = {}

    def entry_for(profile_id, bill):
        info = index[str(profile_id)]
        pid = info["player_id"]

        person = history.setdefault(
            pid,
            {
                "player_id": pid,
                "name": info.get("name", ""),
                "discord": info.get("discord", ""),
                "profiles": [],
                "bills": {},
            },
        )
        if str(profile_id) not in person["profiles"]:
            person["profiles"].append(str(profile_id))
        if info.get("on_site"):
            person["name"] = info.get("name", person["name"])

        key = (bill["resolution_id"], str(profile_id))
        if key not in person["bills"]:
            person["bills"][key] = {
                "resolution_id": bill["resolution_id"],
                "number": bill["number"],
                "title": bill["title"],
                "status": bill["status"],
                "finalized": bill["finalized"],
                "introduced": bill["introduced"],
                "passed": bill["passed"],
                "profile_id": str(profile_id),
                "sponsored": False,
                "cosponsored": False,
                "senate_vote": None,
                "house_vote": None,
                "house_seats": None,
            }
        return person["bills"][key]

    for bill in bills:
        if bill.get("sponsor"):
            entry_for(bill["sponsor"]["profile_id"], bill)["sponsored"] = True

        for cosponsor in bill.get("cosponsors", []):
            entry_for(cosponsor["profile_id"], bill)["cosponsored"] = True

        for chamber, groups in bill["votes"].items():
            for vote, voters in groups.items():
                for voter in voters:
                    entry = entry_for(voter["profile_id"], bill)
                    entry[f"{chamber}_vote"] = vote
                    if chamber == "house":
                        entry["house_seats"] = voter.get("seats")

    result = []
    for person in history.values():
        person["bills"] = sorted(
            person["bills"].values(),
            key=lambda b: (b["resolution_id"], b["profile_id"]),
        )
        person["bill_count"] = len(person["bills"])
        result.append(person)

    result.sort(key=lambda p: p["player_id"].lower())
    return result


def main():
    players = load_json(PLAYERS_FILE, [])
    bills = load_json(BILLS_FILE, [])
    index = load_json(INDEX_FILE, {})

    if not isinstance(index, dict):
        index = {}

    index = update_index(index, players, bills, date.today().isoformat())
    history = build_history(index, bills)

    save_json(INDEX_FILE, dict(sorted(index.items(), key=lambda kv: int(kv[0]))))
    save_json(HISTORY_FILE, history)

    departed = sum(1 for e in index.values() if not e.get("on_site"))
    print(f"Profiles indexed: {len(index)} ({departed} no longer on site)")
    print(f"Bills read: {len(bills)}")
    print(f"Players with legislative history: {len(history)}")
    print(f"Saved: {INDEX_FILE}, {HISTORY_FILE}")


if __name__ == "__main__":
    main()
