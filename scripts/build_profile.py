"""Build the profile README panels as SVGs.

GitHub strips CSS from READMEs, so every styled panel is an image. Each SVG embeds
its fonts (Geist Mono, Geist Pixel) and bitmaps, so it renders the same everywhere.

The header's aurora is a NumPy port of the dithercn Aurora used on screeen.us.ci:
curtains of light from layered noise, quantised to a five-colour palette with an
8x8 Bayer matrix.

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
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ROOT / "fonts"

# Panels are drawn at 880 units, close to GitHub's README column, so 14 stays ~14px.
W = 880

# One neutral ramp tinted toward the portfolio's midnight, plus electric blue.
MIDNIGHT = "#02070A"
SURFACE = "#071017"
LINE = "#16232D"
LINE_STRONG = "#1E5A80"
TEXT = "#E6EDF2"
SECOND = "#8B98A4"
MUTED = "#52606B"
ACCENT = "#0297DE"
AURORA = ["#02070A", "#0A2A4A", "#0E4F80", "#0297DE", "#FFFFFF"]

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


def font_faces(text: str, pixel_text: str) -> str:
    rules = []
    for weight, name in ((400, "GeistMono-Regular.ttf"), (500, "GeistMono-Medium.ttf")):
        data = subset(TTFont(FONTS / name), text)
        rules.append(f"@font-face{{font-family:GM;font-weight:{weight};"
                     f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    if pixel_text:
        # ELSH 1 is the "Square" cut: each pixel a separate square, like the dither
        pixel = instantiateVariableFont(TTFont(FONTS / "GeistPixel.ttf"), {"ELSH": 1})
        data = subset(pixel, pixel_text)
        rules.append(f"@font-face{{font-family:GP;src:url(data:font/woff2;base64,{data}) format('woff2')}}")
    return "".join(rules)


def svg(width: int, height: int, title: str, body: list[str], text: str, pixel_text: str = "") -> str:
    style = (
        font_faces(text, pixel_text)
        + f"text{{font-family:GM,'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f"fill:{SECOND};white-space:pre}}"
        f".p{{fill:{TEXT}}}.m{{fill:{MUTED}}}.a{{fill:{ACCENT}}}.w{{font-weight:500}}"
        f".px{{font-family:GP,'Geist Pixel','Geist Mono',monospace;fill:{TEXT}}}"
        "image{image-rendering:pixelated}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
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


def hline(x1: float, x2: float, y: float, color: str = LINE) -> str:
    return f'<line x1="{x1:g}" y1="{y + .5:g}" x2="{x2:g}" y2="{y + .5:g}" stroke="{color}"/>'


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


def png_data(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, "PNG", optimize=True)
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


class Noise:
    """Vectorised 2D gradient noise in roughly [-1, 1], standing in for GLSL snoise."""

    def __init__(self, seed: int = 7) -> None:
        rng = np.random.default_rng(seed)
        self.perm = np.concatenate([rng.permutation(256)] * 2)
        angles = rng.uniform(0, 2 * np.pi, 256)
        self.grad = np.stack([np.cos(angles), np.sin(angles)], -1)

    def __call__(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        xi, yi = np.floor(x).astype(int), np.floor(y).astype(int)
        xf, yf = x - xi, y - yi
        xi, yi = xi & 255, yi & 255

        def corner(dx: int, dy: int) -> np.ndarray:
            g = self.grad[self.perm[self.perm[xi + dx] + yi + dy] & 255]
            return g[..., 0] * (xf - dx) + g[..., 1] * (yf - dy)

        u = xf * xf * xf * (xf * (xf * 6 - 15) + 10)
        v = yf * yf * yf * (yf * (yf * 6 - 15) + 10)
        top = corner(0, 0) + u * (corner(1, 0) - corner(0, 0))
        bottom = corner(0, 1) + u * (corner(1, 1) - corner(0, 1))
        return (top + v * (bottom - top)) * 1.9

    def fbm(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        total, amp = 0.0, 0.5
        for _ in range(4):
            total = total + amp * (self(x, y) * 0.5 + 0.5)
            x, y, amp = x * 2.02, y * 2.02, amp * 0.5
        # gradient noise is flatter than GLSL simplex; stretch so rays get their contrast
        return np.clip(0.5 + (total / 0.9375 - 0.5) * 2.4, 0, 1)


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    k = np.clip((x - e0) / (e1 - e0), 0, 1)
    return k * k * (3 - 2 * k)


def aurora(cols: int, rows: int, *, curtains: int = 4, height: float = 0.36, spread: float = 0.06,
           sway: float = 1.4, turbulence: float = 0.8, rays: float = 10, length: float = 0.8,
           glow: float = 1.1, intensity: float = 0.95, drift: float = 0.25,
           t: float = 11.0) -> np.ndarray:
    """Tone field from the dithercn Aurora shader (direction up, no tilt, no mask).
    Defaults are the AuroraHero settings from the portfolio."""
    noise = Noise()
    ux, uy = np.meshgrid((np.arange(cols) + 0.5) / cols, 1 - (np.arange(rows) + 0.5) / rows)
    py = uy  # y points up, as in GLSL
    x = (ux - 0.5) * cols / rows + t * drift * 0.04
    const = lambda v: np.full_like(x, v)  # noqa: E731
    decay = 15.0 + (2.2 - 15.0) * length
    light = np.zeros_like(x)
    for i in range(curtains):
        depth = i / max(curtains - 1, 1)
        edge = (height + i * spread
                + sway * 0.11 * noise(x * 0.55 + i * 3.1, const(t * 0.035 + i * 1.7))
                + turbulence * 0.05 * noise(x * 2.1 - i * 1.3, const(t * 0.07 + i)))
        above = py - edge
        curtain = np.where(above > 0, np.exp(-np.abs(above) * decay * (1 + i * 0.4)),
                           np.exp(-np.abs(above) * 48))
        rx = (x + noise(x * 0.8, const(t * 0.03 + i)) * (0.25 + 0.35 * sway)) * rays
        ray = 0.2 + 0.8 * smoothstep(0.25, 0.75, noise.fbm(rx + i * 9.0, const(t * 0.045 + i)))
        ray = ray * (0.75 + 0.25 * noise(rx * 3.2, const(i * 4.0 + t * 0.02)))
        patch = 0.3 + 0.7 * smoothstep(0.25, 0.7, noise.fbm(x * 0.45 + i * 5.0, const(t * 0.02 + i * 2)))
        rim = np.exp(-np.abs(above) * 34) * glow
        haze = np.where(above > 0, np.exp(-np.abs(above) * 5) * 0.09, np.exp(-np.abs(above) * 14) * 0.05)
        light += (curtain * ray + rim * (0.5 + 0.5 * ray) + haze) * patch * (1 - 0.5 * depth)
    return (1 - np.exp(-light * 1.25)) * intensity


# ---------------------------------------------------------------- header

# The shader's noise isn't periodic, so the loop plays forward then back.
FRAMES = 20
SECONDS_PER_FRAME = 0.2
TIME_SCALE = 2.0  # run the shader clock twice as fast so 4 seconds shows real movement


def animated_frames(frames: list[str], x: float, y: float, w: float, h: float) -> list[str]:
    """Stack the frames and show one at a time with discrete opacity steps (ping-pong)."""
    order = list(range(len(frames))) + list(range(len(frames) - 2, 0, -1))
    steps = len(order)
    times = ";".join(f"{k / steps:.4f}" for k in range(steps))
    duration = steps * SECONDS_PER_FRAME
    parts = []
    for n, data in enumerate(frames):
        values = ";".join("1" if f == n else "0" for f in order)
        uri = f"data:image/png;base64,{data}"
        parts.append(
            f'<image x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" preserveAspectRatio="none" '
            f'href="{uri}" xlink:href="{uri}" opacity="{1 if n == 0 else 0}">'
            f'<animate attributeName="opacity" values="{values}" keyTimes="{times}" '
            f'dur="{duration:g}s" calcMode="discrete" repeatCount="indefinite"/></image>'
        )
    return parts

def dithered_avatar(path: Path, cells: int) -> Image.Image:
    with Image.open(path) as im:
        gray = im.convert("L")
        side = min(gray.size)
        crop = int(side * 0.06)
        gray = gray.crop((crop, crop, side - crop, side - crop)).resize((cells, cells), Image.LANCZOS)
    tone = np.clip((np.asarray(gray, dtype=float) / 255 - 0.08) / 0.9, 0, 1) ** 1.2
    colors = [MIDNIGHT, "#0E4F80", ACCENT, "#FFFFFF"]
    return palette_image(ordered_dither(tone, len(colors)), colors)


def header() -> str:
    t = Text()
    strip, scene_h, details_h = 28, 140, 198
    H = strip + scene_h + details_h
    cell = 2  # aurora cell in viewBox units; the portfolio hero uses 2px
    frames = []
    for n in range(FRAMES):
        tone = aurora(W // cell, scene_h // cell, height=0.38, length=0.85, rays=12,
                      t=11.0 + n * SECONDS_PER_FRAME * TIME_SCALE)
        scene = palette_image(ordered_dither(tone, len(AURORA)), AURORA)
        frames.append(png_data(scene.resize((scene.width * 2, scene.height * 2), Image.NEAREST)))

    body = [
        rect(0, 0, W, H, MIDNIGHT),
        rect(0, 0, W, strip, SURFACE),
        t(12, 19, "Screen", 12, "p w"),
        t(100, 19, "BUILDING", 12, "p w"),
        t(W - 12, 19, "github.com/screen-gd", 12, "m", "end"),
        *animated_frames(frames, 0, strip, W, scene_h),
        hline(0, W, strip - 1),
    ]

    # Four pixels cycle clockwise to mark ongoing building, with a static fallback.
    body.append('<style>@keyframes building{0%,24%{opacity:1}25%,100%{opacity:.2}}'
                '.building{animation:building 1.2s steps(1,end) infinite}'
                '@media(prefers-reduced-motion:reduce){.building{animation:none}}</style>')
    for step, (x, y) in enumerate(((79, 10), (85, 10), (85, 16), (79, 16))):
        body.append(f'<rect class="building" x="{x}" y="{y}" width="4" height="4" '
                    f'fill="{ACCENT}" style="animation-delay:-{(4-step)*.3:g}s"/>')

    # The banner sits above a name panel and a two-by-two details grid.
    top = strip + scene_h
    split, middle = 536, 708
    body += [rect(0, top, W, details_h, MIDNIGHT), hline(0, W, top)]
    body.append(f'<text x="24" y="{top + 62}" font-size="54" '
                f'style="font-family:Arial,Helvetica,sans-serif;letter-spacing:-2px" '
                f'class="p">Screen</text>')
    body.append(t(24, top + 90, "Product designer and developer.", 14, "p"))
    for n, (label, value) in enumerate((("NOW", "building Col and Emc²"),
                                       ("HANDLE", "@screen-gd"))):
        y = top + 136 + n * 28
        body.append(t(24, y, label, 11, "m"))
        body.append(t(104, y, value, 13, "p w"))
    for x in (split, middle):
        body.append(f'<line x1="{x + .5}" y1="{top}" x2="{x + .5}" y2="{H}" stroke="{LINE}"/>')
    body.append(hline(split, W, top + details_h // 2))
    for x, y, label, value in (
        (split, top, "Working at", "GitCafe"),
        (middle, top, "FOCUS", "web products"),
        (split, top + 99, "STATUS", "building"),
        (middle, top + 99, "ALSO", "game dev"),
    ):
        body.append(t(x + 16, y + 28, label, 10, "m"))
        body.append(t(x + 16, y + 61, value, 13, "p w"))
    body.append(rect(0, 0, W, H, "none", LINE))

    return svg(W, H, "Screen: product designer and developer. Building Col and Emc². Helping out at GitCafe.",
               body, t.all + "Screen")


# ---------------------------------------------------------------- link chips

ICONS = {
    # lucide "globe" and the X logo, both on a 24 grid
    "globe": '<g fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
             '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
             '<path d="M2 12h20"/></g>',
    "x": '<path fill="{c}" d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 '
         '1.15h7.6l5.24 6.93zM17.6 20.64h2.04L6.49 3.24H4.3z"/>',
}


def chip(icon: str, label: str) -> str:
    t = Text()
    h = box = 36
    width = int(box + 12 + len(label + "  ↗") * 13 * MONO_ADVANCE + 12)
    width += width % 2
    body = [
        rect(0, 0, width, h, MIDNIGHT),
        f'<g transform="translate({(box - 16) / 2} {(h - 16) / 2}) scale({16 / 24})">'
        + ICONS[icon].format(c=SECOND) + "</g>",
        f'<line x1="{box + .5}" y1="0" x2="{box + .5}" y2="{h}" stroke="{LINE}"/>',
        t(box + 12, 23, label, 13, "p"),
        t(width - 12, 23, "↗", 13, "m", "end"),
        rect(0, 0, width, h, "none", LINE),
    ]
    return svg(width, h, label, body, t.all)


# ---------------------------------------------------------------- project tiles

def tile(image_path: Path, index: str, label: str, domain: str, blurb: str, kind: str) -> str:
    """Half of an 880 row. Shown at width=50% with no gap between the two images,
    so the cards touch at a shared centre divider, matching the header's width."""
    t = Text()
    half = W // 2
    x0, cw = 0, half
    ih = round(cw * 630 / 1200)
    with Image.open(image_path) as im:
        shot = im.convert("RGB").resize((cw * 2, ih * 2), Image.LANCZOS)
    H = 28 + ih + 48
    body = [rect(x0, 0, cw, H, MIDNIGHT)]
    body += window_bar(t, x0, 0, cw, index, label, domain)
    body.append(image(x0, 28, cw, ih, jpeg_data(shot), "image/jpeg"))
    body.append(hline(x0, x0 + cw, 28 + ih))
    body.append(t(x0 + 16, 28 + ih + 29, blurb, 13, "p"))
    body.append(t(x0 + cw - 16, 28 + ih + 29, kind, 12, "m", "end"))
    body.append(rect(x0, 0, cw, H, "none", LINE))
    return svg(half, H, f"{label}: {blurb} ({domain})", body, t.all)


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
    return svg(W, H, "More repositories by screen-gd", body, t.all)


def main() -> None:
    outputs = {
        "header.svg": header(),
        "chip-site.svg": chip("globe", "screeen.us.ci"),
        "chip-nexus.svg": chip("globe", "znsnexus.com"),
        "chip-x.svg": chip("x", "@screeendev"),
        "tile-col.svg": tile(ASSETS / "website-col.png", "2", "col", "usecol.com",
                             "UI libraries, all in one place", "web"),
        "tile-emc2.svg": tile(ASSETS / "website-emc2.png", "3", "emc²", "emclient2.vercel.app",
                              "One inbox for every account", "desktop"),
        "repos.svg": repo_list(),
    }
    for name, content in outputs.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
        print(f"{name}: {len(content.encode()) // 1024} KB")

    # Change the image URL after a rebuild so GitHub fetches the updated header.
    version = hashlib.sha256(outputs["header.svg"].encode()).hexdigest()[:12]
    readme = ROOT / "README.md"
    readme.write_text(re.sub(r'\./assets/header\.svg(?:\?v=[a-f0-9]+)?',
                             f"./assets/header.svg?v={version}",
                             readme.read_text(encoding="utf-8")), encoding="utf-8")


if __name__ == "__main__":
    main()
