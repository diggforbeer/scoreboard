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


def fb_standings_division() -> Panel:
    """The favourite's division: rank, team, record, streak, points for-against."""
    p = Panel()
    table_header(p, "NFC EAST", "WK 10")
    rows = [("1", "NYG", "5-3-1", "W2", "256-187"), ("2", "DAL", "4-5", "L1", "201-222"),
            ("3", "PHI", "4-4", "W1", "190-198"), ("4", "WSH", "3-6", "L3", "151-240")]  # fmt: skip
    for i, (rank, team, rec, streak, points) in enumerate(rows):
        y = 13 + i * 6
        fav = team == FAV
        txt = WHITE if fav else DIM
        p.rect(7, y - 4, 9, y - 2, TEAMS[team])
        p.text("4x6", 14, y, txt, rank)
        team_text(p, "4x6", 24, y, team, team, 1.0 if fav else 0.7)
        p.text("4x6", 48, y, txt, rec)
        p.text("4x6", 80, y, GREEN if streak.startswith("W") else RED, streak)
        p.text("4x6", 94, y, txt, points)
        if fav:
            p.vline(3, y - 5, y, WHITE)
    return p


def fb_standings_conference() -> Panel:
    """The conference seeds, 1-7 and the cut line, in two columns."""
    p = Panel()
    table_header(p, "NFC SEEDS", "WK 10")
    left = [("1", "PHI", "7-1"), ("2", "DET", "7-2"), ("3", "NYG", "5-3-1"), ("4", "SEA", "5-4")]
    right = [("5", "GB", "6-2"), ("6", "SF", "5-4"), ("7", "DAL", "4-5")]
    for rows, x0 in ((left, 4), (right, 68)):
        for i, (seed, team, rec) in enumerate(rows):
            y = 13 + i * 6
            fav = team == FAV
            txt = WHITE if fav else DIM
            p.text("4x6", x0, y, txt, seed)
            team_text(p, "4x6", x0 + 8, y, team, team, 1.0 if fav else 0.7)
            p.text("4x6", x0 + 28, y, txt, rec)
            if fav:
                p.vline(x0 - 3, y - 5, y, WHITE)
    p.line(68, 26, 124, 26, scale(AMBER, 0.6))  # the cut line under seed 7
    p.text("4x6", 68, 31, DIM, "8 CHI 4-5")
    return p


def fb_week() -> Panel:
    """The league's slate, eight games a page (away over home): finals with the winner bright, a
    game in progress in green, an upcoming one with its kickoff hour. Two pages for 16 games."""
    p = Panel()
    games = [
        ("WSH", 17, "NYG", 24, "F"), ("DAL", 20, "PHI", 27, "F"), ("DET", 31, "GB", 28, "F"),
        ("SF", 14, "SEA", 10, "LIVE"), ("BUF", 0, "CHI", 0, "1P"), ("MIA", 0, "NE", 0, "1P"),
        ("KC", 0, "LV", 0, "4P"), ("LAR", 0, "ARI", 0, "4P"),
    ]  # fmt: skip
    for i, (away, sa, home, sh, status) in enumerate(games):
        col, row = i % 4, i // 4
        x, top = 3 + col * 31, 7 + row * 17
        for t in (away, home):
            TEAMS.setdefault(t, (200, 200, 200))
        final, live = status == "F", status == "LIVE"
        for j, (team, score) in enumerate(((away, sa), (home, sh))):
            y = top + j * 6
            winner = final and score == max(sa, sh)
            team_text(p, "4x6", x, y, team, team, 0.55 if final and not winner else 1.0)
            if final:
                p.text("4x6", x + 16, y, WHITE if winner else DIM, f"{score:>2}")
            elif live:
                p.text("4x6", x + 16, y, GREEN, f"{score:>2}")
        if not (final or live):
            p.text("4x6", x + 16, top, DIM, status)
    p.rect(0, 17, p.w - 1, 17, scale(DIM, 0.35))
    p.rect(60, 31, 61, 31, DIM)  # page 1 of 2
    p.rect(66, 31, 67, 31, scale(DIM, 0.35))
    return p


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
    "fb_standings_division": fb_standings_division,
    "fb_standings_conference": fb_standings_conference,
    "fb_week": fb_week,
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
