"""Build the profile README panels as SVGs.

GitHub strips CSS from READMEs, so every styled panel is an image. Each SVG embeds
its fonts (Geist Mono, Geist Pixel) and bitmaps, so it renders the same everywhere.

The design is a quiet profile on a transparent background: a dithered portrait
tile beside a dither-gradient pixel wordmark, framed project screenshots with
one-line captions, outlined link buttons and labelled rows of tech chips. Every
image is built twice, dark and light, and the README picks between them with
<picture> and prefers-color-scheme. The portrait is assets/portrait.png, baked
by astro-dither through scripts/bake_portrait.py (needs a browser, run manually).

Usage: python scripts/build_profile.py
"""

import base64
import hashlib
import io
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


def stack(th: dict) -> str:
    """Full-width block: four RULE-separated rows of labelled tech chips."""
    t = Text()
    rows = [("languages", ["TypeScript", "JavaScript", "Python"]),
            ("frontend", ["React", "Next.js", "Astro", "TanStack", "Tailwind", "Vite", "Motion"]),
            ("desktop / ai", ["Electron", "AI SDK", "Claude", "OpenAI"]),
            ("infra", ["Bun", "Cloudflare", "Convex", "SQLite"])]
    body = []
    for i, (label, names) in enumerate(rows):
        top = 12 + i * 40
        body.append(rule(6, 874, top, th))
        body.append(t(6, top + 24.5, label, 12, "p w"))
        cx = 130.0
        for name in names:
            icon = ICONS.get(name)
            cw = 16 + (19 if icon else 0) + len(name) * 12 * MONO_ADVANCE
            cy = top + 8
            parts = [f'<path d="{notch(cx, cy, cw, 24, 2)}" fill="{th["ACCENT"]}" '
                     f'fill-opacity="{th["CHIP"]}"/>']
            tx = cx + 8
            if icon:
                parts.append(f'<g transform="translate({tx:g} {cy + 5.5:g}) scale({13 / 24})">'
                             f'<path fill="{th["ACCENT"]}" d="{icon}"/></g>')
                tx += 19
            parts.append(t(tx, top + 24.5, name, 12, "p"))
            body.append("".join(parts))
            cx += cw + 6
    body.append(rule(6, 874, 172, th))
    return svg(W, 176, "Stack: TypeScript, JavaScript, Python, React, Next.js, Astro, "
                       "TanStack, Tailwind, Vite, Motion, Electron, AI SDK, Claude, "
                       "OpenAI, Bun, Cloudflare, Convex, SQLite.",
               body, css(th, t.all))


def build(th: dict, portrait: str) -> dict[str, str]:
    """The eight README images for one theme; the portrait PNG is shared."""
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
        "stack": stack(th),
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
    for theme, th in THEMES.items():
        for name, content in build(th, portrait).items():
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
