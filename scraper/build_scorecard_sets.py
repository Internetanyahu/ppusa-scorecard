"""Build all configurable scorecard sets from the compiled bill/player data."""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = ROOT / "conservative_scorecard.json"
CONFIG_FILE = ROOT / "scorecard_sets_config.json"
OUT_FILE = ROOT / "scorecard_sets.json"

CATEGORIES = ("social", "economic", "foreign")


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def norm(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def provision_text(raw, classified):
    parts = [raw.get("name", ""), classified.get("rationale", "")]
    parts.extend(str(v) for v in (raw.get("notes") or {}).values())
    for effect in raw.get("effects") or []:
        parts.append(str(effect.get("metric", "")))
        parts.extend(str(v) for v in effect.values())
    return " ".join(parts).lower()


def states_rights_classification(raw, classified):
    """Heuristic for the State's Rights Index.

    +1 favors state/local authority or lower federal spending.
    -1 favors more federal control or higher federal spending.
    0 means the provision has no clear federalism/federal-spending signal.
    Admin overrides can replace any result.
    """
    text = provision_text(raw, classified)

    positive_patterns = [
        r"state(?:s| governments?)? (?:control|authority|power|choice|decide|administer)",
        r"state[- ]administered",
        r"state sovereignty",
        r"10th amendment",
        r"tenth amendment",
        r"return(?:s|ed)? .* to the states",
        r"devolve .* to (?:the )?states",
        r"block federal",
        r"repeal federal mandate",
        r"eliminate federal mandate",
        r"reduce federal (?:spending|funding|appropriation|outlays)",
        r"cut federal (?:spending|funding|appropriation|outlays)",
        r"lower federal (?:spending|funding|appropriation|outlays)",
        r"federal spending cut",
        r"federal budget reduction",
    ]
    negative_patterns = [
        r"federal (?:control|authority|mandate|standard|requirement)",
        r"national (?:standard|mandate|requirement)",
        r"federal(?:ly)? administered",
        r"federalize",
        r"nationalize",
        r"centralize",
        r"increase federal (?:spending|funding|appropriation|outlays)",
        r"expand federal (?:spending|funding|appropriation|outlays)",
        r"additional federal (?:spending|funding|appropriation|outlays)",
        r"federal grant(?:s)?",
        r"federal program",
        r"new federal program",
        r"federal subsidy",
        r"federal benefit",
    ]

    positive = sum(bool(re.search(p, text, re.I)) for p in positive_patterns)
    negative = sum(bool(re.search(p, text, re.I)) for p in negative_patterns)

    # Strong federal spending language gets an explicit signal even when the
    # provision does not literally say "increase" or "decrease".
    if re.search(r"\b(?:spend|spending|appropriation|outlays|budget)\b", text, re.I):
        if re.search(r"\b(?:cut|reduce|lower|decrease|eliminate|repeal|restraint)\w*\b", text, re.I):
            positive += 2
        if re.search(r"\b(?:increase|expand|raise|add|new|additional|boost)\w*\b", text, re.I):
            negative += 2

    if positive > negative:
        category = "economic" if re.search(r"\b(?:spend|spending|appropriation|outlays|budget|funding)\b", text, re.I) else "social"
        return 1, category, "State's Rights strategy: favors state/local authority or reduced federal spending."
    if negative > positive:
        category = "economic" if re.search(r"\b(?:spend|spending|appropriation|outlays|budget|funding|subsidy|benefit)\b", text, re.I) else "social"
        return -1, category, "State's Rights strategy: favors federal control or increased federal spending."

    return 0, None, "State's Rights strategy: no clear federalism or federal-spending direction."


def classify(set_cfg, base_provision, raw_provision):
    overrides = set_cfg.get("provision_overrides") or {}
    override = overrides.get(norm(base_provision.get("name")))
    if override is None:
        # Also accept exact-name keys so hand-edited configs remain friendly.
        override = overrides.get(base_provision.get("name"))

    if override is not None:
        direction = int(override.get("direction", 0))
        category = override.get("category") if direction else None
        return {
            "direction": direction if direction in (-1, 0, 1) else 0,
            "category": category if direction else None,
            "rule_id": override.get("id", "SET-OVERRIDE"),
            "rationale": override.get("rationale") or "Explicitly assigned in this scorecard set.",
            "source": "set_override",
            "scorable": direction in (-1, 1),
        }

    strategy = set_cfg.get("strategy", "conservative")
    if strategy == "states_rights":
        direction, category, rationale = states_rights_classification(raw_provision, base_provision)
        return {
            "direction": direction,
            "category": category,
            "rule_id": "STATE-RIGHTS-HEURISTIC",
            "rationale": rationale,
            "source": "strategy",
            "scorable": direction in (-1, 1),
        }

    return {
        "direction": int(base_provision.get("direction", 0)) if int(base_provision.get("direction", 0)) in (-1, 0, 1) else 0,
        "category": base_provision.get("category") if base_provision.get("direction") else None,
        "rule_id": base_provision.get("rule_id", "CONSERVATIVE-BASE"),
        "rationale": base_provision.get("rationale", "Inherited from the conservative scorecard."),
        "source": base_provision.get("source", "conservative"),
        "scorable": base_provision.get("scorable", True) and base_provision.get("direction") in (-1, 1),
    }


def score_player(player, bills):
    details = []
    distinct = set()
    aligned_total = 0
    possible_total = 0
    category_possible = {c: 0 for c in CATEGORIES}
    category_aligned = {c: 0 for c in CATEGORIES}

    for row in player.get("bill_details", []):
        bill = bills.get(str(row.get("resolution_id")))
        if not bill or not bill.get("finalized"):
            continue
        vote = str(row.get("vote", "")).lower()
        provision = next((p for p in bill.get("scorecard", {}).get("provisions", []) if p.get("name") == row.get("provision")), None)
        if not provision or vote not in {"aye", "nay"}:
            continue
        direction = provision.get("direction")
        if direction not in (-1, 1) or provision.get("scorable") is False:
            continue
        distinct.add(int(row.get("resolution_id")))
        aligned = vote == "aye" if direction == 1 else vote == "nay"
        possible_total += 1
        aligned_total += int(aligned)
        category = provision.get("category")
        if category in CATEGORIES:
            category_possible[category] += 1
            category_aligned[category] += int(aligned)
        details.append({
            **row,
            "direction": direction,
            "category": category,
            "aligned": aligned,
            "scorable": True,
        })

    eligible = len(distinct) >= 3
    scores = {}
    for category in CATEGORIES:
        scores[category] = round(100 * category_aligned[category] / category_possible[category], 2) if eligible and category_possible[category] else None
    overall = round(100 * aligned_total / possible_total, 2) if eligible and possible_total else None
    if overall is None:
        grade = "N/A"
    elif overall >= 90:
        grade = "S"
    elif overall >= 80:
        grade = "A"
    elif overall >= 70:
        grade = "B"
    elif overall >= 60:
        grade = "C"
    elif overall >= 50:
        grade = "D"
    else:
        grade = "F"

    return {
        **player,
        "bill_details": details,
        "scores": {**scores, "overall": overall, "tier": grade},
        "sample_size": {**category_possible, "overall": possible_total},
        "aligned_provisions": aligned_total,
        "provisions_scored": possible_total,
        "finalized_bills_voted": len(distinct),
        "eligible_for_grade": eligible,
    }


def main():
    base = load(BASE_FILE, {})
    config = load(CONFIG_FILE, {})
    sets = config.get("sets") or []
    if not sets:
        raise SystemExit("scorecard_sets_config.json contains no scorecard sets")

    raw_by_id = {str(b.get("resolution_id")): b for b in load(ROOT / "bills.json", [])}
    generated_sets = []

    for set_cfg in sets:
        bills = {}
        for rid, base_bill in (base.get("bills") or {}).items():
            raw_bill = raw_by_id.get(str(rid), {})
            copy_bill = copy.deepcopy(base_bill)
            scored = []
            raw_provisions = raw_bill.get("provisions") or []
            raw_by_name = {norm(p.get("name")): p for p in raw_provisions}
            for base_provision in base_bill.get("scorecard", {}).get("provisions", []):
                raw_provision = raw_by_name.get(norm(base_provision.get("name")), {})
                result = classify(set_cfg, base_provision, raw_provision)
                scored.append({"name": base_provision.get("name", ""), **result, "current_law": base_provision.get("current_law")})
            copy_bill["scorecard"] = dict(copy_bill.get("scorecard") or {})
            copy_bill["scorecard"]["provisions"] = scored
            scorable = [p for p in scored if p.get("scorable") and p.get("direction") in (-1, 1)]
            total = sum(int(p["direction"]) for p in scorable)
            copy_bill["scorecard"]["total"] = total
            copy_bill["scorecard"]["scored_provisions"] = len(scorable)
            copy_bill["scorecard"]["alignment"] = "Conservative" if total > 0 else "Liberal" if total < 0 else "Neutral / mixed"
            bills[str(rid)] = copy_bill

        pending = []
        for pending_base in base.get("pending_bills", []):
            rid = str(pending_base.get("resolution_id"))
            raw_bill = raw_by_id.get(rid, {})
            copy_bill = copy.deepcopy(pending_base)
            scored = []
            raw_by_name = {norm(p.get("name")): p for p in raw_bill.get("provisions") or []}
            for base_provision in pending_base.get("scorecard", {}).get("provisions", []):
                raw_provision = raw_by_name.get(norm(base_provision.get("name")), {})
                scored.append({"name": base_provision.get("name", ""), **classify(set_cfg, base_provision, raw_provision)})
            copy_bill["scorecard"] = dict(copy_bill.get("scorecard") or {})
            copy_bill["scorecard"]["provisions"] = scored
            copy_bill["scorecard"]["total"] = sum(int(p["direction"]) for p in scored if p.get("scorable") and p.get("direction") in (-1, 1))
            copy_bill["scorecard"]["alignment"] = "Conservative" if copy_bill["scorecard"]["total"] > 0 else "Liberal" if copy_bill["scorecard"]["total"] < 0 else "Neutral / mixed"
            pending.append(copy_bill)

        players = [score_player(player, bills) for player in base.get("players", [])]
        generated_sets.append({
            "id": set_cfg["id"],
            "name": set_cfg.get("name") or set_cfg["id"],
            "description": set_cfg.get("description", ""),
            "strategy": set_cfg.get("strategy", "conservative"),
            "owner_name": set_cfg.get("owner_name", ""),
            "owner_player_id": set_cfg.get("owner_player_id", ""),
            "category_names": set_cfg.get("category_names") or {c: c.title() for c in CATEGORIES},
            "ideology_labels": set_cfg.get("ideology_labels") or {},
            "bills": bills,
            "pending_bills": sorted(pending, key=lambda b: int(b.get("resolution_id") or 0)),
            "players": players,
        })

    default_set = config.get("default_set") or generated_sets[0]["id"]
    if default_set not in {s["id"] for s in generated_sets}:
        default_set = generated_sets[0]["id"]

    save(OUT_FILE, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "default_set": default_set,
        "sets": generated_sets,
    })
    print(f"Built {len(generated_sets)} scorecard sets: {', '.join(s['id'] for s in generated_sets)}")


if __name__ == "__main__":
    main()
