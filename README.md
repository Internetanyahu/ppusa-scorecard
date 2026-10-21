# PPUSA-SCORECARD

This repository contains the PPUSA-SCORECARD legislative scorecard and the data pipeline used to compile and publish it.

The site supports multiple selectable scorecard sets, including the Conservative Scorecard and State's Rights Index.

## Workflows

- **Scrape bills** — `.github/workflows/bills.yml` runs separately and updates `bills.json` from Power Play USA.
- **Compile PPUSA-SCORECARD** — `.github/workflows/scorecard.yml` consumes the checked-in bill data, refreshes player data, rebuilds history/records, scores finalized bills, validates every provision, and publishes website-ready JSON under `public/data/`.

Provision scoring remains editable through the scorecard configuration. The compiler does not invent new provision options.
