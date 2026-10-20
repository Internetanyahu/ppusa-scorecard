"""
Deterministic conservative legislative scorecard compiler.

Rules:
- Only finalized bills affect player scores.
- Each scored provision is evaluated independently.
- +1 = conservative/rightward.
- -1 = liberal/leftward.
- 0 = neutral and excluded from scoring.
- Marijuana legalization/decriminalization is neutral.
- Nuclear energy itself is neutral.
- Custom Bills are neutral.
- Taxes are -1.
- Subsidies are -1.
- Tax credits are +1 except non-nuclear green-energy credits, which are -1.
- VA/GI Bill provisions are +1 under the configured policy.
- Category grades require at least 3 raw scored provisions.
- Overall grade requires at least 3 scored provisions in at least one category.
- Finalized bills decay by half every 12 in-game months.
- Pending bills are informational only.
"""

import html
import json
import math
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MIN_CATEGORY_PROVISIONS = 3
HALF_LIFE_MONTHS = 12

CATEGORIES = ("social", "economic", "foreign")

FLOOR_STATUSES = {
    "Senate Floor",
    "House Floor",
    "Awaiting Speaker's Call",
    "Awaiting Majority Leader's Call",
}

COMMITTEE_STATUS = "In Committee"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def game_date(value):
    match = re.search(
        r"Week\s+(\d+)\s*,\s*(\d{4})",
        str(value or ""),
        re.I,
    )
    if not match:
        return None

    return int(match.group(2)), int(match.group(1))


def month_index(date):
    if not date:
        return 0

    year, week = date
    return year * 12 + math.floor((week - 1) * 12 / 52)


def date_text(date):
    if not date:
        return None

    return f"Week {date[1]}, {date[0]}"


def provision_text(provision):
    parts = []

    for key in (
        "name",
        "title",
        "description",
        "summary",
        "text",
        "details",
    ):
        value = provision.get(key)

        if value is not None:
            parts.append(str(value))

    return " ".join(parts)


def fallback_classification(provision):
    text = provision_text(provision).lower()

    if re.search(
        r"\b("
        r"abortion|parental|school prayer|religion|gun|firearm|"
        r"immigration|border|crime|police|sentenc|marriage|gender|"
        r"election integrity"
        r")\b",
        text,
    ):
        return (
            1,
            "social",
            "Fallback social-policy classification.",
        )

    if re.search(
        r"\b("
        r"tax|spending|budget|debt|subsid|welfare|minimum wage|union|"
        r"regulation|business|trade|tariff|veteran|va|gi bill"
        r")\b",
        text,
    ):
        direction = (
            1
            if re.search(
                r"\b("
                r"tax cut|reduce tax|deregulat|tariff|protection|"
                r"veteran|va|gi bill"
                r")\b",
                text,
            )
            else -1
        )

        return (
            direction,
            "economic",
            "Fallback economic classification.",
        )

    if re.search(
        r"\b("
        r"military|defense|foreign|war|troop|sanction|treaty|"
        r"nato|overseas|invasion|aid to"
        r")\b",
        text,
    ):
        direction = (
            1
            if re.search(
                r"\b("
                r"defense|military readiness|anti-communist|hemispheric"
                r")\b",
                text,
            )
            else -1
        )

        return (
            direction,
            "foreign",
            "Fallback foreign-policy classification.",
        )

    return (
        -1,
        "economic",
        "Fallback unmatched provision classification.",
    )


def classify_provision(bill, provision, rules):
    name = str(provision.get("name", "")).strip()
    text = provision_text(provision)

    admin = rules.get("admin_policy", {})
    overrides = admin.get("provision_overrides", {})

    exact = overrides.get(name)

    if exact is not None:
        direction = int(exact.get("direction", 0))

        if direction not in (-1, 0, 1):
            raise ValueError(
                f"Invalid admin direction for {name!r}: {direction}"
            )

        category = exact.get("category")

        if category:
            category = str(category).lower()

        return {
            "direction": direction,
            "category": category,
            "rule_id": f"ADMIN-{exact.get('group') or 'EXACT'}",
            "rationale": (
                exact.get("rationale")
                or "Assigned by the scorecard policy editor."
            ),
            "source": "admin",
            "scorable": direction != 0,
        }

    if re.fullmatch(
        r"marijuana\s+(legalization|decriminalization):\s*"
        r"(legal|decriminalized)",
        name,
        re.I,
    ):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "NEUTRAL-MARIJUANA",
            "rationale": (
                "Marijuana legalization/decriminalization is neutral."
            ),
            "source": "neutral",
            "scorable": False,
        }

    if re.fullmatch(
        r"nuclear energy:\s*(expanded|allowed|legal|neutral)",
        name,
        re.I,
    ):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "NEUTRAL-NUCLEAR",
            "rationale": "Nuclear energy itself is neutral.",
            "source": "neutral",
            "scorable": False,
        }

    if re.fullmatch(r"custom\s+bill", name, re.I):
        return {
            "direction": 0,
            "category": None,
            "rule_id": "CUSTOM-BILL-NEUTRAL",
            "rationale": "Custom Bills are neutral.",
            "source": "neutral",
            "scorable": False,
        }

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
                "rationale": (
                    "Non-nuclear green-energy tax credits are scored -1."
                ),
                "source": "general",
                "scorable": True,
            }

        return {
            "direction": 1,
            "category": "economic",
            "rule_id": "GENERAL-TAX-CREDIT",
            "rationale": "Tax credits are scored +1.",
            "source": "general",
            "scorable": True,
        }

    if re.search(
        r"\b("
        r"tax|taxes|taxation|sales tax|excise tax|income tax|"
        r"corporate tax|capital gains tax|payroll tax|property tax"
        r")\b",
        text,
        re.I,
    ):
        return {
            "direction": -1,
            "category": "economic",
            "rule_id": "GENERAL-TAX",
            "rationale": "Taxation is scored -1.",
            "source": "general",
            "scorable": True,
        }

    if re.search(r"\bsubsid(?:y|ies|ized)\b", text, re.I):
        return {
            "direction": -1,
            "category": "economic",
            "rule_id": "GENERAL-SUBSIDY",
            "rationale": "Government subsidies are scored -1.",
            "source": "general",
            "scorable": True,
        }

    for rule in rules.get("calibrated_rules", []):
        pattern = rule.get("pattern_compiled")

        if pattern and pattern.search(name.lower()):
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
                "category": str(rule["category"]).lower(),
                "rule_id": rule["id"],
                "rationale": rule["rationale"],
                "source": "calibrated",
                "scorable": True,
            }

    matches = []

    for rule in rules.get("general_rules", []):
        pattern = rule.get("pattern_compiled")

        if pattern and pattern.search(text):
            matches.append(rule)

    signatures = {
        (
            int(rule["direction"]),
            str(rule["category"]).lower(),
        )
        for rule in matches
    }

    if len(signatures) == 1:
        rule = matches[0]

        return {
            "direction": int(rule["direction"]),
            "category": str(rule["category"]).lower(),
            "rule_id": rule["id"],
            "rationale": rule["rationale"],
            "source": "general",
            "scorable": True,
        }

    direction, category, rationale = fallback_classification(provision)

    return {
        "direction": direction,
        "category": category,
        "rule_id": (
            "FALLBACK"
            if not matches
            else "FALLBACK-CONFLICT"
        ),
        "rationale": rationale,
        "source": "fallback",
        "scorable": True,
    }


def build_rule_index(rules):
    for group in ("calibrated_rules", "general_rules"):
        for rule in rules.get(group, []):
            rule["pattern_compiled"] = re.compile(
                rule["pattern"],
                re.I,
            )


def classify_bill(bill, rules):
    provisions = []

    for provision in bill.get("provisions") or []:
        result = classify_provision(
            bill,
            provision,
            rules,
        )

        provisions.append(
            {
                "name": provision.get(
                    "name",
                    "Unnamed provision",
                ),
                **result,
            }
        )

    return provisions


def alignment(provisions):
    scored = [
        provision
        for provision in provisions
        if (
            provision.get("scorable") is not False
            and provision.get("direction") in (-1, 1)
        )
    ]

    total = sum(
        int(provision["direction"])
        for provision in scored
    )

    if total > 0:
        label = "Conservative"
    elif total < 0:
        label = "Liberal"
    else:
        label = "Neutral / mixed"

    return total, label, len(scored)


def tier(score):
    if score is None:
        return "N/A"

    if score >= 90:
        return "A+"

    if score >= 80:
        return "A"

    if score >= 70:
        return "B"

    if score >= 60:
        return "C"

    if score >= 50:
        return "D"

    return "F"


def score_category(details, category):
    rows = [
        row
        for row in details
        if (
            row.get("category") == category
            and row.get("direction") in (-1, 1)
        )
    ]

    if len(rows) < MIN_CATEGORY_PROVISIONS:
        return None, len(rows)

    denominator = sum(
        float(row.get("weight", 1.0))
        for row in rows
    )

    aligned = sum(
        float(row.get("weight", 1.0))
        for row in rows
        if row.get("aligned")
    )

    if denominator == 0:
        return None, len(rows)

    return (
        100 * aligned / denominator,
        len(rows),
    )


def reclassify_player_details(details, compiled):
    result = []

    for detail in details:
        resolution_id = str(
            detail.get("resolution_id", "")
        )

        bill = compiled.get(resolution_id)

        if not bill:
            continue

        provision_name = str(
            detail.get("provision", "")
        ).strip()

        provision = None

        for candidate in bill.get(
            "scorecard",
            {},
        ).get("provisions", []):
            if (
                str(candidate.get("name", "")).strip()
                == provision_name
            ):
                provision = candidate
                break

        if provision is None:
            provision = {
                "direction": 0,
                "category": None,
                "scorable": False,
            }

        vote = str(
            detail.get("vote", "")
        ).lower()

        direction = int(
            provision.get("direction", 0)
        )

        aligned = (
            direction == 1
            and vote == "aye"
        ) or (
            direction == -1
            and vote == "nay"
        )

        updated = dict(detail)

        updated["category"] = provision.get(
            "category"
        )

        updated["direction"] = direction

        updated["aligned"] = (
            bool(aligned)
            if direction in (-1, 1)
            else False
        )

        updated["scorable"] = provision.get(
            "scorable",
            direction in (-1, 1),
        )

        updated["weight"] = bill.get(
            "scorecard",
            {},
        ).get("weight", 1.0)

        result.append(updated)

    return result


def compute_player_scores(details):
    scored = [
        row
        for row in details
        if (
            row.get("scorable") is not False
            and row.get("direction") in (-1, 1)
        )
    ]

    counts = {
        category: sum(
            1
            for row in scored
            if row.get("category") == category
        )
        for category in CATEGORIES
    }

    scores = {}

    for category in CATEGORIES:
        scores[category], _ = score_category(
            details,
            category,
        )

    eligible = any(
        count >= MIN_CATEGORY_PROVISIONS
        for count in counts.values()
    )

    if not eligible or not scored:
        return (
            {
                "social": None,
                "economic": None,
                "foreign": None,
                "overall": None,
                "tier": "N/A",
            },
            counts,
            len(scored),
        )

    denominator = sum(
        float(row.get("weight", 1.0))
        for row in scored
    )

    aligned = sum(
        float(row.get("weight", 1.0))
        for row in scored
        if row.get("aligned")
    )

    overall = (
        100 * aligned / denominator
        if denominator
        else None
    )

    scores["overall"] = overall
    scores["tier"] = tier(overall)

    return scores, counts, len(scored)


def site_base_url():
    explicit = os.environ.get(
        "SCORECARD_SITE_URL",
        "",
    ).strip().rstrip("/")

    if explicit:
        return explicit

    repository = os.environ.get(
        "GITHUB_REPOSITORY",
        "",
    ).strip()

    if "/" in repository:
        owner, repo = repository.split(
            "/",
            1,
        )

        return (
            f"https://{owner}.github.io/{repo}"
        ).rstrip("/")

    return ""


def write_share_pages(data):
    public = ROOT / "public"
    share_root = public / "share"

    share_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    for child in list(share_root.iterdir()):
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()

    ranked_players = [
        player
        for player in data.get("players", [])
        if player.get("scores", {}).get("overall")
        is not None
    ]

    ranked_players.sort(
        key=lambda player: float(
            player["scores"]["overall"]
        ),
        reverse=True,
    )

    ranks = {}

    for index, player in enumerate(
        ranked_players,
        start=1,
    ):
        player_id = str(
            player.get("user_id")
            or player.get("player_id")
            or ""
        ).strip()

        if player_id:
            ranks[player_id] = index

    base_url = site_base_url()

    total_ranked = len(ranked_players)

    for player in data.get("players", []):
        player_id = str(
            player.get("user_id")
            or player.get("player_id")
            or ""
        ).strip()

        if not player_id:
            continue

        scores = player.get("scores", {})

        score = scores.get("overall")
        tier_value = scores.get(
            "tier",
            "N/A",
        )

        score_text = (
            "N/A"
            if score is None
            else f"{float(score):.2f}"
        )

        rank = ranks.get(player_id)

        rank_text = (
            f"#{rank} of {total_ranked}"
            if rank
            else "N/A"
        )

        name = str(
            player.get("name")
            or "PPUSA Player"
        )

        page_url = (
            f"{base_url}/share/{player_id}/"
            if base_url
            else f"share/{player_id}/"
        )

        scorecard_url = (
            f"{base_url}/?player={player_id}"
            if base_url
            else f"../../?player={player_id}"
        )

        title = (
            f"{name} — Chud Score "
            f"{score_text}/100 · "
            f"Chud Ranking {rank_text}"
        )

        description = (
            f"{name}'s Power Play USA "
            f"Conservative Scorecard. "
            f"Chud Score: {score_text}/100 · "
            f"Chud Ranking: {rank_text} · "
            f"Tier: {tier_value}."
        )

        safe_title = html.escape(title)
        safe_description = html.escape(
            description,
            quote=True,
        )
        safe_url = html.escape(
            page_url,
            quote=True,
        )
        safe_name = html.escape(name)

        page = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>

  <meta name="description"
        content="{safe_description}">

  <meta property="og:type"
        content="website">

  <meta property="og:title"
        content="{safe_title}">

  <meta property="og:description"
        content="{safe_description}">

  <meta property="og:url"
        content="{safe_url}">

  <meta name="twitter:card"
        content="summary">

  <meta name="twitter:title"
        content="{safe_title}">

  <meta name="twitter:description"
        content="{safe_description}">
</head>

<body>
  <main>
    <h1>{safe_name}</h1>

    <p>
      <strong>Chud Score:</strong>
      {html.escape(score_text)}/100
    </p>

    <p>
      <strong>Chud Ranking:</strong>
      {html.escape(rank_text)}
    </p>

    <p>
      <strong>Tier:</strong>
      {html.escape(str(tier_value))}
    </p>

    <p>
      <a href="{html.escape(scorecard_url, quote=True)}">
        View PPUSA Scorecard
      </a>
    </p>
  </main>

  <script>
    window.location.replace(
      {json.dumps(scorecard_url)}
    );
  </script>
</body>
</html>
"""

        player_dir = (
            share_root / player_id
        )

        player_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        (player_dir / "index.html").write_text(
            page,
            encoding="utf-8",
        )


def main():
    rules = read_json(
        ROOT / "scorecard_rules.json"
    )

    build_rule_index(rules)

    source_bills = read_json(
        ROOT / "bills.json"
    )

    data = read_json(
        ROOT / "conservative_scorecard.json"
    )

    bills_by_id = {
        str(bill.get("resolution_id")): bill
        for bill in source_bills
    }

    dated = {}

    for bill in sorted(
        source_bills,
        key=lambda value: int(
            value.get("resolution_id", 0)
        ),
    ):
        resolution_id = str(
            bill.get("resolution_id")
        )

        date = (
            game_date(bill.get("passed"))
            or game_date(bill.get("introduced"))
        )

        if date:
            dated[resolution_id] = date
            continue

        previous = [
            (int(key), value)
            for key, value in dated.items()
            if int(key) < int(resolution_id)
        ]

        if previous:
            dated[resolution_id] = max(
                previous,
                key=lambda item: item[0],
            )[1]

    observed_dates = []

    for bill in source_bills:
        for field in ("introduced", "passed"):
            date = game_date(
                bill.get(field)
            )

            if date:
                observed_dates.append(date)

    current = (
        max(
            observed_dates,
            key=lambda value: (
                value[0],
                value[1],
            ),
        )
        if observed_dates
        else None
    )

    override_path = (
        ROOT / "current_game_date.txt"
    )

    if override_path.exists():
        override_date = game_date(
            override_path.read_text(
                encoding="utf-8"
            ).strip()
        )

        if override_date:
            current = override_date

    current_index = month_index(current)

    finalized = [
        bill
        for bill in source_bills
        if bill.get("finalized") is True
    ]

    compiled = {}

    for bill in finalized:
        resolution_id = str(
            bill.get("resolution_id")
        )

        date = dated.get(resolution_id)

        age = (
            max(
                0,
                current_index
                - month_index(date),
            )
            if date
            else 0
        )

        weight = (
            0.5 ** (
                age / HALF_LIFE_MONTHS
            )
        )

        old = data.get(
            "bills",
            {},
        ).get(
            resolution_id,
            {},
        )

        provisions = classify_bill(
            bill,
            rules,
        )

        total, bill_alignment, count = alignment(
            provisions
        )

        old.update(
            {
                "resolution_id": int(
                    bill.get("resolution_id")
                ),
                "number": bill.get("number"),
                "title": bill.get("title"),
                "status": bill.get("status"),
                "finalized": True,
                "introduced": bill.get(
                    "introduced"
                ),
                "passed": bill.get("passed"),
                "url": bill.get("url"),
                "scorecard": {
                    "provisions": provisions,
                    "total": total,
                    "alignment": bill_alignment,
                    "scored_provisions": count,
                    "weight": weight,
                    "finalized_game_date": date_text(
                        date
                    ),
                    "age_months": age,
                },
            }
        )

        compiled[resolution_id] = old

    pending = []

    for bill in source_bills:
        if bill.get("finalized") is True:
            continue

        status = str(
            bill.get("status") or ""
        )

        if (
            status not in FLOOR_STATUSES
            and status != COMMITTEE_STATUS
        ):
            continue

        provisions = classify_bill(
            bill,
            rules,
        )

        total, bill_alignment, count = alignment(
            provisions
        )

        pending.append(
            {
                "resolution_id": int(
                    bill.get("resolution_id")
                ),
                "number": bill.get("number"),
                "title": bill.get("title"),
                "status": status,
                "committee": bill.get(
                    "committee"
                ),
                "introduced": bill.get(
                    "introduced"
                ),
                "url": bill.get("url"),
                "sponsor": bill.get(
                    "sponsor"
                ),
                "finalized": False,
                "scorecard": {
                    "provisions": provisions,
                    "total": total,
                    "alignment": bill_alignment,
                    "scored_provisions": count,
                },
            }
        )

    for player in data.get("players", []):
        details = reclassify_player_details(
            player.get("bill_details", []),
            compiled,
        )

        scores, counts, scored_count = (
            compute_player_scores(details)
        )

        player["bill_details"] = details
        player["scores"] = scores

        player["sample_size"] = {
            **counts,
            "overall": scored_count,
        }

        player["provisions_scored"] = (
            scored_count
        )

        player["aligned_provisions"] = sum(
            1
            for row in details
            if (
                row.get("scorable") is not False
                and row.get("aligned")
            )
        )

        player["aligned_votes"] = (
            player["aligned_provisions"]
        )

        player["eligible_for_grade"] = any(
            count >= MIN_CATEGORY_PROVISIONS
            for count in counts.values()
        )

    named_provisions = sorted(
        {
            str(provision.get("name", "")).strip()
            for bill in source_bills
            for provision in (
                bill.get("provisions") or []
            )
            if str(
                provision.get("name", "")
            ).strip()
        }
    )

    admin_overrides = (
        rules.get("admin_policy", {})
        .get("provision_overrides", {})
    )

    unassigned = [
        name
        for name in named_provisions
        if name not in admin_overrides
    ]

    data["bills"] = compiled
    data["pending_bills"] = pending

    data["policy_assignment_coverage"] = {
        "named_provisions_in_bills": len(
            named_provisions
        ),
        "explicitly_assigned": (
            len(named_provisions)
            - len(unassigned)
        ),
        "unassigned": unassigned,
        "complete_for_current_bills": not unassigned,
    }

    data["decay"] = {
        "rule": (
            "Each finalized bill's weight halves every "
            "12 in-game months. Weight is applied per "
            "scored provision to weighted alignment "
            "percentages; minimum category eligibility "
            "uses raw provision counts."
        ),
        "half_life_months": 12,
        "current_game_date": date_text(current),
        "current_month_index": current_index,
        "month_model": (
            "year*12 + floor((week-1)*12/52)"
        ),
        "override_file": (
            "current_game_date.txt "
            "(optional, format: Week N, YYYY)"
        ),
    }

    data["method"] = (
        "Every named provision currently present in "
        "bills.json has an explicit policy assignment "
        "of +1 Conservative, 0 Neutral, or -1 Liberal. "
        "Neutral provisions do not affect scores. "
        "Finalized bills only affect scores. Older "
        "finalized bills decay monthly by a half-life "
        "of 12 in-game months. Category grades require "
        "at least 3 raw scored provisions in that "
        "category; overall eligibility requires at "
        "least 3 scored provisions in at least one "
        "category. Pending floor and committee bills "
        "are displayed separately and never affect "
        "player scores."
    )

    data["generated_at"] = (
        datetime.now(
            timezone.utc
        ).isoformat(
            timespec="seconds"
        )
    )

    write_json(
        ROOT / "conservative_scorecard.json",
        data,
    )

    write_share_pages(data)

    print(
        f"Updated {len(compiled)} finalized bills, "
        f"{len(pending)} pending bills, "
        f"{len(data.get('players', []))} players; "
        f"game date {date_text(current)}; "
        f"explicit provision assignments "
        f"{len(named_provisions) - len(unassigned)}/"
        f"{len(named_provisions)}."
    )


if __name__ == "__main__":
    main()
