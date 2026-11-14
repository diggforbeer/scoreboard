"""The NFL screens between games (#423-#429), 128px only (decided; see
``screens_not_during_games.md``). Each is a pure function of the data and the clock.

``football/idle_screens.py`` decides when one is chosen; this draws it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..football.models import FbGame, FbTeam
from .football_scenes import DIM, WHITE, side_color

if TYPE_CHECKING:
    from .renderer import Renderer

LOGO_SIZE = 16
#: Centre of the left and right logo, as the halftime card has them.
LEFT_X, RIGHT_DX = 14, 15
LOGO_CY = 13


def draw_side_logo(r: Renderer, canvas: Any, side: FbTeam, x: int, cy: int = LOGO_CY) -> None:
    """``side``'s 16px crest centred on ``x``, else its abbreviation in its colour."""
    have_art = r.nfl_logos is not None and side.is_nfl
    logo = r.nfl_logos.get(side.abbrev, LOGO_SIZE) if have_art else None
    if logo is None:
        r.text_center(canvas, r.fonts.small, x, cy + 3, side_color(side), side.abbrev)
        return
    ox, oy = x - logo.width // 2, cy - logo.height // 2
    for dx, dy, (red, green, blue) in logo.pixels:
        canvas.SetPixel(ox + dx, oy + dy, red, green, blue)


def countdown_text(seconds: float) -> str:
    """``0:42:15``: hours, minutes, seconds, never negative."""
    total = max(int(seconds), 0)
    return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def kickoff_line(game: FbGame, r: Renderer) -> str:
    """``SUN 12:00 PM  FOX``: the local day and time, then the broadcast if the feed gave one."""
    if game.start_utc is None:
        return ""
    local = game.start_utc.astimezone(r.tz)
    when = f"{local:%a} {local:%I:%M %p}".replace(" 0", " ").upper()
    return f"{when}  {game.broadcasts[0].upper()}" if game.broadcasts else when


def draw_fb_countdown(r: Renderer, canvas: Any, game: FbGame, now: datetime) -> None:
    """Kickoff is close: both crests and records at the edges, ``KICKOFF IN`` over the
    countdown in the large face, the day, time and broadcast under it.

    A record or broadcast the feed did not give is left out. At 0:00:00 it holds there until
    the game is live and the board hands over to it.
    """
    canvas.Clear()
    cx = r.width // 2
    away, home = game.away, game.home
    draw_side_logo(r, canvas, away, LEFT_X)
    draw_side_logo(r, canvas, home, r.width - RIGHT_DX)
    r.text_center(canvas, r.fonts.tiny, cx, 7, DIM, "KICKOFF IN")
    remaining = (game.start_utc - now).total_seconds() if game.start_utc is not None else 0.0
    r.text_center(canvas, r.fonts.large, cx, 21, WHITE, countdown_text(remaining))
    line = r._fit_text(r.fonts.tiny, kickoff_line(game, r), r.width - 58)
    if line:
        r.text_center(canvas, r.fonts.tiny, cx, 31, DIM, line)
    for side, x in ((away, LEFT_X), (home, r.width - RIGHT_DX)):
        if side.record:
            r.text_center(canvas, r.fonts.tiny, x, 31, DIM, side.record)
