"""The NFL screens between games (#423-#429), 128px only (decided; see
``screens_not_during_games.md``). Each is a pure function of the data and the clock.

``football/idle_screens.py`` decides when one is chosen; this draws it.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from ..football.models import FbGame
from ..football.teams import is_team, team_color
from .fonts import text_width
from .football_scenes import DIM, UNKNOWN_TEAM, WHITE

if TYPE_CHECKING:
    from .renderer import Renderer

LOGO_SIZE = 16
#: Centre of the left and right logo, as the halftime card has them.
LEFT_X, RIGHT_DX = 14, 15
LOGO_CY = 13


def draw_side_logo(r: Renderer, canvas: Any, abbrev: str, x: int, cy: int = LOGO_CY) -> None:
    """``abbrev``'s 16px crest centred on ``x``, else the abbreviation in its colour."""
    known = is_team(abbrev)
    logo = r.nfl_logos.get(abbrev, LOGO_SIZE) if r.nfl_logos is not None and known else None
    if logo is None:
        color = team_color(abbrev) if known else UNKNOWN_TEAM
        r.text_center(canvas, r.fonts.small, x, cy + 3, color, abbrev)
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
    draw_side_logo(r, canvas, away.abbrev, LEFT_X)
    draw_side_logo(r, canvas, home.abbrev, r.width - RIGHT_DX)
    r.text_center(canvas, r.fonts.tiny, cx, 7, DIM, "KICKOFF IN")
    remaining = (game.start_utc - now).total_seconds() if game.start_utc is not None else 0.0
    r.text_center(canvas, r.fonts.large, cx, 21, WHITE, countdown_text(remaining))
    line = r._fit_text(r.fonts.tiny, kickoff_line(game, r), r.width - 58)
    if line:
        r.text_center(canvas, r.fonts.tiny, cx, 31, DIM, line)
    for side, x in ((away, LEFT_X), (home, r.width - RIGHT_DX)):
        if side.record:
            r.text_center(canvas, r.fonts.tiny, x, 31, DIM, side.record)


AMBER = (255, 170, 0)


def preview_top_line(r: Renderer, view: Any, room: int) -> str:
    """``THU NIGHT  WEEK 12`` if it fits ``room`` px, else the tag alone, else the week."""
    tags = [f"{view.tag}  {view.week}".strip(), view.tag, view.week] if view.tag else [view.week]
    for text in tags:
        if text and text_width(r.fonts.tiny, text) <= room:
            return text
    return r._fit_text(r.fonts.tiny, tags[-1], room)


def draw_fb_preview(r: Renderer, canvas: Any, view: Any, now: datetime) -> None:
    """The favourite's next game: both crests with their records at the edges, the week (and
    a primetime or holiday tag in amber) over the day, and the kickoff time in the large face.
    Away is on the left. A record the feed did not give is left out."""
    canvas.Clear()
    cx = r.width // 2
    draw_side_logo(r, canvas, view.away, LEFT_X)
    draw_side_logo(r, canvas, view.home, r.width - RIGHT_DX)
    room = r.width - 48
    top = preview_top_line(r, view, room)
    if top:
        r.text_center(canvas, r.fonts.tiny, cx, 7, AMBER if view.tag else DIM, top)
    local = view.start_utc.astimezone(r.tz)
    r.text_center(
        canvas, r.fonts.small, cx, 16, WHITE, f"{local:%a} {local.month}/{local.day}".upper()
    )
    when = f"{local:%I:%M %p}".lstrip("0")
    r.text_center(canvas, r.fonts.large, cx, 28, WHITE, when)
    for record, x in ((view.away_record, LEFT_X), (view.home_record, r.width - RIGHT_DX)):
        if record:
            r.text_center(canvas, r.fonts.tiny, x, 31, DIM, record)


def next_game_line(view: Any, team: str, r: Renderer) -> str:
    """``SUN 11/22 AT DAL`` (away) or ``SUN 11/22 VS DAL`` (home), in the board's zone."""
    local = view.start_utc.astimezone(r.tz)
    day = f"{local:%a} {local.month}/{local.day}".upper()
    if view.away == team:
        return f"{day} AT {view.home}"
    return f"{day} VS {view.away}"


def draw_fb_bye(r: Renderer, canvas: Any, view: Any, now: datetime) -> None:
    """The favourite's bye week: its crest, ``BYE WEEK`` in its colour and, when the schedule
    knows it, ``NEXT GAME`` over the day and opponent. Without a next game the title is centred
    on its own."""
    canvas.Clear()
    draw_side_logo(r, canvas, view.team, LEFT_X, 16)
    left = LEFT_X + 14
    cx = (left + r.width - 4) // 2
    color = team_color(view.team) if is_team(view.team) else WHITE
    if view.next_game is None:
        r.text_center(canvas, r.fonts.large, cx, 21, color, "BYE WEEK")
        return
    r.text_center(canvas, r.fonts.large, cx, 15, color, "BYE WEEK")
    r.text_center(canvas, r.fonts.tiny, cx, 24, DIM, "NEXT GAME")
    line = r._fit_text(
        r.fonts.small, next_game_line(view.next_game, view.team, r), r.width - left - 4
    )
    r.text_center(canvas, r.fonts.small, cx, 31, WHITE, line)
