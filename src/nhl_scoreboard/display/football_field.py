"""The static field every football screen draws on (#358): turf, end zones, yard lines, the two
end-zone logos, the line of scrimmage and the first-down line, and the ball.

All of it goes through the renderer's line primitives and ``SetPixel`` (never ``SetImage``), so
hardware, the emulator, the tests and the admin Live view see the same pixels. The geometry lives
in ``football.geometry`` (pure, tested without a canvas); this module only draws it. It draws the
field and nothing above it: the caller clears the canvas and owns the band of text on top.

Layout (see ``docs/football/fb_field.png``): on a 128px panel the end zones are 14px, so the
playing field is exactly 100px for 100 yards; the home team's end zone is on the left and the away
team's on the right, each tinted in its team colour with the team's logo (12px) when there is
room. The team with the ball has its logo at full brightness and the other is dimmed. On a
narrower field (a 64px panel, or a 64px region) the end zones are 7px and carry no logo, only the
tint, because a logo that small is an unreadable blob (checked on real art, #349).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import AWAY, EZ_WIDE, HOME, FieldLayout, first_down_line
from ..football.teams import is_team, team_color
from .fonts import text_width

if TYPE_CHECKING:
    from ..football.models import FbGame
    from .logos import LogoSet
    from .renderer import Renderer

RGB = tuple[int, int, int]

# -- colours (LED-tuned; mirrored in the tests) ------------------------------------------------
TURF: RGB = (0, 52, 16)
YARD_LINE: RGB = (0, 104, 40)
MID_FIELD: RGB = (0, 150, 60)
SCRIMMAGE: RGB = (70, 130, 255)
FIRST_DOWN: RGB = (255, 225, 0)
BALL: RGB = (214, 130, 54)
#: The red zone: the 20 yards in front of the goal line the offence is attacking.
RED_ZONE_TINT: RGB = (90, 0, 0)
RED_ZONE_YARDS = 20
#: A team that is not one of the 32: drawn plain, like the NHL default.
UNKNOWN_TEAM: RGB = (220, 220, 220)
#: How much of a team's colour tints its end zone.
END_ZONE_TINT = 0.30
#: The logo of the team without the ball.
DIM_LOGO = 0.45

#: The logo drawn in an end zone, in pixels, and the size that has to exist in ``LogoSet``.
END_ZONE_LOGO_SIZE = 12


def _scale(color: RGB, factor: float) -> RGB:
    return (round(color[0] * factor), round(color[1] * factor), round(color[2] * factor))


def team_rgb(abbrev: str) -> RGB:
    """An NFL team's colour; a stand-in colour for anything that is not one of the 32."""
    return team_color(abbrev) if is_team(abbrev) else UNKNOWN_TEAM


def draw_field(
    r: Renderer,
    canvas: Any,
    layout: FieldLayout,
    home: str,
    away: str,
    possession: str | None = None,
    *,
    logos: LogoSet | None = None,
    scrimmage: float | None = None,
    first_down: float | None = None,
    red_zone: str | None = None,
) -> None:
    """Draw the field for ``home`` (left) versus ``away`` (right).

    ``possession`` is ``HOME``, ``AWAY`` or ``None`` (nobody has the ball yet: both logos at full
    brightness). ``scrimmage`` and ``first_down`` are yard lines (0-100 from the home goal line)
    for the two markers; leave them out for a plain field. ``red_zone`` is the side whose offence
    is inside the opponent's 20, and tints the 20 yards it attacks. ``logos`` supplies the
    end-zone art; without it, or without a team's logo, the abbreviation is drawn instead where
    it fits.
    """
    colors = {HOME: team_rgb(home), AWAY: team_rgb(away)}
    names = {HOME: home, AWAY: away}

    for y in range(layout.top, layout.bottom + 1):
        r.hline(canvas, layout.left, layout.right - 1, y, TURF)
    for side in (HOME, AWAY):
        first, last = layout.end_zone_columns(side)
        tint = _scale(colors[side], END_ZONE_TINT)
        for y in range(layout.top, layout.bottom + 1):
            r.hline(canvas, first, last, y, tint)

    if red_zone in (HOME, AWAY):
        # The offence drives toward 100 when it is the home team (see geometry.drive_direction).
        near, far = (100 - RED_ZONE_YARDS, 100) if red_zone == HOME else (0, RED_ZONE_YARDS)
        for y in range(layout.top, layout.bottom + 1):
            r.hline(canvas, layout.px(near), layout.px(far), y, RED_ZONE_TINT)

    for yard in range(0, 101, 10):
        color = MID_FIELD if yard in (0, 50, 100) else YARD_LINE
        r.vline(canvas, layout.px(yard), layout.top, layout.bottom, color)
    for yard in range(5, 100, 10):
        x = layout.px(yard)
        canvas.SetPixel(x, layout.top + 3, *YARD_LINE)
        canvas.SetPixel(x, layout.bottom - 3, *YARD_LINE)

    for side in (HOME, AWAY):
        bright = possession in (None, side)
        _draw_end_zone_mark(r, canvas, layout, side, names[side], colors[side], logos, bright)

    if scrimmage is not None:
        r.vline(canvas, layout.px(scrimmage), layout.top, layout.bottom, SCRIMMAGE)
    if first_down is not None:
        r.vline(canvas, layout.px(first_down), layout.top, layout.bottom, FIRST_DOWN)


def draw_markers(
    r: Renderer,
    canvas: Any,
    layout: FieldLayout,
    yard_line: float,
    distance: float,
    possession: str,
) -> None:
    """The line of scrimmage and the first-down line for a ball at ``yard_line``.

    The first-down line lies ``distance`` yards ahead in the direction ``possession`` drives, and
    stops at the goal line when the distance is longer than what is left (goal to go).
    """
    from ..football.geometry import drive_direction

    r.vline(canvas, layout.px(yard_line), layout.top, layout.bottom, SCRIMMAGE)
    target = first_down_line(yard_line, distance, drive_direction(possession))
    r.vline(canvas, layout.px(target), layout.top, layout.bottom, FIRST_DOWN)


def draw_ball(
    canvas: Any,
    layout: FieldLayout,
    yard_line: float,
    y: float | None = None,
    color: RGB = BALL,
) -> None:
    """The ball: a 3x2 dot with a highlight above it, at ``yard_line`` on row ``y`` (the middle
    of the field by default)."""
    bx = layout.px(yard_line)
    by = layout.mid_y if y is None else round(y)
    for dx in (-1, 0, 1):
        for dy in (0, 1):
            canvas.SetPixel(bx + dx, by + dy, *color)
    canvas.SetPixel(bx, by - 1, *_scale(color, 0.7))


def possession_of(game: FbGame, team_id: int | None) -> str | None:
    """``HOME``, ``AWAY`` or ``None`` for the team that has the ball."""
    from ..football.geometry import possession_side

    return possession_side(game, team_id)


def _draw_end_zone_mark(
    r: Renderer,
    canvas: Any,
    layout: FieldLayout,
    side: str,
    name: str,
    color: RGB,
    logos: LogoSet | None,
    bright: bool,
) -> None:
    """A team's logo in its end zone, or its abbreviation where there is room, or nothing."""
    if layout.end_zone < EZ_WIDE:
        return  # too narrow for a readable logo: the tint is the team's mark here
    first, last = layout.end_zone_columns(side)
    factor = 1.0 if bright else DIM_LOGO
    logo = logos.get(name, END_ZONE_LOGO_SIZE) if logos is not None and is_team(name) else None
    if logo is not None:
        ox = first + (last - first + 1 - logo.width) // 2
        oy = layout.mid_y - logo.height // 2
        for dx, dy, (red, green, blue) in logo.pixels:
            shown = _scale((red, green, blue), factor)
            canvas.SetPixel(ox + dx, oy + dy, *shown)
        return
    width = text_width(r.fonts.tiny, name)
    if width <= last - first + 1:
        x = first + (last - first + 1 - width) // 2
        r.text(canvas, r.fonts.tiny, x, layout.mid_y + 3, _scale(color, factor), name)
