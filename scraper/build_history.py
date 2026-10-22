import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

PLAYERS_FILE = Path("players.json")
BILLS_FILE = Path("bills.json")
INDEX_FILE = Path("player_index.json")
HISTORY_FILE = Path("legislative_history.json")
OVERRIDES_FILE = Path("identity_overrides.json")
REVIEW_FILE = Path("identity_review.json")

AVATAR_ID_RE = re.compile(r"/avatars/(\d+)/")


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


def discord_id_of(player):
    match = AVATAR_ID_RE.search(player.get("discord_avatar") or "")
    return match.group(1) if match else ""


def migrate(index):
    legacy = [e for e in index.values() if "discord_history" not in e]
    groups = defaultdict(list)
    for entry in legacy:
        groups[entry["player_id"]].append(int(entry["profile_id"]))
    for entry in legacy:
        entry["player_id"] = "p" + str(min(groups[entry["player_id"]]))
        discord = entry.get("discord", "")
        entry["discord_id"] = ""
        entry["discord_history"] = (
            [{"discord": discord, "discord_id": "", "first_seen": entry.get("first_seen", "")}]
            if discord else []
        )
    return index


def owner_of(index, discord, discord_id, exclude_pid=None):
    for pid, entry in sorted(index.items(), key=lambda kv: int(kv[0])):
        if pid == exclude_pid:
            continue
        if discord_id:
            if any(h.get("discord_id") == discord_id for h in entry.get("discord_history", [])):
                return entry["player_id"]
        elif discord and entry.get("discord", "").lower() == discord.lower():
            return entry["player_id"]
    return None


def update_index(index, players, bills, today, overrides, review):
    for player in sorted(players, key=lambda p: int(p["powerplay_profile_id"])):
        pid = str(player["powerplay_profile_id"])
        discord = player.get("discord") or player.get("discord_user") or ""
        discord_id = discord_id_of(player) if discord else ""
        entry = index.get(pid)
        if entry is None:
            owner = owner_of(index, discord, discord_id) if discord else None
            entry = {
                "profile_id": pid,
                "player_id": owner or f"p{pid}",
                "first_seen": today,
                "discord_history": [],
            }
            index[pid] = entry
        history = entry["discord_history"]
        previous = history[-1] if history else None
        if (discord or previous) and (
            previous is None or (previous["discord"], previous["discord_id"]) != (discord, discord_id)
        ):
            history.append({"discord": discord, "discord_id": discord_id, "first_seen": today})
            if previous and discord and previous["discord"] != discord:
                other = owner_of(index, discord, discord_id, exclude_pid=pid)
                if other and other != entry["player_id"]:
                    note = {
                        "profile_id": pid,
                        "name": player.get("name", ""),
                        "stays_with": entry["player_id"],
                        "new_discord": discord,
                        "matches_player": other,
                        "first_seen": today,
                        "fix": f'To move it, add "{pid}": "{other}" to identity_overrides.json',
                    }
                    if not any(r["profile_id"] == pid and r["new_discord"] == discord for r in review):
                        review.append(note)
        entry.update({
            "name": player.get("name") or entry.get("name", ""),
            "discord": discord,
            "discord_id": discord_id,
            "party": player.get("party") or entry.get("party", ""),
            "state": player.get("state") or entry.get("state", ""),
            "last_seen": today,
            "on_site": True,
        })

    current_ids = {str(p["powerplay_profile_id"]) for p in players}
    for pid, entry in index.items():
        if pid not in current_ids:
            entry["on_site"] = False

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
                "player_id": f"p{pid}",
                "name": person.get("name", ""),
                "discord": "",
                "discord_id": "",
                "discord_history": [],
                "party": person.get("party") or "",
                "state": person.get("state") or "",
                "first_seen": today,
                "last_seen": None,
                "on_site": False,
            }

    for pid, target in overrides.items():
        if str(pid) in index:
            index[str(pid)]["player_id"] = target
    return index


def build_history(index, bills):
    history = {}

    def ensure_person(profile_id):
        info = index[str(profile_id)]
        pid = info["player_id"]
        return history.setdefault(pid, {
            "player_id": pid,
            "name": info.get("name", ""),
            "discord": info.get("discord", ""),
            "profiles": [],
            "bills": {},
        })

    def entry_for(profile_id, bill):
        person = ensure_person(profile_id)
        if str(profile_id) not in person["profiles"]:
            person["profiles"].append(str(profile_id))
        info = index[str(profile_id)]
        if info.get("on_site"):
            person["name"] = info.get("name", person["name"])
            person["discord"] = info.get("discord", person["discord"])
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

    # Include every profile ever indexed, including current players with no vote
    # yet and former players who have left the active roster. These players remain
    # visible on the site and receive N/A until they have enough finalized votes.
    for profile_id, info in index.items():
        person = ensure_person(profile_id)
        if str(profile_id) not in person["profiles"]:
            person["profiles"].append(str(profile_id))
        if info.get("on_site"):
            person["name"] = info.get("name", person["name"])
            person["discord"] = info.get("discord", person["discord"])

    result = []
    for person in history.values():
        person["bills"] = sorted(person["bills"].values(), key=lambda b: (b["resolution_id"], b["profile_id"]))
        person["bill_count"] = len(person["bills"])
        result.append(person)
    result.sort(key=lambda p: p["player_id"].lower())
    return result


def main():
    players = load_json(PLAYERS_FILE, [])
    bills = load_json(BILLS_FILE, [])
    index = load_json(INDEX_FILE, {})
    overrides = load_json(OVERRIDES_FILE, {})
    review = load_json(REVIEW_FILE, [])
    if not isinstance(index, dict):
        index = {}
    if not isinstance(overrides, dict):
        overrides = {}
    if not isinstance(review, list):
        review = []
    index = migrate(index)
    index = update_index(index, players, bills, date.today().isoformat(), overrides, review)
    history = build_history(index, bills)
    save_json(INDEX_FILE, dict(sorted(index.items(), key=lambda kv: int(kv[0]))))
    save_json(HISTORY_FILE, history)
    save_json(REVIEW_FILE, review)
    departed = sum(1 for e in index.values() if not e.get("on_site"))
    print(f"Profiles indexed: {len(index)} ({departed} no longer on site)")
    print(f"Bills read: {len(bills)}")
    print(f"Players in scorecard history: {len(history)}")
    print(f"Identity conflicts awaiting review: {len(review)}")
    print(f"Saved: {INDEX_FILE}, {HISTORY_FILE}, {REVIEW_FILE}")


if __name__ == "__main__":
    main()
