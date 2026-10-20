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

    # Exact admin assignments are authoritative. This lets the site's policy
    # editor change a provision without rewriting the classifier itself.
    admin = rules.get("admin_policy", {})
    exact = admin.get("provision_overrides", {}).get(name)
    if exact:
        direction = int(exact.get("direction", 0))
        category = exact.get("category")
        if direction not in (-1, 0, 1):
            raise ValueError(f"Invalid admin direction for provision {name!r}: {direction}")
        return {
            "direction": direction,
            "category": category,
            "rule_id": f"ADMIN-{exact.get('group') or 'EXACT'}",
            "rationale": exact.get("rationale") or "Assigned by the scorecard policy editor.",
            "source": "admin",
            "scorable": direction != 0,
        }

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
