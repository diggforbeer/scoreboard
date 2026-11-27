#!/usr/bin/env python3
"""Fetch team logos and rasterise them for the panel.

Hockey: downloads each team's SVG from the hockey's asset CDN -- the same source the
score API links per team -- and renders it to a small PNG. Football (#349): reads the
logo links out of ESPN's teams endpoint and downsizes its 500px PNGs. Run before an
image build (CI does) and for local development; output is git-ignored, so the
repository never redistributes the artwork itself.

    python scripts/fetch-logos.py               # hockey: 32px, both variants
    python scripts/fetch-logos.py --size 32 --variant dark
    python scripts/fetch-logos.py --sport football   # football: 12px and 16px, dark
    python scripts/fetch-logos.py --sport college    # the FBS's ~134 teams: 12px and 16px

The "dark" variant is drawn for dark backgrounds and is what a black LED
panel wants; several teams' "light" marks are near-black and vanish (the football
"light" variant is ESPN's default art). Football art goes under ``assets/logos/football/``
so a ``BUF`` is never confused between the leagues.

College (#541) is football's recipe over the FBS table, keyed by ESPN id (``a.espncdn.com/i/
teamlogos/ncaa/500/<id>.png`` and its ``500-dark`` variant), written under ``assets/logos/college/``
because the NFL and the FBS share abbreviations that mean different teams. For each team *both*
variants are downloaded and the one that reads brighter on black is kept (as the hockey's choice
of ``dark`` is made by hand), then brightened if still too dim. ``assets/logos/college/overrides/``
holds hand-fixed crests that win over the fetched ones.

Football sizes: **12px** is the logo in each end zone (a 14px end zone on a 128px panel) and
**16px** is the larger one for the coin toss and score screens. Checked on a contact sheet
of real logos on turf: 12px reads for most teams, 16px for all, 8px and below is a blob.
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from scoreboard.display.teams import TEAM_COLORS  # noqa: E402
from scoreboard.football.teams import ABBREVIATIONS as FOOTBALL_ABBREVIATIONS  # noqa: E402

LOGO_URL = "https://assets.nhle.com/logos/nhl/svg/{abbrev}_{variant}.svg"
ESPN_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams"
USER_AGENT = "scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"
#: The sizes fetched for the football by default (see the module docstring).
FOOTBALL_SIZES = (12, 16)
#: Which of ESPN's logo entries each variant name means.
FOOTBALL_REL = {"dark": ("full", "dark"), "light": ("full", "default")}
#: A crest whose lit pixels average darker than this (0-255 luma) is brightened, like the hockey
#: table lifts navy and burgundy team colours: Carolina's black panther measured 31 at 12px
#: with no bright pixel at all, where every other team is 62 or more. ESPN's other variants
#: (on-black, white) do not help: it is a black cat. Never brightened more than ``LIFT_CAP``x.
LIFT_FLOOR = 60.0
LIFT_CAP = 3.0
DEFAULT_OUT = REPO_ROOT / "assets" / "logos"
RENDER_WIDTH = 640  # rasterise large, then crop and downscale for clean edges


def rasterise(svg_bytes: bytes, size: int):
    import cairosvg
    from PIL import Image

    png = cairosvg.svg2png(bytestring=svg_bytes, output_width=RENDER_WIDTH)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        # The hockey SVGs sit inside a 960x640 viewBox with generous margins;
        # cropping to the drawn area is what makes 32px usable.
        image = image.crop(bbox)
    image.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def rasterise_png(png_bytes: bytes, size: int):
    """A downloaded PNG, cropped to what is drawn and fitted to ``size`` x ``size``.

    Cropping matters as much as for the hockey SVGs: ESPN's 500px logos have a margin, and
    spending the 12 pixels on it would shrink the crest.
    """
    from PIL import Image

    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    bbox = image.getbbox()
    if bbox:
        image = image.crop(bbox)
    image.thumbnail((size, size), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(image, ((size - image.width) // 2, (size - image.height) // 2))
    return canvas


def lift_dim(image, floor: float = LIFT_FLOOR, cap: float = LIFT_CAP):
    """``(image, factor)``: ``image`` brightened by ``factor`` if it is too dim for an LED panel.

    Only the lit pixels (alpha at or above the logo library's floor) count, so a mostly
    transparent crest is not judged by its margin. ``factor`` is 1.0 when nothing was done.
    """
    px = image.load()
    width, height = image.size
    lit = [(x, y) for y in range(height) for x in range(width) if px[x, y][3] >= 48]
    if not lit:
        return image, 1.0
    mean = sum(
        0.2126 * px[x, y][0] + 0.7152 * px[x, y][1] + 0.0722 * px[x, y][2] for x, y in lit
    ) / len(lit)
    if mean >= floor:
        return image, 1.0
    factor = min(cap, floor / max(mean, 1.0))
    out = image.copy()
    target = out.load()
    for x, y in lit:
        r, g, b, a = px[x, y]
        target[x, y] = (
            min(255, int(r * factor)),
            min(255, int(g * factor)),
            min(255, int(b * factor)),
            a,
        )
    return out, factor


#: Football crests whose dark pixels (black, navy, burgundy) vanish into a DARK end-zone tint
#: (``lift_dark``). NO, WSH and LV scored as weak too, but their end zones are gold or silver, so
#: their dark marks already read (dark on light) and lifting them only makes grey on grey.
DARK_CRESTS = frozenset({"CAR", "CHI", "TB"})
DARK_FLOOR = 120.0


def lift_dark(image, floor: float = DARK_FLOOR):
    """``image`` with every lit pixel darker than ``floor`` (luma) mixed toward white until it
    reaches it. ``lift_dim`` multiplies, so it cannot help black; this keeps the crest's bright
    marks as they are and turns its black outlines and fills into readable greys."""
    out = image.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a < 48:
                continue
            luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if luma >= floor:
                continue
            t = (floor - luma) / (255.0 - luma)
            px[x, y] = (
                round(r + (255 - r) * t),
                round(g + (255 - g) * t),
                round(b + (255 - b) * t),
                a,
            )
    return out


def fetch(abbrev: str, variant: str) -> bytes:
    import requests

    response = requests.get(LOGO_URL.format(abbrev=abbrev, variant=variant), timeout=20)
    response.raise_for_status()
    return response.content


def fetch_football_index() -> dict[str, dict[str, str]]:
    """ESPN's logo links: ``{abbrev: {variant: url}}`` for every team in the football endpoint."""
    import requests

    response = requests.get(ESPN_TEAMS_URL, timeout=20, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    index: dict[str, dict[str, str]] = {}
    for entry in response.json()["sports"][0]["leagues"][0]["teams"]:
        team = entry["team"]
        links = {tuple(logo.get("rel", ())): logo.get("href", "") for logo in team.get("logos", [])}
        index[team["abbreviation"].upper()] = {
            variant: links[rel] for variant, rel in FOOTBALL_REL.items() if links.get(rel)
        }
    return index


COLLEGE_LOGO_URLS = {
    "default": "https://a.espncdn.com/i/teamlogos/ncaa/500/{id}.png",
    "dark": "https://a.espncdn.com/i/teamlogos/ncaa/500-dark/{id}.png",
}


def lit_mean(image) -> float:
    """The mean luma (0-255) of the lit pixels of an RGBA ``image``, as ``lift_dim`` judges it;
    0.0 for an image with nothing lit."""
    px = image.load()
    width, height = image.size
    lit = [px[x, y] for y in range(height) for x in range(width) if px[x, y][3] >= 48]
    if not lit:
        return 0.0
    return sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in lit) / len(lit)


def best_variant(candidates: dict[str, bytes], size: int):
    """``(name, image)`` of the downloaded variant that reads brightest at ``size``: ESPN's
    ``500-dark`` art is drawn for dark backgrounds but is not always the better one (some marks
    are only on the default art). Ties keep the dark variant."""
    rendered = {name: rasterise_png(data, size) for name, data in candidates.items()}
    order = sorted(rendered, key=lambda name: (-lit_mean(rendered[name]), name != "dark"))
    return order[0], rendered[order[0]]


def fetch_college_table():
    """Every FBS team (id, abbreviation) from ESPN: two requests, ~1.9 MB (``FootballClient``)."""
    from scoreboard.football.api import LEAGUE_COLLEGE, FootballClient

    table = FootballClient(league=LEAGUE_COLLEGE).college_teams()
    if table is None:
        raise RuntimeError("ESPN's FBS team table could not be read")
    return table


def fetch_college(args: argparse.Namespace) -> int:
    """College logos into ``<out>/college/<size>/dark/<ABBREV>.png`` (#541): the better-reading
    of ESPN's two variants per team, brightened if still dim. The folder is named ``dark`` because
    that is the variant the app asks for; it holds whichever art suits a black panel."""
    sizes = args.size or list(FOOTBALL_SIZES)
    try:
        table = fetch_college_table()
    except Exception as exc:
        print(f"error: could not read ESPN's FBS team list: {exc}", file=sys.stderr)
        return 1
    teams = {t.abbrev.upper(): t for t in table.teams}
    wanted = [a.strip().upper() for a in args.teams] if args.teams else sorted(teams)
    unknown = [a for a in wanted if a not in teams]
    if unknown:
        print(f"error: not FBS teams: {', '.join(unknown)}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for abbrev in wanted:
        team = teams[abbrev]
        downloaded: dict[str, bytes] = {}
        for name, pattern in COLLEGE_LOGO_URLS.items():
            try:
                downloaded[name] = fetch_url(pattern.format(id=team.espn_id))
            except Exception as exc:  # a missing variant is fine while the other exists
                print(f"  {abbrev}  {name} variant unavailable: {exc}", file=sys.stderr)
        if not downloaded:
            failures.append(f"{abbrev}: no logo downloaded")
            continue
        for size in sizes:
            target = args.out / "college" / str(size) / "dark" / f"{abbrev}.png"
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                name, image = best_variant(downloaded, size)
                image, factor = lift_dim(image)
                image.save(target)
            except Exception as exc:  # one bad logo must not stop the rest
                failures.append(f"{abbrev} ({size}px): {exc}")
                print(f"  {abbrev}  {size}px FAILED: {exc}", file=sys.stderr)
                continue
            note = f"  (brightened x{factor:.1f})" if factor > 1.0 else ""
            print(f"  {abbrev:<5} {size}px {name:<7} -> {_show(target)}{note}")

    if failures:
        print(f"\n{len(failures)} logo(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    shown = ", ".join(f"{size}px" for size in sizes)
    print(f"\nFetched {len(wanted)} college teams at {shown}")
    return 0


def fetch_url(url: str) -> bytes:
    import requests

    response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.content


def _show(target: Path) -> Path:
    try:
        return target.relative_to(REPO_ROOT)
    except ValueError:  # --out points outside the repo
        return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--sport",
        choices=["hockey", "football", "college"],
        default="hockey",
        help="Which league's logos",
    )
    parser.add_argument(
        "--size",
        type=int,
        nargs="+",
        default=None,
        help="Output width/height in px (default: 32 for the hockey; 12 and 16 for the football)",
    )
    parser.add_argument(
        "--variant",
        choices=["dark", "light", "both"],
        default=None,
        help="Which artwork (default: both for the hockey, dark for the football)",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output root directory")
    parser.add_argument("--teams", nargs="*", default=None, help="Abbrevs to fetch (default: all)")
    args = parser.parse_args(argv)

    if args.sport == "football":
        return fetch_football(args)
    if args.sport == "college":
        return fetch_college(args)

    sizes = args.size or [32]
    variants_choice = args.variant or "both"
    teams = args.teams if args.teams is not None else sorted(TEAM_COLORS)
    variants = ["dark", "light"] if variants_choice == "both" else [variants_choice]
    failures: list[str] = []
    for size in sizes:
        for variant in variants:
            out_dir = args.out / str(size) / variant
            out_dir.mkdir(parents=True, exist_ok=True)
            for abbrev in teams:
                target = out_dir / f"{abbrev}.png"
                try:
                    rasterise(fetch(abbrev, variant), size).save(target)
                except Exception as exc:  # one bad logo must not stop the rest
                    failures.append(f"{abbrev} ({variant}): {exc}")
                    print(f"  {variant:<5} {abbrev}  FAILED: {exc}", file=sys.stderr)
                    continue
                print(f"  {variant:<5} {abbrev}  -> {_show(target)}")

    if failures:
        print(f"\n{len(failures)} logo(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    shown = ", ".join(f"{size}px" for size in sizes)
    print(f"\nFetched {len(teams)} teams x {len(variants)} variant(s) at {shown}")
    return 0


def fetch_football(args: argparse.Namespace) -> int:
    """Football logos from ESPN into ``<out>/football/<size>/<variant>/<ABBREV>.png`` (#349)."""
    sizes = args.size or list(FOOTBALL_SIZES)
    variants_choice = args.variant or "dark"
    variants = ["dark", "light"] if variants_choice == "both" else [variants_choice]
    teams = [t.strip().upper() for t in (args.teams or FOOTBALL_ABBREVIATIONS)]
    unknown = [t for t in teams if t not in FOOTBALL_ABBREVIATIONS]
    if unknown:
        print(f"error: not football teams: {', '.join(unknown)}", file=sys.stderr)
        return 2
    try:
        index = fetch_football_index()
    except Exception as exc:
        print(f"error: could not read ESPN's team list: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    downloaded: dict[tuple[str, str], bytes] = {}
    for size in sizes:
        for variant in variants:
            out_dir = args.out / "football" / str(size) / variant
            out_dir.mkdir(parents=True, exist_ok=True)
            for abbrev in teams:
                target = out_dir / f"{abbrev}.png"
                try:
                    key = (abbrev, variant)
                    if key not in downloaded:  # each logo is downloaded once, not once per size
                        url = index.get(abbrev, {}).get(variant)
                        if not url:
                            raise LookupError(f"ESPN lists no {variant} logo")
                        downloaded[key] = fetch_url(url)
                    image, factor = lift_dim(rasterise_png(downloaded[key], size))
                    if abbrev in DARK_CRESTS:
                        image = lift_dark(image)
                    image.save(target)
                except Exception as exc:  # one bad logo must not stop the rest
                    failures.append(f"{abbrev} ({variant}, {size}px): {exc}")
                    print(f"  {variant:<5} {abbrev}  {size}px FAILED: {exc}", file=sys.stderr)
                    continue
                note = f"  (too dim: brightened x{factor:.1f})" if factor > 1.0 else ""
                print(f"  {variant:<5} {abbrev}  {size}px -> {_show(target)}{note}")

    if failures:
        print(f"\n{len(failures)} logo(s) failed:", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1
    shown = ", ".join(f"{size}px" for size in sizes)
    print(f"\nFetched {len(teams)} football teams x {len(variants)} variant(s) at {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
