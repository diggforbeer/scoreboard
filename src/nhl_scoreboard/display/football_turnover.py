"""``fb_turnover`` (#394): an interception, a fumble lost, a sack-fumble, a muffed punt or a
turnover on downs. An alert, not a celebration, for ``fb_turnover_seconds`` (4s) and silent.

Between the two teams' logos (the home team's on the left, as on the field) the headline in the
large font, an **arrow drawn from the team that lost the ball toward the team that gained it**,
and under it who took it and where. At the moment the arrow lands the **possession logo swaps
sides**: the team that now has the ball is at full brightness, the other dims. A pure function of
the seconds since the stage began::

    0.00-0.12  the headline fades in; the team that lost the ball is the bright logo
    0.12-0.60  the arrow draws toward the team that gained it, a ball riding its tip
    0.60-0.70  the logos swap: the gaining team brightens, the losing team dims
    0.65-1.00  the detail line: ``INT  B. CARTER  ATL 43``

**Colour** is by what it means for the favourite: green when the favourite gains the ball, red when
it loses it, amber between two teams that are not the favourite (``Turnover.favourite``).
A pick-six is the touchdown's screen only (the detector emits no turnover for it). A single 64px
panel drops the logos and the outer text sizes. The tiny font has no ``#``; the return yards of a
long return are not drawn (the feed's text does not give them separately).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import EVENT
from ..football.events import Turnover
from ..football.teams import is_team, team_color
from .fonts import text_width
from .football_plays import GAIN, LOSS, NEUTRAL, WHITE, event_screen, r_fit
from .goal_light import _ease, _scaled

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

TITLE_FADE, ARROW_START, ARROW_END, SWAP_END, DETAIL_START = 0.12, 0.12, 0.60, 0.70, 0.65
OTHER_DIM = 0.45
LOGO_SIZE, LOGO_X = 16, 11
TITLES = {
    "interception": "INTERCEPTION",
    "fumble": "FUMBLE",
    "sack_fumble": "SACK-FUMBLE",
    "muffed_punt": "MUFFED PUNT",
    "on_downs": "ON DOWNS",
}
TAGS = {
    "interception": "INT",
    "fumble": "FUM",
    "sack_fumble": "SACK FUM",
    "muffed_punt": "MUFF",
    "on_downs": "",
}


def title(scene: Scene) -> str:
    return TITLES.get(scene.fb_event.reason, "TURNOVER")


def alert_color(scene: Scene) -> tuple[int, int, int]:
    """Green when the favourite gains the ball, red when it loses it, amber otherwise."""
    return {"gained": GAIN, "lost": LOSS}.get(scene.fb_event.favourite, NEUTRAL)


def taker(scene: Scene) -> str:
    """Who took it away, as the text spells it: the interceptor or the recoverer."""
    info = scene.fb_play.info
    return (info.interceptor or info.recovered_by or "").upper()


def spot(scene: Scene) -> str:
    """Where: the interception spot the text gives, else where the new possession starts."""
    play = scene.fb_play
    if play.info.intercept_spot:
        return play.info.intercept_spot.upper()
    end = play.end
    return (end.possession_text or "").upper() if end is not None else ""


def detail(scene: Scene) -> str:
    """``INT  B.CARTER  ATL 43``; with no name, the new team stands in (``ON DOWNS  ATL``)."""
    event = scene.fb_event
    if event.reason == "on_downs":  # the headline already says it: say who has the ball
        parts = [event.team, "BALL"]
    else:
        parts = [TAGS.get(event.reason, "TURNOVER"), taker(scene) or event.team]
    where = spot(scene)
    if where:
        parts.append(where)
    return "  ".join(p for p in parts if p)


def sides(scene: Scene) -> tuple[str, str]:
    """``(left, right)`` team abbreviations: the home team is on the left, as on the field."""
    game = scene.fb_game
    return game.home.abbrev, game.away.abbrev


def _logo(r: Renderer, canvas: Any, team: str, x: int, factor: float) -> None:
    logo = r.nfl_logos.get(team, LOGO_SIZE) if r.nfl_logos is not None and is_team(team) else None
    if logo is not None:
        ox, oy = x - logo.width // 2, 16 - logo.height // 2
        for dx, dy, (red, green, blue) in logo.pixels:
            canvas.SetPixel(
                ox + dx, oy + dy, round(red * factor), round(green * factor), round(blue * factor)
            )
        return
    color = team_color(team) if is_team(team) else WHITE
    r.text_center(
        canvas, r.fonts.small, x, 19, _scaled(color, factor), r_fit(team, 22, r.fonts.small)
    )


def _arrow(canvas: Any, x0: int, x1: int, y: int, progress: float, color) -> int:
    """A line from ``x0`` toward ``x1`` drawn ``progress`` of the way, with a head at its tip;
    returns the tip's column."""
    direction = 1 if x1 >= x0 else -1
    tip = x0 + round((x1 - x0) * progress)
    for x in range(x0, tip + direction, direction):
        canvas.SetPixel(x, y, *color)
    if progress > 0.15:
        for step in (1, 2, 3):
            canvas.SetPixel(tip - direction * step, y - step, *color)
            canvas.SetPixel(tip - direction * step, y + step, *color)
    return tip


@event_screen(Turnover, EVENT)
def draw_turnover(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    canvas.Clear()
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    wide = r.width >= 128
    color = alert_color(scene)
    left_team, right_team = sides(scene)
    gained, lost = event.team, event.lost_by
    swapped = share >= ARROW_END
    # Before the swap the team that lost the ball is the bright logo; after it, the one that gained.
    bright = gained if swapped else lost
    lo, hi = LOGO_X, r.width - 1 - LOGO_X

    if wide:
        for team, x in ((left_team, lo), (right_team, hi)):
            _logo(r, canvas, team, x, 1.0 if team == bright or not lost else OTHER_DIM)
    cx = r.width // 2
    left_edge, right_edge = (22, r.width - 22) if wide else (2, r.width - 2)
    fade = _ease(share / TITLE_FADE)
    text = title(scene)
    font = (
        r.fonts.large
        if text_width(r.fonts.large, text) <= right_edge - left_edge
        else r.fonts.medium
    )
    if not wide:
        font = (
            r.fonts.small
            if text_width(r.fonts.small, text) <= right_edge - left_edge
            else r.fonts.tiny
        )
    r.text_center(
        canvas,
        font,
        cx,
        14 if wide else 10,
        _scaled(color, 0.35 + 0.65 * fade),
        r_fit(text, right_edge - left_edge, font),
    )

    # The arrow runs from the team that lost the ball toward the team that gained it.
    toward_right = gained == right_team
    start, end = (
        (left_edge + 2, right_edge - 2) if toward_right else (right_edge - 2, left_edge + 2)
    )
    if share >= ARROW_START:
        progress = min(1.0, (share - ARROW_START) / (ARROW_END - ARROW_START))
        tip = _arrow(canvas, start, end, 22 if wide else 17, _ease(progress), _scaled(color, 0.6))
        ball_x = tip - (1 if toward_right else -1) * 2
        for dx in (-1, 0, 1):
            canvas.SetPixel(ball_x + dx, 22 if wide else 17, 214, 130, 54)

    if share >= DETAIL_START:
        shade = _scaled(WHITE, min(1.0, (share - DETAIL_START) / 0.2))
        line = r_fit(detail(scene), r.width - 4, r.fonts.tiny)  # under the logos: the full width
        r.text_center(canvas, r.fonts.tiny, cx, 31, shade, line)
