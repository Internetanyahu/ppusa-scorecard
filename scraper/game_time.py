import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"
BASE_URL = "https://powerplayusa.net"
OUT = Path("game_time.json")
TOKEN_HEADER = "X-PPUSA-Scorecard-Token"
SCRAPER_TOKEN = os.environ.get("SCRAPER_TOKEN", "").strip()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36"
    ))
    if SCRAPER_TOKEN:
        def add_token(route, request):
            route.continue_(headers={**request.headers, TOKEN_HEADER: SCRAPER_TOKEN})
        context.route("**/*", add_token)
        print(f"Sending {TOKEN_HEADER} to {BASE_URL}")
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    data = page.evaluate("""() => ({
        politicians: window.politiciansData || null,
        body: document.body.innerText || '',
        title: document.title
    })""")
    browser.close()

if re.search(r"performing security verification|security service to protect against malicious bots", data.get("body", ""), re.I):
    raise SystemExit("GAME TIME SCRAPER STOPPED: Power Play security verification detected")

blob = json.dumps(data.get("politicians") or {}, ensure_ascii=False)
text = data.get("body", "")
patterns = [
    r"(?i)(?:game\s*time|in[- ]game\s*time|current\s*time)\s*[:\-]?\s*([^\n]+)",
    r"(?i)\b(day|week)\s*[:\-]?\s*(\d+)\b",
]
found = {}
for pat in patterns:
    for m in re.finditer(pat, text):
        found[m.group(1).lower().replace(" ", "_")] = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)

obj = data.get("politicians") or {}
clock = {}
def walk(x):
    if isinstance(x, dict):
        for k, v in x.items():
            lk = str(k).lower()
            if any(t in lk for t in ("game_time", "gametime", "game_day", "game_week", "current_day", "current_week")):
                clock[k] = v
            walk(v)
    elif isinstance(x, list):
        for v in x[:20]:
            walk(v)
walk(obj)

result = {
    "scraped_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
    "source": URL,
    "page_title": data.get("title", ""),
    "clock_fields": clock,
    "visible_matches": found,
}
OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, ensure_ascii=False))
