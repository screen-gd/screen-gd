"""Bake the profile portrait with astro-dither into assets/portrait.png.

The README portrait is a dithered render of assets/avatar.png produced by the
owner's astro-dither library (@paper-design/shaders WebGL image-dither shader).
GitHub READMEs cannot run it live, so this script mounts <dither-image> once in
headless Edge with software WebGL, screenshots the result, and writes
assets/portrait.png. It is separate from
build_profile.py because it needs a browser and the astro-dither checkout; run
it again only when the avatar or the settings change.

    python scripts/bake_portrait.py [--dither-astro E:/Github/dither-astro]
"""

import argparse
import base64
import io
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SIZE = 288  # CSS and output size; 2px dither cells give a 144x144 grid

# The single place to tune the dither. Parsed by parseImageDitherSettings.
SETTINGS = {"originalColors": True, "type": "8x8", "size": 2, "colorSteps": 4,
            "fit": "cover", "minPixelRatio": 1}

# The two rules from DitherImage.astro, copied verbatim.
CSS = ("dither-image{display:block;position:relative;width:100%;height:100%;overflow:hidden}"
       "dither-image img{position:absolute;inset:0;display:block;width:100%;height:100%;"
       "object-fit:var(--dither-image-fit,cover)}")


def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"{cmd[0]} failed:\n{result.stdout}\n{result.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dither-astro", default=r"E:\Github\dither-astro",
                        help="path to the astro-dither checkout")
    parser.add_argument("--settings", default=None,
                        help="data-dither JSON; defaults to the tuned SETTINGS dict")
    args = parser.parse_args()
    settings = json.loads(args.settings) if args.settings else SETTINGS
    lib = Path(args.dither_astro) / "packages" / "astro-dither" / "src" / "lib"
    if not (lib / "mount-image-dither.ts").exists():
        raise SystemExit(f"mount-image-dither.ts not found under {lib}")

    avatar = base64.b64encode((ROOT / "assets" / "avatar.png").read_bytes()).decode()
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        entry = tmp / "entry.ts"
        entry.write_text(
            f'import {{ defineImageDitherElement }} from '
            f'"{(lib / "mount-image-dither").as_posix()}";\n'
            "defineImageDitherElement();\n", encoding="utf-8")
        bundle = tmp / "bundle.js"
        run(["bun", "build", str(entry), "--outfile", str(bundle)])

        html = tmp / "bake.html"
        html.write_text(
            "<!doctype html><meta charset=utf-8>"
            "<style>html,body{margin:0;background:transparent}" + CSS + "</style>"
            f"<dither-image data-dither='{json.dumps(settings)}' "
            f'style="--dither-image-fit:cover;width:{SIZE}px;height:{SIZE}px">'
            f'<img src="data:image/png;base64,{avatar}" alt="" '
            'crossorigin="anonymous" decoding="async"></dither-image>'
            f'<script type="module">{bundle.read_text(encoding="utf-8")}</script>',
            encoding="utf-8")

        shot = tmp / "shot.png"
        run([EDGE, "--headless=new", "--hide-scrollbars",
             f"--window-size={SIZE},{SIZE}", "--force-device-scale-factor=1",
             "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
             "--virtual-time-budget=15000",
             f"--screenshot={shot}", html.as_uri()])
        with Image.open(shot) as im:
            capture = im.convert("RGBA").resize((SIZE, SIZE), Image.NEAREST)
    cells = np.array(capture).reshape(SIZE // 2, 2, SIZE // 2, 2, 4)
    uniform = (cells == cells[:, :1, :, :1]).all(axis=(1, 2, 3)).mean()
    if uniform < 0.5:
        print(f"warning: only {uniform:.0%} of cells are uniform; "
              "the shader may not have mounted before the screenshot")

    dest = ROOT / "assets" / "portrait.png"
    rgb, pal = capture.convert("RGB"), capture.convert("P", palette=Image.ADAPTIVE)
    candidates = []
    for img in (rgb, pal):
        buffer = io.BytesIO()
        img.save(buffer, "PNG", optimize=True)
        candidates.append(buffer.getvalue())
    dest.write_bytes(min(candidates, key=len))
    print(f"{dest.name}: {dest.stat().st_size // 1024} KB")
    print("settings:", json.dumps(settings))


if __name__ == "__main__":
    main()
