"""Keep editable scorecard rules safe for the compiler.

A malformed direction is made neutral (0), not silently assigned a policy score.
The admin can then replace it with -1, 0, or +1 per scorecard set.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "scorecard_rules.json"
VALID = {-1, 0, 1}


def main():
    data = json.loads(RULES.read_text(encoding="utf-8"))
    changed = 0
    for key in ("provision_rules", "calibrated_rules", "general_rules"):
        for rule in data.get(key, []):
            try:
                direction = int(rule.get("direction", 0))
            except (TypeError, ValueError):
                direction = 0
            if direction not in VALID:
                print(f"WARNING: malformed direction for {rule.get('name') or rule.get('id')!r}; using neutral 0")
                rule["direction"] = 0
                rule["category"] = None
                rule["neutral"] = True
                changed += 1
            else:
                rule["direction"] = direction
    if changed:
        RULES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Rule normalization complete; repaired {changed} malformed directions.")


if __name__ == "__main__":
    main()
