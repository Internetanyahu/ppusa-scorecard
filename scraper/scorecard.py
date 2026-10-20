"""
Deterministic conservative legislative scorecard.

Rules:
- Score ONLY finalized bills.
- Score EACH provision independently; every provision has equal weight.
- +1 = provision moves policy right of the current-law baseline.
- -1 = provision moves policy left of the current-law baseline.
- 0 = neutral/no material policy movement or insufficient evidence.
- Neutral provisions do not enter the vote denominator.
- Aye supports +1; Nay supports -1.
- Categories: Social, Economic, Foreign.
- Overall score is the share of scored provisions on which the member voted
  in the conservative direction. Category scores are calculated separately.

The classifier is intentionally deterministic and auditable. Exact calibrated
rules are stored in scorecard_rules.json. Unknown provisions are assigned 0
and placed in scorecard_review.json instead of being guessed by AI.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BILLS_FILE = ROOT / "bills.json"
HISTORY_FILE = ROOT / "legislative_history.json"
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


def provision_text(provision):
    parts = [provision.get("name", "")]
    parts.extend(str(v) for v in provision.get("notes", {}).values())
    for effect in provision.get("effects", []):
        parts.append(str(effect.get("metric", "")))
    return " ".join(parts).lower()


def compile_rules(rules):
    compiled = []
    for rule in rules:
        compiled.append({
            **rule,
            "pattern_compiled": re.compile(rule["pattern"], re.I),
        })
    return compiled


def classify_provision(bill, provision, rules):
    text = provision_text(provision)

    # Exact calibrated overrides are evaluated first.
    for rule in rules["calibrated_rules"]:
        if rule["pattern_compiled"].search(provision.get("name", "").lower()):
            return {
                "direction": int(rule["direction"]),
                "category": rule["category"],
                "rule_id": rule["id"],
                "rationale": rule["rationale"],
                "source": "calibrated",
            }

    # General deterministic rules cover recurring provision types.
    matches = []
    for rule in rules["general_rules"]:
        if rule["pattern_compiled"].search(text):
            matches.append(rule)

    if not matches:
        return {
            "direction": 0,
            "category": None,
            "rule_id": "UNMATCHED",
            "rationale": "No deterministic rule matched; manual calibration required.",
            "source": "unmatched",
        }

    # If multiple categories/directions conflict, do not guess.
    signatures = {(int(r["direction"]), r["category"]) for r in matches}
    if len(signatures) != 1:
        return {
            "direction": 0,
            "category": None,
            "rule_id": "CONFLICT",
            "rationale": "Multiple deterministic rules conflict; manual calibration required.",
            "source": "conflict",
            "matches": [r["id"] for r in matches],
        }

    r = matches[0]
    return {
        "direction": int(r["direction"]),
        "category": r["category"],
        "rule_id": r["id"],
        "rationale": r["rationale"],
        "source": "general",
    }


def score_vote(vote, direction):
    if vote not in {"aye", "nay"} or direction == 0:
        return None
    return 1 if ((vote == "aye") == (direction == 1)) else 0


def member_vote(row):
    if row.get("house_vote") in {"aye", "nay"}:
        return row["house_vote"]
    if row.get("senate_vote") in {"aye", "nay"}:
        return row["senate_vote"]
    return None


def score_player(rows, bill_meta):
    category_aligned = defaultdict(int)
    category_possible = defaultdict(int)
    aligned_total = 0
    possible_total = 0
    details = []

    for row in rows:
        bill = bill_meta.get(str(row["resolution_id"]))
        if not bill or not bill.get("finalized"):
            continue
        vote = member_vote(row)
        if vote is None:
            continue

        for p in bill["scorecard"]["provisions"]:
            direction = p["direction"]
            if direction == 0:
                continue
            aligned = score_vote(vote, direction)
            if aligned is None:
                continue
            possible_total += 1
            aligned_total += aligned
            cat = p["category"]
            if cat in CATEGORIES:
                category_possible[cat] += 1
                category_aligned[cat] += aligned
            details.append({
                "resolution_id": row["resolution_id"],
                "provision": p["name"],
                "category": cat,
                "direction": direction,
                "vote": vote,
                "aligned": bool(aligned),
            })

    category_scores = {}
    for cat in CATEGORIES:
        category_scores[cat] = round(100 * category_aligned[cat] / category_possible[cat], 2) if category_possible[cat] else None

    overall = round(100 * aligned_total / possible_total, 2) if possible_total else None
    return {
        "social": category_scores["social"],
        "economic": category_scores["economic"],
        "foreign": category_scores["foreign"],
        "overall": overall,
        "tier": tier(overall),
        "sample_size": {c: category_possible[c] for c in CATEGORIES},
        "aligned_votes": {c: category_aligned[c] for c in CATEGORIES},
        "provisions_scored": possible_total,
        "aligned_provisions": aligned_total,
        "bill_details": details,
    }


def main():
    bills = load_json(BILLS_FILE, [])
    history = load_json(HISTORY_FILE, [])
    raw_rules = load_json(RULES_FILE, {"calibrated_rules": [], "general_rules": []})
    rules = {
        "calibrated_rules": compile_rules(raw_rules.get("calibrated_rules", [])),
        "general_rules": compile_rules(raw_rules.get("general_rules", [])),
    }

    bill_meta = {}
    review = []
    for bill in bills:
        if not bill.get("finalized"):
            continue

        scored_provisions = []
        for p in bill.get("provisions", []):
            result = classify_provision(bill, p, rules)
            scored_provisions.append({
                "name": p.get("name", ""),
                **result,
            })
            if result["source"] in {"unmatched", "conflict"} and p.get("name", "").strip():
                review.append({
                    "resolution_id": bill["resolution_id"],
                    "number": bill.get("number", ""),
                    "title": bill.get("title", ""),
                    "provision": p.get("name", ""),
                    "reason": result["rationale"],
                })

        bill_copy = dict(bill)
        bill_copy["scorecard"] = {"provisions": scored_provisions}
        bill_meta[str(bill["resolution_id"])] = bill_copy

    players = []
    for person in history:
        scored = score_player(person.get("bills", []), bill_meta)
        players.append({
            "player_id": person["player_id"],
            "name": person.get("name", ""),
            "discord": person.get("discord", ""),
            "scores": {
                "social": scored["social"],
                "economic": scored["economic"],
                "foreign": scored["foreign"],
                "overall": scored["overall"],
                "tier": scored["tier"],
            },
            "sample_size": scored["sample_size"],
            "aligned_votes": scored["aligned_votes"],
            "provisions_scored": scored["provisions_scored"],
            "aligned_provisions": scored["aligned_provisions"],
            "bill_details": scored["bill_details"],
        })

    players.sort(key=lambda p: (p["scores"]["overall"] is None, -(p["scores"]["overall"] or 0), p["name"].lower()))

    save_json(OUT_FILE, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "method": {
            "finalized_bills_only": True,
            "equal_provision_weight": True,
            "categories": list(CATEGORIES),
            "direction_definition": "+1 = right of current law; -1 = left of current law; 0 = neutral/no material movement.",
            "vote_alignment": "Aye supports +1; Nay supports -1.",
            "neutral_provisions": "Excluded from denominators.",
            "tiers": {"S": "90-100", "A": "80-89.99", "B": "70-79.99", "C": "60-69.99", "D": "50-59.99", "F": "0-49.99"},
        },
        "bills": bill_meta,
        "players": players,
    })
    save_json(REVIEW_FILE, review)
    print(f"Finalized bills: {len(bill_meta)}")
    print(f"Players scored: {len(players)}")
    print(f"Unmatched/neutral provisions for review: {len(review)}")


if __name__ == "__main__":
    main()
