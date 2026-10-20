"""
Deterministic conservative legislative scorecard.

Rules:
- Score ONLY finalized bills.
- Score EACH provision independently; every scored provision has equal weight.
- +1 = conservative/rightward.
- -1 = liberal/leftward.
- 0 = neutral and excluded from scoring.
- Custom Bills are neutral.
- Marijuana legalization/decriminalization is neutral.
- Nuclear energy itself is neutral.
- Taxes are -1.
- All subsidies are -1.
- All tax credits are +1 except tax credits for non-nuclear green energy,
  which are -1.
- Aye supports +1; Nay supports -1.
- Categories: Social, Economic, Foreign.

The classifier is deterministic and auditable.
"""
import json
import math
import re
from pathlib import Path
from datetime import datetime, timezone


def provision_text(provision):
    """Build searchable text from the fields commonly present on a provision."""
    parts = []
    for key in ("name", "title", "description", "summary", "text", "details"):
        value = provision.get(key)
        if value is not None:
            parts.append(str(value))
    return " ".join(parts)


def fallback_classification(provision):
    """Conservative, deterministic fallback for provisions without a rule match."""
    text = provision_text(provision).lower()
    name = str(provision.get("name", "")).lower()
    # Infer a category from common provision wording. The fallback direction is
    # explicit and logged, so unmatched items remain auditable.
    if re.search(r"\b(abortion|parental|school prayer|religion|gun|firearm|immigration|border|crime|police|sentenc|marriage|gender|election integrity)\b", text):
        return 1, "social", "Fallback: social-policy provision scored +1 pending a specific rule."
    if re.search(r"\b(tax|spending|budget|debt|subsid|welfare|minimum wage|union|regulation|business|trade|tariff|veteran|va|gi bill)\b", text):
        return (1 if re.search(r"\b(tax cut|reduce tax|deregulat|tariff|protection|veteran|va|gi bill)\b", text) else -1), "economic", "Fallback: economic provision scored using the stated fiscal framework pending a specific rule."
    if re.search(r"\b(military|defense|foreign|war|troop|sanction|treaty|nato|overseas|invasion|aid to)\b", text):
        return (1 if re.search(r"\b(defense|military readiness|anti-communist|hemispheric)\b", text) else -1), "foreign", "Fallback: foreign-policy provision scored using the stated anti-intervention framework pending a specific rule."
    # Keep the historical fallback deterministic rather than silently neutral.
    return -1, "economic", "Fallback: unmatched provision defaults to -1 economic pending rule review."


def classify_provision(bill, provision, rules, bills):
    name = provision.get("name", "").strip()
    text = provision_text(provision)

    # ---------------------------------------------------------
    # NEUTRAL PROVISIONS
    # ---------------------------------------------------------

    # Marijuana legalization itself is neutral.
    if re.fullmatch(
        r"marijuana\s+(legalization|decriminalization):\s*(legal|decriminalized)",
        name,
        re.I,
    ):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "NEUTRAL-MARIJUANA",
            "rationale": "Marijuana legalization/decriminalization is neutral and is not scored.",
            "source": "neutral",
            "scorable": False,
        }

    # Nuclear energy itself is neutral.
    # A provision that also contains a subsidy is handled below,
    # because all subsidies are explicitly scored -1.
    if re.fullmatch(
        r"nuclear energy:\s*(expanded|allowed|legal|neutral)",
        name,
        re.I,
    ):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "NEUTRAL-NUCLEAR",
            "rationale": "Nuclear energy itself is neutral and is not scored.",
            "source": "neutral",
            "scorable": False,
        }

    # Custom Bills are neutral.
    if re.fullmatch(r"custom\s+bill", name, re.I):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "CUSTOM-BILL-NEUTRAL",
            "rationale": "Custom Bills are neutral and are not scored.",
            "source": "neutral",
            "scorable": False,
        }

    # ---------------------------------------------------------
    # TAXES
    # ---------------------------------------------------------

    # Any tax/tax increase is bad.
    if re.search(
        r"\b("
        r"tax|taxes|taxation|sales tax|excise tax|income tax|"
        r"corporate tax|capital gains tax|payroll tax|property tax"
        r")\b",
        text,
        re.I,
    ):
        # Tax credits are handled separately below.
        if not re.search(r"\btax credit\b", text, re.I):
            return {
                "direction": -1,
                "category": "economic",
                "rule_id": "GENERAL-TAX",
                "rationale": "Taxation is scored -1 under the fiscal-libertarian framework.",
                "source": "general",
                "scorable": True,
            }

    # ---------------------------------------------------------
    # TAX CREDITS
    # ---------------------------------------------------------

    # Tax credits for non-nuclear green energy are -1.
    if re.search(r"\btax credit\b", text, re.I):
        if re.search(
            r"\b("
            r"solar|wind|renewable|green energy|clean energy|"
            r"clean electricity|electric vehicle|ev|battery|"
            r"hydrogen|geothermal|biofuel|biomass"
            r")\b",
            text,
            re.I,
        ):
            return {
                "direction": -1,
                "category": "economic",
                "rule_id": "GENERAL-GREEN-ENERGY-TAX-CREDIT",
                "rationale": "Tax credits for non-nuclear green energy are treated as government support for favored energy technologies and are scored -1.",
                "source": "general",
                "scorable": True,
            }

        # All other tax credits are +1.
        return {
            "direction": 1,
            "category": "economic",
            "rule_id": "GENERAL-TAX-CREDIT",
            "rationale": "Tax credits reduce tax burdens and are scored +1 under the fiscal-libertarian framework.",
            "source": "general",
            "scorable": True,
        }

    # ---------------------------------------------------------
    # SUBSIDIES
    # ---------------------------------------------------------

    # Every subsidy is -1 unless it was already identified as a
    # neutral provision above.
    if re.search(r"\bsubsid(?:y|ies|ized|ized)\b", text, re.I):
        return {
            "direction": -1,
            "category": "economic",
            "rule_id": "GENERAL-SUBSIDY",
            "rationale": "Government subsidies increase government intervention and spending and are scored -1.",
            "source": "general",
            "scorable": True,
        }

    # ---------------------------------------------------------
    # CALIBRATED RULES
    # ---------------------------------------------------------

    for rule in rules["calibrated_rules"]:
        if rule["pattern_compiled"].search(name.lower()):
            direction = int(rule["direction"])

            if direction == 0:
                direction, category, rationale = fallback_classification(
                    provision
                )

                return {
                    "direction": direction,
                    "category": category,
                    "rule_id": rule["id"] + "-FALLBACK",
                    "rationale": rationale,
                    "source": "fallback",
                    "scorable": True,
                }

            return {
                "direction": direction,
                "category": rule["category"].lower(),
                "rule_id": rule["id"],
                "rationale": rule["rationale"],
                "source": "calibrated",
                "scorable": True,
            }

    # ---------------------------------------------------------
    # GENERAL RULES
    # ---------------------------------------------------------

    matches = [
        r
        for r in rules["general_rules"]
        if r["pattern_compiled"].search(text)
    ]

    signatures = {
        (int(r["direction"]), r["category"].lower())
        for r in matches
    }

    if len(signatures) == 1:
        r = matches[0]

        return {
            "direction": int(r["direction"]),
            "category": r["category"].lower(),
            "rule_id": r["id"],
            "rationale": r["rationale"],
            "source": "general",
            "scorable": True,
        }

    # ---------------------------------------------------------
    # FALLBACK
    # ---------------------------------------------------------

    direction, category, rationale = fallback_classification(provision)

    return {
        "direction": direction,
        "category": category,
        "rule_id": "FALLBACK" if not matches else "FALLBACK-CONFLICT",
        "rationale": rationale,
        "source": "fallback",
        "scorable": True,
    }


# ---------------------------------------------------------------------------
# Scorecard compiler: run with `python scraper/scorecard.py` from repo root.
# ---------------------------------------------------------------------------
MIN_CATEGORY_PROVISIONS = 3
HALF_LIFE_MONTHS = 12
FLOOR_STATUSES = {
    "Senate Floor", "House Floor", "Awaiting Speaker's Call",
    "Awaiting Majority Leader's Call",
}
COMMITTEE_STATUS = "In Committee"
ROOT = Path(__file__).resolve().parents[1]

def _read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _game_date(value):
    m = re.search(r"Week\s+(\d+)\s*,\s*(\d{4})", str(value or ""), re.I)
    return (int(m.group(2)), int(m.group(1))) if m else None

def _month_index(date):
    year, week = date
    return year * 12 + math.floor((week - 1) * 12 / 52)

def _date_text(date):
    return f"Week {date[1]}, {date[0]}" if date else None

def _override(bill, provision, result):
    name = str(provision.get("name", "")).strip().lower()
    if re.fullmatch(r"marijuana\s+(legalization|decriminalization):\s*(legal|decriminalized)", name, re.I):
        return {"direction": 0, "category": None, "rule_id": "NEUTRAL-MARIJUANA", "rationale": "Marijuana legalization/decriminalization is neutral and is not scored.", "source": "override", "scorable": False}
    if re.search(r"\b(veterans?|va|gi bill)\b", name, re.I):
        return {"direction": 1, "category": "economic", "rule_id": "USER-VA-GI-BILL", "rationale": "VA and GI Bill provisions are scored +1 under the user-defined rule.", "source": "override", "scorable": True}
    return result

def _classify_bill(bill, rules, bills_by_id):
    result = []
    for provision in bill.get("provisions") or []:
        classified = _override(bill, provision, classify_provision(bill, provision, rules, bills_by_id))
        result.append({"name": provision.get("name", "Unnamed provision"), **classified})
    return result

def _alignment(provisions):
    scored = [p for p in provisions if p.get("scorable") is not False and p.get("direction") in (-1, 1)]
    total = sum(int(p["direction"]) for p in scored)
    label = "Conservative" if total > 0 else "Liberal" if total < 0 else "Neutral / mixed"
    return total, label, len(scored)

def _score_category(details, category):
    rows = [x for x in details if x.get("category") == category and x.get("direction") in (-1, 1)]
    if len(rows) < MIN_CATEGORY_PROVISIONS:
        return None, len(rows)
    denom = sum(float(x.get("weight", 1)) for x in rows)
    return (100 * sum(float(x.get("weight", 1)) for x in rows if x.get("aligned")) / denom if denom else None), len(rows)

def _tier(score):
    if score is None: return "N/A"
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"

def main():
    rules = _read_json(ROOT / "scorecard_rules.json")
    for group in ("calibrated_rules", "general_rules"):
        for rule in rules.get(group, []):
            rule["pattern_compiled"] = re.compile(rule["pattern"], re.I)
    source_bills = _read_json(ROOT / "bills.json")
    data = _read_json(ROOT / "conservative_scorecard.json")
    bills_by_id = {int(b.get("resolution_id")): b for b in source_bills}
    dated = {}
    for bill in sorted(source_bills, key=lambda x: int(x.get("resolution_id", 0))):
        rid = int(bill.get("resolution_id", 0))
        date = _game_date(bill.get("passed")) or _game_date(bill.get("introduced"))
        if date:
            dated[rid] = date
        elif rid - 1 in dated:
            dated[rid] = dated[rid - 1]
        else:
            previous = [key for key in dated if key < rid]
            if previous: dated[rid] = dated[max(previous)]
    observed = [_game_date(b.get(k)) for b in source_bills for k in ("introduced", "passed")]
    observed = [date for date in observed if date]
    current = max(observed, key=lambda d: (d[0], d[1])) if observed else None
    override_path = ROOT / "current_game_date.txt"
    if override_path.exists(): current = _game_date(override_path.read_text().strip()) or current
    current_index = _month_index(current) if current else 0
    finalized = [b for b in source_bills if b.get("finalized") is True]
    compiled = {}
    for bill in finalized:
        rid = int(bill.get("resolution_id", 0))
        date = dated.get(rid)
        age = max(0, current_index - _month_index(date)) if date else 0
        weight = 0.5 ** (age / HALF_LIFE_MONTHS)
        old = data.get("bills", {}).get(str(rid), {})
        # Reclassify every finalized provision so rule/override changes propagate.
        provisions = _classify_bill(bill, rules, bills_by_id)
        total, label, count = _alignment(provisions)
        old.update({"resolution_id": rid, "number": bill.get("number"), "title": bill.get("title"), "status": bill.get("status"), "finalized": True, "introduced": bill.get("introduced"), "passed": bill.get("passed"), "url": bill.get("url"), "scorecard": {"provisions": provisions, "total": total, "alignment": label, "scored_provisions": count, "weight": weight, "finalized_game_date": _date_text(date), "age_months": age}})
        compiled[str(rid)] = old
    pending = []
    for bill in source_bills:
        if bill.get("finalized") is True: continue
        status = str(bill.get("status") or "")
        if status not in FLOOR_STATUSES and status != COMMITTEE_STATUS: continue
        provisions = _classify_bill(bill, rules, bills_by_id)
        total, label, count = _alignment(provisions)
        pending.append({"resolution_id": int(bill.get("resolution_id", 0)), "number": bill.get("number"), "title": bill.get("title"), "status": status, "committee": bill.get("committee"), "introduced": bill.get("introduced"), "url": bill.get("url"), "sponsor": bill.get("sponsor"), "scorecard": {"provisions": provisions, "total": total, "alignment": label, "scored_provisions": count}})
    for player in data.get("players", []):
        details = player.get("bill_details", [])
        for detail in details:
            detail["weight"] = compiled.get(str(detail.get("resolution_id")), {}).get("scorecard", {}).get("weight", 1.0)
        counts = {cat: sum(1 for x in details if x.get("category") == cat and x.get("direction") in (-1, 1)) for cat in ("social", "economic", "foreign")}
        scores = {}
        for cat in ("social", "economic", "foreign"):
            scores[cat], _ = _score_category(details, cat)
        eligible = any(n >= MIN_CATEGORY_PROVISIONS for n in counts.values())
        scored = [x for x in details if x.get("direction") in (-1, 1)]
        if not eligible or not scored:
            scores = {cat: None for cat in ("social", "economic", "foreign")}
            scores["overall"] = None
            scores["tier"] = "N/A"
        else:
            denom = sum(float(x.get("weight", 1)) for x in scored)
            scores["overall"] = 100 * sum(float(x.get("weight", 1)) for x in scored if x.get("aligned")) / denom if denom else None
            scores["tier"] = _tier(scores["overall"])
        player["scores"] = scores
        player["sample_size"] = {**counts, "overall": len(scored)}
        player["provisions_scored"] = len(scored)
        player["aligned_provisions"] = sum(1 for x in scored if x.get("aligned"))
        player["aligned_votes"] = player["aligned_provisions"]
        player["eligible_for_grade"] = eligible
    data["bills"] = compiled
    data["pending_bills"] = pending
    data["decay"] = {"rule": "Each finalized bill's weight halves every 12 in-game months. Weight is applied per scored provision to weighted alignment percentages; minimum category eligibility uses raw provision counts.", "half_life_months": 12, "current_game_date": _date_text(current), "current_month_index": current_index, "month_model": "year*12 + floor((week-1)*12/52)", "override_file": "current_game_date.txt (optional, format: Week N, YYYY)"}
    data["method"] = "Each finalized bill is scored provision-by-provision (+1 conservative, -1 liberal; neutral provisions excluded). Older bills decay by half every in-game year, applied monthly. Category grades require at least 3 raw scored provisions in that category; overall eligibility requires at least 3 scored provisions in one or more categories. Pending floor/committee bills are shown separately and never affect player scores. User IDs combine multiple profiles."
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write_json(ROOT / "conservative_scorecard.json", data)
    print(f"Updated {len(compiled)} finalized bills, {len(pending)} pending bills, {len(data.get('players', []))} players; game date {_date_text(current)}")

if __name__ == "__main__":
    main()
