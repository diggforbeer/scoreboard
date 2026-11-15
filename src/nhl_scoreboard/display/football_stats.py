"""The split team stats shown over an official timeout or the two-minute warning.

A TV timeout is the one stretch where nothing is moving, so the board shows how the game is going
instead of a field with a ball on it. Away on the left, home on the right (like the text
scoreboard), each team's 16px logo at its edge, and between them a table: the stat's name in the
middle, each side's number beside its logo. Five rows a page, the pages sharing the stage's
seconds (``stats_seconds``). Whoever is ahead on a row shows it in their team colour and the other
side dims, so the leader reads at a glance; a tie keeps both lit. Under each logo a pair of dots
says which page this is.

A pure function of the seconds since the stage began, like every other play screen. 128px only:
the director never starts the stage on a narrower panel (a split table does not fit 64px).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import STATS
from ..football.stats import PAGES, GameStats
from ..football.teams import is_team, team_color
from .football_plays import DIM, WHITE, event_screen

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

#: Row baselines for the tiny font (6px a row, five rows).
ROW_BASELINES = (6, 12, 18, 24, 30)
#: Where a side's numbers start, clear of its 16px logo.
LEFT_X, RIGHT_X = 19, 108
LOGO_CENTRE_Y = 16
TRAILING = (70, 70, 70)
LIT_DOT, UNLIT_DOT = WHITE, (45, 45, 45)


def page_of(scene: Scene, pages: int) -> int:
    """Which page is up: the stage's seconds are one page's length, and the pages keep taking
    turns for as long as the stage is held."""
    if scene.fb_seconds <= 0:
        return 0
    return int(max(0.0, scene.fb_elapsed) // scene.fb_seconds) % pages


def _color(abbrev: str) -> tuple[int, int, int]:
    return team_color(abbrev) if is_team(abbrev) else WHITE


def _logo(r: Renderer, canvas: Any, abbrev: str, cx: int) -> None:
    logos = r.football_logos
    logo = logos.get(abbrev, 16) if logos is not None and is_team(abbrev) else None
    if logo is None:
        r.text_center(canvas, r.fonts.small, cx, LOGO_CENTRE_Y + 3, _color(abbrev), abbrev)
        return
    ox, oy = cx - logo.width // 2, LOGO_CENTRE_Y - logo.height // 2
    for dx, dy, (red, green, blue) in logo.pixels:
        canvas.SetPixel(ox + dx, oy + dy, red, green, blue)


def _dots(canvas: Any, cx: int, page: int, pages: int) -> None:
    """One 2x2 dot a page under a logo, the current one lit."""
    x0 = cx - (pages * 4 - 2) // 2
    for i in range(pages):
        shade = LIT_DOT if i == page else UNLIT_DOT
        for dx in range(2):
            for dy in range(2):
                canvas.SetPixel(x0 + i * 4 + dx, 28 + dy, *shade)


def draw_stats(r: Renderer, canvas: Any, scene: Scene) -> None:
    canvas.Clear()
    game, stats = scene.fb_game, scene.fb_stats
    if game is None or not isinstance(stats, GameStats):
        return
    away, home = game.away.abbrev, game.home.abbrev
    colors = {"away": _color(away), "home": _color(home)}
    page = page_of(scene, len(PAGES))

    _logo(r, canvas, away, 8)
    _logo(r, canvas, home, r.width - 8)
    _dots(canvas, 8, page, len(PAGES))
    _dots(canvas, r.width - 8, page, len(PAGES))

    mid = r.width // 2
    for row, baseline in zip(PAGES[page], ROW_BASELINES, strict=False):
        ahead = stats.leader(row)
        r.text_center(canvas, r.fonts.tiny, mid, baseline, DIM, row.label)
        for side, x, draw in (
            ("away", LEFT_X, r.text),
            ("home", RIGHT_X, r.text_right),
        ):
            color = TRAILING if ahead not in (None, side) else colors[side]
            draw(canvas, r.fonts.tiny, x, baseline, color, stats.value(side, row.key))


@event_screen(type(None), STATS)
def draw_team_stats(r: Renderer, canvas: Any, scene: Scene) -> None:
    draw_stats(r, canvas, scene)
