#!/usr/bin/env python3
"""Render scoreboard frames as ASCII art, for iterating on layout without hardware.

Uses the same AsciiCanvas the snapshot tests do, so what you see here is
exactly what tests/test_render.py asserts on.

    python scripts/preview.py              # today's live games
    python scripts/preview.py --fixture    # the checked-in test fixture
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from nhl_scoreboard.config import Settings  # noqa: E402
from nhl_scoreboard.display.ascii import AsciiCanvas  # noqa: E402
from nhl_scoreboard.display.fonts import FontSet  # noqa: E402
from nhl_scoreboard.display.logos import LogoLibrary  # noqa: E402
from nhl_scoreboard.display.renderer import Renderer  # noqa: E402
from nhl_scoreboard.nhl.models import Game  # noqa: E402


def load_games(use_fixture: bool) -> list[Game]:
    if use_fixture:
        path = REPO_ROOT / "tests" / "fixtures" / "score.json"
        return [Game.from_api(raw) for raw in json.loads(path.read_text())["games"]]
    from nhl_scoreboard.nhl.api import NHLClient

    with NHLClient() as client:
        return client.scores()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help="Use the test fixture, not the API")
    parser.add_argument("--team", default="", help="Favourite team, e.g. TOR")
    parser.add_argument("--limit", type=int, default=3, help="How many games to draw")
    parser.add_argument("--no-logos", action="store_true", help="Force the text layout")
    args = parser.parse_args(argv)

    logging.disable(logging.CRITICAL)
    # Imported here so --help works without the optional emulator installed.
    from RGBMatrixEmulator import graphics

    settings = Settings()
    panel = settings.panel
    variant = settings.scoreboard.logo_variant
    renderer = Renderer(
        graphics=graphics,
        fonts=FontSet(graphics),
        width=panel.width,
        height=panel.height,
        tz=ZoneInfo(settings.scoreboard.timezone),
        favourite=args.team,
        logos=None if args.no_logos else LogoLibrary.default(variant=variant),
    )

    games = load_games(args.fixture)
    if not games:
        print("No games to draw.")
        return 0

    w_mm, h_mm = panel.physical_mm
    print(f"{panel.width}x{panel.height} px at P{panel.pitch_mm:g} = {w_mm:g} x {h_mm:g} mm")

    for game in games[: args.limit]:
        canvas = AsciiCanvas(panel.width, panel.height)
        renderer.draw_game(canvas, game)
        status = game.status_label(renderer.tz)
        print(
            f"\n{game.away.abbrev} {game.away.score} @ "
            f"{game.home.abbrev} {game.home.score}  [{status}]"
        )
        print(canvas.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
