"""Scrape Power Play USA's create-legislation page for the current provision catalog."""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

BASE_URL = "https://powerplayusa.net"
URL = f"{BASE_URL}/chambers/create-resolution"
OUT_FILE = Path("resolution_provisions.json")
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()
USER_AGENT = (
    "Mozilla/5.0 (compatible; PPUSA-Scorecard-Bot/1.0; "
    "+https://github.com/SK64HD/ppusa-scorecard)"
)

EXTRACT_JS = r"""
() => {
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  const body = clean(document.body ? document.body.innerText : '');
  const security = /performing security verification|security service to protect against malicious bots/i.test(body);
  if (security) return { security: true, title: document.title, snippet: body.slice(0, 800), provisions: [] };
  const values = [];
  const seen = new Set();
  const add = (value, source) => {
    const text = clean(value);
    if (!text || seen.has(text)) return;
    seen.add(text);
    values.push({ name: text, source });
  };
  for (const option of document.querySelectorAll('option')) {
    const text = clean(option.textContent);
    const value = clean(option.value);
    const combined = `${text} ${value}`;
    if (/provision|effect|policy|tax|visa|marriage|military|spending|health|border|gun|education|energy|trade/i.test(combined)) add(text || value, 'option');
  }
  for (const input of document.querySelectorAll('input, textarea, [data-provision], [data-provision-name]')) {
    const label = input.getAttribute('data-provision') || input.getAttribute('data-provision-name') || input.getAttribute('name') || input.getAttribute('placeholder') || '';
    if (/provision/i.test(label)) add(input.value || input.getAttribute('value') || label, 'input');
  }
  return { security: false, title: document.title, provisions: values, form_count: document.querySelectorAll('form').length, option_count: document.querySelectorAll('option').length };
}
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        if SCRAPER_TOKEN:
            async def add_token(route, request):
                await (route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN}) if request.url.startswith(BASE_URL) else route.continue_())
            await context.route("**/*", add_token)
            print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
        page = await context.new_page()
        try:
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)
            raw = await page.evaluate(EXTRACT_JS)
        finally:
            await browser.close()

    if raw.get("security"):
        print("ERROR: RESOLUTION SCRAPER STOPPED — POWER PLAY SECURITY VERIFICATION DETECTED.")
        print(f"title={raw.get('title')!r} text={raw.get('snippet')!r}")
        raise SystemExit(2)

    provisions = raw.get("provisions") or []
    if not provisions:
        print("ERROR: create-resolution page returned no provision candidates.")
        print(json.dumps(raw, indent=2, ensure_ascii=False))
        raise SystemExit(1)

    old = {}
    if OUT_FILE.exists():
        try:
            old = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = {}

    old_names = {str(x).strip() for x in old.get("provisions", []) if str(x).strip()}
    new_names = {x["name"] for x in provisions if x.get("name")}
    added = sorted(new_names - old_names)
    removed = sorted(old_names - new_names)

    result = {
        "source_url": URL,
        "scraped_at": now_iso(),
        "title": raw.get("title", ""),
        "provisions": sorted(new_names),
        "added_since_last_scrape": added,
        "removed_since_last_scrape": removed,
        "option_count": raw.get("option_count", 0),
        "form_count": raw.get("form_count", 0),
    }
    OUT_FILE.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Provision catalog: {len(new_names)} candidates")
    if added:
        print("NEW PROVISIONS DETECTED:")
        for name in added: print(f"  + {name}")
    if removed:
        print("PROVISIONS NO LONGER EXPOSED:")
        for name in removed: print(f"  - {name}")


if __name__ == "__main__":
    asyncio.run(main())
