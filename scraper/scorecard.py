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
