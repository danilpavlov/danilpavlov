#!/usr/bin/env python3
"""Generate the language-breakdown SVGs used in README.md.

Pulls byte counts per language across all non-fork public repos of USER and
renders two static SVGs (light/dark) into assets/. Static output means the
README never depends on a third-party stats service being up.

Usage: python3 scripts/gen_languages.py
"""

import colorsys
import json
import os
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

USER = "danilpavlov"
# .ipynb files embed base64 cell outputs, so GitHub's byte count inflates
# Jupyter Notebook to ~90% and drowns out everything else.
EXCLUDE = {"Jupyter Notebook"}
TOP_N = 8

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# github/linguist colors
COLORS = {
    "TeX": "#3D6117",
    "C++": "#f34b7d",
    "Python": "#3572A5",
    "Lua": "#000080",
    "Makefile": "#427819",
    "CMake": "#DA3434",
    "Shell": "#89e051",
    "HTML": "#e34c26",
    "Cuda": "#3A4E3A",
    "Go Template": "#000080",
    "Dockerfile": "#384d54",
    "Jupyter Notebook": "#DA5B0B",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "C": "#555555",
    "Nix": "#7e7eff",
    "Vim Script": "#199f4b",
}
OTHER_COLOR = "#8b949e"

WIDTH = 480
BAR_H = 10
GAP = 22
ROW_H = 22
COLS = 2
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"


def api(url):
    headers = {"User-Agent": "gen-languages"}
    # Unauthenticated GitHub allows 60 requests/hour, and one run costs about
    # one request per repo. Any token raises that to 5000.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    return json.load(urllib.request.urlopen(req))


def collect():
    """Fetch byte counts per language, falling back to the committed cache."""
    try:
        repos = api(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner")
        totals = Counter()
        for repo in repos:
            if repo["fork"]:
                continue
            totals.update(api(repo["languages_url"]))
        ASSETS.mkdir(exist_ok=True)
        (ASSETS / "languages.json").write_text(json.dumps(dict(totals.most_common()), indent=2) + "\n")
    except urllib.error.HTTPError as exc:
        cache = ASSETS / "languages.json"
        if not cache.exists():
            raise
        print(f"warning: GitHub API failed ({exc}), using cached {cache.name}")
        totals = Counter(json.loads(cache.read_text()))
    for name in EXCLUDE:
        totals.pop(name, None)
    return totals


def to_hls(hex_color):
    r, g, b = (int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5))
    return colorsys.rgb_to_hls(r, g, b)


def to_hex(h, l, s):
    r, g, b = colorsys.hls_to_rgb(h % 1.0, l, s)
    return "#%02x%02x%02x" % tuple(round(c * 255) for c in (r, g, b))


def brighten(hex_color, min_light=0.55):
    """Raise lightness so dark linguist colors stay visible on a dark bg."""
    h, l, s = to_hls(hex_color)
    return to_hex(h, max(l, min_light), max(s, 0.45))


def spread_hues(items, min_gap=0.06):
    """Rotate hues apart where linguist colors collide.

    Several languages here share a hue (TeX, Makefile and Shell are all green),
    which turns into one indistinguishable block once the dark variant lifts
    every color's lightness. Largest share keeps its real color; smaller ones
    step aside.
    """
    out, used = [], []
    for name, pct, color in items:
        if name == "Other":
            out.append((name, pct, color))
            continue
        h, l, s = to_hls(color)
        step = 0
        while any(min(abs(h - u), 1 - abs(h - u)) < min_gap for u in used) and step < 12:
            step += 1
            h = (h + (min_gap * 1.5) * (1 if step % 2 else -1) * ((step + 1) // 2)) % 1.0
        used.append(h)
        out.append((name, pct, to_hex(h, l, s) if step else color))
    return out


def shares(totals):
    total = sum(totals.values())
    top = totals.most_common(TOP_N)
    rest = total - sum(v for _, v in top)
    out = [(name, 100 * val / total, COLORS.get(name, OTHER_COLOR)) for name, val in top]
    if rest > 0:
        out.append(("Other", 100 * rest / total, OTHER_COLOR))
    return spread_hues(out)


def render(items, text_color, dark):
    rows = -(-len(items) // COLS)
    height = BAR_H + GAP + rows * ROW_H
    col_w = WIDTH // COLS

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
        f'viewBox="0 0 {WIDTH} {height}" role="img" aria-label="Top programming languages">',
        f'<clipPath id="bar"><rect width="{WIDTH}" height="{BAR_H}" rx="{BAR_H / 2}"/></clipPath>',
        '<g clip-path="url(#bar)">',
    ]

    x = 0.0
    for _, pct, color in items:
        w = WIDTH * pct / 100
        fill = brighten(color) if dark and color != OTHER_COLOR else color
        parts.append(f'<rect x="{x:.2f}" y="0" width="{w:.2f}" height="{BAR_H}" fill="{fill}"/>')
        x += w
    parts.append(f'<rect x="{x:.2f}" y="0" width="{WIDTH - x:.2f}" height="{BAR_H}" fill="{OTHER_COLOR}"/>')
    parts.append("</g>")

    parts.append(f'<g font-family="{FONT}" font-size="12" fill="{text_color}">')
    for i, (name, pct, color) in enumerate(items):
        cx = (i // rows) * col_w + 6
        cy = BAR_H + GAP + (i % rows) * ROW_H
        fill = brighten(color) if dark and color != OTHER_COLOR else color
        parts.append(f'<circle cx="{cx}" cy="{cy - 4}" r="5" fill="{fill}"/>')
        parts.append(f'<text x="{cx + 13}" y="{cy}">{name} {pct:.1f}%</text>')
    parts.append("</g></svg>")
    return "\n".join(parts) + "\n"


def main():
    items = shares(collect())
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "languages-light.svg").write_text(render(items, "#24292f", dark=False))
    (ASSETS / "languages-dark.svg").write_text(render(items, "#c9d1d9", dark=True))
    for name, pct, _ in items:
        print(f"{name:20} {pct:5.1f}%")


if __name__ == "__main__":
    main()
