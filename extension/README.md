# PPUSA Bill Scraper

The browser extension in this directory is designed to run in the user's browser because Power Play pages may require the user's authenticated session.

## Tokens

Do not put GitHub tokens in source control. The extension should store them only in `chrome.storage.local`. A read token may be used to download the repository's current `bills.json`; a write token may be used to update it. Use a fine-grained GitHub token restricted to this repository with the minimum required Contents permissions.
