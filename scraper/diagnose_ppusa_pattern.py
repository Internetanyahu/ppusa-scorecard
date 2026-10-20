import re
import sys
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

BASE_URL = "https://powerplayusa.net"
ROSTER_URL = f"{BASE_URL}/national/politicians"
BILL_IDS = [1, 2, 3, 4, 5]
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

SENSITIVE_HEADERS = {"set-cookie", "cookie", "authorization", "proxy-authorization"}
CHALLENGE_MARKERS = (
    "cf-chl-",
    "cf-challenge",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies",
)


def clean_header(name, value):
    if name.lower() in SENSITIVE_HEADERS:
        return "<redacted>"
    return value


def response_line(response):
    headers = response.all_headers()
    server = headers.get("server", "")
    cf_ray = headers.get("cf-ray", "")
    cf_mitigated = headers.get("cf-mitigated", "")
    extras = []
    if server:
        extras.append(f"server={server}")
    if cf_ray:
        extras.append(f"cf-ray={cf_ray}")
    if cf_mitigated:
        extras.append(f"cf-mitigated={cf_mitigated}")
    suffix = " " + " ".join(extras) if extras else ""
    return f"HTTP {response.status} {response.url}{suffix}"


def page_markers(page):
    try:
        text = page.locator("body").inner_text(timeout=5000).lower()[:50000]
    except Exception:
        text = ""
    return [marker for marker in CHALLENGE_MARKERS if marker in text]


def check_page(page, url, label):
    print(f"\n[{label}] {url}")
    seen = []

    def on_response(response):
        if urlparse(response.url).netloc.endswith("powerplayusa.net"):
            if response.request.resource_type in {"document", "xhr", "fetch"}:
                seen.append(response_line(response))

    page.on("response", on_response)
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        print(f"FINAL_URL: {page.url}")
        print(f"TITLE: {page.title()}")
        if response:
            print(f"NAVIGATION: {response_line(response)}")
        markers = page_markers(page)
        print(f"CLOUDFLARE_CHALLENGE_MARKERS: {markers or 'none'}")
        for line in seen[-20:]:
            print(f"RESPONSE: {line}")
        return markers
    finally:
        page.remove_listener("response", on_response)


def main():
    print("PPUSA safe scraper-pattern diagnostic")
    print("This does not bypass challenges or increase request volume.")
    failures = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            markers = check_page(page, ROSTER_URL, "ROSTER - same URL as scraper/main.py")
            if markers:
                failures += 1

            for resolution_id in BILL_IDS:
                markers = check_page(
                    page,
                    f"{BASE_URL}/resolutions/{resolution_id}",
                    f"BILL {resolution_id} - same URL pattern as scraper/bills.py",
                )
                if markers:
                    failures += 1
        finally:
            browser.close()

    print("\nSUMMARY")
    print(f"Pages checked: {1 + len(BILL_IDS)}")
    print(f"Pages with Cloudflare challenge markers: {failures}")
    if failures:
        print("RESULT: challenge/block evidence was observed in this run.")
    else:
        print("RESULT: no Cloudflare challenge markers were observed in this run.")
    print("Note: a clean run proves only that this request pattern passed at this time.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"DIAGNOSTIC_ERROR: {type(exc).__name__}: {exc}")
        sys.exit(1)
