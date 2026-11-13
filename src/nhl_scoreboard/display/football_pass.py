"""``fb_pass``: a completed pass (#381).

The ball arcs from the quarterback's spot (``start.yardLine``) to where the receiver caught it, the
**receiver's jersey number** appears on the catch, and the yards after the catch are a short run
from there to ``end.yardLine``. Depth (``short`` / ``deep``) sets the arc's height, direction
(``left`` / ``middle`` / ``right``) the lane it lands in. Registered for ``Pass Reception`` and
``Passing Touchdown`` (the celebration follows a touchdown, so the ball is seen arriving).

A pure function of the seconds since the stage began::

    0.00-0.15  the quarterback's number at his spot, ball in hand
    0.15-0.60  the ball arcs to the catch spot (a dotted trail behind it)
    0.60-0.85  the receiver's number on the ball, running the yards after the catch
    0.85-1.00  settled at the end spot; the markers move to it

Length scales with yardage like a run (``football.pacing``, 2-4s).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    arc_height,
    arc_point,
    clamp_yard_line,
    drive_direction,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from ..football.pacing import yards_gained
from ..football.people import Person, find
from . import football_field as ff
from .football_plays import DIM, GAIN, LOSS, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_run import MAX_LABEL, draw_carrier, draw_markers_for, draw_trail, eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

#: Where each phase starts, as a share of the stage (see the module docstring).
THROW, CATCH, RUN_END = 0.15, 0.60, 0.85
#: A deep pass arcs higher than a short one of the same length.
DEPTH_HEIGHT = {"short": 0.8, "deep": 1.3}
#: The quarterback stands in the middle of the field.
QB_LANE = "middle"


def pass_label(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    """``PASS +12`` and its colour: green for a gain, red for a loss, amber for none."""
    yards = yards_gained(scene.fb_play)
    color = GAIN if yards > 0 else LOSS if yards < 0 else NEUTRAL
    return (f"PASS {yards:+d}" if yards else "PASS 0"), color


def person_label(person: Person | None, fallback: str) -> str:
    """A number, else a last name, else the name the text gave, else nothing."""
    if person is None and fallback:
        person = Person("receiver", None, fallback, "", "", False)
    return person.label[:MAX_LABEL] if person is not None else ""


def receiver_label(scene: Scene) -> str:
    return person_label(find(scene.fb_people, "receiver", "scorer"), scene.fb_play.info.target)


def passer_label(scene: Scene) -> str:
    return person_label(find(scene.fb_people, "passer"), scene.fb_play.info.passer)


def catch_spot(start: float, end: float, yards_after_catch: int | None, direction: int) -> float:
    """Where the receiver caught it: ``end`` less the yards after the catch, never behind the
    quarterback (a screen caught at the line has no air yards) and never past the end spot."""
    caught = end - direction * (yards_after_catch or 0)
    low, high = sorted((start, end))
    return max(low, min(high, caught))


@play_screen(PlayKind.PASS_COMPLETE)
@play_screen(PlayKind.PASSING_TOUCHDOWN)
def draw_pass(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    start_pos, end_pos = play.start, play.end
    anchor = start_pos or end_pos
    side = possession_side(game, anchor.team_id) if anchor else None
    direction = drive_direction(side) if side else 1
    start = float(start_pos.yard_line) if start_pos and start_pos.yard_line is not None else 50.0
    if end_pos is not None and end_pos.yard_line is not None:
        end = float(end_pos.yard_line)
    else:
        end = start + direction * yards_gained(play)
    start, end = clamp_yard_line(start), clamp_yard_line(end)
    caught = catch_spot(start, end, play.yards_after_catch, direction)

    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    arrived = share >= RUN_END
    draw_markers_for(r, canvas, layout, side, start_pos, end_pos, arrived)

    qb_y = lane_y(QB_LANE, direction, layout)
    target_y = lane_y(play.info.pass_direction, direction, layout)
    height = arc_height(abs(caught - start)) * DEPTH_HEIGHT.get(play.info.pass_depth, 1.0)
    if share < THROW:
        here, y = start, qb_y
        label, at = passer_label(scene), (start, qb_y)
    elif share < CATCH:
        t = eased((share - THROW) / (CATCH - THROW))
        x, y = arc_point(layout.x(start), layout.x(caught), qb_y + (target_y - qb_y) * t, height, t)
        y = max(layout.top + 1.0, y)
        here = layout.yard_at(x)
        _dotted_arc(canvas, layout, start, caught, qb_y, target_y, height, t)
        label, at = "", (here, y)
    else:
        t = eased((share - CATCH) / (RUN_END - CATCH))
        here, y = caught + (end - caught) * t, target_y
        draw_trail(canvas, layout, caught, here, y)
        label, at = receiver_label(scene), (here, y)
    ff.draw_ball(canvas, layout, here, y)
    draw_carrier(r, canvas, layout, at[0], at[1], label)

    text, color = pass_label(scene)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, r.width // 2 - 2, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 2, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)


def _dotted_arc(
    canvas: Any, layout: FieldLayout, start: float, caught: float, y0: float, y1: float,
    height: float, upto: float,
) -> None:  # fmt: skip
    """The path the ball has flown so far, as every other dot, brightening toward the ball."""
    steps = max(6, int(abs(layout.x(caught) - layout.x(start))))
    last = int(steps * upto)
    for i in range(0, last, 2):
        t = i / steps
        x, y = arc_point(layout.x(start), layout.x(caught), y0 + (y1 - y0) * t, height, t)
        shade = round(255 * (0.15 + 0.5 * (i / max(1, last))))
        canvas.SetPixel(round(x), round(max(layout.top + 1.0, y)), shade, shade, shade)
