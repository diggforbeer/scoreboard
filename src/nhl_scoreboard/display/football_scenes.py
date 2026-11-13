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
        logos=r.nfl_logos,
        red_zone=side if in_red_zone else None,
    )
    if sit is not None and sit.yard_line is not None:
        if side is not None:
            ff.draw_markers(r, canvas, layout, sit.yard_line, sit.distance or 0, side)
        ff.draw_ball(canvas, layout, sit.yard_line)
    _band(r, canvas, game, sit, in_red_zone)


def _band(r: Renderer, canvas: Any, game: FbGame, sit: Any, in_red_zone: bool) -> None:
    font, baseline = r.fonts.tiny, 6
    wide = r.width >= 128
    down = ""
    if sit is not None:
        down = (_tight(sit.short_down_distance_text) if wide else _compact_down(sit)).upper()
    color = RED_ZONE if in_red_zone else SITUATION
    right = r._fit_text(font, down, r.width // 2 - 2) if down else ""
    if right:
        r.text_right(canvas, font, r.width - 1, baseline, color, right)
    left_room = r.width - text_width(font, right) - 3 - (56 if wide else 0)
    clock = r._fit_text(font, band_clock(game, r), max(left_room, 8))
    r.text(canvas, font, 1, baseline, status_color(game), clock)
    if wide:
        _score(r, canvas, game, baseline)


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


def _compact_down(sit: Any) -> str:
    """``2&7`` for a 64px band; empty when there is no down."""
    if sit.down is None or sit.distance is None:
        return sit.short_down_distance_text
    return f"{sit.down}&{sit.distance}"


def _score(r: Renderer, canvas: Any, game: FbGame, baseline: int) -> None:
    """``WSH 10 NYG 17`` centred in the band, each abbreviation in its team's colour."""
    font = r.fonts.tiny
    parts = [
        (game.away.abbrev, side_color(game.away)),
        (str(game.away.score), WHITE),
        (game.home.abbrev, side_color(game.home)),
        (str(game.home.score), WHITE),
    ]
    gaps = (2, 4, 2, 0)  # abbreviation-score, between the teams, abbreviation-score
    total = sum(text_width(font, t) for t, _ in parts) + sum(gaps)
    x = (r.width - total) // 2
    for (text, color), gap in zip(parts, gaps, strict=True):
        r.text(canvas, font, x, baseline, color, text)
        x += text_width(font, text) + gap


def draw_fb_halftime(r: Renderer, canvas: Any, game: FbGame) -> None:
    """The halftime card (#388): what the board holds on from the end of the half until play
    resumes. ``HALFTIME`` in the large font, both teams' logos at the edges (128px only, 16px,
    else their abbreviations) and the score under it."""
    canvas.Clear()
    wide = r.width >= 128
    cx = r.width // 2
    font = r.fonts.large
    r.text_center(canvas, font, cx, 15, WHITE, "HALFTIME")
    if wide:
        for side, x in ((game.away, 14), (game.home, r.width - 15)):
            logo = (
                r.nfl_logos.get(side.abbrev, 16)
                if r.nfl_logos is not None and side.is_nfl
                else None
            )
            if logo is not None:
                ox, oy = x - logo.width // 2, 16 - logo.height // 2
                for dx, dy, (red, green, blue) in logo.pixels:
                    canvas.SetPixel(ox + dx, oy + dy, red, green, blue)
            else:
                r.text_center(canvas, r.fonts.small, x, 19, side_color(side), side.abbrev)
    parts = [
        (game.away.abbrev, side_color(game.away)),
        (str(game.away.score), WHITE),
        (game.home.abbrev, side_color(game.home)),
        (str(game.home.score), WHITE),
    ]
    gaps = (2, 6, 2, 0)
    font = r.fonts.small
    total = sum(text_width(font, t) for t, _ in parts) + sum(gaps)
    if total > r.width - 2:  # a long score on a narrow panel: drop to the smaller font
        font = r.fonts.tiny
        total = sum(text_width(font, t) for t, _ in parts) + sum(gaps)
    x = max(0, (r.width - total) // 2)
    for (text, color), gap in zip(parts, gaps, strict=True):
        r.text(canvas, font, x, 29, color, text)
        x += text_width(font, text) + gap
