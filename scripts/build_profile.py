"""Build the profile README panels as SVGs.

GitHub strips CSS from READMEs, so every styled panel is an image. Each SVG embeds
its fonts (Geist Mono) and bitmaps, so it renders the same everywhere.

The design is a quiet neofetch-style profile on a transparent background: a
dithered dot-matrix portrait beside a dotted key/value list, framed project
screenshots, thin-ruled link rows and labelled rows of tech chips. Every image is
built twice, dark and light, and the README picks between them with <picture>
and prefers-color-scheme.

Usage: python scripts/build_profile.py
"""

import base64
import hashlib
import io
import re
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from PIL import Image

from icons import ICONS

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

# The new transparent panels: dark for GitHub's dark mode, light for its light
# one. RULE lines and CHIP fills are ACCENT at fixed opacities in both themes.
# ART is the portrait's dither palette after the transparent index 0.
THEMES = {
    "dark": {"TEXT": "#E6EDF2", "SECOND": "#8B98A4", "MUTED": "#52606B",
             "ACCENT": "#0297DE", "ART": ("#0E4F80", "#0297DE", "#FFFFFF")},
    "light": {"TEXT": "#0B1620", "SECOND": "#4A5864", "MUTED": "#9AA7B2",
              "ACCENT": "#0277B5", "ART": ("#8CC9EC", "#0297DE", "#0A2A4A")},
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


def font_faces(text: str) -> str:
    rules = []
    for weight, name in ((400, "GeistMono-Regular.ttf"), (500, "GeistMono-Medium.ttf")):
        data = subset(TTFont(FONTS / name), text)
        rules.append(f"@font-face{{font-family:GM;font-weight:{weight};"
                     f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return "".join(rules)


def css(th: dict, text: str, extra: str = "") -> str:
    """The <style> content for one themed panel: font subsets, text classes and
    any animation rules the panel needs."""
    return (
        font_faces(text)
        + f"text{{font-family:GM,'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f"fill:{th['SECOND']};white-space:pre}}"
        f".p{{fill:{th['TEXT']}}}.m{{fill:{th['MUTED']}}}.a{{fill:{th['ACCENT']}}}.w{{font-weight:500}}"
        "image{image-rendering:pixelated}" + extra
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


def svg(width: float, height: float, title: str, body: list[str], style: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}" role="img">'
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


def clip(clip_id: str, x: float, y: float, w: float, h: float, rx: float = 8) -> str:
    """A rounded-rect clipPath. Ids only need to be unique within each SVG file."""
    return (f'<clipPath id="{clip_id}"><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'rx="{rx:g}"/></clipPath>')


def hline(x1: float, x2: float, y: float, color: str = LINE) -> str:
    return f'<line x1="{x1:g}" y1="{y + .5:g}" x2="{x2:g}" y2="{y + .5:g}" stroke="{color}"/>'


def rule(x0: float, x1: float, y: float, th: dict) -> str:
    """A 1px RULE divider line."""
    return (f'<line x1="{x0:g}" y1="{y + .5:g}" x2="{x1:g}" y2="{y + .5:g}" '
            f'stroke="{th["ACCENT"]}" stroke-opacity=".28"/>')


def rule_rect(x: float, y: float, w: float, h: float, th: dict, rx: float = 8) -> str:
    """A rounded 1px RULE stroke, inset .5 like rect."""
    return (f'<rect x="{x + .5:g}" y="{y + .5:g}" width="{w - 1:g}" height="{h - 1:g}" '
            f'rx="{rx:g}" fill="none" stroke="{th["ACCENT"]}" stroke-opacity=".28"/>')


def kv(t: Text, th: dict, x0: float, x1: float, y: float, key: str, value: str,
       s: int = 13, accent: bool = False, arrow: bool = False, tail: int = 0) -> str:
    """One neofetch row on a character grid: a MUTED bullet at x0, the SECOND key
    two characters in, a dotted leader with a blank on each side, then the value
    right-aligned at x1 in TEXT (or ACCENT when flagged). `tail` reserves extra
    characters before the value, `arrow` appends an ACCENT ` ↗` after it."""
    adv = s * MONO_ADVANCE
    cols = int((x1 - x0) / adv)
    ks = 2 + len(key)
    vs = cols - len(value) - tail - (2 if arrow else 0)
    parts = [t(x0, y, ".", s, "m"), t(x0 + 2 * adv, y, key, s)]
    dots = "." * max(vs - ks - 2, 0)
    if dots:
        parts.append(t(x0 + (ks + 1) * adv, y, dots, s, "m"))
    cls = "a" if accent else "p"
    if arrow:
        parts += [t(x1 - 2 * adv, y, value, s, cls, "end"),
                  t(x1, y, " ↗", s, "a", "end")]
    else:
        parts.append(t(x1, y, value, s, cls, "end"))
    return "".join(parts)


def head(t: Text, th: dict, x0: float, x1: float, y: float, name: str, s: int = 13,
         arrow: bool = False) -> str:
    """`name@host` in ACCENT weight 500 at x0, then a RULE line from 10 units
    after the text to x1 (or 16 units short of an optional trailing arrow)."""
    end = x1 - 16 if arrow else x1
    parts = [t(x0, y, name, s, "a w"),
             rule(x0 + len(name) * s * MONO_ADVANCE + 10, end, y - 4, th)]
    if arrow:
        parts.append(t(x1, y, "↗", s, "a", "end"))
    return "".join(parts)


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


def png_data(img: Image.Image, transparency: int | None = None) -> str:
    buffer = io.BytesIO()
    extra = {} if transparency is None else {"transparency": transparency}
    img.save(buffer, "PNG", optimize=True, **extra)
    return base64.b64encode(buffer.getvalue()).decode()


def jpeg_data(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, "JPEG", quality=86, optimize=True, progressive=True)
    return base64.b64encode(buffer.getvalue()).decode()


def image(x: float, y: float, w: float, h: float, data: str, mime: str) -> str:
    uri = f"data:{mime};base64,{data}"
    return (f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'preserveAspectRatio="xMidYMid slice" href="{uri}" xlink:href="{uri}"/>')


# ---------------------------------------------------------------- dither

BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
]) / 64 + 1 / 128


def ordered_dither(tone: np.ndarray, colors: int) -> np.ndarray:
    """Palette index per cell: tone in [0,1] split into `colors` steps by a Bayer threshold."""
    rows, cols = tone.shape
    threshold = np.tile(BAYER8, (rows // 8 + 1, cols // 8 + 1))[:rows, :cols]
    scaled = np.clip(tone, 0, 1) * (colors - 1)
    index = np.floor(scaled)
    return np.minimum(index + (scaled - index > threshold), colors - 1).astype(np.uint8)


def palette_image(index: np.ndarray, colors: list[str]) -> Image.Image:
    img = Image.fromarray(index, "P")
    flat = []
    for c in colors:
        flat += [int(c[i:i + 2], 16) for i in (1, 3, 5)]
    img.putpalette(flat)
    return img


# ---------------------------------------------------------------- profile blocks

def portrait_tone(cells: int = 144) -> np.ndarray:
    """Tone for the dithered avatar: a low-gain shading term plus a line term, so
    the face reads as thin line art over a sparse skin dither and the near-white
    background and hair drop to zero. The line term is computed at 2x resolution
    and max-pooled down, keeping strokes 1 to 2 cells wide."""
    with Image.open(ASSETS / "avatar.png") as im:
        gray = im.convert("L")
        lum2 = np.asarray(gray.resize((cells * 2, cells * 2), Image.LANCZOS), dtype=float) / 255
        lum = np.asarray(gray.resize((cells, cells), Image.LANCZOS), dtype=float) / 255
    shade = np.clip((1 - lum - 0.13) * 1.15, 0, 0.55)
    light = lum2 > 0.6
    near = light.copy()
    for _ in range(4):
        near[1:, :] |= near[:-1, :]
        near[:-1, :] |= near[1:, :]
        near[:, 1:] |= near[:, :-1]
        near[:, :-1] |= near[:, 1:]
    dark_thin = (lum2 < 0.5) & near
    gy, gx = np.gradient(lum2)
    edge = np.clip((np.hypot(gx, gy) - 0.09) * 6, 0, 1)
    lines = np.maximum(dark_thin, edge).reshape(cells, 2, cells, 2).max(axis=(1, 3))
    tone = np.clip(shade + lines, 0, 1)
    return np.where(tone < 0.05, 0, tone)


def intro(th: dict, tone: np.ndarray) -> str:
    """The top block: the dithered portrait on the left, a neofetch info list on
    the right. One soft scanline travels down the portrait."""
    t = Text()
    body = [clip("av", 6, 16, 288, 288, rx=10)]
    art = palette_image(ordered_dither(tone, 4), ["#000000", *th["ART"]])
    png = png_data(art.resize((288, 288), Image.NEAREST), transparency=0)
    scan = (f'<rect class="scan" x="6" y="16" width="288" height="28" '
            f'fill="{th["ACCENT"]}" opacity=".1"/>')
    body.append(f'<g clip-path="url(#av)">{image(6, 16, 288, 288, png, "image/png")}{scan}</g>')

    x0, x1, s, pitch = 336, 874, 13, 26
    body.append(head(t, th, x0, x1, 46, "screen@github", s))
    rows = [("Name:", "Screen", False),
            ("Role:", "Product designer and developer", False),
            ("Working at:", "GitCafe", True),
            ("Building:", "Col · Emc²", True),
            ("Also:", "game dev", False),
            ("Based in:", "Sharjah, UAE", False),
            ("Languages:", "TypeScript · JavaScript · Python", False),
            ("Fuel:", "caffeine", False)]
    for i, (key, value, accent) in enumerate(rows):
        body.append(kv(t, th, x0, x1, 72 + i * pitch, key, value, s, accent))
    y = 72 + 8 * pitch
    body.append(kv(t, th, x0, x1, y, "Status:", "building", s, True, tail=2))
    sq = x1 - len("building") * s * MONO_ADVANCE - 14
    body.append(f'<rect class="blink" x="{sq:g}" y="{y - 8:g}" width="6" height="6" '
                f'fill="{th["ACCENT"]}"/>')

    extra = ('@keyframes scan{0%{transform:translateY(-28px)}100%{transform:translateY(316px)}}'
             '@keyframes blink{0%,49%{opacity:1}50%,100%{opacity:.2}}'
             '.scan{animation:scan 5s linear infinite}'
             '.blink{animation:blink 1.2s steps(1,end) infinite}'
             '@media(prefers-reduced-motion:reduce){.scan,.blink{animation:none}}')
    return svg(W, 320, "Screen: product designer and developer. Building Col and Emc². "
                       "Working at GitCafe.", body, css(th, t.all, extra))


def project(image_path: Path, th: dict, name: str, rows: list[tuple[str, str]],
            title: str) -> str:
    """Half-width block: a RULE-framed screenshot over a header and three rows."""
    t = Text()
    iw, ih = 428, 225
    with Image.open(image_path) as im:
        shot = jpeg_data(im.convert("RGB").resize((iw * 2, ih * 2), Image.LANCZOS))
    x0, x1, s, pitch = 6, 434, 12, 24
    top = 20 + ih
    body = [clip("shot", 6, 20, iw, ih),
            f'<g clip-path="url(#shot)">{image(6, 20, iw, ih, shot, "image/jpeg")}</g>',
            rule_rect(6, 20, iw, ih, th),
            head(t, th, x0, x1, top + 30, name, s, arrow=True)]
    for i, (key, value) in enumerate(rows):
        body.append(kv(t, th, x0, x1, top + 30 + (i + 1) * pitch, key, value, s))
    return svg(W // 2, top + 30 + 3 * pitch + 10, title, body, css(th, t.all))


def link_row(th: dict, key: str, value: str, title: str) -> str:
    """A third-width block: a RULE line on top, then one dotted key/value row."""
    t = Text()
    w = W / 3
    body = [rule(6, w - 6, 16, th),
            kv(t, th, 6, w - 6, 42, key, value, 13, arrow=True)]
    return svg(w, 60, title, body, css(th, t.all))


def stack(th: dict) -> str:
    """Full-width block: four RULE-separated rows of labelled tech chips."""
    t = Text()
    rows = [("languages", ["TypeScript", "JavaScript", "Python"]),
            ("frontend", ["React", "Next.js", "Astro", "TanStack", "Tailwind", "Vite", "Motion"]),
            ("desktop / ai", ["Electron", "MCP", "AI SDK", "Claude", "OpenAI"]),
            ("infra", ["Bun", "Cloudflare", "Vercel", "Convex", "SQLite"])]
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
            parts = [f'<rect x="{cx:g}" y="{cy:g}" width="{cw:g}" height="24" rx="6" '
                     f'fill="{th["ACCENT"]}" fill-opacity=".1"/>']
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
                       "TanStack, Tailwind, Vite, Motion, Electron, MCP, AI SDK, Claude, "
                       "OpenAI, Bun, Cloudflare, Vercel, Convex, SQLite.",
               body, css(th, t.all))


def build(th: dict) -> dict[str, str]:
    """The seven README blocks for one theme; the portrait tone is shared."""
    tone = portrait_tone()
    return {
        "intro": intro(th, tone),
        "project-col": project(ASSETS / "website-col.png", th, "col@usecol.com",
                               [("What:", "UI libraries, components and design tools"),
                                ("Kind:", "community directory"),
                                ("Stack:", "TypeScript · React · TanStack Start")],
                               "Col: UI libraries, components and design tools, all in one place. usecol.com"),
        "project-emc2": project(ASSETS / "website-emc2.png", th, "emc2@emclient2.vercel.app",
                                [("What:", "Desktop email, one inbox for every account"),
                                 ("Runs on:", "Windows · macOS · Linux"),
                                 ("Stack:", "TypeScript · Electron · React")],
                                "Emc²: a desktop email client with one inbox for every account"),
        "link-site": link_row(th, "Site:", "screeen.us.ci", "screeen.us.ci"),
        "link-nexus": link_row(th, "Nexus:", "znsnexus.com", "znsnexus.com"),
        "link-x": link_row(th, "X:", "@screeendev", "@screeendev on X"),
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
    for theme, th in THEMES.items():
        for name, content in build(th).items():
            outputs[f"{name}-{theme}.svg"] = content
    for name, content in outputs.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
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
