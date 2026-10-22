"""Validate saved Power Play page-source examples against the production parsers.

This is deliberately separate from the live scrapers: fixtures prove that changes to
DOM extraction do not silently break the known Power Play HTML shape.
"""
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from main import parse_source_html
from bills import EXTRACT_JS, build_bill, SECURITY_VERIFICATION_RE

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
POLITICIANS = EXAMPLES / "powerplayusa.net_national_politicians.txt"
BILL = EXAMPLES / "powerplayusa.net_resolutions_1.txt"


def validate_politicians():
    source = POLITICIANS.read_text(encoding="utf-8")
    politicians, title, meta, _ = parse_source_html(source)
    if not politicians:
        raise RuntimeError("Politicians fixture produced no players")
    required = {"user_id", "name", "partyAbbreviation2", "stateName", "is_main"}
    missing = required - set(politicians[0])
    if missing:
        raise RuntimeError(f"Politicians fixture is missing expected fields: {sorted(missing)}")
    if "American Politicians" not in title:
        raise RuntimeError(f"Unexpected politicians title: {title!r}")
    print(f"OK politicians fixture: {len(politicians)} players; title={title!r}")


async def validate_bill():
    source = BILL.read_text(encoding="utf-8")
    if SECURITY_VERIFICATION_RE.search(source):
        raise RuntimeError("Bill fixture unexpectedly contains a security verification page")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.set_content(source, wait_until="domcontentloaded")
        raw = await page.evaluate(EXTRACT_JS)
        await browser.close()
    if raw.get("security"):
        raise RuntimeError("Bill fixture was classified as a security verification page")
    if not raw.get("found"):
        raise RuntimeError(f"Bill fixture was not recognized; h4s={raw.get('h4s')}")
    bill = build_bill(raw, 1)
    if bill["title"] != "Same-Sex Marriage Act":
        raise RuntimeError(f"Unexpected bill title: {bill['title']!r}")
    if not bill["sponsor"] or bill["sponsor"]["name"] != "Gary Locke":
        raise RuntimeError("Sponsor parsing failed")
    if not bill["provisions"]:
        raise RuntimeError("Provision parsing failed")
    if sum(len(v) for chamber in bill["votes"].values() for v in chamber.values()) == 0:
        raise RuntimeError("Vote parsing returned no voters")
    print(f"OK bill fixture: {bill['title']!r}; provisions={len(bill['provisions'])}")


async def main():
    validate_politicians()
    await validate_bill()
    print("Power Play source examples validated successfully.")


if __name__ == "__main__":
    asyncio.run(main())
