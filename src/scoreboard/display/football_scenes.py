"""The plain football scoreboard (#352): the base every designed ``fb_*`` screen builds on.

This is deliberately **not** one of the designed football screens (the field, the run, the
pass, ...): it is the thin, honest text scoreboard that gets real ESPN data onto the panel,
the football counterpart of the hockey text layout in ``Renderer._draw_game_text``. Away on the
left, home on the right, each abbreviation in its team colour with the score at the edge of
its half; the down and distance (and a red tint in the red zone) while a game is live; the
state of the game along the bottom.

Everything goes through ``SetPixel``-backed drawing calls on the renderer, so hardware, the
emulator, tests and the admin Live view all see the same pixels.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..football.models import FbGame, FbTeam
from ..football.teams import team_color
from .fonts import text_width

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
#: A team that is not one of the 32 (a Pro Bowl side): drawn plain, like the hockey default.
UNKNOWN_TEAM = (220, 220, 220)
#: A ranked college team's number: light violet, so it reads as none of the clock (green), the down
#: and distance (yellow), a score (white) or a team colour (a mockup of the first version, gold,
#: could not be told from the yellow).
RANK_COLOR = (200, 160, 255)


def rank_badge(side: FbTeam, r: Renderer) -> str:
    """``5`` for a ranked college team, else ``""``: just the number, in its own colour (a ``#``
    is not needed, and costs four pixels of a crowded line). 128px panels only: a single 64px
    panel has no room beside the abbreviation, so it never shows a badge."""
    return str(side.rank) if side.rank and r.width >= 128 else ""


def side_color(side: FbTeam) -> tuple[int, int, int]:
    return team_color(side.abbrev) if side.is_football else UNKNOWN_TEAM


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

    label_x: dict[int, int] = {}
    for side, x0 in ((game.away, 0), (game.home, half)):
        x = x0 + 3
        badge = "" if game.is_live else rank_badge(side, r)  # none in a live game
        if badge:
            # The abbreviation moves right to make room, unless that would run into the score.
            shift = text_width(r.fonts.small, badge) + 2
            score_left = (
                x0 + half - 3 - (0 if game.is_pregame else text_width(font, str(side.score)))
            )
            if x + shift + text_width(font, side.abbrev) + 1 <= score_left:
                r.text(canvas, r.fonts.small, x, score_baseline, RANK_COLOR, badge)
                x += shift
        label_x[id(side)] = x
        r.text(canvas, font, x, score_baseline, side_color(side), side.abbrev)
        if not game.is_pregame:
            r.text_right(canvas, font, x0 + half - 3, score_baseline, WHITE, str(side.score))

    r.vline(canvas, half - 1, 2, situation_baseline - 7, DIM)

    sit = game.situation
    if wide and game.is_live and sit is not None:
        from ..football.geometry import AWAY
        from . import football_ball as fball
        from . import football_field as ff

        holder = ff.possession_of(game, sit.possession_team_id)
        if holder is not None:
            team = game.away if holder == AWAY else game.home
            bx = label_x[id(team)] + text_width(font, team.abbrev) + 4
            fball.draw_sprite(canvas, bx, score_baseline - 8, fball.LARGE)
    if game.is_live and sit is not None and sit.down_distance_text:
        color = RED_ZONE if sit.is_red_zone else SITUATION
        text = r._fit_text(r.fonts.tiny, sit.down_distance_text.upper(), r.width - 6)
        r.text_center(canvas, r.fonts.tiny, half, situation_baseline, color, text)

    text = r._fit_text(r.fonts.small, status_text(game, r), r.width - 4)
    r.text_center(canvas, r.fonts.small, half, status_baseline, status_color(game), text)


def draw_fb_field(r: Renderer, canvas: Any, game: FbGame) -> None:
    """The resting field (#378): the screen between plays.

    Turf, end zones tinted in team colours with the logos, the ball at ``yardLine``, the line of
    scrimmage and the first-down line ``distance`` yards ahead **in the direction the offence
    drives** (``yardLine`` runs from the home goal line, so the away team drives toward 0), and a
    one-line band over it: the clock and quarter on the left, the down and distance on the right
    (red in the red zone, which is also tinted on the field), and on a 128px panel the score
    between them, because nothing else on this screen says it. No situation (a kickoff, between
    quarters) draws the plain field. On a single 64px panel the end zones are 7px with no logo and
    the band is the clock and ``2&7`` only.
    """
    from ..football.geometry import FieldLayout
    from . import football_field as ff

    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    sit = game.situation
    side = ff.possession_of(game, sit.possession_team_id) if sit is not None else None
    in_red_zone = sit is not None and sit.is_red_zone and side is not None
    ff.draw_field(
        r,
        canvas,
        layout,
        game.home.abbrev,
        game.away.abbrev,
        side,
        logos=r.football_logos,
        red_zone=side if in_red_zone else None,
    )
    if sit is not None and sit.yard_line is not None:
        if side is not None:
            ff.draw_markers(r, canvas, layout, sit.yard_line, sit.distance or 0, side)
        ff.draw_ball(canvas, layout, sit.yard_line)
    _band(r, canvas, game, sit, in_red_zone, side)


def _band(
    r: Renderer, canvas: Any, game: FbGame, sit: Any, in_red_zone: bool, side: str | None = None
) -> None:
    font, baseline = r.fonts.tiny, 6
    wide = r.width >= 128
    down = ""
    if sit is not None:
        down = (_tight(sit.short_down_distance_text) if wide else _compact_down(sit)).upper()
    color = RED_ZONE if in_red_zone else SITUATION
    right = r._fit_text(font, down, r.width // 2 - 2) if down else ""
    full_clock = band_clock(game, r)

    def clock_room(text: str) -> int:
        return r.width - text_width(font, text) - 3 - (60 if wide else 0)

    if wide and right and text_width(font, full_clock) > clock_room(right):
        # ``1ST&GOAL`` leaves 33px, and ``4TH 10:30`` needs 36: the clock was cut to ``4TH 1...``,
        # which reads as a minute left. A long down shrinks to ``1&G`` before the time is cut.
        right = _squeezed_down(sit)
    clock = r._fit_text(font, full_clock, max(clock_room(right), 8))
    if wide and right:
        # Four-letter college abbreviations and a two-digit score leave no room for a long down
        # (``1ST&GOAL``); it shrinks to ``1&G`` / ``2&7`` rather than printing over the score.
        min_x = 1 + text_width(font, clock) + 3
        if not _score_fits(r, game, min_x, r.width - 1 - text_width(font, right) - 2):
            right = _squeezed_down(sit)
    if right:
        r.text_right(canvas, font, r.width - 1, baseline, color, right)
    r.text(canvas, font, 1, baseline, status_color(game), clock)
    if wide:
        # The score sits between the clock on the left and the down and distance on the right.
        max_x = r.width - 1 - text_width(font, right) - 2 if right else r.width
        _score(r, canvas, game, baseline, side, min_x=1 + text_width(font, clock) + 3, max_x=max_x)


_LIVE_CLOCK = re.compile(r"^\s*(\d{1,2}:\d{2})\s*-\s*(\d)(?:st|nd|rd|th)\s*$", re.I)


def band_clock(game: FbGame, r: Renderer) -> str:
    """``3RD 12:24`` for a live game (the feed says ``12:24 - 3rd``): short enough to leave the
    middle of the band for the score, and not ``Q3`` because the 4x6 ``Q`` reads as a zero.
    Anything else (halftime, OT wording) is shown as the feed words it."""
    match = _LIVE_CLOCK.match(game.short_detail or game.detail or "") if game.is_live else None
    if not match:
        return status_text(game, r)
    n = int(match.group(2))
    ordinal = {1: "1ST", 2: "2ND", 3: "3RD"}.get(n, f"{n}TH")
    return f"{ordinal} {match.group(1)}"


def _tight(text: str) -> str:
    """``1ST & GOAL`` -> ``1ST&GOAL`` when it would crowd the score."""
    return text.replace(" & ", "&") if len(text) > 7 else text


def _squeezed_down(sit: Any) -> str:
    """``1&G`` for goal to go, else ``2&7``: the shortest form that still says what it is."""
    if sit.down is None:
        return _compact_down(sit)
    if "goal" in sit.short_down_distance_text.lower():
        return f"{sit.down}&G"
    return _compact_down(sit)


def _compact_down(sit: Any) -> str:
    """``2&7`` for a 64px band; empty when there is no down."""
    if sit.down is None or sit.distance is None:
        return sit.short_down_distance_text
    return f"{sit.down}&{sit.distance}"


def _score_parts(
    r: Renderer, game: FbGame, badges: bool
) -> list[tuple[str, str, tuple[int, int, int], int]]:
    """(kind, text, colour, gap after) for the band's score: a badge, the abbreviation, then the
    score, per team."""
    out: list[tuple[str, str, tuple[int, int, int], int]] = []
    for side, between in ((game.away, 3), (game.home, 0)):
        badge = rank_badge(side, r) if badges else ""
        if badge:
            out.append(("badge", badge, RANK_COLOR, 1))
        out.append(("abbrev", side.abbrev, side_color(side), 1))
        out.append(("score", str(side.score), WHITE, between))
    return out


def _score_fits(r: Renderer, game: FbGame, min_x: int, max_x: int) -> bool:
    """Whether the band's score fits between ``min_x`` and ``max_x`` even with no badges."""
    from . import football_ball as fball

    font = r.fonts.tiny
    ball_w = fball.sprite_width(fball.SMALL) + 1
    total = sum(text_width(font, t) + g for _, t, _, g in _score_parts(r, game, False)) + 2 * ball_w
    return max((r.width - total) // 2, min_x) + total <= max_x


def _score(
    r: Renderer,
    canvas: Any,
    game: FbGame,
    baseline: int,
    side: str | None = None,
    min_x: int = 0,
    max_x: int | None = None,
) -> None:
    """``WSH 10 NYG 17`` centred in the band, each abbreviation in its team's colour. The team
    with the ball gets a small football before its abbreviation; both slots are reserved so the
    text does not jump on a turnover."""
    from ..football.geometry import AWAY, HOME
    from . import football_ball as fball

    font = r.fonts.tiny
    ball_w = fball.sprite_width(fball.SMALL) + 1

    def placed(badges: bool) -> tuple[list[tuple[str, str, tuple[int, int, int], int]], int, int]:
        parts = _score_parts(r, game, badges)
        total = sum(text_width(font, t) + gap for _, t, _, gap in parts) + 2 * ball_w
        return parts, total, max((r.width - total) // 2, min_x)

    # No rank badges on a live game (owner's call, 2026-11-22: too cluttered); `badges` stays for
    # the layout helpers' sake.
    parts, _total, x = placed(False)
    teams = iter((AWAY, HOME))
    holder = None
    for kind, text, color, gap in parts:
        if kind == "abbrev":
            holder = next(teams)
            if side == holder:
                fball.draw_sprite(canvas, x, baseline - 4, fball.SMALL)
            x += ball_w
        r.text(canvas, font, x, baseline, color, text)
        x += text_width(font, text) + gap


def draw_fb_halftime(r: Renderer, canvas: Any, game: FbGame) -> None:
    """The halftime card (#388): what the board holds on from the end of the half until play
    resumes. ``HALFTIME`` in the large font, both teams' logos at the edges (128px only, 16px,
    else their abbreviations) and the score under it. Never a rank badge (owner's call)."""
    canvas.Clear()
    wide = r.width >= 128
    cx = r.width // 2
    font = r.fonts.large
    r.text_center(canvas, font, cx, 15, WHITE, "HALFTIME")
    if wide:
        for side, x in ((game.away, 14), (game.home, r.width - 15)):
            logo = (
                r.football_logos.get(side.abbrev, 16)
                if r.football_logos is not None and side.is_football
                else None
            )
            if logo is not None:
                ox, oy = x - logo.width // 2, 16 - logo.height // 2
                for dx, dy, (red, green, blue) in logo.pixels:
                    canvas.SetPixel(ox + dx, oy + dy, red, green, blue)
            else:
                r.text_center(canvas, r.fonts.small, x, 19, side_color(side), side.abbrev)

    # No rank badges here, by the owner's call (2026-11-22, from a real board at the half of
    # Georgia at South Carolina): the card is about the score, and a number before each team made
    # the line cluttered. Every other college screen keeps its badges.
    parts: list[tuple[str, tuple[int, int, int], int]] = []
    for side, between in ((game.away, 6), (game.home, 0)):
        parts.append((side.abbrev, side_color(side), 2))
        parts.append((str(side.score), WHITE, between))
    font = r.fonts.small
    total = sum(text_width(font, t) + gap for t, _, gap in parts)
    if total > r.width - 2:  # a long score on a narrow panel: drop to the smaller font
        font = r.fonts.tiny
        total = sum(text_width(font, t) + gap for t, _, gap in parts)
    x = max(0, (r.width - total) // 2)
    for text, color, gap in parts:
        r.text(canvas, font, x, 29, color, text)
        x += text_width(font, text) + gap
