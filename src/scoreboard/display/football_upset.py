"""The upset alert screen (#557): a ranked college team is losing to a lower-ranked or unranked one.

``UPSET ALERT`` flashing in red over the matchup (the ranked team that is behind first, its number
beside it, then the team beating it), and the clock with how far behind it is. At the final the
header is a steady gold ``UPSET FINAL`` and the line says how much it lost by. 128px only (an idle
screen, like the red zone alert); silent.

A pure function of the game and the seconds it has been up, like the other alerts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.models import FbGame, FbTeam
from ..football.upset import Upset
from . import football_scenes as fs
from .fonts import text_width

if TYPE_CHECKING:
    from .renderer import Renderer

ALERT = (235, 50, 50)
ALERT_DIM = (110, 22, 22)
FINAL_GOLD = (255, 200, 40)
WHITE = (255, 255, 255)
#: The header flashes: bright for the first half of each period, dim for the second.
FLASH_SECONDS = 1.0


def draw_fb_upset(r: Renderer, canvas: Any, game: FbGame, upset: Upset, seconds: float) -> None:
    canvas.Clear()
    cx = r.width // 2
    if upset.final:
        header, color = "UPSET FINAL", FINAL_GOLD
    else:
        bright = (seconds % FLASH_SECONDS) < FLASH_SECONDS / 2
        header, color = "UPSET ALERT", ALERT if bright else ALERT_DIM
    r.text_center(canvas, r.fonts.large, cx, 13, color, header)
    _matchup(r, canvas, upset, 23)
    r.text_center(canvas, r.fonts.tiny, cx, 31, fs.status_color(game), _status(game, upset, r))


def _status(game: FbGame, upset: Upset, r: Renderer) -> str:
    margin = upset.margin
    if upset.final:
        return f"FINAL  LOST BY {margin}"
    clock = "HALFTIME" if game.is_halftime else fs.band_clock(game, r).upper()
    return f"{clock}  DOWN {margin}"


def _matchup(r: Renderer, canvas: Any, upset: Upset, baseline: int) -> None:
    """``5 TEX 17   OKST 20``: the favourite then the team beating it, each with its number
    (if ranked), abbreviation in its colour and score in white. The numbers are dropped, then the
    font shrunk, if the line is too wide."""
    font = r.fonts.small

    def parts(badges: bool, font: Any) -> list[tuple[str, tuple[int, int, int], int]]:
        out: list[tuple[str, tuple[int, int, int], int]] = []
        for team, after in ((upset.favourite, 6), (upset.underdog, 0)):
            badge = fs.rank_badge(team, r) if badges else ""
            if badge:
                out.append((badge, fs.RANK_COLOR, 3))
            out.append((team.abbrev, _color(team), 3))
            out.append((str(team.score), WHITE, after))
        return out

    def width(items: list[tuple[str, tuple[int, int, int], int]], f: Any) -> int:
        return sum(text_width(f, t) + gap for t, _, gap in items)

    items = parts(True, font)
    if width(items, font) > r.width - 2:
        items = parts(False, font)
    if width(items, font) > r.width - 2:
        font = r.fonts.tiny
        items = parts(False, font)
    x = max(0, (r.width - width(items, font) + items[-1][2]) // 2)
    for text, color, gap in items:
        r.text(canvas, font, x, baseline, color, text)
        x += text_width(font, text) + gap


def _color(team: FbTeam) -> tuple[int, int, int]:
    return fs.side_color(team)
