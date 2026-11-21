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
#: The playoff cut's rule: the colour of the hockey tables' playoff line, so it reads as the same
#: thing (``renderer.PLAYOFF_LINE``).
CUT_LINE = (150, 40, 40)
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
    cut = getattr(view, "cut", 0)
    if 0 < cut < len(view.rows):
        # The spacer pixel row under the last team in the field: no row shifts for it.
        line_y = cut * ROW_HEIGHT - 1 - scroll
        if 0 <= line_y < r.height:
            for x in range(LABEL_WIDTH, r.width):
                canvas.SetPixel(x, line_y, *CUT_LINE)


@college_screen("cfb_ap")
@college_screen("cfb_cfp")
def _draw_poll(r: Any, canvas: Any, scene: Any, now: Any) -> None:
    draw_cfb_ap(r, canvas, scene.fb_idle, scene.scroll_px)


# -- a conference's standings (#553) --------------------------------------------------------------

#: Columns of a conference row, as offsets from ``LABEL_WIDTH``: the conference record, the overall
#: record in brackets, the streak at the right edge.
CONF_ABBREV_X = 12
CONF_RECORD_X = 36
CONF_OVERALL_X = 60


def draw_cfb_conference(r: Any, canvas: Any, view: Any, scroll: int = 0) -> None:
    """The lead team's conference as a scrolling table: the conference at the left, then a row
    per team in standings order with its place, the abbreviation in the team's colour, the
    conference record, the overall record in brackets and the streak (green a win streak, red a
    losing one). The lead team is white with a bar beside it; the rest are grey. A team with no
    conference record (an Independent) shows a dash. Scrolls like ``draw_cfb_ap``."""
    canvas.Clear()
    font = r.fonts.tiny
    r.text_center(canvas, font, LABEL_WIDTH // 2, 12, AMBER, view.short)
    r.text_center(canvas, font, LABEL_WIDTH // 2, 19, GREY, "CONF")
    r.text_center(canvas, font, LABEL_WIDTH // 2, 25, GREY, "TABLE")
    left = LABEL_WIDTH + 2
    for i, row in enumerate(view.rows):
        y = 1 + i * ROW_HEIGHT + (ROW_HEIGHT - 2) - scroll
        if y < 0 or y - ROW_HEIGHT >= r.height:
            continue  # scrolled clear of the panel
        mine = row.abbrev == view.team
        ink = WHITE if mine else GREY
        r.text_right(canvas, font, left + RANK_RIGHT, y, RANK_COLOR if mine else GREY, str(i + 1))
        if mine:
            for dy in range(-4, 1):
                canvas.SetPixel(LABEL_WIDTH - 1, y + dy, *WHITE)
        color = team_color(row.abbrev) if is_team(row.abbrev) else UNKNOWN_TEAM
        r.text(canvas, font, left + CONF_ABBREV_X, y, color, row.abbrev)
        r.text(canvas, font, left + CONF_RECORD_X, y, ink, row.conf or "-")
        if row.overall:
            r.text(canvas, font, left + CONF_OVERALL_X, y, GREY, f"({row.overall})")
        if row.streak:
            streak = LIVE if row.streak.startswith("W") else RED_ZONE
            r.text_right(canvas, font, r.width - POINTS_RIGHT_PAD, y, streak, row.streak)


@college_screen("cfb_conference")
def _draw_conference(r: Any, canvas: Any, scene: Any, now: Any) -> None:
    draw_cfb_conference(r, canvas, scene.fb_idle, scene.scroll_px)


# -- the lead team's next game (#554) -------------------------------------------------------------


@college_screen("cfb_preview")
def _draw_preview(r: Any, canvas: Any, scene: Any, now: Any) -> None:
    """The NFL's preview layout over a college game: the rank rides in front of each record."""
    r.draw_fb_preview(canvas, scene.fb_idle, now)


# -- the scores grid (#556) -----------------------------------------------------------------------

from ..football.models import FbGame  # noqa: E402
from .fonts import text_width  # noqa: E402
from .football_scenes import FINAL  # noqa: E402

COLUMN_WIDTH = 32
_AWAY_BASELINE, _HOME_BASELINE, _STATUS_BASELINE, _DETAIL_BASELINE = 7, 15, 24, 31


def _status(r: Any, game: FbGame) -> tuple[str, str, tuple[int, int, int]]:
    """``(status, detail, colour)`` sized for a 32px column."""
    if game.is_final:
        return "FINAL", "OT" if game.period > 4 else "", FINAL
    if game.is_live:
        if game.is_halftime:
            return "HALF", "", AMBER
        return game.display_clock, f"Q{game.period}" if game.period <= 4 else "OT", LIVE
    if game.start_utc is None:
        return "TBD", "", GREY
    local = game.start_utc.astimezone(r.tz)
    return f"{local.hour % 12 or 12}:{local.minute:02d}{'A' if local.hour < 12 else 'P'}", "", GREY


def _inline_room(r: Any, game: FbGame, side: Any, x0: int, right: int) -> int:
    """Pixels free between a team's abbreviation and its score."""
    score = "" if game.is_pregame else str(side.score)
    left = x0 + 1 + text_width(r.fonts.small, side.abbrev) + 1
    stop = right - text_width(r.fonts.small, score) - 1 if score else right
    return stop - left


def _draw_column(r: Any, canvas: Any, game: FbGame, x0: int, right: int) -> None:
    font, tiny = r.fonts.small, r.fonts.tiny
    inline = all(
        _inline_room(r, game, side, x0, right) >= text_width(tiny, str(side.rank))
        for side in (game.away, game.home)
        if side.rank
    )
    for side, baseline in ((game.away, _AWAY_BASELINE), (game.home, _HOME_BASELINE)):
        score = "" if game.is_pregame else str(side.score)
        color = team_color(side.abbrev) if is_team(side.abbrev) else UNKNOWN_TEAM
        r.text(canvas, font, x0 + 1, baseline, color, side.abbrev)
        if score:
            r.text_right(canvas, font, right, baseline, WHITE, score)
        if inline and side.rank:
            gap = x0 + 1 + text_width(font, side.abbrev) + 1
            r.text(canvas, tiny, gap, baseline, RANK_COLOR, str(side.rank))
    status, detail, color = _status(r, game)
    cx = (x0 + right) // 2
    r.text_center(canvas, font, cx, _STATUS_BASELINE, color, status)
    if not inline:
        # Too tight beside the names: the ranks flank the bottom line, away left, home right.
        if game.away.rank:
            r.text(canvas, tiny, x0 + 1, _DETAIL_BASELINE, RANK_COLOR, str(game.away.rank))
        if game.home.rank:
            r.text_right(canvas, tiny, right, _DETAIL_BASELINE, RANK_COLOR, str(game.home.rank))
    if detail:
        dim = tuple(round(c * 0.5) for c in color)
        r.text_center(canvas, tiny, cx, _DETAIL_BASELINE, dim, detail)


def draw_cfb_scores(r: Any, canvas: Any, view: Any, page: int = 0) -> None:
    """Four games a page, one 32px column each, away over home: the abbreviation in the team's
    colour, its rank beside it where there is room, the score at the right, then the clock (or
    kickoff, or ``FINAL``) with the quarter under it. A short last page is centred."""
    canvas.Clear()
    games = view.page(min(max(page, 0), view.pages - 1))
    left = (r.width - len(games) * COLUMN_WIDTH) // 2
    for i, game in enumerate(games):
        x0 = left + i * COLUMN_WIDTH
        if i:
            r.vline(canvas, x0 - 1, 1, r.height - 2, DIM)
        _draw_column(r, canvas, game, x0, x0 + COLUMN_WIDTH - 2)
    if view.pages > 1:
        for n in range(view.pages):
            canvas_dim = DIM if n == page else tuple(round(c * 0.35) for c in DIM)
            r.hline(canvas, 60 + n * 6, 61 + n * 6, r.height - 1, canvas_dim)


@college_screen("cfb_scores")
def _draw_scores(r: Any, canvas: Any, scene: Any, now: Any) -> None:
    draw_cfb_scores(r, canvas, scene.fb_idle, scene.fb_page)
