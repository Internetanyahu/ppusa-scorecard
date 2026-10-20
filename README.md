# Power Play USA Conservative Scorecard

This repository contains the deterministic legislative scorecard and the data pipeline used to compile it.

## Workflows

- **Scrape bills** — `.github/workflows/bills.yml` runs separately and is the only workflow that updates `bills.json` from Power Play USA. It does not control the scorecard's provision-option rules.
- **Compile scorecard** — `.github/workflows/scorecard.yml` consumes the checked-in `bills.json`, refreshes player data, rebuilds history/records, scores finalized bills, validates every provision, and publishes website-ready JSON under `public/data/`.

New provision options should be added to the repository's scoring rules manually when the game is updated. The scorecard compiler never invents or scrapes new provision options.
