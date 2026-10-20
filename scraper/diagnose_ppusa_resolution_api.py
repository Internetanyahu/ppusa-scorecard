import re
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE_URL = "https://powerplayusa.net"
ROSTER_URL = f"{BASE_URL}/national/politicians"

KEYWORDS = re.compile(
    r"(?:/api/|ajax|graphql|json|fetch\(|axios|/resolutions?/|resolution|bill|provision|vote|voters|legislation)",
    re.I,
)
URL_RE = re.compile(
    r"(?:https?://[^\"'`\\s]+|/api/[^\"'`\\s]+|/[^\"'`\\s]*(?:resolution|bill|vote|provision)[^\"'`\\s]*)",
    re.I,
)


def clean_url(url):
    return url.replace("\\/", "/").replace("\\u0026", "&")


def main():
    print("PPUSA resolution/API source diagnostic")
    print("This only inspects public page HTML/JavaScript. It does not bypass Cloudflare or submit protected requests.")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/154.0.0.0 Safari/537.36"
            )
        )

        responses = []
        page.on("response", lambda r: responses.append((r.status, r.url, r.headers.get("content-type", ""))))
        response = page.goto(ROSTER_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"ROSTER: {response.status if response else 'unknown'} {page.url}")
        if not response or response.status >= 400:
            print("Roster page was not available; cannot inspect its script references safely.")
            browser.close()
            return

        html = page.content()
        print(f"HTML bytes: {len(html)}")
        print()

        script_urls = page.eval_on_selector_all(
            "script[src]",
            "els => els.map(e => e.src).filter(Boolean)"
        )
        script_urls = list(dict.fromkeys(script_urls))
        print(f"SCRIPT FILES: {len(script_urls)}")

        candidates = set()
        for src in script_urls:
            try:
                text = page.request.get(src, timeout=15000).text()
            except Exception as exc:
                print(f"SCRIPT ERROR: {src} ({exc})")
                continue

            matches = []
            for match in URL_RE.findall(text):
                value = clean_url(match)
                if KEYWORDS.search(value):
                    matches.append(value)
                    candidates.add(value)

            if matches:
                print(f"SCRIPT: {src}")
                for value in sorted(set(matches))[:80]:
                    print(f"  {value[:500]}")

            # Print short source-context snippets around resolution/bill/vote API strings.
            for needle in ("/api/", "resolution", "bill", "provision", "vote"):
                for m in list(re.finditer(needle, text, re.I))[:8]:
                    start = max(0, m.start() - 180)
                    end = min(len(text), m.end() + 260)
                    snippet = re.sub(r"\s+", " ", text[start:end])
                    if "/api/" in snippet.lower() or "fetch(" in snippet.lower() or "axios" in snippet.lower():
                        print(f"  CONTEXT[{needle}]: {snippet[:700]}")

        print()
        print("INLINE HTML URL/API CANDIDATES")
        for value in sorted(set(URL_RE.findall(html))):
            value = clean_url(value)
            if KEYWORDS.search(value):
                print(f"  {value[:500]}")
                candidates.add(value)

        print()
        print("OBSERVED SAME-ORIGIN RESPONSES FROM ROSTER PAGE")
        for status, url, content_type in responses:
            if url.startswith(BASE_URL) and (
                "/api/" in url or "json" in content_type.lower() or
                any(k in url.lower() for k in ("resolution", "bill", "vote", "provision"))
            ):
                print(f"  {status} {url} [{content_type}]")

        print()
        print("UNIQUE CANDIDATES")
        for value in sorted(candidates):
            if value.startswith("/"):
                value = urljoin(BASE_URL, value)
            print(f"  {value[:700]}")

        browser.close()


if __name__ == "__main__":
    main()
