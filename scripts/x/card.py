#!/usr/bin/env python3
"""Draws the daily top-N card (1200x630, the link-preview size) from top.cjs output."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONTS = Path(__file__).resolve().parent.parent.parent / "assets" / "fonts"
S = 2
INK, FAINT, RED = (236, 238, 242), (140, 148, 160), (255, 77, 61)
TIER = {"ELITE": (245, 196, 81), "STRONG": (74, 222, 128), "SOLID": (107, 168, 255),
        "FRINGE": (140, 153, 168), "LONGSHOT": (94, 106, 120)}
LOOK = {
    "nba": {"bg": (11, 15, 20), "accent": (255, 138, 61), "unit": "PROJ PTS"},
    "nhl": {"bg": (11, 15, 20), "accent": (124, 200, 255), "unit": "PROJ SOG"},
    "nfl": {"bg": (12, 17, 16), "accent": (255, 77, 61), "unit": "PROJ YDS"},
}
HANDLE = "@yaboitroy247"


def osw(sz, w=600):
    f = ImageFont.truetype(str(FONTS / "Oswald.ttf"), sz)
    try:
        f.set_variation_by_axes([w])
    except Exception:
        pass
    return f


def mono(sz, bold=True):
    return ImageFont.truetype(str(FONTS / ("IBMPlexMono-Bold.ttf" if bold else "IBMPlexMono-SemiBold.ttf")), sz)


def draw(data, out):
    look = LOOK[data["sport"]]
    bg, accent = look["bg"], look["accent"]
    rows = data["rows"]
    W, H = 1200 * S, 630 * S
    im = Image.new("RGBA", (W, H), bg + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * .15, -H * .75, W * .85, H * .35], fill=accent + (46,))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(120 * S)))
    d = ImageDraw.Draw(im, "RGBA")

    x0 = 56 * S
    tf = osw(54 * S)
    d.text((x0, 30 * S), data["name"], font=tf, fill=INK)
    d.text((x0 + d.textlength(data["name"] + " ", font=tf), 30 * S), "HQ", font=tf, fill=RED)
    d.text((x0, 100 * S), data["league"] + "  ·  " + data["line"], font=mono(18 * S), fill=accent)
    d.line([x0, 136 * S, W - x0, 136 * S], fill=(255, 255, 255, 30), width=2 * S)

    per_col = 5
    cols = 1 if len(rows) <= per_col else 2
    gap = 40 * S
    colw = (W - 2 * x0 - (gap if cols == 2 else 0)) // cols
    rh, top = 84 * S, 150 * S
    for i, r in enumerate(rows):
        x = x0 + (i // per_col) * (colw + gap)
        y = top + (i % per_col) * rh
        if i % per_col:
            d.line([x, y, x + colw, y], fill=(255, 255, 255, 16), width=S)
        d.text((x, y + 22 * S), str(i + 1), font=mono(21 * S), fill=FAINT)
        d.text((x + 42 * S, y + 10 * S), r["name"], font=osw(29 * S, 500), fill=INK)
        d.text((x + 42 * S, y + 47 * S), r["sub"], font=mono(14 * S, False), fill=FAINT)
        col = TIER.get(r["tier"], FAINT)
        cx, cy, rr = x + colw - 34 * S, y + 36 * S, 28 * S
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=4 * S, fill=(25, 28, 34, 255))
        sf = osw(26 * S)
        sv = str(r["score"])
        bb = d.textbbox((0, 0), sv, font=sf)
        d.text((cx - d.textlength(sv, font=sf) / 2, cy - (bb[1] + bb[3]) / 2), sv, font=sf, fill=INK)
        tl = mono(11 * S)
        d.text((cx - d.textlength(r["tier"], font=tl) / 2, cy + rr + 3 * S), r["tier"], font=tl, fill=col)
        if r.get("proj"):
            pf, uf = mono(21 * S), mono(11 * S, False)
            right = cx - rr - 18 * S
            d.text((right - d.textlength(r["proj"], font=pf), y + 14 * S), r["proj"], font=pf, fill=INK)
            d.text((right - d.textlength(look["unit"], font=uf), y + 46 * S), look["unit"], font=uf, fill=FAINT)

    ff = mono(17 * S)
    site = data["url"].split("//")[1].strip("/")
    d.text((x0, H - 50 * S), site, font=ff, fill=INK)
    d.text((x0 + d.textlength(site + "  ", font=ff), H - 50 * S), HANDLE, font=ff, fill=accent)
    note = "Scores 0–100 · analysis, not guarantees"
    nf = mono(14 * S, False)
    d.text((W - x0 - d.textlength(note, font=nf), H - 48 * S), note, font=nf, fill=FAINT)
    im.convert("RGB").resize((1200, 630), Image.LANCZOS).save(out, optimize=True)


if __name__ == "__main__":
    draw(json.load(open(sys.argv[1])), sys.argv[2])
