"""The plain NFL scoreboard (#352): the base every designed ``fb_*`` screen builds on.

This is deliberately **not** one of the designed football screens (the field, the run, the
pass, ...): it is the thin, honest text scoreboard that gets real ESPN data onto the panel,
the NFL counterpart of the NHL text layout in ``Renderer._draw_game_text``. Away on the
left, home on the right, each abbreviation in its team colour with the score at the edge of
its half; the down and distance (and a red tint in the red zone) while a game is live; the
state of the game along the bottom.

Everything goes through ``SetPixel``-backed drawing calls on the renderer, so hardware, the
emulator, tests and the admin Live view all see the same pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.models import FbGame, FbTeam
from ..football.teams import team_color

if TYPE_CHECKING:
    from .renderer import Renderer

WHITE = (255, 255, 255)
DIM = (48, 48, 48)
LIVE = (0, 235, 90)
HALFTIME = (255, 170, 0)
FINAL = (150, 150, 150)
PREGAME = (90, 180, 255)
SITUATION = (255, 210, 0)
RED_ZONE = (235, 50, 50)
#: A team that is not one of the 32 (a Pro Bowl side): drawn plain, like the NHL default.
UNKNOWN_TEAM = (220, 220, 220)


def side_color(side: FbTeam) -> tuple[int, int, int]:
    return team_color(side.abbrev) if side.is_nfl else UNKNOWN_TEAM


def status_color(game: FbGame) -> tuple[int, int, int]:
    if game.is_final:
        return FINAL
    if game.is_live:
        return HALFTIME if "HALF" in game.status_name.upper() else LIVE
    return PREGAME


def status_text(game: FbGame, r: Renderer) -> str:
    """What the bottom line says, upper case and short enough for a 64px panel."""
    if game.is_pregame and game.start_utc is not None:
        local = game.start_utc.astimezone(r.tz)
        if r.width < 128:
            return f"{local:%I:%M %p}".lstrip("0")
        return game.status_label(r.tz).upper()
    return (game.short_detail or game.detail or game.status_name or "").upper()


def draw_fb_scores(r: Renderer, canvas: Any, game: FbGame) -> None:
    """One game as text. See the module docstring."""
    canvas.Clear()
    wide = r.width >= 128
    font = r.fonts.large if wide else r.fonts.small
    score_baseline = 13 if wide else 11
    situation_baseline = 20 if wide else 19
    status_baseline = r.height - 2
    half = r.width // 2

    for side, x0 in ((game.away, 0), (game.home, half)):
        r.text(canvas, font, x0 + 3, score_baseline, side_color(side), side.abbrev)
        if not game.is_pregame:
            r.text_right(canvas, font, x0 + half - 3, score_baseline, WHITE, str(side.score))

    r.vline(canvas, half - 1, 2, situation_baseline - 7, DIM)

    sit = game.situation
    if game.is_live and sit is not None and sit.down_distance_text:
        color = RED_ZONE if sit.is_red_zone else SITUATION
        text = r._fit_text(r.fonts.tiny, sit.down_distance_text.upper(), r.width - 6)
        r.text_center(canvas, r.fonts.tiny, half, situation_baseline, color, text)

    text = r._fit_text(r.fonts.small, status_text(game, r), r.width - 4)
    r.text_center(canvas, r.fonts.small, half, status_baseline, status_color(game), text)
