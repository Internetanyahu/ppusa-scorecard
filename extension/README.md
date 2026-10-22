# PPUSA Bill & Office Scraper

This Chrome extension runs in the user's browser so it can use the user's Power Play session when needed.

## API token

Paste one fine-grained GitHub API token into the extension. It is stored only in `chrome.storage.local` and is used for both reading and writing:

- `bills.json`
- `offices.json`

The token needs **Contents: Read and write** access to `SK64HD/ppusa-scorecard` and no broader repository permissions.

`API_TOKEN.txt` is intentionally blank. It is a local placeholder for helper code that needs a token; never commit the actual token.

## Scraping

- **Scrape current page**: bill pages update `bills.json`; main politician wiki pages update `offices.json`.
- **Paginate bills to 404**: starts after the highest stored bill ID and stops at the first real 404. It does not use a five-miss heuristic.
- Office scraping uses the main politician wiki page and the same page structure represented by `examples/powerplayusa.net_wiki_politician_1007`.
