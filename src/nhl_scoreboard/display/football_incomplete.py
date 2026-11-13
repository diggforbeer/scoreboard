"""``Pass Incompletion`` (#384, also a spike and an intentional grounding).

The most common non-run, non-pass play, so it is **quick (3s)**. The ball arcs toward the lane
and depth the text names (``short`` / ``deep``, ``left`` / ``middle`` / ``right``), **drops and
bounces short of the receiver** (his number stands where he was, when the play names a target),
and the ball marker stays put: the line of scrimmage and first-down line do not move. A pure
function of the seconds since the stage began::

    0.00-0.10  the quarterback's number at his spot
    0.10-0.55  the ball arcs toward the receiver and comes down short of him
    0.55-0.80  it bounces twice, smaller each time, and rolls on a little
    0.80-1.00  it lies there; the label stays

A spike throws the ball straight into the ground at the quarterback. An intentional grounding
reads as an incompletion here: its penalty is in the text, not the type, and is the penalty
story's. The defender who broke the pass up (``[C.Thomas]``) is not drawn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    arc_point,
    clamp_yard_line,
    drive_direction,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from ..football.people import Person, find
from . import football_field as ff
from .football_pass import draw_dotted_arc, passer_label
from .football_plays import DIM, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_run import MAX_LABEL, draw_carrier, eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

THROW, DOWN, BOUNCED = 0.10, 0.55, 0.80
#: How far the pass was meant to go, by the depth the text gives (yards from the line).
AIR_YARDS = {"short": 8.0, "deep": 25.0, "": 14.0}
#: The ball comes down this share of the way to the receiver: short of him.
SHORT_OF_TARGET = 0.8
#: Bounce heights in pixels and the yards the ball rolls on after each.
BOUNCES = ((3.0, 1.2), (1.5, 0.8))
QB_LANE = "middle"
#: The resting ball marker at the line of scrimmage, dimmer than the ball in the air.
RESTING_BALL = tuple(round(c * 0.5) for c in ff.BALL)
SPIKE_ARC = 3.0


def label(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    return ("SPIKE" if scene.fb_play.info.spike else "INCOMPLETE"), NEUTRAL


def target_label(scene: Scene) -> str:
    """The target's number, else his last name, else nothing (and nothing on a spike)."""
    play = scene.fb_play
    if play.info.spike:
        return ""
    person = find(scene.fb_people, "target", "receiver")
    if person is None and play.info.target:
        person = Person("receiver", None, play.info.target, "", "", False)
    return person.label[:MAX_LABEL] if person is not None else ""


def intended_spot(start: float, depth: str, direction: int) -> float:
    """Where the receiver was: ``depth`` yards from the line in the drive direction."""
    return clamp_yard_line(start + direction * AIR_YARDS.get(depth, AIR_YARDS[""]))


@play_screen(PlayKind.PASS_INCOMPLETE)
def draw_incomplete(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    pos = play.start or play.end
    side = possession_side(game, pos.team_id) if pos else None
    direction = drive_direction(side) if side else 1
    start = float(pos.yard_line) if pos and pos.yard_line is not None else 50.0
    start = clamp_yard_line(start)
    info = play.info
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    qb_y = lane_y(QB_LANE, direction, layout)

    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    # The ball marker stays put: the plays own lines, the resting ball at the quarterback.
    if side is not None and pos is not None:
        ff.draw_markers(r, canvas, layout, start, pos.distance or 0, side)
    ff.draw_ball(canvas, layout, start, qb_y, RESTING_BALL)

    if info.spike:
        target_x, target_y = start, qb_y
        lands = start + direction * 1.5
    else:
        target_x = intended_spot(start, info.pass_depth, direction)
        target_y = lane_y(info.pass_direction, direction, layout)
        lands = start + (target_x - start) * SHORT_OF_TARGET
    height = SPIKE_ARC if info.spike else min(8.0, 2.0 + abs(lands - start) * 0.25)
    height = min(height, qb_y - layout.top - 2)

    label_text = ""
    if share < THROW:
        here, y = start, qb_y
        label_text = passer_label(scene)
        at = (start, qb_y)
    elif share < DOWN:
        t = eased((share - THROW) / (DOWN - THROW))
        x, y = arc_point(layout.x(start), layout.x(lands), qb_y + (target_y - qb_y) * t, height, t)
        here = layout.yard_at(x)
        draw_dotted_arc(canvas, layout, start, lands, qb_y, target_y, height, t)
        at = (here, y)
    else:
        here, y = _bounce(layout, share, lands, target_y, direction)
        at = (target_x, target_y)
    ff.draw_ball(canvas, layout, here, y)
    if share >= THROW and not info.spike:
        label_text = target_label(scene)
        # The receiver's number stands where he was, a little off the ball.
        at = (target_x, target_y)
    draw_carrier(r, canvas, layout, at[0], at[1], label_text)

    text, color = label(scene)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, r.width // 2 - 2, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 2, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)


def _bounce(layout: FieldLayout, share: float, lands: float, y: float, direction: int):
    """The ball after it comes down: two shrinking hops, rolling on, then lying still."""
    t = min(1.0, (share - DOWN) / (BOUNCED - DOWN))
    total_roll = sum(roll for _, roll in BOUNCES)
    x = lands + direction * total_roll * t
    # Which hop are we in, and how far through it?
    hop_t = t * len(BOUNCES)
    index = min(len(BOUNCES) - 1, int(hop_t))
    within = hop_t - index
    lift = BOUNCES[index][0] * 4 * within * (1 - within) if t < 1.0 else 0.0
    return x, y - lift
