"""``fb_run``: a rush (#380).

The ball (with the carrier's **jersey number**, or the last name when there is none) runs from
where the play started to where it ended, leaving a fading trail, along the lane the text names
(``left end`` ... ``right end``; ``up the middle`` is the centre). Length scales with yardage
(``football.pacing``). It ends with the ball settled at the end spot, the line of scrimmage and
first-down line moved to it, and the label ``RUSH +9`` (green gain, red loss, amber for none)
over the field.

A pure function of the seconds since the stage began. Registered for ``Rush`` and ``Rushing
Touchdown`` (the celebration follows a touchdown, so the ball is seen arriving in the end zone);
a QB scramble and a kneel are rushes too and are read off the play's flags.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    clamp_yard_line,
    drive_direction,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from ..football.pacing import yards_gained
from ..football.people import Person, find
from . import football_field as ff
from .fonts import text_width
from .football_plays import DIM, GAIN, LOSS, NEUTRAL, WHITE, play_screen, quarter_clock, r_fit

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

#: The ball travels for this share of the stage and rests for the rest.
TRAVEL = 0.75
#: Brightness of the trail: dim at the start of the run, brightest next to the ball.
TRAIL_DIM, TRAIL_BRIGHT = 0.15, 0.7
#: Longest label drawn on the ball (a last name; numbers are two digits).
MAX_LABEL = 6


def run_label(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    """``RUSH +9``, ``SCRAMBLE -2`` or ``KNEEL`` and its colour."""
    play = scene.fb_play
    info = play.info
    if info.kneel:
        return "KNEEL", NEUTRAL
    yards = yards_gained(play)
    name = "SCRAMBLE" if info.scramble else "RUSH"
    color = GAIN if yards > 0 else LOSS if yards < 0 else NEUTRAL
    return f"{name} {yards:+d}" if yards else f"{name} 0", color


def carrier_label(scene: Scene) -> str:
    """What goes on the ball: the carrier's number, else the last name, else nothing."""
    play = scene.fb_play
    person = find(scene.fb_people, "rusher", "scorer")
    if person is None and play.info.rusher:
        person = Person("rusher", None, play.info.rusher, "", "", False)
    return person.label[:MAX_LABEL] if person is not None else ""


def eased(progress: float) -> float:
    """Smoothstep: a run gets going and slows to a stop rather than sliding at one speed."""
    p = max(0.0, min(1.0, progress))
    return p * p * (3 - 2 * p)


@play_screen(PlayKind.RUSH)
@play_screen(PlayKind.RUSHING_TOUCHDOWN)
def draw_run(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    start_pos, end_pos = play.start, play.end
    side = possession_side(game, (start_pos or end_pos).team_id) if (start_pos or end_pos) else None
    direction = drive_direction(side) if side else 1
    start = float(start_pos.yard_line) if start_pos and start_pos.yard_line is not None else 50.0
    if end_pos is not None and end_pos.yard_line is not None:
        end = float(end_pos.yard_line)
    else:
        end = start + direction * yards_gained(play)
    start, end = clamp_yard_line(start), clamp_yard_line(end)
    travel = scene.fb_seconds * TRAVEL
    progress = 1.0 if travel <= 0 else min(1.0, scene.fb_elapsed / travel)
    arrived = progress >= 1.0
    here = start + (end - start) * eased(progress)

    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    draw_markers_for(r, canvas, layout, side, start_pos, end_pos, arrived)
    y = lane_y(play.info.run_gap, direction, layout)
    draw_trail(canvas, layout, start, here, y)
    ff.draw_ball(canvas, layout, here, y)
    draw_carrier(r, canvas, layout, here, y, carrier_label(scene))
    label, color = run_label(scene)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(label, r.width // 2 - 2, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 2, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)


def draw_markers_for(r, canvas, layout, side, start_pos, end_pos, arrived) -> None:
    """Scrimmage and first-down lines: the play's own until the ball arrives, then the new ones
    (when the same team has the ball and the feed gives the new down and distance)."""
    pos = start_pos
    if arrived and end_pos is not None and end_pos.distance is not None:
        same = start_pos is None or end_pos.team_id in (None, start_pos.team_id)
        if same:
            pos = end_pos
    if side is not None and pos is not None and pos.yard_line is not None:
        ff.draw_markers(r, canvas, layout, pos.yard_line, pos.distance or 0, side)


def draw_trail(canvas: Any, layout: FieldLayout, start: float, here: float, y: float) -> None:
    """A line of dots from the start spot to the ball, fading toward the start."""
    x0, x1 = layout.px(start), layout.px(here)
    step = 1 if x1 >= x0 else -1
    count = abs(x1 - x0)
    row = round(y)
    for i, x in enumerate(range(x0, x1, step)):
        k = TRAIL_DIM + (TRAIL_BRIGHT - TRAIL_DIM) * (i / max(1, count))
        shade = round(255 * k)
        canvas.SetPixel(x, row, shade, shade, shade)


def draw_carrier(r: Renderer, canvas: Any, layout: FieldLayout, here: float, y: float, label: str):
    """The number (or name) beside the ball: below it in the top half of the field, above it in
    the bottom half, so it never runs into the band or the bottom edge."""
    if not label:
        return
    font = r.fonts.tiny
    width = text_width(font, label)
    x = layout.px(here) - width // 2
    x = max(layout.left + 1, min(layout.right - width - 1, x))
    by = round(y)
    baseline = by + 9 if by < layout.mid_y else by - 3
    r.text(canvas, font, x, baseline, WHITE, label)
