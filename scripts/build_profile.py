"""Build the profile README panels as SVGs.

GitHub strips CSS from READMEs, so every styled panel is an image. Each SVG embeds
its fonts (Geist Mono, Geist Pixel) and bitmaps, so it renders the same everywhere.

The design is a night sky map: one 880x660 star chart emitted as seven slices
that tile seamlessly in the README. The aurora glows along the horizon behind a
stepped skyline, projects and links hang in the sky as labelled stars joined
into a constellation, and the graticule sits on the slice boundaries so the
seams between images read as grid lines.

The aurora is a NumPy port of the dithercn Aurora used on screeen.us.ci:
curtains of light from layered noise, quantised to a five-colour palette with an
8x8 Bayer matrix.

Usage: python scripts/build_profile.py
"""

import base64
import hashlib
import io
import math
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
RADIUS = 14  # the plate's rounded corners

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


def css(text: str, pixel_text: str = "") -> str:
    """The <style> content every panel shares: font subsets and text classes.
    GM follows GP in .px so glyphs Geist Pixel lacks fall back per glyph."""
    return (
        font_faces(text, pixel_text)
        + f"text{{font-family:GM,'Geist Mono',ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        f"fill:{SECOND};white-space:pre}}"
        f".p{{fill:{TEXT}}}.m{{fill:{MUTED}}}.a{{fill:{ACCENT}}}.w{{font-weight:500}}"
        f".px{{font-family:GP,GM,'Geist Pixel','Geist Mono',monospace;fill:{TEXT}}}"
        "image{image-rendering:pixelated}"
    )


def svg(width: float, height: float, title: str, body: list[str], style: str,
        viewbox: tuple[float, ...] = ()) -> str:
    vb = " ".join(f"{v:g}" for v in (viewbox or (0.0, 0.0, width, height)))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width:g}" height="{height:g}" viewBox="{vb}" role="img">'
        f"<title>{escape(title)}</title><style>{style}</style>{''.join(body)}</svg>\n"
    )


class Text:
    """Collects every string drawn so the font subsets cover exactly those glyphs."""

    def __init__(self) -> None:
        self.seen: list[str] = []
        self.pixel_seen: list[str] = []

    def __call__(self, x: float, y: float, content: str, size: int = 14, cls: str = "",
                 anchor: str = "start") -> str:
        self.seen.append(content)
        c = f' class="{cls}"' if cls else ""
        a = f' text-anchor="{anchor}"' if anchor != "start" else ""
        return f'<text x="{x:g}" y="{y:g}" font-size="{size}"{c}{a} xml:space="preserve">{escape(content)}</text>'

    def px(self, x: float, y: float, content: str, size: int, cls: str = "",
           anchor: str = "start") -> str:
        """Pixel-font text. The string also joins the mono subset, which supplies
        any glyphs Geist Pixel lacks through per-glyph fallback."""
        self.pixel_seen.append(content)
        return self(x, y, content, size, "px" + (f" {cls}" if cls else ""), anchor)

    @property
    def all(self) -> str:
        return "".join(self.seen)

    @property
    def pixels(self) -> str:
        return "".join(self.pixel_seen)


def rect(x: float, y: float, w: float, h: float, fill: str = "none", stroke: str = "") -> str:
    if stroke:
        return (f'<rect x="{x + .5:g}" y="{y + .5:g}" width="{w - 1:g}" height="{h - 1:g}" '
                f'fill="{fill}" stroke="{stroke}"/>')
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" fill="{fill}"/>'


def card(x: float, y: float, w: float, h: float, fill: str, stroke: str = "",
         rx: float = RADIUS) -> str:
    """A rounded rect; the stroked variant insets by .5 like rect."""
    if stroke:
        return (f'<rect x="{x + .5:g}" y="{y + .5:g}" width="{w - 1:g}" height="{h - 1:g}" '
                f'rx="{rx:g}" fill="{fill}" stroke="{stroke}"/>')
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" fill="{fill}"/>'


def clip(clip_id: str, x: float, y: float, w: float, h: float, rx: float = RADIUS) -> str:
    """A rounded-rect clipPath. Ids only need to be unique within each SVG file."""
    return (f'<clipPath id="{clip_id}"><rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" '
            f'rx="{rx:g}"/></clipPath>')


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


# ---------------------------------------------------------------- animation

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


# ---------------------------------------------------------------- star chart

ICONS = {
    # lucide "globe" and the X logo, both on a 24 grid
    "globe": '<g fill="none" stroke="{c}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">'
             '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
             '<path d="M2 12h20"/></g>',
    "x": '<path fill="{c}" d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.58-6.64 7.58H.47l8.6-9.83L0 '
         '1.15h7.6l5.24 6.93zM17.6 20.64h2.04L6.49 3.24H4.3z"/>',
}


def star(x: float, y: float, halo_r: float, arms: float, core: float) -> str:
    """One labelled star: an ACCENT glow, a cross and a white core."""
    return (f'<circle cx="{x:g}" cy="{y:g}" r="{halo_r:g}" fill="url(#starglow)"/>'
            + rect(x - arms, y - 1, arms * 2, 2, ACCENT)
            + rect(x - 1, y - arms, 2, arms * 2, ACCENT)
            + rect(x - core / 2, y - core / 2, core, core, "#FFFFFF"))


def brackets(x: float, y: float, w: float, h: float, out: float = 4.5, arm: int = 8) -> str:
    """Path data for four finder brackets sitting `out` units outside a rect."""
    d = []
    for cx, dx in ((x, -1), (x + w, 1)):
        for cy, dy in ((y, -1), (y + h, 1)):
            d.append(f"M{cx + dx * (out + arm):g} {cy + dy * out:g}h{-dx * arm:g}"
                     f"M{cx + dx * out:g} {cy + dy * (out + arm):g}v{-dy * arm:g}")
    return "".join(d)


def star_chart() -> dict[str, str]:
    """One 880x660 night sky map emitted as seven slices whose viewBoxes share
    master coordinates. Light vector content goes into every slice unfiltered;
    each embedded bitmap carries a bounding box and lands only in slices it
    touches, so every star, label and inset stays inside its link's rect."""
    t = Text()
    H = 660
    full = (0.0, 0.0, W, H)
    items: list[tuple[tuple[float, float, float, float], str]] = []

    def light(frag: str) -> None:
        items.append((full, frag))

    # The plate: MIDNIGHT inside rounded corners, everything clipped to it.
    light(clip("plate", 0, 0, W, H))
    light(card(0, 0, W, H, MIDNIGHT))
    light(f'<radialGradient id="starglow"><stop offset="0" stop-color="{ACCENT}" stop-opacity=".35"/>'
          f'<stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient>'
          f'<radialGradient id="moonglow"><stop offset="0" stop-color="{ACCENT}" stop-opacity=".3"/>'
          f'<stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></radialGradient>')

    # Graticule: the lines land on every slice boundary, so seams read as grid.
    gx = [k * W / 6 for k in range(1, 6)]
    gy = [110, 220, 330, 440, 550]
    for x in gx:
        light(f'<line x1="{x + .5:g}" y1="0" x2="{x + .5:g}" y2="{H}" stroke="{LINE}"/>')
    for y in gy:
        light(hline(0, W, y))
    marks = "".join(f"M{x - 4:g} {y + .5}h8M{x + .5:g} {y - 4}v8" for x in gx for y in gy)
    light(f'<path d="{marks}" stroke="{LINE_STRONG}" fill="none"/>')

    # The aurora along the horizon; a ramp fades its top out into the open sky,
    # and palette index 0 stays transparent so stars show through the dark.
    cell = 2  # aurora cell in viewBox units; the portfolio hero uses 2px
    cols, rows = W // cell, 220 // cell
    ramp = smoothstep(0.0, 0.35, (np.arange(rows) + 0.5) / rows)[:, None]
    frames = []
    for n in range(FRAMES):
        tone = aurora(cols, rows, height=0.30, length=0.9, rays=22,
                      t=11.0 + n * SECONDS_PER_FRAME * TIME_SCALE)
        scene = palette_image(ordered_dither(tone * ramp, len(AURORA)), AURORA)
        frames.append(png_data(scene.resize((scene.width * 2, scene.height * 2), Image.NEAREST),
                               transparency=0))
    items.append(((0.0, 440.0, W, 220.0),
                  "".join(animated_frames(frames, 0, 440, W, 220))))

    # Background stars, denser toward the top; some twinkle in stepped fades.
    rng = np.random.default_rng(11)
    labelled = {"col": (318.0, 190.0), "emc2": (548.0, 250.0), "site": (150.0, 382.0),
                "nexus": (430.0, 366.0), "x": (720.0, 384.0)}
    insets = {"col": (40, 140, 208, 109), "emc2": (632, 136, 208, 109)}
    moon = (812.0, 55.0)
    # Rectangles to keep star-free: screenshot insets, the title block and every
    # label, blurb and domain line.
    boxes = list(insets.values()) + [
        (28, 14, 492, 84),    # title and tagline
        (296, 142, 48, 28),   # "Col"
        (570, 216, 66, 28),   # "Emc²"
        (36, 258, 230, 40),   # Col blurb and domain
        (628, 256, 206, 38),  # Emc² blurb and domain
        (150, 398, 148, 22),  # screeen.us.ci
        (436, 384, 140, 22),  # znsnexus.com
        (726, 400, 132, 22),  # @screeendev
    ]

    def crowded(x: float, y: float, clear: float = 12) -> bool:
        """True when a background star at (x, y) would crowd text, the moon or a star."""
        if any(a <= x < a + w and b <= y < b + h for a, b, w, h in boxes):
            return True
        if (x - moon[0]) ** 2 + (y - moon[1]) ** 2 < 46 * 46:
            return True
        return any((x - sx) ** 2 + (y - sy) ** 2 < clear * clear for sx, sy in labelled.values())

    edges = (("col", "emc2"), ("emc2", "nexus"), ("col", "nexus"),
             ("nexus", "site"), ("emc2", "x"))
    ends = []
    for a, b in edges:
        (x1, y1), (x2, y2) = labelled[a], labelled[b]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        ends += [(x1 + dx / length * 12, y1 + dy / length * 12),
                 (x2 - dx / length * 12, y2 - dy / length * 12)]

    n = 320
    xs, ys = rng.random(n) * W, 560 * rng.random(n) ** 1.4
    sizes = rng.choice([1, 2, 3], n, p=[0.6, 0.32, 0.08])
    tones = rng.choice(["#0E4F80", MUTED, SECOND, "#FFFFFF"], n, p=[0.34, 0.28, 0.26, 0.12])
    durs = 2.4 + rng.random(n) * 1.6
    dels = -rng.random(n) * 4
    kept = [(round(float(xs[i])), round(float(ys[i])), int(sizes[i]), tones[i], i)
            for i in range(n) if not crowded(round(float(xs[i])), round(float(ys[i])))]
    twinkling = set(rng.choice(len(kept), 30, replace=False).tolist())
    parts = []
    for j, (x, y, s, c, i) in enumerate(kept):
        tw = (f' class="twinkle" style="animation-duration:{durs[i]:.1f}s;'
              f'animation-delay:{dels[i]:.1f}s"') if j in twinkling else ""
        parts.append(f'<rect x="{x}" y="{y}" width="{s}" height="{s}" fill="{c}"{tw}/>')
    light("".join(parts))

    # Nine brighter sparkle stars, kept well clear of the constellation's ends.
    spark = []
    while len(spark) < 9:
        x, y = round(float(rng.random() * W)), round(20 + float(rng.random() * 400))
        if crowded(x, y, 30):
            continue
        if any((x - ex) ** 2 + (y - ey) ** 2 < 900 for ex, ey in ends):
            continue
        spark.append((x, y))
    spark_tw = set(rng.choice(9, 4, replace=False).tolist())
    parts = []
    for j, (x, y) in enumerate(spark):
        tw = (f' class="twinkle" style="animation-duration:{durs[j]:.1f}s;'
              f'animation-delay:{dels[j]:.1f}s"') if j in spark_tw else ""
        parts.append(f'<g{tw}>' + rect(x - 3, y - 0.5, 6, 1, SECOND)
                     + rect(x - 0.5, y - 3, 1, 6, SECOND)
                     + rect(x - 1, y - 1, 2, 2, "#FFFFFF") + "</g>")
    light("".join(parts))

    # Ground silhouette: a stepped skyline over the aurora, capped low enough
    # that the ground text below always sits on dark.
    skyline = Noise(23)
    tops = np.clip(np.round((595 + skyline(np.arange(0, W, 4) * 0.012,
                                         np.zeros(W // 4)) * 11) / 2) * 2, 584, 606)
    d = [f"M0 {H}V{tops[0]:g}"]
    for i in range(1, len(tops)):
        d.append(f"H{i * 4}V{tops[i]:g}")
    d.append(f"H{W}V{H}Z")
    light(f'<path d="{"".join(d)}" fill="{MIDNIGHT}"/>')

    # Constellation edges, trimmed at both ends so they never touch a star.
    for a, b in edges:
        (x1, y1), (x2, y2) = labelled[a], labelled[b]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        ux, uy = dx / length, dy / length
        light(f'<line x1="{x1 + ux * 12:g}" y1="{y1 + uy * 12:g}" '
              f'x2="{x2 - ux * 12:g}" y2="{y2 - uy * 12:g}" stroke="{LINE_STRONG}"/>')

    # The projects are the bright stars, the links the smaller ones.
    light(star(*labelled["col"], 26, 11, 6) + star(*labelled["emc2"], 26, 11, 6))
    light(t.px(318, 166, "Col", 22, anchor="middle"))
    light(t.px(574, 240, "Emc²", 22))
    for key in ("site", "nexus", "x"):
        light(star(*labelled[key], 16, 7, 4))

    # Link labels sit below-right of their star: icon, name, arrow.
    for icon, ix, baseline, label in (
            ("globe", 154, 414, "screeen.us.ci"),
            ("globe", 440, 400, "znsnexus.com"),
            ("x", 730, 416, "@screeendev")):
        light(f'<g transform="translate({ix} {baseline - 11}) scale(.5)">'
              + ICONS[icon].format(c=SECOND) + "</g>"
              + t(ix + 20, baseline, label, 13, "p")
              + t(ix + 20 + len(label) * 13 * MONO_ADVANCE, baseline, " ↗", 13, "a"))

    # Screenshot insets in finder frames, tied to their star by a dashed leader.
    shots = {}
    for key, path in (("col", "website-col.png"), ("emc2", "website-emc2.png")):
        with Image.open(ASSETS / path) as im:
            shots[key] = jpeg_data(im.convert("RGB").resize((416, 218), Image.LANCZOS))
    for key, (ix, iy), (blurb, domain) in (
            ("col", (40, 140), ("UI libraries, all in one place", "usecol.com")),
            ("emc2", (632, 136), ("One inbox for every account", "emclient2.vercel.app"))):
        iw, ih = insets[key][2:]
        sx, sy = labelled[key]
        px_, py_ = min(max(sx, ix), ix + iw), min(max(sy, iy), iy + ih)
        dx, dy = sx - px_, sy - py_
        length = math.hypot(dx, dy)
        items.append(((float(ix), float(iy), float(iw), float(ih)),
                      f'<g clip-path="url(#{key}shot)">'
                      + image(ix, iy, iw, ih, shots[key], "image/jpeg") + "</g>"))
        light(clip(f"{key}shot", ix, iy, iw, ih, rx=6)
              + card(ix, iy, iw, ih, "none", LINE_STRONG, rx=6)
              + f'<path d="{brackets(ix, iy, iw, ih)}" stroke="{ACCENT}" fill="none"/>'
              + f'<line x1="{px_:g}" y1="{py_:g}" x2="{sx - dx / length * 12:g}" '
                f'y2="{sy - dy / length * 12:g}" stroke="{LINE_STRONG}" stroke-dasharray="2 3"/>')
        by = iy + ih + 25
        light(t(ix, by, blurb, 12)
              + t(ix, by + 19, domain, 12, "m")
              + t(ix + len(domain) * 12 * MONO_ADVANCE, by + 19, " ↗", 12, "a"))

    # Title top-left, the dithered avatar as the moon top-right.
    light(t.px(32, 64, "Screen", 56))
    light(t(34, 90, "Product designer and developer. Working at GitCafe.", 13, "p"))
    light('<circle cx="812" cy="55" r="60" fill="url(#moonglow)"/>')
    avatar = dithered_avatar(ASSETS / "avatar.jpg", 36)
    items.append(((776.0, 19.0, 72.0, 72.0),
                  '<clipPath id="moon"><circle cx="812" cy="55" r="36"/></clipPath>'
                  f'<g clip-path="url(#moon)">{image(776, 19, 72, 72, png_data(avatar), "image/png")}</g>'
                  f'<circle cx="812" cy="55" r="35.5" fill="none" stroke="{LINE_STRONG}"/>'))

    # Blink and twinkle animation, both quiet under prefers-reduced-motion.
    light('<style>@keyframes building{0%,24%{opacity:1}25%,100%{opacity:.2}}'
          '@keyframes twinkle{0%,100%{opacity:1}50%{opacity:.15}}'
          '.building{animation:building 1.2s steps(1,end) infinite}'
          '.twinkle{animation:twinkle 3s steps(2,end) infinite}'
          '@media(prefers-reduced-motion:reduce){.building,.twinkle{animation:none}}</style>')
    light(f'<rect class="building" x="32" y="635" width="6" height="6" fill="{ACCENT}"/>')
    light(t(48, 642, "Building Col and Emc²", 12, "p w"))
    light(t(848, 642, "25.3° N 55.4° E  Sharjah", 12, "m", "end"))

    light(card(0, 0, W, H, "none", LINE))

    # Each slice is the same plate seen through its own viewBox window.
    plates = [
        ("header.svg", 0.0, 0.0, W, 110.0,
         "Screen: product designer and developer. Building Col and Emc². Working at GitCafe."),
        ("tile-col.svg", 0.0, 110.0, 440.0, 220.0,
         "Col: UI libraries, components and design tools, all in one place. usecol.com"),
        ("tile-emc2.svg", 440.0, 110.0, 440.0, 220.0,
         "Emc²: a desktop email client with one inbox for every account"),
        ("chip-site.svg", 0.0, 330.0, W / 3, 110.0, "screeen.us.ci"),
        ("chip-nexus.svg", W / 3, 330.0, W / 3, 110.0, "znsnexus.com"),
        ("chip-x.svg", 2 * W / 3, 330.0, W / 3, 110.0, "@screeendev on X"),
        ("horizon.svg", 0.0, 440.0, W, 220.0, "Aurora over the horizon. Building Col and Emc²."),
    ]
    style = css(t.all, t.pixels)
    outputs = {}
    for name, sx, sy, sw, sh, title in plates:
        body = ['<g clip-path="url(#plate)">']
        body += [frag for (bx, by, bw, bh), frag in items
                 if bx < sx + sw and bx + bw > sx and by < sy + sh and by + bh > sy]
        body.append("</g>")
        outputs[name] = svg(sw, sh, title, body, style, (sx, sy, sw, sh))
    return outputs


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
    return svg(W, H, "More repositories by screen-gd", body, css(t.all))


def main() -> None:
    outputs = star_chart()
    outputs["repos.svg"] = repo_list()
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
