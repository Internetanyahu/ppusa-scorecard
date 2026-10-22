"""Neutralize appropriations bills in the compiled scorecard until policy rules are defined."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORECARD_FILE = ROOT / "conservative_scorecard.json"

APPROPRIATION_RE = re.compile(r"\bappropriations?\b", re.I)


def is_appropriation(bill: dict) -> bool:
    haystack = " ".join(
        str(bill.get(key, ""))
        for key in ("title", "number", "type", "committee")
    )
    return bool(APPROPRIATION_RE.search(haystack))


def main() -> None:
    data = json.loads(SCORECARD_FILE.read_text(encoding="utf-8"))
    bills = data.get("bills", {})
    neutral_ids = set()

    for key, bill in bills.items():
        if not is_appropriation(bill):
            continue

        neutral_ids.add(str(key))
        scorecard = bill.setdefault("scorecard", {})
        provisions = scorecard.get("provisions", [])

        for provision in provisions:
            provision["direction"] = 0
            provision["category"] = None
            provision["scorable"] = False
            provision["rule_id"] = "APPROPRIATION-NEUTRAL"
            provision["source"] = "neutral"
            provision["rationale"] = "Appropriations bills are neutral until a dedicated policy rule is defined."

        scorecard["total"] = 0
        scorecard["scored_provisions"] = 0
        scorecard["alignment"] = "Neutral / mixed"

    if not neutral_ids:
        print("No appropriations bills found; scorecard unchanged.")
        return

    # Remove neutral appropriations from player scoring details and recalculate
    # the published percentages from the remaining scored votes.
    for player in data.get("players", []):
        details = [
            detail
            for detail in player.get("bill_details", [])
            if str(detail.get("resolution_id")) not in neutral_ids
        ]

        category_possible = {"social": 0, "economic": 0, "foreign": 0}
        category_aligned = {"social": 0, "economic": 0, "foreign": 0}
        distinct_bills = set()

        for detail in details:
            direction = detail.get("direction")
            category = detail.get("category")
            if direction not in (-1, 1) or category not in category_possible:
                continue
            distinct_bills.add(int(detail["resolution_id"]))
            category_possible[category] += 1
            category_aligned[category] += int(bool(detail.get("aligned")))

        total_possible = sum(category_possible.values())
        total_aligned = sum(category_aligned.values())
        eligible = len(distinct_bills) >= 3

        player["bill_details"] = details
        player["sample_size"] = {
            **category_possible,
            "overall": total_possible,
        }
        player["aligned_votes"] = dict(category_aligned)
        player["provisions_scored"] = total_possible
        player["aligned_provisions"] = total_aligned
        player["finalized_bills_voted"] = len(distinct_bills)
        player["eligible_for_grade"] = eligible
        player["scores"] = {
            "social": round(100 * category_aligned["social"] / category_possible["social"], 2) if eligible and category_possible["social"] else None,
            "economic": round(100 * category_aligned["economic"] / category_possible["economic"], 2) if eligible and category_possible["economic"] else None,
            "foreign": round(100 * category_aligned["foreign"] / category_possible["foreign"], 2) if eligible and category_possible["foreign"] else None,
            "overall": round(100 * total_aligned / total_possible, 2) if eligible and total_possible else None,
            "tier": "N/A" if not eligible or not total_possible else (
                "S" if 100 * total_aligned / total_possible >= 90 else
                "A" if 100 * total_aligned / total_possible >= 80 else
                "B" if 100 * total_aligned / total_possible >= 70 else
                "C" if 100 * total_aligned / total_possible >= 60 else
                "D" if 100 * total_aligned / total_possible >= 50 else "F"
            ),
        }

    data["appropriations_neutral"] = {
        "enabled": True,
        "bill_count": len(neutral_ids),
        "rule": "Appropriations bills are neutral and do not affect player scores until a dedicated policy rule is defined.",
    }

    SCORECARD_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Neutralized {len(neutral_ids)} appropriations bills in the compiled scorecard.")


if __name__ == "__main__":
    main()
