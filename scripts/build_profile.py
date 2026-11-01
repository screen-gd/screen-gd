"""Build the profile README artwork: a terminal header, project tiles and a repo list.

GitHub strips CSS from READMEs, so every styled panel is an SVG image. Each SVG embeds
a Cascadia Mono subset and its screenshots so it renders the same everywhere.

Usage: python scripts/build_profile.py <avatar image>
"""

import base64
import io
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT_PATH = Path("C:/Windows/Fonts/CascadiaMono.ttf")

BG = "#0a0a0a"
PANEL = "#111111"
LINE = "#262626"
INK = "#ededed"
DIM = "#8f8f8f"
FAINT = "#555555"
ACCENT = "#e5484d"  # the red ring in the avatar
ADVANCE = 1200 / 2048  # Cascadia Mono advance width per em

MONO = "Cascadia, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"


def font_face(text: str) -> str:
    """Return @font-face rules for regular and semibold subsets covering `text`."""
    rules = []
    for weight in (400, 600):
        font = instantiateVariableFont(TTFont(FONT_PATH), {"wght": weight})
        options = Options()
        options.flavor = "woff2"
        options.layout_features = []
        subsetter = Subsetter(options)
        subsetter.populate(text=text + " ")
        subsetter.subset(font)
        font.flavor = "woff2"
        buffer = io.BytesIO()
        font.save(buffer)
        data = base64.b64encode(buffer.getvalue()).decode()
        rules.append(
            f"@font-face{{font-family:Cascadia;font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2')}}"
        )
    return "".join(rules)


def svg(width: int, height: int, title: str, body: str, text: str) -> str:
    style = (
        font_face(text)
        + f"text{{font-family:{MONO};fill:{DIM};white-space:pre}}"
        + f".b{{font-weight:600;fill:{INK}}}.i{{fill:{INK}}}.f{{fill:{FAINT}}}.a{{fill:{ACCENT}}}"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
        f"<title>{escape(title)}</title><style>{style}</style>{body}</svg>\n"
    )


def t(x: float, y: float, content: str, size: int = 14, cls: str = "", anchor: str = "start", extra: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    a = f' text-anchor="{anchor}"' if anchor != "start" else ""
    return f'<text x="{x}" y="{y}" font-size="{size}"{c}{a}{extra} xml:space="preserve">{escape(content)}</text>'


def window(x: int, y: int, w: int, h: int, label: str, note: str = "") -> str:
    """A titled TUI pane: a prompt-coloured marker, a name and a right-aligned note."""
    parts = [
        f'<rect x="{x + .5}" y="{y + .5}" width="{w - 1}" height="{h - 1}" rx="8" fill="{PANEL}" stroke="{LINE}"/>',
        f'<line x1="{x}" y1="{y + 36.5}" x2="{x + w}" y2="{y + 36.5}" stroke="{LINE}"/>',
        t(x + 18, y + 23, "~", 13, "a"),
        t(x + 34, y + 23, label, 13, "b"),
    ]
    if note:
        parts.append(t(x + w - 18, y + 23, note, 13, "f", "end"))
    return "".join(parts)


# ---------------------------------------------------------------- ASCII avatar

RAMP = " .:-=+*#%@"

# The avatar's ring, as an ellipse in a 0..1 unit square of the uncropped image:
# centre, semi-axes and tilt. Its red is too faint to detect from pixels.
RING = (0.405, 0.333, 0.266, 0.036, -0.351)


def on_ring(u: float, v: float) -> bool:
    """True near the ring's front arc; the back arc is hidden behind the head."""
    cx, cy, a, b, angle = RING
    dx, dy = u - cx, v - cy
    ca, sa = math.cos(angle), math.sin(angle)
    x, y = dx * ca + dy * sa, -dx * sa + dy * ca
    near = abs(math.hypot(x / a, y / b) - 1) < 0.2 or (abs(y) < b * 1.3 and abs(abs(x) - a) < 0.025)
    return near and (y > -b * 0.2 or abs(x) > a * 0.8)


def ascii_rows(avatar: Path, cols: int, rows: int, crop: float = 0.07) -> list[list[tuple[str, bool]]]:
    """Map the avatar to characters. Edges get the densest glyphs so the silhouette reads;
    cells on the ring are flagged for the accent colour."""
    with Image.open(avatar) as im:
        gray = im.convert("L")
        side = min(gray.size)
        box = (int(side * crop), int(side * crop), int(side * (1 - crop)), int(side * (1 - crop)))
        gray = gray.crop(box).filter(ImageFilter.GaussianBlur(side / 260))
        small = gray.resize((cols, rows), Image.LANCZOS)
        edges = small.filter(ImageFilter.FIND_EDGES)
    out = []
    for yy in range(rows):
        row = []
        for xx in range(cols):
            lum = small.getpixel((xx, yy)) / 255
            # FIND_EDGES marks the image border itself; ignore it
            border = xx in (0, cols - 1) or yy in (0, rows - 1)
            edge = 0 if border else edges.getpixel((xx, yy)) / 255
            # interior whites become mid-density texture, outlines become solid
            level = 0.62 * lum ** 1.4 + 0.9 * edge
            if lum < 0.12 and edge < 0.18:
                level = 0
            ch = RAMP[max(0, min(len(RAMP) - 1, int(level * len(RAMP))))]
            u = crop + (xx + 0.5) / cols * (1 - 2 * crop)
            v = crop + (yy + 0.5) / rows * (1 - 2 * crop)
            row.append((ch, on_ring(u, v) and ch != " "))
        out.append(row)
    return out


def ascii_block(rows: list[list[tuple[str, bool]]], cx: float, top: float, size: float, lead: float) -> str:
    width = len(rows[0]) * size * ADVANCE
    x = cx - width / 2
    lines = []
    for i, row in enumerate(rows):
        spans, run, run_red = [], "", False
        for ch, red in row:
            if red != run_red and run:
                spans.append((run, run_red))
                run = ""
            run_red = red
            run += ch
        spans.append((run, run_red))
        inner = "".join(
            f'<tspan class="a">{escape(s)}</tspan>' if red else escape(s) for s, red in spans
        )
        lines.append(
            f'<text x="{x:.1f}" y="{top + i * lead:.1f}" font-size="{size}" class="i" '
            f'xml:space="preserve" opacity=".92">{inner}</text>'
        )
    return "".join(lines)


# ---------------------------------------------------------------- header

PROMPTS = [
    'Try "ship the inbox before the coffee wears off"',
    'Try "find a date picker that isn\'t ugly"',
    'Try "one more level, then sleep"',
]


def header(avatar: Path) -> str:
    W, H = 1200, 660
    body = [
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="14" fill="{BG}" stroke="{LINE}"/>',
        *[f'<circle cx="{26 + i * 20}" cy="24" r="6" fill="#2c2c2c"/>' for i in range(3)],
        t(W / 2, 29, "~/screen-gd", 14, "f", "middle"),
        # main pane with its label cut into the top border
        f'<rect x="32.5" y="62.5" width="1135" height="463" rx="8" fill="none" stroke="{LINE}"/>',
        f'<rect x="50" y="54" width="{len("screen-gd") * 14 * ADVANCE + 20:.0f}" height="18" fill="{BG}"/>',
        t(60, 68, "screen-gd", 14, "i"),
    ]

    # left column: name, ASCII portrait, location
    cx = 262
    body.append(t(cx, 112, "Screen", 18, "b", "middle"))
    rows = ascii_rows(avatar, cols=78, rows=39)
    body.append(ascii_block(rows, cx, 140, 7.2, 8.5))
    body.append(t(cx, 498, "Sharjah, UAE", 14, "f", "middle"))
    body.append(f'<line x1="492.5" y1="96" x2="492.5" y2="494" stroke="{LINE}"/>')

    # right column
    x = 532
    sections = [
        ("About", 116, [("Designs and builds web & desktop software.", ""),
                        ("Game dev at heart. Runs on caffeine.", "")]),
        ("Now", 236, [("Col   ", "i", "UI libraries, all in one place"),
                      ("Emc²  ", "i", "one inbox for every account")]),
        ("Stack", 348, [("TypeScript · Next.js · Electron · Rust", "")]),
        ("Elsewhere", 426, [("znsnexus.com · zaid.us.ci · @screeendev on X", "")]),
    ]
    for title, y, lines in sections:
        body.append(t(x, y, title, 15, "b"))
        for n, line in enumerate(lines):
            ly = y + 30 + n * 26
            if len(line) == 3:
                lead, cls, rest = line
                body.append(
                    f'<text x="{x}" y="{ly}" font-size="15" xml:space="preserve">'
                    f'<tspan class="{cls}">{escape(lead)}</tspan>{escape(rest)}</text>'
                )
            else:
                body.append(t(x, ly, line[0], 15))
    body.append(f'<line x1="{x}" y1="196.5" x2="1136" y2="196.5" stroke="{LINE}"/>')

    # prompt bar with rotating placeholders and a blinking cursor
    body.append(f'<rect x="32.5" y="548.5" width="1135" height="55" rx="8" fill="none" stroke="#333"/>')
    body.append(t(54, 582, ">", 16, "a"))
    body.append(
        f'<rect x="76" y="565" width="9" height="21" fill="{INK}">'
        '<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" repeatCount="indefinite"/></rect>'
    )
    n = len(PROMPTS)
    for i, prompt in enumerate(PROMPTS):
        # each prompt is visible for its own third of a 12s loop
        start, end = i / n, (i + 1) / n
        # discrete steps: a linear ramp would fade the next prompt in over the current one
        values, times = ["0", "1", "0"], [0, start, end]
        if i == 0:
            values, times = ["1", "0"], [0, end]
        elif i == n - 1:
            values, times = ["0", "1"], [0, start]
        body.append(
            f'<text x="96" y="582" font-size="15" class="f" opacity="{1 if i == 0 else 0}" '
            f'xml:space="preserve">{escape(prompt)}'
            f'<animate attributeName="opacity" values="{";".join(values)}" '
            f'keyTimes="{";".join(f"{v:.3f}" for v in times)}" dur="12s" calcMode="discrete" repeatCount="indefinite"/></text>'
        )
    body.append(t(54, 634, "? for shortcuts", 13, "f"))
    body.append(t(1146, 634, "col · emc² · closure · screen-time", 13, "f", "end"))

    text = "".join(ch for row in rows for ch, _ in row) + "".join(PROMPTS) + str(sections) + \
        "~/screen-gd Screen Sharjah, UAE ? for shortcuts col · emc² · closure · screen-time >"
    return svg(W, H, "Screen (screen-gd): designs and builds web and desktop software", "".join(body), text)


# ---------------------------------------------------------------- project tiles

def tile(image: Path, name: str, kind: str, blurb: str, domain: str, side: str) -> str:
    """Half of a 1200-wide row. Shown at width=50% with no gap between the two images,
    so the row matches the header's width; the 16px gutter lives inside the SVGs."""
    W, H, gutter = 600, 408, 8
    x0 = 0 if side == "left" else gutter
    cw = W - gutter
    ih = round(cw * 630 / 1200)
    with Image.open(image) as im:
        im = im.convert("RGB").resize((1000, 525), Image.LANCZOS)
        buffer = io.BytesIO()
        im.save(buffer, "JPEG", quality=84, optimize=True, progressive=True)
    data = base64.b64encode(buffer.getvalue()).decode()
    body = [
        f'<defs><clipPath id="c"><rect x="{x0}" width="{cw}" height="{H}" rx="10"/></clipPath></defs>',
        f'<g clip-path="url(#c)"><rect x="{x0}" width="{cw}" height="{H}" fill="{PANEL}"/>',
        f'<image x="{x0}" y="0" width="{cw}" height="{ih}" preserveAspectRatio="xMidYMid slice" '
        f'href="data:image/jpeg;base64,{data}" xlink:href="data:image/jpeg;base64,{data}"/>',
        f'<line x1="{x0}" y1="{ih + .5}" x2="{x0 + cw}" y2="{ih + .5}" stroke="{LINE}"/></g>',
        f'<rect x="{x0 + .5}" y=".5" width="{cw - 1}" height="{H - 1}" rx="10" fill="none" stroke="{LINE}"/>',
        t(x0 + 22, ih + 41, name, 22, "b"),
        t(x0 + cw - 22, ih + 41, kind, 13, "f", "end"),
        t(x0 + 22, ih + 71, blurb, 14),
        t(x0 + cw - 22, ih + 71, domain, 14, "i", "end"),
    ]
    text = name + kind + blurb + domain
    return svg(W, H, f"{name}: {blurb} ({domain})", "".join(body), text)


# ---------------------------------------------------------------- repo list

REPOS = [
    ("Closure", "self-hosted feedback, changelog & roadmap", "web", "TypeScript"),
    ("screen-time", "which app and which website took your day", "windows", "JavaScript"),
    ("Syllo", "work in progress", "-", "Python"),
]


def repo_list() -> str:
    W = 1200
    row_h = 46
    H = 37 + 34 + row_h * len(REPOS) + 14
    body = [
        f'<rect width="{W}" height="{H}" rx="8" fill="{BG}"/>',
        window(0, 0, W, H, "more", "other repos on github.com/screen-gd"),
        t(22, 60, "repo", 13, "f"), t(380, 60, "what", 13, "f"),
        t(900, 60, "runs on", 13, "f"), t(1178, 60, "lang", 13, "f", "end"),
    ]
    for i, (name, what, where, lang) in enumerate(REPOS):
        y = 71 + i * row_h
        body.append(f'<line x1="0" y1="{y + .5}" x2="{W}" y2="{y + .5}" stroke="{LINE}"/>')
        body.append(t(22, y + 29, name, 15, "b"))
        body.append(t(380, y + 29, what, 14))
        body.append(t(900, y + 29, where, 14, "i"))
        body.append(t(1178, y + 29, lang, 14, "f", "end"))
    text = "".join("".join(r) for r in REPOS) + "~repowhatruns onlangmoreother repos on github.com/screen-gd"
    return svg(W, H, "More repositories by screen-gd", "".join(body), text)


def main() -> None:
    avatar = Path(sys.argv[1])
    outputs = {
        "header.svg": header(avatar),
        "tile-col.svg": tile(ASSETS / "website-col.png", "Col", "web",
                             "UI libraries, all in one place", "usecol.com", "left"),
        "tile-emc2.svg": tile(ASSETS / "website-emc2.png", "Emc²", "desktop",
                              "one inbox for every account", "emclient2.vercel.app", "right"),
        "repos.svg": repo_list(),
    }
    for name, content in outputs.items():
        (ASSETS / name).write_text(content, encoding="utf-8")
        print(f"{name}: {len(content.encode()) // 1024} KB")


if __name__ == "__main__":
    main()
