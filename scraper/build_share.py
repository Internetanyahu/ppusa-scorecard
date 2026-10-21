#!/usr/bin/env python3
"""Build Discord-friendly share pages and score cards for every player.

For each player in conservative_scorecard.json this writes, under public/share/<id>/:

  index.html  Open Graph / Twitter tags (Discord reads these for its link embed)
              plus an instant redirect into the app at ?player=<id>.
  card.png    A 1200x630 scorecard image used as the embed picture.

The app's "Copy Discord link" button points at public/share/<id>/, so those pages
must exist for the link to produce a widget. Discord does not run JavaScript, so
the tags have to be in the static HTML and the image URL has to be absolute.

Set SITE_BASE to the public URL of the folder that holds index.html and share/
(default: the GitHub Pages "deploy from branch" layout for this repo).
"""
import html
import json
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SCORECARD = ROOT / "conservative_scorecard.json"
OUT_DIR = ROOT / "public" / "share"
SITE_BASE = os.environ.get(
    "SITE_BASE", "https://sk64hd.github.io/ppusa_conservative_scorecard/public/"
).rstrip("/") + "/"

W, H = 1200, 630
BG, PANEL, TEXT, MUTED, TRACK = "#0f172a", "#1e293b", "#f8fafc", "#94a3b8", "#334155"
TIER_COLORS = {"S": "#22c55e", "A": "#22c55e", "B": "#14b8a6", "C": "#f59e0b",
               "D": "#f97316", "F": "#ef4444"}
CATEGORIES = [("social", "Social"), ("economic", "Economic"), ("foreign", "Foreign")]
FONT_BOLD = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
FONT_REG = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]


def font(paths, size):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # Pillow >= 10.1


def fit(draw, text, fnt_paths, size, max_width):
    """Largest font (down to 26px) that fits max_width; ellipsis as a last resort."""
    while size > 26:
        f = font(fnt_paths, size)
        if draw.textlength(text, font=f) <= max_width:
            return f, text
        size -= 2
    f = font(fnt_paths, 26)
    while text and draw.textlength(text + "…", font=f) > max_width:
        text = text[:-1]
    return f, text + "…"


def fmt(score):
    return "N/A" if score is None else f"{score:.1f}"


def player_id(player):
    return str(player.get("user_id") or player.get("player_id") or "").strip()


def safe_dir_name(pid):
    return "".join(c for c in pid if c.isalnum() or c in "-_.") or None


def draw_card(player, path):
    scores = player.get("scores") or {}
    overall, tier = scores.get("overall"), scores.get("tier")
    accent = TIER_COLORS.get(tier, "#64748b")
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 14, H], fill=accent)

    d.text((70, 52), "POWER PLAY USA  ·  CONSERVATIVE SCORECARD", font=font(FONT_BOLD, 26), fill=MUTED)
    name_font, name = fit(d, player.get("name") or "Unknown player", FONT_BOLD, 78, 760)
    d.text((70, 108), name, font=name_font, fill=TEXT)
    sub = " · ".join(x for x in [player.get("state"), (player.get("discord") or "").strip()] if x)
    if sub:
        sub_font, sub = fit(d, sub, FONT_REG, 32, 760)
        d.text((70, 214), sub, font=sub_font, fill=MUTED)

    # Overall score panel
    d.rounded_rectangle([860, 70, 1130, 330], radius=28, fill=PANEL)
    if overall is None:
        d.text((995, 165), "N/A", font=font(FONT_BOLD, 84), fill=MUTED, anchor="mm")
        d.text((995, 245), "not enough votes", font=font(FONT_REG, 26), fill=MUTED, anchor="mm")
    else:
        d.text((995, 150), fmt(overall), font=font(FONT_BOLD, 92), fill=TEXT, anchor="mm")
        d.text((995, 232), f"Overall  ·  Tier {tier}", font=font(FONT_BOLD, 30), fill=accent, anchor="mm")
        d.text((995, 282), "out of 100", font=font(FONT_REG, 24), fill=MUTED, anchor="mm")

    # Category bars
    label, value, bar_x, bar_w = font(FONT_BOLD, 30), font(FONT_BOLD, 30), 300, 640
    for i, (key, title) in enumerate(CATEGORIES):
        y = 382 + i * 68
        score = scores.get(key)
        d.text((70, y), title, font=label, fill=TEXT)
        d.rounded_rectangle([bar_x, y + 6, bar_x + bar_w, y + 34], radius=14, fill=TRACK)
        if score is not None:
            fill_w = max(28, int(bar_w * max(0, min(100, score)) / 100))
            d.rounded_rectangle([bar_x, y + 6, bar_x + fill_w, y + 34], radius=14, fill=accent)
        d.text((bar_x + bar_w + 30, y), fmt(score), font=value, fill=TEXT if score is not None else MUTED)

    n = player.get("finalized_bills_voted", 0)
    d.text((70, 580), f"{n} finalized bill{'s' if n != 1 else ''} voted on  ·  finalized bills only, equal provision weight",
           font=font(FONT_REG, 24), fill=MUTED)
    img.save(path, "PNG", optimize=True)


def page_html(player, pid, folder):
    scores = player.get("scores") or {}
    overall, tier = scores.get("overall"), scores.get("tier")
    name = player.get("name") or "Unknown player"
    n = player.get("finalized_bills_voted", 0)
    title = f"{name} — Conservative Scorecard"
    if overall is None:
        desc = f"No grade yet: {n} of 3 finalized bills voted on."
    else:
        desc = (f"Overall {fmt(overall)} (Tier {tier}) · Social {fmt(scores.get('social'))} · "
                f"Economic {fmt(scores.get('economic'))} · Foreign {fmt(scores.get('foreign'))} · "
                f"{n} finalized bills")
    url = f"{SITE_BASE}share/{folder}/"
    image = f"{url}card.png"
    color = TIER_COLORS.get(tier, "#64748b")
    target = f"../../?player={pid}"
    e = html.escape
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{e(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc, quote=True)}">
<meta name="theme-color" content="{color}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Power Play USA Conservative Scorecard">
<meta property="og:title" content="{e(title, quote=True)}">
<meta property="og:description" content="{e(desc, quote=True)}">
<meta property="og:url" content="{e(url, quote=True)}">
<meta property="og:image" content="{e(image, quote=True)}">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="{W}">
<meta property="og:image:height" content="{H}">
<meta property="og:image:alt" content="{e(title, quote=True)} scorecard">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title, quote=True)}">
<meta name="twitter:description" content="{e(desc, quote=True)}">
<meta name="twitter:image" content="{e(image, quote=True)}">
<meta http-equiv="refresh" content="0; url={e(target, quote=True)}">
<link rel="canonical" href="{e(url, quote=True)}">
</head>
<body>
<p><a href="{e(target, quote=True)}">Open {e(name)}'s scorecard</a></p>
<script>location.replace({json.dumps(target)});</script>
</body>
</html>
"""


def main():
    data = json.loads(SCORECARD.read_text(encoding="utf-8"))
    players = data.get("players", [])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    keep = set()
    built = 0
    for player in players:
        pid = player_id(player)
        folder = safe_dir_name(pid)
        if not pid or not folder:
            continue
        out = OUT_DIR / folder
        out.mkdir(parents=True, exist_ok=True)
        draw_card(player, out / "card.png")
        (out / "index.html").write_text(page_html(player, pid, folder), encoding="utf-8")
        keep.add(folder)
        built += 1
    for stale in OUT_DIR.iterdir():  # drop pages for players that no longer exist
        if stale.is_dir() and stale.name not in keep:
            shutil.rmtree(stale)
    print(f"Share pages built: {built} (base {SITE_BASE})")


if __name__ == "__main__":
    main()
