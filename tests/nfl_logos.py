"""Synthetic NFL logos for tests and docs (#349): a plain circle in each team's colour.

The real crests are team artwork: fetched, git-ignored and never committed, exactly like the
NHL ones. Anything that needs NFL logos without the artwork writes these instead.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from nhl_scoreboard.football.teams import TEAMS


def write_synthetic_nfl_logos(root: Path, sizes=(12, 16), variant: str = "dark") -> Path:
    """Write ``root/nfl/<size>/<variant>/<ABBREV>.png`` for all 32 teams; returns ``root``."""
    for size in sizes:
        directory = root / "nfl" / str(size) / variant
        directory.mkdir(parents=True, exist_ok=True)
        for abbrev, team in TEAMS.items():
            image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            ImageDraw.Draw(image).ellipse((0, 0, size - 1, size - 1), fill=(*team.color, 255))
            image.save(directory / f"{abbrev}.png")
    return root
