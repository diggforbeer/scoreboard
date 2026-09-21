#!/usr/bin/env python3
"""Fetch NHL team logos and rasterise them for the panel.

Downloads each team's SVG from the NHL's asset CDN -- the same source the
score API links per team -- and renders it to a small PNG. Run before an
image build (CI does) and for local development; output is git-ignored, so
the repository never redistributes the artwork itself.

    python scripts/fetch-logos.py               # 32px, both variants
    python scripts/fetch-logos.py --size 32 --variant dark

The "dark" variant is drawn for dark backgrounds and is what a black LED
panel wants; several teams' "light" marks are near-black and vanish.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from nhl_scoreboard.display.teams import TEAM_COLORS  # noqa: E402

LOGO_URL = "https://assets.nhle.com/logos/nhl/svg/{abbrev}_{variant}.svg"
DEFAULT_OUT = REPO_ROOT / "assets" / "logos"
RENDER_WIDTH = 640  # rasterise large, then crop and downscale for clean edges


def rasterise(svg_bytes: bytes, size: int):
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(bytestring=svg_bytes, output_width=RENDER_WIDTH)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        # The NHL SVGs sit inside a 960x640 viewBox with generous margins;
        # cropping to the drawn area is what makes 32px usable.
        image = image.crop(bbox)
    image.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def fetch(abbrev: str, variant: str) -> bytes:
    import requests

    response = requests.get(LOGO_URL.format(abbrev=abbrev, variant=variant), timeout=20)
    response.raise_for_status()
    return response.content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--size", type=int, default=32, help="Output width/height in px")
    parser.add_argument(
        "--variant", choices=["dark", "light", "both"], default="both", help="Which NHL artwork"
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output root directory")
    parser.add_argument("--teams", nargs="*", default=sorted(TEAM_COLORS), help="Abbrevs to fetch")
    args = parser.parse_args(argv)

    variants = ["dark", "light"] if args.variant == "both" else [args.variant]
    failures: list[str] = []
    for variant in variants:
        out_dir = args.out / str(args.size) / variant
        out_dir.mkdir(parents=True, exist_ok=True)
        for abbrev in args.teams:
            target = out_dir / f"{abbrev}.png"
            try:
                rasterise(fetch(abbrev, variant), args.size).save(target)
                print(f"  {variant:<5} {abbrev}  -> {target.relative_to(REPO_ROOT)}")
            except Exception as exc:  # one bad logo must not stop the rest
                failures.append(f"{abbrev} ({variant}): {exc}")
                print(f"  {variant:<5} {abbrev}  FAILED: {exc}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} logo(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"\nFetched {len(args.teams)} teams x {len(variants)} variant(s) at {args.size}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
