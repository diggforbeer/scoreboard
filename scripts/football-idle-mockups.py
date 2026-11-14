#!/usr/bin/env python3
"""Draw the mockups for screens_not_during_games.md as LED-dot PNGs.

    python scripts/football-idle-mockups.py        # write docs/football-idle/*.png

Like ``football-mockups.py`` (whose Panel and palette it reuses) these are **design mockups,
not renderer output**: hand-drawn to show the layout the design describes, in the project's own
fonts and dot rendering, with plain colour circles for the crests (the artwork is not committed).
They are 128px only (decided: these screens are skipped on a 64px panel). The numbers are made up.
When the screens are built, the images should come from the real renderer and this script should
be deleted.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("fm", REPO_ROOT / "scripts" / "football-mockups.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)

OUT = REPO_ROOT / "docs" / "football-idle"
Panel, scale = fm.Panel, fm.scale
WHITE, DIM, AMBER, GREEN, RED = fm.WHITE, fm.DIM, fm.AMBER, fm.GREEN, fm.RED
fm.TEAMS.update(
    {
        "DAL": (110, 150, 255),
        "PHI": (0, 190, 150),
        "SEA": (80, 220, 120),
        "SF": (230, 40, 40),
        "GB": (60, 200, 80),
        "DET": (60, 170, 255),
        "CHI": (255, 110, 0),
        "BUF": (60, 120, 255),
    }
)
TEAMS = fm.TEAMS
FAV = "NYG"  # the favourite throughout


def team_text(p: Panel, name: str, x: int, y: int, team: str, s: str, dim: float = 1.0) -> int:
    return p.text(name, x, y, scale(TEAMS[team], dim), s)


# -- the screens ---------------------------------------------------------------------------------


def table_header(p: Panel, title: str, sub: str = "") -> None:
    p.text("4x6", 3, 6, AMBER, title)
    if sub:
        p.text("4x6", p.w - p.width_of("4x6", sub) - 3, 6, DIM, sub)


def fb_schedule() -> Panel:
    """The favourite's next three games: week, date, opponent, time."""
    p = Panel()
    table_header(p, "NYG  NEXT", "")
    games = [("11", "SUN 11/22", "AT", "DAL", "12:00P"), ("12", "THU 11/26", "VS", "DET", "7:20P"),
             ("13", "SUN 12/06", "AT", "PHI", "4:25P")]  # fmt: skip
    for i, (wk, day, at, opp, when) in enumerate(games):
        y = 14 + i * 8
        p.text("4x6", 4, y, DIM, f"WK{wk}")
        p.text("4x6", 24, y, WHITE, day)
        p.text("4x6", 62, y, DIM, at)
        p.disc(80, y - 3, 2.5, TEAMS[opp])
        team_text(p, "4x6", 86, y, opp, opp)
        p.text("4x6", 104, y, WHITE, when)
    return p


SCREENS = {
    "fb_schedule": fb_schedule,
}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        if old.stem not in SCREENS:
            old.unlink()
    for name, build in SCREENS.items():
        fm.render_screens.to_image(build().frame()).save(OUT / f"{name}.png", optimize=True)
    print(f"Wrote {len(SCREENS)} mockups to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
