import base64
import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

SITE_URL = "https://sk64hd.github.io/ppusa_conservative_scorecard"
ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "public" / "data" / "conservative_scorecard.json"
SHARE_ROOT = ROOT / "public" / "share"


def esc(value):
    return html.escape(str(value or ""), quote=True)


def safe_id(value):
    return quote(str(value), safe="")


def score(value):
    try:
        n = float(value)
        if n != n:
            return None
        return n
    except (TypeError, ValueError):
        return None


def score_palette(value):
    n = score(value)
    if n is None:
        return ("#4b5563", "#e5e7eb")
    if n >= 80:
        return ("#14532d", "#dcfce7")
    if n >= 60:
        return ("#854d0e", "#fef3c7")
    if n >= 40:
        return ("#9a3412", "#ffedd5")
    return ("#991b1b", "#fee2e2")


def fmt(value):
    n = score(value)
    return "N/A" if n is None else (str(int(round(n))) if n.is_integer() else f"{n:.1f}")


def avatar_data(url):
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    convert = shutil.which("convert")
    if not convert:
        return None
    try:
        req = Request(str(url), headers={"User-Agent": "PPUSA-Scorecard/1.0"})
        with urlopen(req, timeout=10) as response:
            raw = response.read()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "avatar"
            target = Path(tmp) / "avatar.png"
            source.write_bytes(raw)
            subprocess.run(
                [convert, str(source), "-thumbnail", "128x128^", "-gravity", "center", "-extent", "128x128", str(target)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return base64.b64encode(target.read_bytes()).decode("ascii")
    except Exception:
        return None


def svg_for_player(player):
    player_id = player.get("user_id") or player.get("player_id")
    name = str(player.get("name") or "Unknown politician")
    discord = str(player.get("discord") or "").strip()
    scores = player.get("scores") or {}
    overall = scores.get("overall")
    tier = scores.get("tier") or "N/A"
    categories = [
        ("SOCIAL", scores.get("social")),
        ("ECONOMIC", scores.get("economic")),
        ("FOREIGN", scores.get("foreign")),
    ]

    overall_fg, overall_bg = score_palette(overall)
    blocks = []
    x_positions = [42, 414, 786]
    for (label, value), x in zip(categories, x_positions):
        fg, bg = score_palette(value)
        blocks.append(
            f'''<rect x="{x}" y="300" width="330" height="190" rx="24" fill="{bg}"/>
<text x="{x + 26}" y="338" font-family="DejaVu Sans,Arial,sans-serif" font-size="22" font-weight="700" fill="#111827">{label}</text>
<text x="{x + 26}" y="402" font-family="DejaVu Sans,Arial,sans-serif" font-size="58" font-weight="800" fill="{fg}">{esc(fmt(value))}</text>
<text x="{x + 26}" y="446" font-family="DejaVu Sans,Arial,sans-serif" font-size="18" fill="#374151">/ 100</text>'''
        )

    avatar = avatar_data(player.get("avatar") or player.get("discord_avatar"))
    if avatar:
        avatar_svg = f'<image href="data:image/png;base64,{avatar}" x="1018" y="34" width="128" height="128" preserveAspectRatio="xMidYMid slice"/>'
    else:
        initials = "".join(part[:1] for part in name.split()[:2]).upper() or "?"
        avatar_svg = f'<circle cx="1082" cy="98" r="64" fill="#374151"/><text x="1082" y="113" text-anchor="middle" font-family="DejaVu Sans,Arial,sans-serif" font-size="40" font-weight="800" fill="#ffffff">{esc(initials)}</text>'

    discord_line = f"@{discord}" if discord and not discord.startswith("@") else discord
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#0b1220"/>
<rect x="30" y="30" width="1140" height="230" rx="28" fill="#111827" stroke="#334155" stroke-width="2"/>
<text x="58" y="68" font-family="DejaVu Sans,Arial,sans-serif" font-size="16" font-weight="700" letter-spacing="2" fill="#94a3b8">POWER PLAY USA · CONSERVATIVE SCORECARD</text>
<text x="58" y="130" font-family="DejaVu Sans,Arial,sans-serif" font-size="24" font-weight="700" fill="#e5e7eb">OVERALL / COMPOSITE SCORE</text>
<text x="58" y="218" font-family="DejaVu Sans,Arial,sans-serif" font-size="82" font-weight="900" fill="{overall_bg}">{esc(fmt(overall))}<tspan font-size="30" fill="#94a3b8"> / 100</tspan></text>
<rect x="365" y="165" width="82" height="46" rx="23" fill="{overall_bg}"/>
<text x="406" y="196" text-anchor="middle" font-family="DejaVu Sans,Arial,sans-serif" font-size="22" font-weight="800" fill="{overall_fg}">{esc(tier)}</text>
<text x="490" y="193" font-family="DejaVu Sans,Arial,sans-serif" font-size="28" font-weight="800" fill="#f8fafc">{esc(name)}</text>
<text x="490" y="228" font-family="DejaVu Sans,Arial,sans-serif" font-size="20" fill="#94a3b8">{esc(discord_line)}</text>
{avatar_svg}
{''.join(blocks)}
<text x="42" y="548" font-family="DejaVu Sans,Arial,sans-serif" font-size="17" fill="#94a3b8">Scores are calculated from the published Power Play USA conservative scorecard.</text>
<text x="42" y="584" font-family="DejaVu Sans,Arial,sans-serif" font-size="16" font-weight="700" fill="#64748b">Click to open this politician's scorecard on GitHub Pages.</text>
</svg>'''
    return svg


def page_for_player(player):
    player_id = player.get("user_id") or player.get("player_id")
    encoded = safe_id(player_id)
    share_url = f"{SITE_URL}/share/{encoded}/"
    target_url = f"{SITE_URL}/?player={quote(str(player_id), safe='')}"
    image_url = f"{share_url}scorecard.png"
    name = str(player.get("name") or "Unknown politician")
    scores = player.get("scores") or {}
    description = (
        f"{name}: overall {fmt(scores.get('overall'))}/100 · "
        f"Social {fmt(scores.get('social'))} · "
        f"Economic {fmt(scores.get('economic'))} · "
        f"Foreign {fmt(scores.get('foreign'))}."
    )
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(name)} — Power Play USA Conservative Scorecard</title>
  <meta name="description" content="{esc(description)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(name)} — Conservative Scorecard">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(share_url)}">
  <meta property="og:image" content="{esc(image_url)}">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{esc(name)} — Conservative Scorecard">
  <meta name="twitter:description" content="{esc(description)}">
  <meta name="twitter:image" content="{esc(image_url)}">
  <meta http-equiv="refresh" content="0;url={esc(target_url)}">
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#0b1220; color:#e5e7eb; font-family:system-ui,sans-serif; }}
    main {{ max-width:760px; padding:32px; text-align:center; }}
    a {{ color:#93c5fd; }}
  </style>
</head>
<body>
  <main>
    <p>Opening <strong>{esc(name)}</strong>'s scorecard…</p>
    <p><a href="{esc(target_url)}">Open scorecard</a></p>
  </main>
  <script>window.location.replace({json.dumps(target_url)});</script>
</body>
</html>
'''


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    players = data.get("players") or []
    SHARE_ROOT.mkdir(parents=True, exist_ok=True)

    generated = 0
    for player in players:
        player_id = player.get("user_id") or player.get("player_id")
        if player_id is None:
            continue
        folder = SHARE_ROOT / safe_id(player_id)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "index.html").write_text(page_for_player(player), encoding="utf-8")
        svg = svg_for_player(player)
        svg_path = folder / "scorecard.svg"
        png_path = folder / "scorecard.png"
        svg_path.write_text(svg, encoding="utf-8")
        subprocess.run(
            ["convert", str(svg_path), "-background", "none", str(png_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        svg_path.unlink(missing_ok=True)
        generated += 1

    print(f"Generated {generated} Discord share pages in {SHARE_ROOT}")


if __name__ == "__main__":
    main()
