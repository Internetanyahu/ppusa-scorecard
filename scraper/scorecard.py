name: Compile Conservative Scorecard

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * *"

concurrency:
  group: data-commit
  cancel-in-progress: false

permissions:
  contents: write
  pages: write
  id-token: write

jobs:
  scorecard:
    name: Compile user scorecards
    runs-on: ubuntu-latest

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Rebuild user identity history
        run: python scraper/build_history.py

      - name: Compile conservative scorecard, pending bills, and decay
        run: python scraper/scorecard.py

      - name: Build combined voting records
        run: python scraper/build_records.py

      - name: Build website data
        run: |
          mkdir -p public/data
          cp bills.json public/data/bills.json
          cp conservative_scorecard.json public/data/conservative_scorecard.json
          cp legislative_history.json public/data/legislative_history.json
          cp players.json public/data/players.json
          cp scorecard_rules.json public/data/scorecard_rules.json
          cp voting_records.json public/data/voting_records.json

      - name: Validate outputs
        run: |
          python - <<'PY'
          import json
          from pathlib import Path

          required_files = [
              "bills.json",
              "players.json",
              "player_index.json",
              "legislative_history.json",
              "voting_records.json",
              "conservative_scorecard.json",
              "scorecard_review.json",
          ]

          for filename in required_files:
              path = Path(filename)
              if not path.exists():
                  raise SystemExit(f"Missing required file: {filename}")
              json.loads(path.read_text(encoding="utf-8"))

          public_scorecard = Path(
              "public/data/conservative_scorecard.json"
          )

          if not public_scorecard.exists():
              raise SystemExit(
                  "Missing public/data/conservative_scorecard.json"
              )

          json.loads(public_scorecard.read_text(encoding="utf-8"))

          scorecard = json.loads(
              Path("conservative_scorecard.json").read_text(
                  encoding="utf-8"
              )
          )

          bills = scorecard.get("bills", {})

          for bill in bills.values():
              scorecard_data = bill.get("scorecard", {})
              provisions = scorecard_data.get("provisions", [])

              for provision in provisions:
                  name = str(
                      provision.get("name", "")
                  ).strip().lower()

                  direction = provision.get("direction")
                  scorable = provision.get("scorable", True)

                  if name == "custom bill":
                      if direction != 0 or scorable is not False:
                          raise SystemExit(
                              "Custom Bill must be neutral "
                              "(direction 0, scorable false): "
                              f"{provision!r}"
                          )
                      continue

                  if scorable is False:
                      if direction != 0:
                          raise SystemExit(
                              "Neutral provision must have direction 0: "
                              f"{provision!r}"
                          )
                      continue

                  if direction not in (-1, 1):
                      resolution_id = bill.get("resolution_id")
                      raise SystemExit(
                          "Invalid provision direction for "
                          f"resolution {resolution_id}: "
                          f"{provision!r}"
                      )

          print(
              "All scorecard outputs validated, "
              "including neutral Custom Bills."
          )
          PY

      - name: Commit compiled data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

          git add \
            players.json \
            player_index.json \
            legislative_history.json \
            voting_records.json \
            conservative_scorecard.json \
            scorecard_rules.json \
            identity_review.json \
            scorecard_review.json

          git diff --cached --quiet || \
            git commit -m "Update conservative scorecard"

          git pull --rebase
          git push

      - name: Configure Pages
        uses: actions/configure-pages@v5

      - name: Upload Pages artifact
        uses: actions/upload-pages-artifact@v3
        with:
          path: ./public

      - name: Deploy Pages
        uses: actions/deploy-pages@v4
