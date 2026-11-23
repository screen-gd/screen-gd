"""Build the profile README panels as SVGs.

GitHub strips CSS from READMEs, so every styled panel is an image. Each SVG embeds
its fonts (Geist Mono, Geist Pixel) and bitmaps, so it renders the same everywhere.

The design is a quiet profile on a transparent background: a dithered portrait
tile beside a dither-gradient pixel wordmark, framed project screenshots with
one-line captions, outlined link buttons and an animated pixel harbour city. Every
image is built twice, dark and light, and the README picks between them with
<picture> and prefers-color-scheme. The portrait is assets/portrait.png, baked
by astro-dither through scripts/bake_portrait.py (needs a browser, run manually).

Usage: python scripts/build_profile.py
"""

import base64
import hashlib
import io
import random
import re
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image

from icons import GLOBE, ICONS

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ROOT / "fonts"

# Panels are drawn at 880 units, close to GitHub's README column, so 14 stays ~14px.
W = 880

# The legacy dark ramp, still used by repos.svg.
MIDNIGHT = "#02070A"
SURFACE = "#071017"
LINE = "#16232D"
TEXT = "#E6EDF2"
SECOND = "#8B98A4"
MUTED = "#52606B"
ACCENT = "#0297DE"
GITCAFE = "#A78BFA"

# The new transparent panels: dark for GitHub's dark mode, light for its light
# one. RULE lines and CHIP fills are ACCENT at per-theme opacities; WM is the
# wordmark's dither palette, darkest colour last.
THEMES = {
    "dark": {"TEXT": "#E6EDF2", "SECOND": "#8B98A4", "MUTED": "#52606B",
             "ACCENT": "#0297DE", "RULE": ".28", "CHIP": ".1",
             "WM": ["#0E4F80", "#0297DE", "#FFFFFF"]},
    "light": {"TEXT": "#0B1620", "SECOND": "#3A4752", "MUTED": "#6B7884",
              "ACCENT": "#0969A8", "RULE": ".5", "CHIP": ".14",
              "WM": ["#8CC9EC", "#0969A8", "#0B1620"]},
}

MONO_ADVANCE = 0.6  # Geist Mono advance per em

LANG_COLORS = {"TypeScript": "#3178C6", "JavaScript": "#F1E05A", "Python": "#3572A5"}


# ---------------------------------------------------------------- fonts

def subset(font: TTFont, text: str) -> str:
    options = Options()
    options.flavor = "woff2"
    options.layout_features = []
    subsetter = Subsetter(options)
    subsetter.populate(text=text + " ")
    subsetter.subset(font)
    font.flavor = "woff2"
    buffer = io.BytesIO()
    font.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()


def font_faces(text: str, pixel_text: str = "") -> str:
    rules = []
    for weight, name in ((400, "GeistMono-Regular.ttf"), (500, "GeistMono-Medium.ttf")):
        data = subset(TTFont(FONTS / name), text)
        rules.append(f"@font-face{{font-family:GM;font-weight:{weight};"
                     f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    if pixel_text:
        # ELSH 1 is the "Square" cut: each pixel a separate square, like the dither.
        pixel = instantiateVariableFont(TTFont(FONTS / "GeistPixel.ttf"), {"ELSH": 1})
        data = subset(pixel, pixel_text)
        rules.append(f"@font-face{{font-family:GP;src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return "".join(rules)


def css(th: dict, text: str, extra: str = "", pixel_text: str = "") -> str:
    """The <style> content for one themed panel: font subsets, text classes and
    any animation rules the panel needs."""
    return (
        font_faces(text, pixel_text)
        + f"text{{font-family:GM,'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f"fill:{th['SECOND']};white-space:pre}}"
        f".p{{fill:{th['TEXT']}}}.m{{fill:{th['MUTED']}}}.a{{fill:{th['ACCENT']}}}.w{{font-weight:500}}"
        + (".px{font-family:GP,'Geist Pixel','Geist Mono',monospace}" if pixel_text else "")
        + "image{image-rendering:pixelated}" + extra
    )


def repos_css(text: str) -> str:
    """The style block repos.svg was always built with, kept so the regenerated
    file stays byte-identical to the old one."""
    return (
        font_faces(text)
        + f"text{{font-family:GM,'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f"fill:{SECOND};white-space:pre}}"
        f".p{{fill:{TEXT}}}.m{{fill:{MUTED}}}.a{{fill:{ACCENT}}}.w{{font-weight:500}}"
        f".px{{font-family:GP,'Geist Pixel','Geist Mono',monospace;fill:{TEXT}}}"
        "image{image-rendering:pixelated}"
    )


def svg(width: float, height: float, title: str, body: list[str], style: str,
        viewbox: tuple[float, float, float, float] | None = None) -> str:
    vb = viewbox or (0, 0, width, height)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width:g}" height="{height:g}" '
        f'viewBox="{vb[0]:g} {vb[1]:g} {vb[2]:g} {vb[3]:g}" role="img">'
        f"<title>{escape(title)}</title><style>{style}</style>{''.join(body)}</svg>\n"
    )


class Text:
    """Collects every string drawn so the font subsets cover exactly those glyphs."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    def __call__(self, x: float, y: float, content: str, size: int = 14, cls: str = "",
                 anchor: str = "start") -> str:
        self.seen.append(content)
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        return f'<text x="{x:g}" y="{y:g}" font-size="{size}"{c}{a} xml:space="preserve">{escape(content)}</text>'

    @property
    def all(self) -> str:
        return "".join(self.seen)


def rect(x: float, y: float, w: float, h: float, fill: str = "none", stroke: str = "") -> str:
    if stroke:
        return (f'<rect x="{x + .5:g}" y="{y + .5:g}" width="{w - 1:g}" height="{h - 1:g}" '
                f'fill="{fill}" stroke="{stroke}"/>')
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}"/>'


def notch(x: float, y: float, w: float, h: float, n: float) -> str:
    """A rectangle path with one n-square step cut from every corner, used for
    fills, strokes and clipPaths in place of rounded corners."""
    return (f"M{x + n:g} {y:g}H{x + w - n:g}V{y + n:g}H{x + w:g}V{y + h - n:g}"
            f"H{x + w - n:g}V{y + h:g}H{x + n:g}V{y + h - n:g}H{x:g}V{y + n:g}H{x + n:g}Z")


def clip(clip_id: str, x: float, y: float, w: float, h: float, n: float = 4) -> str:
    """A notched clipPath. Ids only need to be unique within each SVG file."""
    return f'<clipPath id="{clip_id}"><path d="{notch(x, y, w, h, n)}"/></clipPath>'


def hline(x1: float, x2: float, y: float, color: str = LINE) -> str:
    return f'<line x1="{x1:g}" y1="{y + .5:g}" x2="{x2:g}" y2="{y + .5:g}" stroke="{color}"/>'


def rule(x0: float, x1: float, y: float, th: dict) -> str:
    """A 1px RULE divider line."""
    return (f'<line x1="{x0:g}" y1="{y + .5:g}" x2="{x1:g}" y2="{y + .5:g}" '
            f'stroke="{th["ACCENT"]}" stroke-opacity="{th["RULE"]}"/>')


def rule_notch(x: float, y: float, w: float, h: float, th: dict, n: float = 4) -> str:
    """A notched 1px RULE stroke, on half pixels so it renders crisp."""
    return (f'<path d="{notch(x + .5, y + .5, w - 1, h - 1, n)}" fill="none" '
            f'stroke="{th["ACCENT"]}" stroke-opacity="{th["RULE"]}"/>')


def window_bar(t: Text, x: float, y: float, w: float, index: str, label: str, note: str = "",
               fill: str = SURFACE, line: str = LINE) -> list[str]:
    """A tmux-style title bar: index, name and a muted note on the right."""
    h = 28
    parts = [rect(x, y, w, h, fill), hline(x, x + w, y + h - 1, line)]
    parts.append(rect(x + 8, y + 6, 16, 16, "#0B2233"))
    parts.append(t(x + 16, y + 18, index, 12, "a w", "middle"))
    parts.append(t(x + 32, y + 18, label, 12, "p w"))
    if note:
        parts.append(t(x + w - 12, y + 18, note, 12, "m", "end"))
    return parts


def jpeg_data(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, "JPEG", quality=86, optimize=True, progressive=True)
    return base64.b64encode(buffer.getvalue()).decode()


def image(x: float, y: float, w: float, h: float, data: str, mime: str,
          cls: str = "") -> str:
    uri = f"data:{mime};base64,{data}"
    c = f' class="{cls}"' if cls else ""
    return (f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'preserveAspectRatio="xMidYMid slice" href="{uri}" xlink:href="{uri}"{c}/>')


# ---------------------------------------------------------------- dither

BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
]) / 64 + 1 / 128


def dither_gradient(w: int, h: int, box_h: int, colors: list[str], cell: int = 2) -> str:
    """A vertical ordered-dither gradient PNG for the wordmark mask: solid top
    colour over the top 55% of the visible box, thinning to sparse dots at its
    foot and empty below it. Palette index 0 is transparent."""
    gw, gh = w // cell, h // cell
    v = np.linspace(0, h / box_h, gh)[:, None]  # position in box heights
    tone = np.clip(1 - (v - 0.55) / 0.45 * 0.7, 0, 1)
    thr = np.tile(BAYER8, (gh // 8 + 1, gw // 8 + 1))[:gh, :gw]
    idx = np.clip(np.floor(tone * 3 + thr), 0, 3).astype(np.uint8)
    img = Image.fromarray(idx, "P")
    flat = []
    for c in ["#000000"] + colors:
        flat += [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    img.putpalette(flat)
    img = img.resize((gw * cell, gh * cell), Image.NEAREST)
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True, transparency=0)
    return base64.b64encode(buffer.getvalue()).decode()


# ---------------------------------------------------------------- profile blocks

def wordmark_box(text: str) -> tuple[tuple[float, float, float, float], int]:
    """Ink bounds of `text` in the Square cut of Geist Pixel, measured from the
    actual outlines: ((left, bottom, right, top) in font units relative to the
    pen origin and baseline, unitsPerEm)."""
    font = instantiateVariableFont(TTFont(FONTS / "GeistPixel.ttf"), {"ELSH": 1})
    cmap, hmtx, gs = font.getBestCmap(), font["hmtx"], font.getGlyphSet()
    pen = BoundsPen(gs)
    pos = 0.0
    for c in text:
        gs[cmap[ord(c)]].draw(TransformPen(pen, (1, 0, 0, 1, pos, 0)))
        pos += hmtx[cmap[ord(c)]][0]
    return pen.bounds, font["head"].unitsPerEm


def portrait_tile(th: dict, portrait: str) -> list[str]:
    """The baked portrait as an opaque notched RULE-framed tile at the master
    position (x=6, y=16, 288x288). Emitted into every slice that shows it."""
    return [clip("av", 6, 16, 288, 288),
            f'<g clip-path="url(#av)">{image(6, 16, 288, 288, portrait, "image/png")}</g>',
            rule_notch(6, 16, 288, 288, th)]


def intro(th: dict, portrait: str) -> dict[str, str]:
    """The master top block cut into the `intro` and `portrait-foot` slices:
    the portrait tile on the left; on the right a pixel wordmark filled with
    an animated ordered-dither gradient, a role line and a meta line. The three
    link images sit beside portrait-foot, so the portrait is cut at y=264."""
    t = Text()
    body = portrait_tile(th, portrait)

    # Wordmark: largest size whose ink fits 500 units, S top at y=16. The mask
    # and the dither image keep a >=6-unit margin around the ink box at every
    # point of the breathing animation, so no glyph edge is clipped.
    (lx, ly, rx, ry), upm = wordmark_box("Screen")
    size = int(500 / (rx - lx) * upm * 10) / 10
    x, baseline = 336, 16 + ry / upm * size
    cell, margin = 2, 6
    box_x = int(np.floor((x - margin) / cell)) * cell
    box_w = int(np.ceil((x + (rx - lx) / upm * size + margin) / cell)) * cell - box_x
    top = int(np.floor((16 - margin) / cell)) * cell
    box_h = int(np.ceil((baseline - ly / upm * size + margin) / cell)) * cell - top
    spare = int(round(0.4 * box_h / cell)) * cell
    grad = dither_gradient(box_w, box_h + spare, box_h, th["WM"], cell)
    body.append(
        f'<mask id="wm" maskUnits="userSpaceOnUse" x="{box_x}" y="{top}" '
        f'width="{box_w}" height="{box_h}">'
        f'<text x="{x - lx / upm * size:g}" y="{baseline:g}" font-size="{size:g}" '
        'class="px" style="fill:#fff">Screen</text></mask>'
        f'<g mask="url(#wm)">'
        f'{image(box_x, top, box_w, box_h + spare, grad, "image/png", "wmd")}</g>')
    body.append(t(x, baseline + 36, "Product designer and developer", 16, "p"))
    # GitCafe's mark is a flat purple square beside its lowercase name. Both
    # lines are 16px; the square sits on whole pixels, centred on the cap height.
    line = round(baseline + 67)
    body.append(rect(x, line - 13, 14, 14, GITCAFE))
    body.append(t(x + 24, line, "gitcafe", 16, "p w"))
    # Geist Mono advances 0.6em, so the name above is 7 * 16 * 0.6 wide.
    body.append(t(x + 24 + 7 * 16 * .6, line, " · SWE intern", 16))

    steps = spare // cell
    extra = (f'@keyframes wmd{{to{{transform:translateY(-{spare}px)}}}}'
             f'.wmd{{animation:wmd 7s steps({steps}) infinite alternate}}'
             '@media(prefers-reduced-motion:reduce){.wmd{animation:none}}')
    title = ("Screen: product designer and developer. Building Col and Emc². "
             "Working at GitCafe.")
    out = {"intro": svg(W, 264, title, body, css(th, t.all, extra, "Screen"),
                        (0, 0, W, 264))}
    # The foot slice is only the tile's bottom 40 units; it needs no fonts.
    out["portrait-foot"] = svg(330, 56, "", portrait_tile(th, portrait),
                               "image{image-rendering:pixelated}", (0, 264, 330, 56))
    return out


def project(image_path: Path, th: dict, name: str, caption: str, title: str) -> str:
    """Half-width block: a notched RULE-framed screenshot over a one-line
    caption."""
    t = Text()
    iw, ih = 428, 225
    with Image.open(image_path) as im:
        shot = jpeg_data(im.convert("RGB").resize((iw * 2, ih * 2), Image.LANCZOS))
    y = 4 + ih + 28
    body = [clip("shot", 6, 4, iw, ih),
            f'<g clip-path="url(#shot)">{image(6, 4, iw, ih, shot, "image/jpeg")}</g>',
            rule_notch(6, 4, iw, ih, th),
            t(6, y, name, 14, "p w"),
            t(6 + len(name) * 14 * MONO_ADVANCE + 12, y, caption, 12),
            t(434, y, "↗", 13, "a", "end")]
    return svg(W // 2, y + 12, title, body, css(th, t.all))


def link_btn(th: dict, label: str, icon: str, title: str, mx: float) -> str:
    """One outlined link button, drawn at its master x so the slice viewBox can
    cut it out of the intro master's bottom row (button y 264..304)."""
    t = Text()
    w = 550 / 3
    bx, by = mx + 6, 264
    icon_markup = (f'<g transform="translate({bx + 12:g} {by + 13.5:g}) scale({13 / 24})" '
                   f'stroke="{th["ACCENT"]}">{GLOBE}</g>' if icon == "globe" else
                   f'<g transform="translate({bx + 12:g} {by + 13.5:g}) scale({13 / 24})">'
                   f'<path fill="{th["ACCENT"]}" d="{ICONS[icon]}"/></g>')
    body = [f'<path d="{notch(bx, by, w - 12, 40, 4)}" fill="{th["ACCENT"]}" '
            f'fill-opacity="{th["CHIP"]}"/>',
            f'<path d="{notch(bx + .5, by + .5, w - 13, 39, 4)}" fill="none" '
            f'stroke="{th["ACCENT"]}" stroke-opacity="{th["RULE"]}"/>',
            icon_markup,
            t(bx + 33, by + 24.5, label, 12, "p"),
            t(bx + w - 18, by + 24.5, "↗", 12, "a", "end")]
    return svg(w, 56, title, body, css(th, t.all), (mx, 264, w, 56))


# ---------------------------------------------------------------- pixel city

# The README footer is a harbour skyline painted on a 434x112 grid of 2-unit
# pixels inside a notched frame at (6, 4). The still layers are baked into two
# PNGs (sky behind, city in front) so clouds, stars and planes can pass behind
# the towers; everything that moves is SVG rects animated with CSS, which plays
# inside an <img> on GitHub.
CITY_W, CITY_H, CELL, OX, OY = 434, 112, 2, 6, 4
BASE = 89          # row where buildings meet the road
QUAY = 134         # first column of the city bank; the river runs left of it
MOON = (66, 22)    # moon (dark) or sun (light) centre
BAYER_GRID = np.tile(BAYER8, (CITY_H // 8 + 1, CITY_W // 8 + 1))[:CITY_H, :CITY_W]

# Night for the dark theme, a clear morning for the light one. "lit" colours
# are window lights at night and sky glints on glass by day.
CITY = {
    "dark": {
        "sky": ["#02050B", "#040A15", "#071222", "#0B1C31", "#102841", "#173651", "#1F4360"],
        "glow": "#2C5878", "moon": "#E9F2F6", "shade": "#AFC4D0", "halo": "#16304A",
        "star": "#D6E8F4", "ridge": "#0B1C2D", "ridge_top": "#123049",
        "far": "#0C1E31", "far_win": "#2A5878", "far_lit": "#8A7A52",
        "mid": "#07111C", "rim": "#16304A", "roof": "#1E3C57", "edge": "#040A12",
        "front": "#04090F", "front_rim": "#0F2236", "off": "#0A1826",
        "lit": ["#F6C86C", "#FFE0A0", "#E8A458", "#FFD07E"], "cool": ["#7CCBF2", "#0297DE"],
        "lit_p": .3, "flood": "#C9A15E", "neon": "#0297DE",
        "bridge": "#0A1828", "cable": "#2D5778", "lamp": "#FFD98A",
        "road": "#050C14", "kerb": "#13283C", "water": "#030A13", "ripple": "#0D2135",
        "beacon": "#FF5A4E", "cloud": "#0D1D30", "cloud_hi": "#1B3651",
        "train": "#18304A", "train_hi": "#3B6A8E", "train_win": "#FFE3A3",
        "head": "#FFF2C7", "tail": "#FF5A4E", "glint": "#FFE6AE", "boat": "#0B1826",
        "bird": "#0B1826",
    },
    "light": {
        "sky": ["#6FB1DE", "#7DB9E2", "#8EC3E7", "#A2CDEC", "#B8D9F1", "#CDE5F5", "#E2EFF8"],
        "glow": "#F5EFE3", "moon": "#FFF9E3", "shade": "#FFE9AE", "halo": "#D8ECF8",
        "star": "#FFFFFF", "ridge": "#AEC8D9", "ridge_top": "#BDD3E2",
        "far": "#9CB8CC", "far_win": "#B7CEDD", "far_lit": "#C8DCE8",
        "mid": "#6B889E", "rim": "#93AFC2", "roof": "#A9C2D2", "edge": "#57738A",
        "front": "#4C667C", "front_rim": "#6A869C", "off": "#55728A",
        "lit": ["#A9C7DA", "#BBD5E5", "#C9DFEC", "#E2EFF7"], "cool": ["#0969A8", "#3B8CC2"],
        "lit_p": .34, "flood": "#C3D8E6", "neon": "#0969A8",
        "bridge": "#55718A", "cable": "#7C99AE", "lamp": "#E9F2F7",
        "road": "#41596C", "kerb": "#7C97AA", "water": "#5B8DB0", "ripple": "#86B2CE",
        "beacon": "#E0453A", "cloud": "#FFFFFF", "cloud_hi": "#DCEAF4",
        "train": "#EEF4F8", "train_hi": "#FFFFFF", "train_win": "#33536B",
        "head": "#FFFFFF", "tail": "#E0453A", "glint": "#FFFFFF", "boat": "#EEF4F8",
        "bird": "#2E4A60",
    },
}


def rgb(color: str) -> np.ndarray:
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)


def mix(a: str, b: str, t: float) -> str:
    """Blend hex colour a towards b by t."""
    c = rgb(a) * (1 - t) + rgb(b) * t
    return "#" + "".join(f"{int(round(v)):02X}" for v in c)


class Canvas:
    """One baked RGBA layer of the city scene. fill() paints a grid rectangle,
    optionally as an ordered dither at the given density."""

    def __init__(self) -> None:
        self.px = np.zeros((CITY_H, CITY_W, 4), np.uint8)

    def paint(self, mask: np.ndarray, color: str) -> None:
        self.px[mask] = (*rgb(color).astype(np.uint8), 255)

    def fill(self, x0: float, y0: float, x1: float, y1: float, color: str,
             density: float = 1) -> None:
        x0, x1 = max(int(x0), 0), min(int(x1), CITY_W)
        y0, y1 = max(int(y0), 0), min(int(y1), CITY_H)
        if x0 >= x1 or y0 >= y1:
            return
        mask = np.zeros((CITY_H, CITY_W), bool)
        mask[y0:y1, x0:x1] = BAYER_GRID[y0:y1, x0:x1] < density
        self.paint(mask, color)

    def png(self, opaque: bool = False) -> str:
        img = Image.fromarray(self.px if not opaque else self.px[..., :3],
                              "RGBA" if not opaque else "RGB")
        img = img.quantize(255, Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
        buffer = io.BytesIO()
        img.save(buffer, "PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode()


def city_sky(p: dict, rng: random.Random, night: bool) -> Canvas:
    """The sky layer: a dithered vertical ramp, a warm haze over the skyline,
    the moon or sun with its halo, and faint fixed stars at night."""
    sky = Canvas()
    ramp = p["sky"]
    n = len(ramp) - 1
    for y in range(CITY_H):
        t = min(y / 90, 1) * n
        i = min(int(t), n - 1)
        sky.fill(0, y, CITY_W, y + 1, ramp[i])
        sky.fill(0, y, CITY_W, y + 1, ramp[i + 1], t - i)
    yy, xx = np.mgrid[0:CITY_H, 0:CITY_W]
    haze = np.clip((yy - 52) / 38, 0, 1) ** 1.6 * (.25 + .5 * np.exp(-((xx - 280) / 120) ** 2))
    sky.paint(BAYER_GRID < haze, p["glow"])

    mx, my = MOON
    d = np.hypot(xx - mx, (yy - my) * 1.0)
    sky.paint((d > 6.5) & (d < 17) & (BAYER_GRID < .5 * (1 - (d - 6.5) / 10.5)), p["halo"])
    disc = d <= 6.5
    sky.paint(disc, p["moon"])
    if night:
        # A gibbous moon: a dithered limb shadow and a few craters.
        sky.paint(disc & ((xx - mx) * .9 + (yy - my) * .4 > 2.5) & (BAYER_GRID < .55), p["shade"])
        sky.paint(disc & ((xx - mx) * .9 + (yy - my) * .4 > 4.5), p["shade"])
        for cx, cy in ((-2, -3), (-3, 1), (1, 2), (0, -1), (2, -2)):
            sky.fill(mx + cx, my + cy, mx + cx + 1, my + cy + 1, p["shade"])
        for _ in range(150):
            x, y = rng.randrange(CITY_W), int(rng.random() ** 1.5 * 74)
            if np.hypot(x - mx, y - my) > 18:
                sky.fill(x, y, x + 1, y + 1, mix(ramp[min(y // 13, n)], p["star"],
                                                  rng.uniform(.25, .7)))
    else:
        sky.paint(disc & (d > 5.2), p["shade"])
    return sky


def windows(cv: Canvas, rng, p: dict, spots: list, x0: int, x1: int, y0: int,
            y1: int, sx: int = 2, sy: int = 2, ww: int = 1, wh: int = 1,
            lit: float | None = None, top=None) -> None:
    """A grid of windows between x0..x1 and y0..y1. Some floors are lit end to
    end; every window is recorded in spots so a few can switch on and off."""
    lit = p["lit_p"] if lit is None else lit
    for wy in range(y0, y1 - wh + 1, sy):
        floor = rng.random() < .1
        for wx in range(x0, x1 - ww + 1, sx):
            if top and wy < top(wx) + 2:
                continue
            on_color = rng.choice(p["cool"]) if rng.random() < .12 else rng.choice(p["lit"])
            color = on_color if floor or rng.random() < lit else p["off"]
            cv.fill(wx, wy, wx + ww, wy + wh, color)
            spots.append((wx, wy, ww, wh, on_color))


def block(cv: Canvas, p: dict, x0: int, x1: int, y0: int) -> None:
    """A building mass: lit left rim, dark right edge and a pale roof line."""
    cv.fill(x0, y0, x1, BASE, p["mid"])
    cv.fill(x0, y0, x0 + 1, BASE, p["rim"])
    cv.fill(x1 - 1, y0, x1, BASE, p["edge"])
    cv.fill(x0, y0, x1, y0 + 1, p["roof"])


def tower(cv: Canvas, rng, p: dict, spots: list, beacons: list,
          x: int, w: int, top: int, kind: str) -> None:
    """One skyline building. kind picks its silhouette and facade."""
    if kind == "needle":
        # A broadcast tower: tapered shaft, a two-deck pod with a lit
        # restaurant ring, and a mast. x is the shaft's left column.
        cv.fill(x - 1, BASE - 12, x + 3, BASE, p["mid"])
        cv.fill(x, top + 20, x + 2, BASE, p["mid"])
        cv.fill(x, top + 20, x + 1, BASE, p["rim"])
        for i, half in enumerate((2, 4, 5, 5, 4, 3, 1)):
            cv.fill(x + 1 - half, top + 13 + i, x + 1 + half, top + 14 + i,
                    p["roof"] if i == 0 else p["mid"])
            cv.fill(x + 1 - half, top + 13 + i, x + 2 - half, top + 14 + i, p["rim"])
        windows(cv, rng, p, spots, x - 3, x + 5, top + 16, top + 17, lit=.8)
        cv.fill(x - 1, top + 7, x + 3, top + 8, p["roof"])
        cv.fill(x, top, x + 1, top + 13, p["roof"])
        beacons.append((x, top - 1))
        return
    lit_top = None
    if kind == "deco":
        # The hero tower: three setback tiers with a floodlit crown, ribbed
        # facade and a spire.
        block(cv, p, x, x + w, top + 12)
        for i, inset in enumerate((2, 4, 6)):
            y = top + 8 - 4 * i
            block(cv, p, x + inset, x + w - inset, y)
            cv.fill(x + inset + 1, y + 1, x + w - inset - 1, y + 4, p["flood"], .3 + .12 * i)
        cx = x + w // 2
        cv.fill(cx - 1, top - 6, cx + 1, top, p["roof"])
        cv.fill(cx - 1, top - 6, cx, top, p["rim"])
        cv.fill(cx, top - 14, cx + 1, top - 6, p["roof"])
        beacons.append((cx, top - 15))
        for rx in range(x + 1, x + w - 1, 4):
            cv.fill(rx, top + 13, rx + 1, BASE, p["edge"])
        windows(cv, rng, p, spots, x + 2, x + w - 1, top + 14, BASE, sx=4, sy=2, ww=2)
        return
    if kind == "setback":
        block(cv, p, x, x + w, top + 10)
        block(cv, p, x + 3, x + w - 3, top)
        cv.fill(x + w - 6, top - 7, x + w - 5, top, p["roof"])
        beacons.append((x + w - 6, top - 8))
        windows(cv, rng, p, spots, x + 5, x + w - 4, top + 3, top + 9, sx=3, ww=2)
        windows(cv, rng, p, spots, x + 2, x + w - 1, top + 12, BASE, sx=3, ww=2)
        return
    if kind == "dome":
        r = (w - 2) // 2
        block(cv, p, x, x + w, top + r)
        cx = x + w / 2
        for i in range(r):
            half = int(round((r * r - (r - i - .5) ** 2) ** .5))
            cv.fill(cx - half, top + i, cx + half, top + i + 1, p["mid"])
            cv.fill(cx - half, top + i, cx - half + 1, top + i + 1, p["roof"])
        cv.fill(int(cx), top - 3, int(cx) + 1, top, p["roof"])
        cv.fill(x, top + r + 2, x + w, top + r + 3, p["roof"], .5)
        windows(cv, rng, p, spots, x + 2, x + w - 1, top + r + 4, BASE, sx=3, sy=4, wh=2)
        return
    if kind in ("slant", "pyramid", "crown"):
        def lit_top(cx: int) -> int:
            i = cx - x
            if kind == "slant":
                return top + i * 2 // 3
            if kind == "pyramid":
                return top + int(abs(i - (w - 1) / 2))
            return top + max(0, i - w // 2)
        for i in range(w):
            ty = lit_top(x + i)
            cv.fill(x + i, ty, x + i + 1, BASE, p["mid"])
            cv.fill(x + i, ty, x + i + 1, ty + 1, p["roof"])
        cv.fill(x, top, x + 1, BASE, p["rim"])
        cv.fill(x + w - 1, lit_top(x + w - 1), x + w, BASE, p["edge"])
        if kind == "pyramid":
            cx = x + w // 2
            cv.fill(cx, top - 5, cx + 1, top, p["roof"])
        if kind == "crown":
            # A glass tower: continuous ribbon windows.
            windows(cv, rng, p, spots, x + 2, x + w - 1, top + 2, BASE, sx=3, ww=3,
                    lit=p["lit_p"] + .15, top=lit_top)
            return
    else:
        block(cv, p, x, x + w, top)
        if kind == "antenna":
            mx = x + w // 2
            cv.fill(mx, top - 14, mx + 1, top, p["roof"])
            cv.fill(mx - 1, top - 10, mx + 2, top - 9, p["roof"])
            cv.fill(mx - 1, top - 6, mx + 2, top - 5, p["roof"])
            beacons.append((mx, top - 15))
        elif kind == "water":
            # A wooden water tank on legs with a conical cap.
            tx = x + 2
            for lx in (tx, tx + 4):
                cv.fill(lx, top - 3, lx + 1, top, p["roof"])
            cv.fill(tx, top - 8, tx + 5, top - 3, p["mid"])
            cv.fill(tx, top - 8, tx + 1, top - 3, p["rim"])
            cv.fill(tx, top - 6, tx + 5, top - 5, p["edge"])
            cv.fill(tx + 1, top - 9, tx + 4, top - 8, p["roof"])
            cv.fill(tx + 2, top - 10, tx + 3, top - 9, p["roof"])
        else:
            for _ in range(rng.randrange(1, 3)):
                bx = rng.randrange(x + 1, x + w - 3)
                cv.fill(bx, top - 2, bx + 2, top, p["mid"])
                cv.fill(bx, top - 2, bx + 2, top - 1, p["roof"])
    windows(cv, rng, p, spots, x + 2, x + w - 1, top + 3, BASE, top=lit_top)


SKYLINE = [
    (136, 12, 56, "slab"), (146, 10, 46, "water"), (155, 16, 60, "dome"),
    (170, 14, 40, "slant"), (194, 12, 52, "antenna"), (186, 0, 10, "needle"),
    (205, 20, 30, "setback"), (224, 12, 48, "slab"), (234, 24, 18, "deco"),
    (257, 14, 44, "pyramid"), (270, 18, 32, "crown"), (287, 12, 52, "water"),
    (298, 16, 26, "setback"), (313, 10, 48, "antenna"), (322, 20, 38, "crown"),
    (341, 14, 56, "dome"), (354, 18, 34, "slant"), (371, 12, 50, "slab"),
    (382, 18, 30, "setback"), (399, 14, 46, "pyramid"), (412, 22, 40, "crown"),
]
BRIDGE_TOWERS = (22, 100)
DECK = 79  # rail level on the bridge and the viaduct


def city_layer(p: dict, sky: Canvas, rng) -> tuple[Canvas, list, list]:
    """The city layer, back to front: hills, a hazy far skyline, the bridge,
    the main skyline, the rail viaduct, waterfront shops, the road and the
    water with its reflection. Returns the canvas, window spots and beacons."""
    cv, spots, beacons = Canvas(), [], []

    for x in range(CITY_W):
        h = int(70 + 4 * np.sin(x / 37) + 3 * np.sin(x / 13 + 1) + 1.5 * np.sin(x / 5.3))
        cv.fill(x, h, x + 1, BASE, p["ridge"])
        cv.fill(x, h, x + 1, h + 1, p["ridge_top"])
    x = 112
    while x < CITY_W:
        w, top = rng.randrange(3, 10), rng.randrange(50, 76)
        cv.fill(x, top, x + w, BASE, p["far"])
        if rng.random() < .2:
            cv.fill(x + w // 2, top - 4, x + w // 2 + 1, top, p["far"])
        for wy in range(top + 2, BASE, 2):
            for wx in range(x + 1, x + w - 1, 2):
                r = rng.random()
                if r < .2:
                    cv.fill(wx, wy, wx + 1, wy + 1, p["far_lit"] if r < .05 else p["far_win"])
        x += w + rng.randrange(0, 2)
    # The far bank of the river under the bridge, with scattered lights.
    for x in range(0, QUAY):
        top = 83 - int(1.5 + 1.5 * np.sin(x / 6) + (rng.random() < .15) * rng.randrange(1, 4))
        cv.fill(x, top, x + 1, 86, p["far"])
        if rng.random() < .12:
            cv.fill(x, 84, x + 1, 85, p["far_lit"])

    # Suspension bridge: twin-legged towers, a sagging main cable with
    # hangers, a lamplit deck and a truss beneath it.
    t1, t2 = (t + 1.5 for t in BRIDGE_TOWERS)
    def cable(cx: int) -> float:
        if cx < t1:
            return 46 + (t1 - cx) / t1 * 18
        if cx > t2:
            return 46 + (cx - t2) / (QUAY + 6 - t2) * (DECK - 47)
        return 46 + 30 * (1 - ((cx - (t1 + t2) / 2) / ((t2 - t1) / 2)) ** 2)
    prev = cable(0)
    for cx in range(QUAY + 6):
        cy = cable(cx)
        cv.fill(cx, min(cy, prev), cx + 1, max(cy, prev) + 1, p["cable"])
        if cx % 4 == 0:
            cv.fill(cx, cy + 1, cx + 1, DECK, mix(p["cable"], p["sky"][-1], .45))
        prev = cy
    cv.fill(0, DECK, QUAY + 6, DECK + 1, p["roof"])
    cv.fill(0, DECK + 1, QUAY + 6, DECK + 3, p["bridge"])
    for cx in range(0, QUAY + 6, 2):
        cv.fill(cx, DECK + 3, cx + 1, DECK + 4, p["bridge"])
    for cx in range(2, QUAY + 6, 6):
        cv.fill(cx, DECK - 1, cx + 1, DECK, p["lamp"])
    for tx in BRIDGE_TOWERS:
        for lx in (tx, tx + 3):
            cv.fill(lx, 45, lx + 1, 86, p["bridge"])
        cv.fill(tx, 45, tx + 1, 86, p["rim"])
        for by in (46, 57, 68, DECK + 4):
            cv.fill(tx, by, tx + 4, by + 2, p["bridge"])
        cv.fill(tx - 1, 84, tx + 5, 86, p["bridge"])
        beacons += [(tx, 44), (tx + 3, 44)]

    for x, w, top, kind in SKYLINE:
        tower(cv, rng, p, spots, beacons, x, w, top, kind)
    # A rooftop sign on the slab at 224; its face is an animated overlay.
    cv.fill(226, 41, 235, 46, p["front_rim"])
    cv.fill(227, 46, 228, 48, p["roof"])
    cv.fill(233, 46, 234, 48, p["roof"])

    # Rail viaduct continuing off the bridge, on piers.
    cv.fill(QUAY, DECK, CITY_W, DECK + 1, p["roof"])
    cv.fill(QUAY, DECK + 1, CITY_W, DECK + 3, p["bridge"])
    for px in range(QUAY + 10, CITY_W, 22):
        cv.fill(px, DECK + 3, px + 2, BASE, p["bridge"])

    # Waterfront shops under the viaduct, with lit storefronts.
    x = QUAY
    while x < CITY_W:
        w, top = rng.randrange(8, 17), rng.randrange(82, 86)
        cv.fill(x, top, x + w, BASE, p["front"])
        cv.fill(x, top, x + w, top + 1, p["front_rim"])
        cv.fill(x, top, x + 1, BASE, p["front_rim"])
        if rng.random() < .5:
            cx = rng.randrange(x + 1, x + w - 1)
            cv.fill(cx, top - 2, cx + 1, top, p["front_rim"])
        windows(cv, rng, p, spots, x + 2, x + w - 1, top + 2, BASE - 2, lit=p["lit_p"] + .2)
        cv.fill(x + 1, BASE - 1, x + w - 1, BASE, rng.choice(p["lit"]), .55)
        x += w + rng.randrange(0, 3)

    # Road, lamp posts and the quay wall.
    cv.fill(QUAY, BASE, CITY_W, BASE + 3, p["road"])
    for rx in range(QUAY + 2, CITY_W, 5):
        cv.fill(rx, BASE + 1, rx + 2, BASE + 2, p["kerb"], .5)
    for lx in range(QUAY + 6, CITY_W, 14):
        cv.fill(lx, BASE - 4, lx + 1, BASE, p["front_rim"])
        cv.fill(lx, BASE - 4, lx + 2, BASE - 3, p["lamp"])
    cv.fill(QUAY, BASE + 3, CITY_W, BASE + 4, p["kerb"])
    cv.fill(QUAY - 1, 84, QUAY + 1, BASE + 4, p["front"])

    # Water: mirror the composited scene about each bank's waterline, darken
    # it, shift rows for ripples, and let bright lights stretch into streaks.
    above = np.where(cv.px[..., 3:] > 0, cv.px[..., :3], sky.px[..., :3]).astype(float)
    water, ripple = rgb(p["water"]), rgb(p["ripple"])
    lum = above @ np.array([.3, .59, .11])
    bright = lum > np.percentile(lum, 97)
    for x in range(CITY_W):
        line = 86 if x < QUAY else BASE + 4
        for y in range(line, CITY_H):
            r = y - line
            sx = min(max(x + int(round(np.sin(r * 1.7 + x * .11) * (.5 + r / 8))), 0), CITY_W - 1)
            sy = max(2 * line - 1 - y, 0)
            k = max(.34 - r * .012, .12)
            if bright[sy, sx] and r % 2 == 0 and r < 16:
                k = .6 - r * .02
            c = water * (1 - k) + above[sy, sx] * k
            if r % 3 == 1 and BAYER_GRID[y, x] < .12:
                c = ripple
            cv.px[y, x] = (*np.round(c).astype(np.uint8), 255)
    # Moon glade or sun glitter on the river.
    for y in range(86, CITY_H):
        r = y - 86
        for _ in range(2):
            gx = MOON[0] + int(rng.gauss(0, 2 + r * .3))
            cv.fill(gx, y, gx + rng.randrange(1, 5), y + 1,
                    mix(p["water"], p["moon"], max(.55 - r * .015, .25)))
    return cv, spots, beacons


def grid_rect(gx: float, gy: float, gw: float, gh: float, fill: str, attrs: str = "") -> str:
    """A rect in grid pixels, placed in SVG units."""
    return (f'<rect x="{OX + CELL * gx:g}" y="{OY + CELL * gy:g}" width="{CELL * gw:g}" '
            f'height="{CELL * gh:g}" fill="{fill}"{attrs}/>')


def grid_path(rects: list[tuple[float, float, float, float]], fill: str, attrs: str = "") -> str:
    """Several grid rects merged into one path."""
    d = "".join(f"M{OX + CELL * x:g} {OY + CELL * y:g}h{CELL * w:g}v{CELL * h:g}h{-CELL * w:g}z"
                for x, y, w, h in rects)
    return f'<path d="{d}" fill="{fill}"{attrs}/>'


def anim(delay: float, duration: float | None = None) -> str:
    dur = f";animation-duration:{duration:g}s" if duration else ""
    return f' style="animation-delay:-{delay:g}s{dur}"'


def cloud_shapes(rng, p: dict, night: bool) -> list[str]:
    """Pixel clouds spread over two scene widths so the drift loops seamlessly."""
    shapes = []
    for i in range(5):
        x = i * 87 + rng.randrange(0, 30)
        y = rng.randrange(8, 34) if night else rng.randrange(10, 40)
        w = rng.randrange(22, 44)
        rows = [(x + 6, y, w - 14), (x + 2, y + 1, w - 6), (x, y + 2, w)]
        if not night:
            rows = [(x + 8, y - 2, w // 3), (x + w // 2, y - 1, w // 3)] + rows
        body = [(rx, ry, rw, 1) for rx, ry, rw in rows]
        hi = [(x + 3, y + 3, w - 4, 1)] if not night else [(x + 6, y, w // 2, 1)]
        for copy in (0, CITY_W):
            shapes.append(grid_path([(a + copy, b, c, d) for a, b, c, d in body], p["cloud"],
                                    ' opacity=".9"' if night else ""))
            shapes.append(grid_path([(a + copy, b, c, d) for a, b, c, d in hi], p["cloud_hi"]))
    return shapes


def pixel_wave(theme: str) -> str:
    """The animated harbour city footer for one theme."""
    night = theme == "dark"
    p = CITY[theme]
    rng = random.Random(7)
    sky = city_sky(p, rng, night)
    city, spots, beacons = city_layer(p, sky, random.Random(11))
    rng = random.Random(23)

    # Pick windows that switch on and off; bake them dark underneath.
    visible = [s for s in spots
               if (city.px[s[1], s[0], :3] == rgb(p["off"])).all() or
               (city.px[s[1], s[0], :3] == rgb(s[4])).all()]
    flicker = rng.sample(visible, 56)
    for wx, wy, ww, wh, _ in flicker:
        city.fill(wx, wy, wx + ww, wy + wh, p["off"])

    fw, fh = CELL * CITY_W, CELL * CITY_H
    body = [clip("city", OX, OY, fw, fh),
            '<g clip-path="url(#city)">',
            image(OX, OY, fw, fh, sky.png(opaque=True), "image/png")]

    # Behind the towers: stars, clouds, a plane, a meteor or birds.
    if night:
        for i in range(34):
            x, y = rng.randrange(CITY_W), int(rng.random() ** 1.4 * 60)
            if np.hypot(x - MOON[0], y - MOON[1]) < 16:
                continue
            body.append(grid_rect(x, y, 1, 1, p["star"], ' class="tw"' + anim(
                rng.uniform(0, 7), rng.choice((4, 5.5, 7)))))
        for x, y in ((150, 12), (330, 8), (24, 30), (405, 22)):
            body.append(f'<g class="tw"{anim(rng.uniform(0, 6), 6)}>' + grid_path(
                [(x, y - 1, 1, 3), (x - 1, y, 3, 1)], p["star"]) + "</g>")
    body.append(f'<g class="cl">{"".join(cloud_shapes(rng, p, night))}</g>')
    plane = "" if night else grid_path(
        [(300, 36, 5, 1), (301, 35, 1, 1), (302, 37, 2, 1)], p["bird"])
    body.append(f'<g class="pl">{plane}'
                + grid_rect(304 if not night else 302, 36, 1, 1, p["beacon"], ' class="bc"')
                + grid_rect(300, 36, 1, 1, p["head"], ' class="bc" style="animation-delay:-.6s"')
                + "</g>")
    if night:
        body.append('<g class="mt">' + "".join(
            grid_rect(140 - 3 * i, 6 - 2 * i, 2, 1, p["star"], f' opacity="{1 - i * .22:g}"')
            for i in range(4)) + "</g>")
    else:
        for i, (bx, by) in enumerate(((180, 30), (186, 27), (191, 32))):
            up = [(bx, by, 1, 1), (bx + 1, by + 1, 1, 1), (bx + 2, by, 1, 1)]
            down = [(bx, by + 1, 1, 1), (bx + 1, by, 1, 1), (bx + 2, by + 1, 1, 1)]
            body.append(f'<g class="bd"{anim(i * 1.3)}>'
                        f'<g class="f1"{anim(i * .2)}>{grid_path(up, p["bird"])}</g>'
                        f'<g class="f2"{anim(i * .2)}>{grid_path(down, p["bird"])}</g></g>')

    body.append(image(OX, OY, fw, fh, city.png(), "image/png"))

    # In front: windows, beacons, sign, train, traffic, boat and water glints.
    for i, (wx, wy, ww, wh, color) in enumerate(flicker):
        body.append(grid_rect(wx, wy, ww, wh, color, ' class="wn"' + anim(
            rng.uniform(0, 30), rng.choice((17, 23, 29, 37)))))
    for i, (bx, by) in enumerate(beacons):
        body.append(grid_rect(bx - 1, by - 1, 3, 3, p["beacon"],
                              ' class="bc" opacity=".25"' + anim(i * .37 % 2.4)))
        body.append(grid_rect(bx, by, 1, 1, p["beacon"], ' class="bc"' + anim(i * .37 % 2.4)))
    body.append(grid_rect(227, 42, 7, 3, p["neon"], ' class="ns"'))
    body.append(grid_path([(228, 43, 2, 1), (231, 43, 2, 1)], p["lit"][1], ' class="ns"'))

    cars = []
    for car in range(3):
        cx = 150 + car * 40
        cars += [(cx, DECK - 3, 20, 3)]
    train = (grid_path(cars, p["train"])
             + grid_path([(x, DECK - 3, w, 1) for x, _, w, _ in cars], p["train_hi"])
             + grid_path([(x + i, DECK - 2, 1, 1) for x, _, w, _ in cars
                          for i in range(2, w - 1, 2)], p["train_win"])
             + grid_rect(cars[-1][0] + 19, DECK - 2, 1, 1, p["head"]))
    body.append(f'<g class="tr">{train}</g>')

    road = [f'<clipPath id="road"><rect x="{OX + CELL * QUAY}" y="{OY + CELL * BASE}" '
            f'width="{CELL * (CITY_W - QUAY)}" height="{CELL * 3}"/></clipPath><g clip-path="url(#road)">']
    for i in range(4):
        east = i % 2 == 0
        y = BASE + (2 if east else 0)
        x = 160 + i * 50
        light = (x + 4, y, 1, 1) if east else (x, y, 1, 1)
        road.append(f'<g class="{"ce" if east else "cw"}"{anim(i * 5.3, 14 + i * 3)}>'
                    + grid_rect(x, y, 5, 1, p["front_rim"])
                    + grid_rect(*light, p["head"] if east else p["tail"])
                    + (grid_rect(x + 5, y, 3, 1, p["head"], ' opacity=".3"') if east else "")
                    + "</g>")
    body.append("".join(road) + "</g>")

    boat = [(300, 101, 14, 2), (302, 99, 8, 2)]
    body.append(f'<g class="bt">{grid_path(boat, p["boat"])}'
                + grid_path([(303 + i, 100, 1, 1) for i in range(0, 7, 2)], p["train_win"])
                + grid_rect(306, 97, 1, 2, p["roof"])
                + grid_rect(306, 96, 1, 1, p["head"], ' class="bc"')
                + grid_rect(314, 102, 6, 1, p["ripple"]) + "</g>")

    for i in range(64):
        if i < 14:
            x, y = MOON[0] + rng.randrange(-7, 8), rng.randrange(88, CITY_H)
        else:
            x, y = rng.randrange(QUAY + 2, CITY_W - 4), rng.randrange(BASE + 5, CITY_H)
        body.append(grid_rect(x, y, rng.randrange(1, 4), 1, p["glint"], ' class="sh"' + anim(
            rng.uniform(0, 6), rng.uniform(3, 6))))
    body.append("</g>")
    body.append(f'<path d="{notch(OX + .5, OY + .5, fw - 1, fh - 1, 4)}" fill="none" '
                f'stroke="{THEMES[theme]["ACCENT"]}" stroke-opacity="{THEMES[theme]["RULE"]}"/>')

    tr_from, tr_to = -CELL * 300, CELL * (CITY_W - 140) + 40
    style = (
        "image{image-rendering:pixelated}"
        ".tw{animation:tw 5s ease-in-out infinite}"
        ".cl{animation:cl 240s linear infinite}"
        ".pl{animation:pl 46s linear infinite}"
        ".mt{opacity:0;animation:mt 17s linear infinite}"
        ".bd{animation:bd 38s linear infinite}"
        ".f1{animation:f1 .7s steps(1,end) infinite}.f2{opacity:0;animation:f2 .7s steps(1,end) infinite}"
        ".wn{animation:wn 23s steps(1,end) infinite}"
        ".bc{animation:bc 2.4s steps(1,end) infinite}"
        ".ns{animation:ns 9s steps(1,end) infinite}"
        ".tr{animation:tr 26s linear infinite}"
        ".ce{animation:ce 16s linear infinite}.cw{animation:cw 16s linear infinite}"
        ".bt{animation:bt 90s linear infinite}"
        ".sh{opacity:0;animation:sh 4s ease-in-out infinite}"
        "@keyframes tw{0%,100%{opacity:.25}50%{opacity:1}}"
        f"@keyframes cl{{to{{transform:translateX(-{fw}px)}}}}"
        "@keyframes pl{from{transform:translate(-680px,14px)}to{transform:translate(300px,-10px)}}"
        "@keyframes mt{0%,80%{opacity:0;transform:translate(0,0)}81%{opacity:1}"
        "88%{opacity:0;transform:translate(150px,100px)}100%{opacity:0}}"
        "@keyframes bd{from{transform:translate(-420px,0)}50%{transform:translate(80px,-8px)}"
        "to{transform:translate(560px,4px)}}"
        "@keyframes f1{50%{opacity:0}}@keyframes f2{0%,100%{opacity:0}50%{opacity:1}}"
        "@keyframes wn{0%,64%{opacity:1}65%,100%{opacity:0}}"
        "@keyframes bc{0%,45%{opacity:1}46%,100%{opacity:.12}}"
        "@keyframes ns{0%,88%,91%,94%,100%{opacity:1}89%,92%{opacity:.25}}"
        f"@keyframes tr{{0%{{transform:translateX({tr_from}px)}}"
        f"60%,100%{{transform:translateX({tr_to}px)}}}}"
        "@keyframes ce{from{transform:translateX(-120px)}to{transform:translateX(640px)}}"
        "@keyframes cw{from{transform:translateX(520px)}to{transform:translateX(-160px)}}"
        "@keyframes bt{from{transform:translateX(320px)}to{transform:translateX(-660px)}}"
        "@keyframes sh{50%{opacity:.85}}"
        "@media(prefers-reduced-motion:reduce){*{animation:none!important}}"
    )
    title = ("Pixel harbour city at night: a suspension bridge, lit towers, a passing "
             "train and moonlight on the water" if night else
             "Pixel harbour city in the morning: a suspension bridge, glass towers, a "
             "passing train and sunlight on the water")
    return svg(W, CELL * CITY_H + 2 * OY, title, body, style)


def build(theme: str, portrait: str) -> dict[str, str]:
    """The eight README images for one theme; the portrait PNG is shared."""
    th = THEMES[theme]
    lw = 550 / 3
    return {
        **intro(th, portrait),
        "link-site": link_btn(th, "screeen.us.ci", "globe", "screeen.us.ci", 330),
        "link-nexus": link_btn(th, "znsnexus.com", "globe", "znsnexus.com",
                               330 + lw),
        "link-x": link_btn(th, "@screeendev", "X", "@screeendev on X",
                           330 + 2 * lw),
        "project-col": project(ASSETS / "website-col.png", th, "Col",
                               "UI libraries, all in one place",
                               "Col: UI libraries, components and design tools, all in one place. usecol.com"),
        "project-emc2": project(ASSETS / "website-emc2.png", th, "Emc²",
                                "One inbox for every account",
                                "Emc²: a desktop email client with one inbox for every account"),
        "pixel-wave": pixel_wave(theme),
    }


# ---------------------------------------------------------------- repo list

REPOS = [
    ("Closure", "self-hosted feedback, changelog and roadmap", "TypeScript"),
    ("screen-time", "which app and which website took your day, on Windows", "JavaScript"),
    ("Syllo", "work in progress", "Python"),
]


def repo_list() -> str:
    t = Text()
    row = 56
    H = 28 + row * len(REPOS)
    body = [rect(0, 0, W, H, MIDNIGHT)]
    body += window_bar(t, 0, 0, W, "4", "repos")
    for i, (name, what, lang) in enumerate(REPOS):
        y = 28 + i * row
        if i:
            body.append(hline(0, W, y))
        body.append(t(16, y + 24, name, 14, "p w"))
        body.append(t(16, y + 43, what, 12))
        lang_w = len(lang) * 12 * MONO_ADVANCE
        body.append(rect(W - 16 - lang_w - 14, y + 20, 8, 8, LANG_COLORS[lang]))
        body.append(t(W - 16, y + 28, lang, 12, "", "end"))
    body.append(rect(0, 0, W, H, "none", LINE))
    return svg(W, H, "More repositories by screen-gd", body, repos_css(t.all))


def main() -> None:
    # repos.svg is not rebuilt: fontTools no longer encodes the subset to the
    # same bytes, so regenerating it would only churn the file.
    outputs = {}
    portrait = base64.b64encode((ASSETS / "portrait.png").read_bytes()).decode()
    for theme in THEMES:
        for name, content in build(theme, portrait).items():
            outputs[f"{name}-{theme}.svg"] = content
    for name, content in outputs.items():
        (ASSETS / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"{name}: {len(content.encode()) // 1024} KB")

    # Stamp each image URL with the content hash so GitHub fetches the fresh SVGs.
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    for name, content in outputs.items():
        version = hashlib.sha256(content.encode()).hexdigest()[:12]
        text = re.sub(rf"\./assets/{re.escape(name)}(?:\?v=[a-f0-9]+)?",
                      f"./assets/{name}?v={version}", text)
    readme.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
