"""``Punt`` (#383): a long, high kick and one of its endings.

A punt hangs longer than a kickoff. The ball arcs from the punter's spot to where it comes down
(the spot plus the printed distance in the punting team's direction, as for a kickoff), then one
of the four endings the feed's text gives::

    fair catch    a flag marks the catch; the catcher's number stands there      ``FAIR CATCH``
    returned      the returner's number runs it back (can be a loss)             ``RETURN -3``
    out of bounds the ball skips to the sideline and stops                       ``OUT OF BOUNDS``
    touchback     it lands in the end zone and the ball steps out to the spot    ``TOUCHBACK``

and a punt **downed** by the coverage just stops where it landed (``DOWNED``). A pure function of
the seconds since the stage began::

    0.00-0.08  on the punter's spot       0.55-0.60  down
    0.08-0.55  the kick                    0.60-0.90  the ending        0.90-1.00 settled

5s for a fair catch or a return, 4s for the rest (``football/pacing.py``). A punt that is muffed
or blocked is a turnover and gets the generic animation until it is seen in real data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    arc_height,
    arc_point,
    clamp_yard_line,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from . import football_field as ff
from .football_kickoff import KICK_LIFT, kicker_direction, landing_spot, returner_label
from .football_pass import draw_dotted_arc
from .football_plays import DIM, GAIN, LOSS, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_run import draw_carrier, draw_markers_for, draw_trail, eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

TEE, LANDED, ENDING, SETTLED = 0.08, 0.55, 0.60, 0.90
#: More hang than a kickoff of the same length.
PUNT_LIFT = KICK_LIFT * 1.25
#: How far the ball skips along the ground before it crosses the sideline, in yards.
SKIP_YARDS = 3.0
FLAG = (255, 225, 0)
LANE = "middle"


def ending(scene: Scene) -> str:
    """``fair_catch``, ``returned``, ``out_of_bounds``, ``touchback``, ``downed`` or ``plain``."""
    info = scene.fb_play.info
    if info.touchback:
        return "touchback"
    if info.fair_catch:
        return "fair_catch"
    if info.out_of_bounds:
        return "out_of_bounds"
    if info.downed:
        return "downed"
    if info.return_yards is not None:
        return "returned"
    return "plain"


def punt_label(scene: Scene, share: float) -> tuple[str, tuple[int, int, int]]:
    """``PUNT 53 YD`` in the air, then the ending's label once it is down."""
    info = scene.fb_play.info
    if share < LANDED:
        return (f"PUNT {info.kick_yards} YD" if info.kick_yards else "PUNT"), NEUTRAL
    how = ending(scene)
    if how == "returned":
        yards = info.return_yards
        color = GAIN if yards > 0 else LOSS if yards < 0 else NEUTRAL
        return f"RETURN {yards}", color
    text = {
        "fair_catch": "FAIR CATCH",
        "out_of_bounds": "OUT OF BOUNDS",
        "touchback": "TOUCHBACK",
        "downed": "DOWNED",
    }.get(how)
    if text:
        return text, NEUTRAL
    return (f"PUNT {info.kick_yards} YD" if info.kick_yards else "PUNT"), NEUTRAL


def draw_flag(canvas: Any, x: int, y: int) -> None:
    """A small yellow flag on a pole whose foot is at ``(x, y)``: the fair-catch signal."""
    for dy in range(0, 6):
        canvas.SetPixel(x, y - dy, *FLAG)
    for dx in (1, 2, 3):
        canvas.SetPixel(x + dx, y - 5, *FLAG)
        canvas.SetPixel(x + dx, y - 4, *FLAG)


@play_screen(PlayKind.PUNT)
def draw_punt(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    start_pos, end_pos = play.start, play.end
    direction = kicker_direction(play, game)
    tee = float(start_pos.yard_line) if start_pos and start_pos.yard_line is not None else 35.0
    end = float(end_pos.yard_line) if end_pos and end_pos.yard_line is not None else tee
    tee, end = clamp_yard_line(tee), clamp_yard_line(end)
    landing = landing_spot(play, tee, direction, end)
    how = ending(scene)
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    y = lane_y(LANE, direction, layout)
    height = min(arc_height(abs(landing - tee)) * PUNT_LIFT, y - layout.top - 2)

    receiving = possession_side(game, end_pos.team_id) if end_pos else None
    ff.draw_field(
        r, canvas, layout, game.home.abbrev, game.away.abbrev, receiving, logos=r.nfl_logos
    )
    if share >= SETTLED:
        draw_markers_for(r, canvas, layout, receiving, end_pos, end_pos, True)

    here, by = tee, y
    runner = False
    if share < TEE:
        pass
    elif share < LANDED:
        t = (share - TEE) / (LANDED - TEE)
        x, by = arc_point(layout.x(tee), layout.x(landing), y, height, t)
        here = layout.yard_at(x)
        draw_dotted_arc(canvas, layout, tee, landing, y, y, height, t)
    else:
        here, by, runner = _ending(canvas, layout, how, share, landing, end, y, direction)
    ff.draw_ball(canvas, layout, here, by)
    if how == "fair_catch" and share >= LANDED:
        draw_flag(canvas, layout.px(here) + 3, round(by) + 1)
    if runner or (how == "fair_catch" and share >= LANDED):
        draw_carrier(r, canvas, layout, here, by, returner_label(scene))

    text, color = punt_label(scene, share)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, r.width // 2 + 8, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 12, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)


def _ending(canvas, layout, how, share, landing, end, y, direction):
    """Where the ball is during the ending, and whether a runner's number goes with it."""
    t = eased((share - ENDING) / (SETTLED - ENDING))
    if how == "returned":
        here = landing + (end - landing) * t
        draw_trail(canvas, layout, landing, here, y)
        return here, y, True
    if how == "touchback":
        here = landing + (end - landing) * t
        draw_trail(canvas, layout, landing, here, y)
        return here, y, False
    if how == "out_of_bounds":
        # Skips along the ground to the near sideline and stops there.
        edge = layout.bottom - 1 if y >= layout.mid_y else layout.top + 1
        return clamp_yard_line(landing + direction * SKIP_YARDS * t), y + (edge - y) * t, False
    return landing, y, False
