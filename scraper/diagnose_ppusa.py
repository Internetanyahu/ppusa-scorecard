import json
import re
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE_URL = "https://powerplayusa.net"
OUT = Path("ppusa_diagnostic.txt")
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
)

SENSITIVE = re.compile(r"(authorization|cookie|set-cookie|token|secret|password|api[-_]?key|client[-_]?secret)", re.I)
INTERESTING = re.compile(r"(whitelist|allowlist|developer|service.?token|cloudflare|api|authorization|access)", re.I)


def safe_headers(headers):
    out = {}
    for k, v in headers.items():
        if SENSITIVE.search(k):
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out


def main():
    lines = []
    def log(s=""):
        lines.append(s)
        print(s)

    log("PPUSA ACCESS DIAGNOSTIC")
    log("This report identifies visible access/security mechanisms only.")
    log("Secrets, cookies, authorization values, and token values are redacted.")
    log()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        responses = []
        requests = []

        page.on("request", lambda r: requests.append(r))
        page.on("response", lambda r: responses.append(r))

        try:
            response = page.goto(
                f"{BASE_URL}/resolutions/1",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)
        except Exception as exc:
            log(f"NAVIGATION ERROR: {type(exc).__name__}: {exc}")
            log(f"Final URL: {page.url}")
            browser.close()
            OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

        log(f"HTTP STATUS: {response.status if response else 'unknown'}")
        log(f"FINAL URL: {page.url}")
        log(f"PAGE TITLE: {page.title()}")
        log()

        if response:
            log("MAIN RESPONSE HEADERS:")
            for k, v in safe_headers(response.headers).items():
                if INTERESTING.search(k) or k.lower() in {"server", "location", "content-security-policy"}:
                    log(f"  {k}: {v}")
            log()

        log("VISIBLE CLOUDFLARE INDICATORS:")
        cf = []
        for r in responses:
            if any(x in r.headers for x in ("cf-ray", "cf-cache-status", "server")):
                cf.append((r.url, r.status, {k: v for k, v in r.headers.items() if k.startswith("cf-") or k == "server"}))
        if cf:
            for url, status, headers in cf[:20]:
                log(f"  {status} {url}")
                for k, v in headers.items():
                    log(f"    {k}: {v}")
        else:
            log("  No obvious Cloudflare response headers found.")
        log()

        log("SECURITY/CSP HEADERS:")
        if response:
            for k, v in response.headers.items():
                if "security" in k.lower() or "content-security-policy" in k.lower():
                    log(f"  {k}: {v}")
        log()

        html = page.content()
        log("HTML SECURITY/AUTH REFERENCES:")
        matches = sorted(set(re.findall(r"[^\"'<>]{0,100}(?:whitelist|allowlist|developer|service.?token|cloudflare|authorization|api)[^\"'<>]{0,160}", html, re.I)))
        for m in matches[:100]:
            log("  " + re.sub(r"\s+", " ", m).strip())
        if not matches:
            log("  None found in initial HTML.")
        log()

        log("NETWORK REQUESTS WITH POSSIBLE ACCESS/AUTH CLUES:")
        seen = set()
        for r in requests:
            key = (r.method, r.url)
            if key in seen or not INTERESTING.search(r.url):
                continue
            seen.add(key)
            log(f"  {r.method} {r.url}")
            hdr = safe_headers(r.headers)
            interesting_headers = {k: v for k, v in hdr.items() if INTERESTING.search(k)}
            for k, v in interesting_headers.items():
                log(f"    {k}: {v}")
        if not seen:
            log("  None found.")
        log()

        log("SCRIPT SOURCES TO INSPECT:")
        scripts = page.locator("script[src]").evaluate_all("els => els.map(e => e.src)")
        for src in sorted(set(scripts)):
            log(f"  {src}")
        log()

        log("CONCLUSION:")
        if page.url != f"{BASE_URL}/resolutions/1":
            log("  The bill request was redirected. The redirect destination is above.")
        if any("cf-ray" in r.headers for r in responses):
            log("  Cloudflare headers were observed. Any actual Cloudflare allowlist is server-side and is not exposed by this report.")
        else:
            log("  No Cloudflare-specific header was confirmed from this request.")
        log("  A browser extension domain-whitelist.txt is not treated as the PPUSA server whitelist.")

        browser.close()

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
