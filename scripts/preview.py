#!/usr/bin/env python3
"""Render scoreboard frames as ASCII art, for iterating on layout without hardware.

The emulator's ``graphics`` module is pure Python and draws through
``SetPixel``, so a recording canvas can capture a frame and print it.

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
from nhl_scoreboard.display.fonts import FontSet  # noqa: E402
from nhl_scoreboard.display.renderer import Renderer  # noqa: E402
from nhl_scoreboard.nhl.models import Game  # noqa: E402


class RecordingCanvas:
    """Stands in for a matrix canvas, keeping the pixels that were lit."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels: dict[tuple[int, int], tuple[int, int, int]] = {}

    def Clear(self) -> None:  # noqa: N802 - mirrors the binding's API
        self.pixels.clear()

    def SetPixel(self, x, y, r, g, b) -> None:  # noqa: N802
        if 0 <= x < self.width and 0 <= y < self.height and (r or g or b):
            self.pixels[(int(x), int(y))] = (r, g, b)

    def render(self, on: str = "#", off: str = " ") -> str:
        rows = []
        for y in range(self.height):
            row = "".join(on if (x, y) in self.pixels else off for x in range(self.width))
            if row.strip():
                rows.append("|" + row + "|")
        border = "+" + "-" * self.width + "+"
        return "\n".join([border, *rows, border])


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
    args = parser.parse_args(argv)

    logging.disable(logging.CRITICAL)
    # Imported here so --help works without the optional emulator installed.
    from RGBMatrixEmulator import graphics

    settings = Settings()
    panel = settings.panel
    renderer = Renderer(
        graphics=graphics,
        fonts=FontSet(graphics),
        width=panel.width,
        height=panel.height,
        tz=ZoneInfo(settings.scoreboard.timezone),
        favourite=args.team,
    )

    games = load_games(args.fixture)
    if not games:
        print("No games to draw.")
        return 0

    for game in games[: args.limit]:
        canvas = RecordingCanvas(panel.width, panel.height)
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
