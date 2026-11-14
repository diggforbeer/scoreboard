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
from .football_scenes import DIM, LIVE, RED_ZONE, UNKNOWN_TEAM, WHITE

if TYPE_CHECKING:
    from .renderer import Renderer

LOGO_SIZE = 16
#: Centre of the left and right logo, as the halftime card has them.
LEFT_X, RIGHT_DX = 14, 15
LOGO_CY = 13


def _dimmed(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return (int(color[0] * factor), int(color[1] * factor), int(color[2] * factor))


def draw_side_logo(
    r: Renderer, canvas: Any, abbrev: str, x: int, cy: int = LOGO_CY, dim: float = 1.0
) -> None:
    """``abbrev``'s 16px crest centred on ``x``, else the abbreviation in its colour.
    ``dim`` (0-1) darkens it: the loser of a final."""
    known = is_team(abbrev)
    logo = r.nfl_logos.get(abbrev, LOGO_SIZE) if r.nfl_logos is not None and known else None
    if logo is None:
        color = _dimmed(team_color(abbrev) if known else UNKNOWN_TEAM, dim)
        r.text_center(canvas, r.fonts.small, x, cy + 3, color, abbrev)
        return
    ox, oy = x - logo.width // 2, cy - logo.height // 2
    for dx, dy, color in logo.pixels:
        red, green, blue = _dimmed(color, dim)
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


#: The loser's crest, as a fraction of its brightness.
LOSER_DIM = 0.4
RECAP_GAP = 2  # px between recap entries (on top of the font's own spacing)


def recap_segments(r: Renderer, view: Any, room: int) -> list[tuple[str, tuple[int, int, int]]]:
    """The recap entries that fit ``room`` px as (text, colour), best first. A surname too long
    for the row on its own is cut to fit; no leaders at all gives the margin line instead."""
    font = r.fonts.tiny
    segments = [(f"{line.surname} {line.yards} YD", team_color(line.team)) for line in view.recap]
    if not segments:
        return [(view.margin, DIM)]
    chosen: list[tuple[str, tuple[int, int, int]]] = []
    used = 0
    for text, color in segments:
        width = text_width(font, text) + (RECAP_GAP * 2 if chosen else 0)
        if used + width > room:
            break
        chosen.append((text, color))
        used += width
    if not chosen:
        text, color = segments[0]
        chosen.append((r._fit_text(font, text, room), color))
    return chosen


def draw_fb_final(r: Renderer, canvas: Any, view: Any, now: datetime) -> None:
    """The favourite's final, held after the game: both crests (the loser's dimmed), ``FINAL``
    over the score in the large face, and the recap across the bottom -- the game's top
    passer, rusher and receiver as far as they fit, each in his team's colour, else the margin."""
    canvas.Clear()
    game = view.game
    cx = r.width // 2
    away_dim = LOSER_DIM if game.away.winner is False or game.away.score < game.home.score else 1.0
    home_dim = LOSER_DIM if game.home.winner is False or game.home.score < game.away.score else 1.0
    draw_side_logo(r, canvas, game.away.abbrev, LEFT_X, 12, away_dim)
    draw_side_logo(r, canvas, game.home.abbrev, r.width - RIGHT_DX, 12, home_dim)
    r.text_center(canvas, r.fonts.tiny, cx, 7, DIM, view.status)
    r.text_center(canvas, r.fonts.large, cx, 21, WHITE, f"{game.away.score} - {game.home.score}")
    segments = recap_segments(r, view, r.width - 4)
    total = sum(text_width(r.fonts.tiny, t) for t, _ in segments) + RECAP_GAP * 2 * (
        len(segments) - 1
    )
    x = (r.width - total) // 2
    for text, color in segments:
        r.text(canvas, r.fonts.tiny, x, 31, color, text)
        x += text_width(r.fonts.tiny, text) + RECAP_GAP * 2


def _team_ink(abbrev: str, factor: float) -> tuple[int, int, int]:
    return _dimmed(team_color(abbrev) if is_team(abbrev) else UNKNOWN_TEAM, factor)


def _table_header(r: Renderer, canvas: Any, title: str, sub: str) -> None:
    r.text(canvas, r.fonts.tiny, 3, 6, AMBER, title)
    if sub:
        r.text_right(canvas, r.fonts.tiny, r.width - 3, 6, DIM, sub)


def _marker(r: Renderer, canvas: Any, abbrev: str, x: int, y: int) -> None:
    """The little team-colour chip beside a row."""
    for dy in (-4, -3, -2):
        r.hline(canvas, x, x + 2, y + dy, _team_ink(abbrev, 1.0))


def draw_fb_standings(r: Renderer, canvas: Any, view: Any, page: int = 0) -> None:
    """Page 0: the favourite's division (rank, team, record, streak, points for-against).
    Page 1: the conference's seven seeds with the cut line and the first team out. The favourite
    is white with a bar at the edge; the others are dimmed team colours. A view without seeds
    has the division page only."""
    canvas.Clear()
    if page == 1 and view.seeds:
        _draw_conference(r, canvas, view)
    else:
        _draw_division(r, canvas, view)


def _draw_division(r: Renderer, canvas: Any, view: Any) -> None:
    _table_header(r, canvas, view.division_name, view.week)
    font = r.fonts.tiny
    for i, row in enumerate(view.division[:4]):
        y = 13 + i * 6
        mine = row.team == view.team
        ink = WHITE if mine else DIM
        _marker(r, canvas, row.team, 7, y)
        r.text(canvas, font, 14, y, ink, str(i + 1))
        r.text(canvas, font, 24, y, _team_ink(row.team, 1.0 if mine else 0.7), row.team)
        r.text(canvas, font, 48, y, ink, row.overall)
        streak = (LIVE if row.streak.startswith("W") else RED_ZONE) if row.streak else ink
        r.text(canvas, font, 80, y, streak, row.streak)
        r.text(canvas, font, 94, y, ink, f"{row.points_for}-{row.points_against}")
        if mine:
            r.vline(canvas, 3, y - 5, y, WHITE)
    if len(view.seeds) > 0:
        r.hline(canvas, 60, 61, r.height - 1, DIM)  # page 1 of 2
        r.hline(canvas, 66, 67, r.height - 1, _dimmed(DIM, 0.35))


CUT_COLOR = (153, 102, 0)  # the amber cut line, dimmed


def _draw_conference(r: Renderer, canvas: Any, view: Any) -> None:
    _table_header(r, canvas, f"{view.conference} SEEDS", view.week)
    font = r.fonts.tiny
    columns = ((view.seeds[:4], 4, 0), (view.seeds[4:], 68, 4))
    for rows, x0, first in columns:
        for i, row in enumerate(rows):
            y = 13 + i * 6
            mine = row.team == view.team
            ink = WHITE if mine else DIM
            r.text(canvas, font, x0, y, ink, str(first + i + 1))
            r.text(canvas, font, x0 + 8, y, _team_ink(row.team, 1.0 if mine else 0.7), row.team)
            r.text(canvas, font, x0 + 28, y, ink, row.overall)
            if mine:
                r.vline(canvas, x0 - 3, y - 5, y, WHITE)
    r.hline(canvas, 68, 124, 26, CUT_COLOR)
    out = view.first_out
    if out is not None:
        mine = out.team == view.team
        seed = out.seed if out.seed is not None else PLAYOFF_NEXT
        text = f"{seed} {out.team} {out.overall}"
        r.text(canvas, font, 68, 31, WHITE if mine else DIM, text)
        if mine:
            r.vline(canvas, 65, 26, 31, WHITE)
    r.hline(canvas, 60, 61, r.height - 1, _dimmed(DIM, 0.35))
    r.hline(canvas, 66, 67, r.height - 1, DIM)


PLAYOFF_NEXT = 8
