import re
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
API_PATTERNS = (
    r"(?:https?:)?//[^\"'\\s<>]+",
    r"/(?:api|ajax|graphql|trpc|json|data|backend)[^\"'\\s<>]*",
    r"/(?:resolutions?|bills?)[^\"'\\s<>]*(?:json|api|ajax)[^\"'\\s<>]*",
)


def response_line(response):
    headers = response.all_headers()
    extras = []
    for key in ("server", "cf-ray", "cf-mitigated"):
        value = headers.get(key, "")
        if value:
            extras.append(f"{key}={value}")
    suffix = " " + " ".join(extras) if extras else ""
    return f"HTTP {response.status} {response.url}{suffix}"


def page_markers(page):
    try:
        text = page.locator("body").inner_text(timeout=5000).lower()[:50000]
    except Exception:
        text = ""
    return [marker for marker in CHALLENGE_MARKERS if marker in text]


def inspect_app_sources(page):
    print("\nAPP SOURCE / API CANDIDATE SCAN")
    script_urls = page.locator("script[src]").evaluate_all(
        "els => els.map(e => e.src).filter(Boolean)"
    )
    print(f"SCRIPT_URLS: {len(script_urls)}")
    candidates = set()

    inline_scripts = page.locator("script:not([src])").evaluate_all(
        "els => els.map(e => e.textContent || '')"
    )
    for text in inline_scripts:
        for pattern in API_PATTERNS:
            for match in re.findall(pattern, text, flags=re.I):
                candidates.add(match[:500])

    for src in script_urls[:40]:
        try:
            response = page.request.get(src, timeout=15000)
            if response.status != 200:
                continue
            text = response.text()
            for pattern in API_PATTERNS:
                for match in re.findall(pattern, text, flags=re.I):
                    candidates.add(match[:500])
        except Exception as exc:
            print(f"SCRIPT_READ_ERROR: {src} {type(exc).__name__}")

    useful = sorted(
        c for c in candidates
        if any(word in c.lower() for word in ("api", "ajax", "graphql", "resolution", "bill", "data", "json"))
    )
    if useful:
        for candidate in useful[:200]:
            print(f"API_CANDIDATE: {candidate}")
    else:
        print("API_CANDIDATE: none found in accessible HTML/JS")


def check_page(page, url, label, inspect_sources=False):
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
        for line in seen[-30:]:
            print(f"RESPONSE: {line}")
        if inspect_sources and not markers:
            inspect_app_sources(page)
        return markers
    finally:
        page.remove_listener("response", on_response)


def main():
    print("PPUSA safe scraper-pattern/API diagnostic")
    print("This does not bypass challenges or increase bill request volume.")
    failures = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        try:
            markers = check_page(
                page,
                ROSTER_URL,
                "ROSTER - same URL as scraper/main.py",
                inspect_sources=True,
            )
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
