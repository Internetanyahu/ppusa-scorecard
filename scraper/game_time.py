import json
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "https://powerplayusa.net/national/politicians"
OUT = Path("game_time.json")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ))
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    data = page.evaluate("""() => ({
        politicians: window.politiciansData || null,
        body: document.body.innerText || '',
        title: document.title
    })""")
    browser.close()

# Power Play has changed its public game-clock representation over time, so
# inspect the page's embedded data and visible text without assuming one field.
blob = json.dumps(data.get("politicians") or {}, ensure_ascii=False)
text = data.get("body", "")
patterns = [
    r"(?i)(?:game\s*time|in[- ]game\s*time|current\s*time)\s*[:\-]?\s*([^\n]+)",
    r"(?i)\b(day|week)\s*[:\-]?\s*(\d+)\b",
]
import re
found = {}
for pat in patterns:
    for m in re.finditer(pat, text):
        found[m.group(1).lower().replace(" ", "_")] = m.group(2) if m.lastindex and m.lastindex >= 2 else m.group(1)

# Also search embedded JSON for common clock keys.
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
