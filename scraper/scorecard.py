"""Build the deterministic Power Play USA conservative scorecard."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BILLS_FILE = ROOT / "bills.json"
HISTORY_FILE = ROOT / "legislative_history.json"
PLAYERS_FILE = ROOT / "players.json"
INDEX_FILE = ROOT / "player_index.json"
RULES_FILE = ROOT / "scorecard_rules.json"
OUT_FILE = ROOT / "conservative_scorecard.json"
REVIEW_FILE = ROOT / "scorecard_review.json"

CATEGORIES = ("social", "economic", "foreign")
TIERS = [(90, "S"), (80, "A"), (70, "B"), (60, "C"), (50, "D"), (0, "F")]


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tier(score):
    if score is None:
        return "N/A"
    for minimum, label in TIERS:
        if score >= minimum:
            return label
    return "F"


def week_number(value):
    m = re.search(r"Week\s+(\d+),\s*(\d+)", value or "")
    return (int(m.group(2)), int(m.group(1))) if m else None


def issue_key(name):
    raw = re.sub(r"\s+", " ", (name or "").strip().lower())
    return raw.split(":", 1)[0].strip() if ":" in raw else raw


def law_sort_key(bill):
    return (week_number(bill.get("passed", "")) or (0, 0), int(bill.get("resolution_id", 0)))


def prior_law_reference(bill, provision, bills):
    key = issue_key(provision.get("name", ""))
    if not key:
        return None
    current_intro = week_number(bill.get("introduced", "")) or (999999, 999999)
    candidates = []
    for other in bills:
        if other.get("resolution_id") == bill.get("resolution_id"):
            continue
        if not other.get("finalized") or not other.get("passed"):
            continue
        passed = week_number(other.get("passed", ""))
        if not passed or passed >= current_intro:
            continue
        for op in other.get("provisions", []):
            if issue_key(op.get("name", "")) == key:
                candidates.append((law_sort_key(other), other, op))
    if not candidates:
        return None
    _, prior_bill, prior_provision = max(candidates, key=lambda x: x[0])
    return {
        "resolution_id": prior_bill.get("resolution_id"),
        "number": prior_bill.get("number", ""),
        "title": prior_bill.get("title", ""),
        "passed": prior_bill.get("passed", ""),
        "provision": prior_provision.get("name", ""),
    }


def provision_text(provision):
    parts = [provision.get("name", "")]
    parts.extend(str(v) for v in provision.get("notes", {}).values())
    for effect in provision.get("effects", []):
        parts.append(str(effect.get("metric", "")))
    return " ".join(parts).lower()


def compile_rules(rules):
    return [{**rule, "pattern_compiled": re.compile(rule["pattern"], re.I)} for rule in rules]


def norm_name(name):
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def build_provision_rules(raw_rules):
    """Explicit per-provision rules (edited from the admin page), keyed by normalised name."""
    table = {}
    for rule in raw_rules.get("provision_rules", []):
        key = norm_name(rule.get("name"))
        if key:
            table[key] = rule
    return table


def explicit_result(rule):
    """Turn an explicit provision rule into a classification, or None if it is malformed."""
    rule_id = rule.get("id") or "EXPLICIT"
    try:
        direction = int(rule.get("direction", 0))
    except (TypeError, ValueError):
        direction = None
    category = (rule.get("category") or "").lower() or None
    rationale = rule.get("rationale") or "Explicit rule set by the scorecard administrator."
    if direction == 0 or (direction is not None and rule.get("neutral")):
        return {"direction": 0, "category": None, "rule_id": rule_id, "rationale": rationale, "source": "explicit", "scorable": False}
    if direction in (-1, 1) and category in CATEGORIES:
        return {"direction": direction, "category": category, "rule_id": rule_id, "rationale": rationale, "source": "explicit", "scorable": True}
    print(f"WARNING: ignoring malformed explicit rule {rule_id!r} for {rule.get('name')!r}")
    return None


def fallback_classification(provision):
    text = provision_text(provision)
    if re.search(r"\b(visa|immigration|h-1b|border|citizenship|abortion|marriage|gun|firearm|religious|police|crime|election|campaign)\b", text):
        direction = -1 if re.search(r"\b(visa|immigration|h-1b)\b", text) and not re.search(r"\b(restrict|cap|deport|border enforcement)\b", text) else 1
        return direction, "social", "Deterministic social-policy fallback."
    if re.search(r"\b(tax|wage|benefit|medicare|healthcare|regulat|spending|appropriation|union|tariff|import|subsid)", text):
        direction = 1 if re.search(r"\b(tariff|import|protection|buy american|tax cut|spending cut|deregulat)", text) else -1
        return direction, "economic", "Deterministic economic-policy fallback."
    if re.search(r"\b(military|defense|intelligence|war|troop|foreign|cuba|communist|sanction|aid|treaty)", text):
        direction = 1 if re.search(r"\b(defense|military readiness|anti-communist|communist party ban|sanction.*communist|cuba)", text) else -1
        return direction, "foreign", "Deterministic foreign-policy fallback."
    return 1, "social", "Final binary fallback; retained for deterministic scoring."


def classify_provision(bill, provision, rules, bills):
    name = provision.get("name", "").strip()
    # An explicit per-provision rule always wins over pattern rules and fallbacks.
    explicit = rules.get("provision_rules", {}).get(norm_name(name))
    if explicit is not None:
        result = explicit_result(explicit)
        if result is not None:
            return result

    # Custom/placeholder bills are intentionally neutral and never affect a score.
    if re.fullmatch(r"custom bill", name, re.I):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "CUSTOM-BILL-NEUTRAL",
            "rationale": "Custom bills contain no deterministic policy position and are neutral.",
            "source": "neutral",
            "scorable": False,
        }

    for rule in rules["calibrated_rules"]:
        if rule["pattern_compiled"].search(name.lower()):
            direction = int(rule["direction"])
            if rule.get("neutral"):
                return {"direction": 0, "category": None, "rule_id": rule["id"], "rationale": rule.get("rationale", "Neutral."), "source": "calibrated", "scorable": False}
            if name.lower() == "h-1b skilled worker visa: 200,000" and direction == 0:
                direction = -1
            if direction == 0:
                # Only explicit custom bills may be neutral.
                direction, category, rationale = fallback_classification(provision)
                return {"direction": direction, "category": category, "rule_id": rule["id"] + "-FALLBACK", "rationale": rationale, "source": "fallback", "scorable": True}
            return {
                "direction": direction,
                "category": rule["category"].lower(),
                "rule_id": rule["id"],
                "rationale": rule["rationale"],
                "source": "calibrated",
                "scorable": True,
            }

    matches = [r for r in rules["general_rules"] if r["pattern_compiled"].search(provision_text(provision))]
    signatures = {(int(r["direction"]), r["category"].lower()) for r in matches}
    if len(signatures) == 1:
        r = matches[0]
        return {"direction": int(r["direction"]), "category": r["category"].lower(), "rule_id": r["id"], "rationale": r["rationale"], "source": "general", "scorable": True}

    direction, category, rationale = fallback_classification(provision)
    return {"direction": direction, "category": category, "rule_id": "FALLBACK" if not matches else "FALLBACK-CONFLICT", "rationale": rationale, "source": "fallback", "scorable": True}


def score_vote(vote, direction):
    if vote not in {"aye", "nay"} or direction not in {-1, 1}:
        return None
    return vote == "aye" if direction == 1 else vote == "nay"


def member_vote(row):
    if row.get("house_vote") in {"aye", "nay"}:
        return row["house_vote"], "House"
    if row.get("senate_vote") in {"aye", "nay"}:
        return row["senate_vote"], "Senate"
    return None, "Other"


def build_profile_metadata(players, index, history_person):
    player_id = history_person["player_id"]
    profiles = []
    player_map = {str(p.get("powerplay_profile_id")): p for p in players}
    index_profiles = [e for e in index.values() if e.get("player_id") == player_id]
    by_id = {str(e.get("profile_id")): e for e in index_profiles}

    vote_chambers = defaultdict(lambda: defaultdict(int))
    for row in history_person.get("bills", []):
        pid = str(row.get("profile_id"))
        if row.get("senate_vote") in {"aye", "nay", "present"}:
            vote_chambers[pid]["Senate"] += 1
        if row.get("house_vote") in {"aye", "nay", "present"}:
            vote_chambers[pid]["House"] += 1

    for pid in history_person.get("profiles", []):
        source = player_map.get(str(pid), {})
        idx = by_id.get(str(pid), {})
        counts = vote_chambers[str(pid)]
        chamber = source.get("chamber") or source.get("chamber_name") or source.get("office_chamber") or ""
        if not chamber:
            chamber = max(counts, key=counts.get) if counts else "Other"
        chamber = str(chamber).lower()
        if "senate" in chamber:
            chamber = "Senate"
        elif "house" in chamber:
            chamber = "House"
        else:
            chamber = "Other"
        profiles.append({
            "profile_id": str(pid),
            "name": source.get("name") or idx.get("name") or "",
            "party": (source.get("party") or idx.get("party") or "").lower(),
            "state": source.get("state") or idx.get("state") or "",
            "chamber": chamber,
            "avatar": source.get("discord_avatar") or "",
            "is_main": bool(source.get("is_main")),
            "on_site": bool(idx.get("on_site", True)),
        })

    profiles.sort(key=lambda p: (not p["is_main"], p["profile_id"]))
    main = next((p for p in profiles if p["is_main"]), profiles[0] if profiles else {})
    return profiles, main


def score_player(person, bill_meta):
    category_aligned = defaultdict(int)
    category_possible = defaultdict(int)
    aligned_total = 0
    possible_total = 0
    details = []
    distinct_bills = set()

    for row in person.get("bills", []):
        bill = bill_meta.get(str(row["resolution_id"]))
        if not bill or not bill.get("finalized"):
            continue
        vote, chamber = member_vote(row)
        if vote is None:
            continue
        distinct_bills.add(int(row["resolution_id"]))
        profile_id = str(row.get("profile_id", ""))
        profile_name = next((p.get("name") for p in person.get("profiles_meta", []) if p.get("profile_id") == profile_id), "")
        for p in bill["scorecard"]["provisions"]:
            if not p.get("scorable", True) or p.get("direction") not in {-1, 1}:
                continue
            aligned = score_vote(vote, p["direction"])
            if aligned is None:
                continue
            possible_total += 1
            aligned_total += int(aligned)
            cat = p["category"]
            if cat in CATEGORIES:
                category_possible[cat] += 1
                category_aligned[cat] += int(aligned)
            details.append({
                "resolution_id": row["resolution_id"],
                "number": bill.get("number", ""),
                "bill_title": bill.get("title", ""),
                "provision": p["name"],
                "category": cat,
                "direction": p["direction"],
                "vote": vote,
                "aligned": bool(aligned),
                "profile_id": profile_id,
                "profile_name": profile_name,
                "chamber": chamber,
            })

    # The user requested N/A when the user has participated in fewer than three
    # finalized bills. Votes remain visible, but they do not receive a grade.
    eligible = len(distinct_bills) >= 3
    category_scores = {
        cat: (round(100 * category_aligned[cat] / category_possible[cat], 2) if eligible and category_possible[cat] else (None if not eligible else None))
        for cat in CATEGORIES
    }
    overall = round(100 * aligned_total / possible_total, 2) if eligible and possible_total else None
    return {
        "scores": {
            "social": category_scores["social"],
            "economic": category_scores["economic"],
            "foreign": category_scores["foreign"],
            "overall": overall,
            "tier": tier(overall),
        },
        "sample_size": dict(category_possible),
        "aligned_votes": dict(category_aligned),
        "provisions_scored": possible_total,
        "aligned_provisions": aligned_total,
        "finalized_bills_voted": len(distinct_bills),
        "bill_details": details,
        "eligible_for_grade": eligible,
    }


def main():
    bills = load_json(BILLS_FILE, [])
    history = load_json(HISTORY_FILE, [])
    players = load_json(PLAYERS_FILE, [])
    index = load_json(INDEX_FILE, {})
    raw_rules = load_json(RULES_FILE, {"calibrated_rules": [], "general_rules": []})
    rules = {"calibrated_rules": compile_rules(raw_rules.get("calibrated_rules", [])), "general_rules": compile_rules(raw_rules.get("general_rules", [])), "provision_rules": build_provision_rules(raw_rules)}

    bill_meta = {}
    review = []
    all_names, explicit_names = set(), set()
    for bill in bills:
        if not bill.get("finalized"):
            continue
        scored_provisions = []
        for p in bill.get("provisions", []):
            result = classify_provision(bill, p, rules, bills)
            result["current_law"] = prior_law_reference(bill, p, bills)
            if p.get("name", "").strip():
                all_names.add(norm_name(p["name"]))
                if result["source"] == "explicit":
                    explicit_names.add(norm_name(p["name"]))
            scored_provisions.append({"name": p.get("name", ""), **result})
            if result["source"] == "fallback" and p.get("name", "").strip():
                review.append({"resolution_id": bill["resolution_id"], "number": bill.get("number", ""), "title": bill.get("title", ""), "provision": p.get("name", ""), "reason": result["rationale"], "current_law": result.get("current_law")})
        copy = dict(bill)
        copy["scorecard"] = {"provisions": scored_provisions}
        bill_meta[str(bill["resolution_id"])] = copy

    out_players = []
    for person in history:
        profiles, main = build_profile_metadata(players, index, person)
        person = dict(person)
        person["profiles_meta"] = profiles
        scored = score_player(person, bill_meta)
        party_values = [p["party"] for p in profiles if p.get("party")]
        state_values = [p["state"] for p in profiles if p.get("state")]
        chambers = sorted({p["chamber"] for p in profiles})
        avatar = main.get("avatar", "")
        discord_ids = sorted({str(e.get("discord_id")) for e in index.values() if e.get("player_id") == person["player_id"] and e.get("discord_id")})
        out_players.append({
            "user_id": person["player_id"],
            "player_id": person["player_id"],
            "name": main.get("name") or person.get("name", ""),
            "discord": person.get("discord", ""),
            "discord_ids": discord_ids,
            "party": party_values[0] if party_values else "",
            "state": main.get("state") or (state_values[0] if state_values else ""),
            "chambers": chambers,
            "avatar": avatar,
            "profiles": profiles,
            **scored,
        })

    out_players.sort(key=lambda p: ((p["scores"]["overall"] is None), -(p["scores"]["overall"] or 0), p["name"].lower()))
    save_json(OUT_FILE, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": {
            "identity_key": "player_id/user_id, not Discord username",
            "finalized_bills_only": True,
            "equal_provision_weight": True,
            "categories": list(CATEGORIES),
            "vote_alignment": "Aye aligns with +1; Nay aligns with -1.",
            "custom_bills": "Neutral and excluded from scoring.",
            "minimum_finalized_bills": 3,
            "tiers": {"S": "90-100", "A": "80-89.99", "B": "70-79.99", "C": "60-69.99", "D": "50-59.99", "F": "0-49.99"},
        },
        "bills": bill_meta,
        "players": out_players,
    })
    save_json(REVIEW_FILE, review)
    print(f"Finalized bills: {len(bill_meta)}")
    print(f"User scorecards: {len(out_players)}")
    print(f"Fallback provisions for review: {len(review)}")
    print(f"Provisions with an explicit rule: {len(explicit_names)} of {len(all_names)}")


if __name__ == "__main__":
    main()
