"""The college football idle screens' drawers (#579, screens #551-#556).

The idle screens a college board rotates through have their own scene kinds, ``cfb_*``, apart from
the NFL's ``fb_*`` (they show different data: polls, conferences, bowls). This is the registry the
app's draw dispatch reads: a screen's story adds ``@college_screen("cfb_ap")`` over its drawer and
registers its builder in ``football/idle_screens.py`` with ``@idle_screen("cfb_ap")``. Nothing is
drawn here yet; with none registered a college board has no idle rows and sits out the alternation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: scene kind -> ``draw(renderer, canvas, scene, now)``.
COLLEGE_DRAWERS: dict[str, Callable[[Any, Any, Any, Any], None]] = {}


def college_screen(
    kind: str,
) -> Callable[[Callable[[Any, Any, Any, Any], None]], Callable[[Any, Any, Any, Any], None]]:
    """Register ``draw`` as the drawer of the scene kind ``kind``."""

    def register(
        draw: Callable[[Any, Any, Any, Any], None],
    ) -> Callable[[Any, Any, Any, Any], None]:
        COLLEGE_DRAWERS[kind] = draw
        return draw

    return register


# -- the AP Top 25 (#551) -----------------------------------------------------------------------

from ..football.scroll import ROW_HEIGHT  # noqa: E402
from ..football.teams import is_team, team_color  # noqa: E402
from .football_scenes import DIM, LIVE, RANK_COLOR, RED_ZONE, UNKNOWN_TEAM, WHITE  # noqa: E402

AMBER = (255, 176, 0)
#: A row that is not the lead team's: light enough to read at a distance, below the white of
#: the lead team's (``DIM`` is the colour of a status line and was too dark for a table).
GREY = (170, 170, 170)
#: The label block at the left (the poll's name, where hockey's conference table puts "WEST").
LABEL_WIDTH = 30
#: Columns of a row, as offsets from ``LABEL_WIDTH``.
RANK_RIGHT = 9
MOVE_X = 12
ABBREV_X = 28
RECORD_X = 52
POINTS_RIGHT_PAD = 2


def _arrow(canvas: Any, x: int, y: int, up: bool, color: tuple[int, int, int]) -> None:
    """A 3px-wide, 2px-tall triangle with its tip up or down, resting on baseline ``y``."""
    top, bottom = (y - 2, y - 1) if up else (y - 1, y - 2)
    canvas.SetPixel(x + 1, top, *color)
    for dx in range(3):
        canvas.SetPixel(x + dx, bottom, *color)


def _movement(r: Any, canvas: Any, x: int, y: int, movement: int | None) -> None:
    """The change since the last poll: a green arrow and the places gained, a red one and the
    places lost, a dim dash when unchanged, ``NEW`` in amber for a team new to the poll."""
    font = r.fonts.tiny
    if movement is None:
        r.text(canvas, font, x, y, AMBER, "NEW")
    elif movement == 0:
        for dx in range(3):
            canvas.SetPixel(x + dx, y - 2, *DIM)
    else:
        color = LIVE if movement > 0 else RED_ZONE
        _arrow(canvas, x, y, movement > 0, color)
        r.text(canvas, font, x + 4, y, color, str(abs(movement)))


def draw_cfb_ap(r: Any, canvas: Any, view: Any, scroll: int = 0) -> None:
    """A ranking poll (the AP Top 25, the committee's rankings) as a scrolling table: the poll's
    name at the left, then a row per team with its rank, the movement since the last poll, the
    abbreviation in the team's colour, the record and the points (the conference, where the poll
    has no points). The lead team is white (its rank in the badge colour) with a bar beside it; the
    rest are grey.
    ``scroll`` shifts the rows up by that many pixels; the label stays put, rows partly off the
    panel are drawn and clipped."""
    canvas.Clear()
    font = r.fonts.tiny
    head, middle, tail = view.label
    r.text_center(canvas, font, LABEL_WIDTH // 2, 12, AMBER, head)
    r.text_center(canvas, font, LABEL_WIDTH // 2, 19, GREY, middle)
    r.text_center(canvas, font, LABEL_WIDTH // 2, 25, GREY, tail)
    left = LABEL_WIDTH + 2
    for i, row in enumerate(view.rows):
        y = 1 + i * ROW_HEIGHT + (ROW_HEIGHT - 2) - scroll
        if y < 0 or y - ROW_HEIGHT >= r.height:
            continue  # scrolled clear of the panel
        mine = row.abbrev == view.team
        ink = WHITE if mine else GREY
        r.text_right(
            canvas, font, left + RANK_RIGHT, y, RANK_COLOR if mine else GREY, str(row.rank)
        )
        if mine:
            for dy in range(-4, 1):
                canvas.SetPixel(LABEL_WIDTH - 1, y + dy, *WHITE)
        _movement(r, canvas, left + MOVE_X, y, row.movement)
        known = is_team(row.abbrev)
        color = team_color(row.abbrev) if known else UNKNOWN_TEAM
        r.text(canvas, font, left + ABBREV_X, y, color, row.abbrev)
        r.text(canvas, font, left + RECORD_X, y, ink, row.record)
        # The right edge: the AP's points, or the conference where the poll has none.
        side = f"{row.points:,}" if row.points else row.conference
        if side:
            r.text_right(canvas, font, r.width - POINTS_RIGHT_PAD, y, ink, side)


@college_screen("cfb_ap")
@college_screen("cfb_cfp")
def _draw_poll(r: Any, canvas: Any, scene: Any, now: Any) -> None:
    draw_cfb_ap(r, canvas, scene.fb_idle, scene.scroll_px)
