"""``Penalty`` (#386): a yellow flag flies in, lands at the spot, and the marker moves.

The feed types a play ``Penalty`` **even when a play happened**: a scramble that gained 6 yards and
was then wiped out by a hold. So the rule is: if the text has a result before the word ``PENALTY``,
that result plays **compressed** (the first quarter of the stage), then the flag, then the
marker moves to where the penalty was enforced. A pure function of the seconds since the stage
began (4s)::

    0.00-0.25  the result as first played, compressed (ball slides; absent for a pre-snap foul)
    0.25-0.50  a yellow flag flies in and lands at the spot of the foul       ``FLAG``
    0.50-0.55  it lies there; the label names the foul and the yards         ``FALSE START 5 YD``
    0.55-0.85  the line of scrimmage and the ball move to the enforced spot  (``NO PLAY`` shows)
    0.85-1.00  settled; the new markers

Three variants: a penalty that is **declined** shows the flag and ``<FOUL> DECLINED`` with the ball
where the play left it; **offsetting** penalties show ``OFFSETTING``, again with no move; an
accepted penalty moves the ball to ``end.yardLine``. Penalties that ride on another play type (an
incompletion with intentional grounding, a kickoff with a foul) are drawn by that play's screen.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    clamp_yard_line,
    drive_direction,
    first_down_line,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from . import football_field as ff
from .fonts import text_width
from .football_plays import DIM, GAIN, LOSS, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_punt import FLAG, draw_flag
from .football_run import draw_trail, eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

COMPRESS_END, FLAG_START, FLAG_END, LANDED, MOVE_END = 0.25, 0.25, 0.50, 0.55, 0.85
SETTLED_FROM = MOVE_END
#: Where the flag comes from: this many columns to the side and from the top of the field.
FLAG_APPROACH = 14
LANE = "middle"
_GAIN = re.compile(r"\bfor (-?\d+) yards?\b", re.I)


def accepted(scene: Scene):
    """The penalty that changes the result: the first one neither declined nor offsetting."""
    for penalty in scene.fb_play.info.penalties:
        if not penalty.declined and not penalty.offsetting:
            return penalty
    return None


def variant(scene: Scene) -> str:
    """``accepted``, ``declined`` or ``offsetting``."""
    pens = scene.fb_play.info.penalties
    if accepted(scene) is not None:
        return "accepted"
    if any(p.offsetting for p in pens):
        return "offsetting"
    return "declined"


def foul_text(scene: Scene) -> str:
    """``FALSE START 5 YD``: the foul and the yards."""
    pens = scene.fb_play.info.penalties
    penalty = accepted(scene) or (pens[0] if pens else None)
    if penalty is None:
        return "PENALTY"
    name = penalty.name.upper()
    return f"{name} {penalty.yards} YD" if penalty.yards else name


def result_gain(scene: Scene) -> int | None:
    """The yards the play had gained before the flag, if the text gives a result before it:
    ``None`` for a pre-snap foul (nothing happened), ``0`` for an incompletion."""
    info = scene.fb_play.info
    text = info.underlying_text.strip()
    if not re.sub(r"\([^)]*\)", "", text).strip():
        return None  # nothing but the formation: a foul before the snap
    match = _GAIN.search(text)
    if match:
        return int(match.group(1))
    return 0


def label(scene: Scene, share: float) -> tuple[str, tuple[int, int, int]]:
    """What the band says at this point: the result, ``FLAG``, the foul, then ``NO PLAY``."""
    how = variant(scene)
    gain = result_gain(scene)
    if share < COMPRESS_END and gain is not None:
        if gain:
            return f"{abs(gain)} YD", GAIN if gain > 0 else LOSS
        return "INCOMPLETE" if scene.fb_play.info.incomplete else "NO GAIN", NEUTRAL
    if share < LANDED:
        return "FLAG", FLAG
    if how == "offsetting":
        return "OFFSETTING", FLAG
    if how == "declined":
        pens = scene.fb_play.info.penalties
        name = pens[0].name.upper() if pens else "PENALTY"
        return f"{name} DECLINED", NEUTRAL
    if share >= MOVE_END and scene.fb_play.info.no_play:
        return "NO PLAY", LOSS
    return foul_text(scene), FLAG


@play_screen(PlayKind.PENALTY)
def draw_penalty(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    pos = play.start or play.end
    side = possession_side(game, pos.team_id) if pos else None
    direction = drive_direction(side) if side else 1
    start = clamp_yard_line(float(pos.yard_line) if pos and pos.yard_line is not None else 50.0)
    end_pos = play.end
    end = clamp_yard_line(
        float(end_pos.yard_line) if end_pos and end_pos.yard_line is not None else start
    )
    how = variant(scene)
    gain = result_gain(scene)
    result = clamp_yard_line(start + direction * (gain or 0)) if gain is not None else start
    if how != "accepted":
        end = result  # nothing is enforced: the ball stays where the play left it
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    y = lane_y(LANE, direction, layout)

    # The line of scrimmage follows the compressed result, then moves to the enforced spot.
    if gain is not None and share < COMPRESS_END:
        here = start + (result - start) * eased(share / COMPRESS_END)
    elif share < LANDED:
        here = result
    else:
        here = result + (end - result) * eased((share - LANDED) / (MOVE_END - LANDED))
    distance = pos.distance if pos and pos.distance is not None else 0
    settled = share >= SETTLED_FROM
    first_down = None
    if side is not None and distance:
        first_down = first_down_line(end if settled else start, distance, direction)
    ff.draw_field(
        r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos,
        scrimmage=here, first_down=first_down,
    )  # fmt: skip
    if gain is not None and share < COMPRESS_END:
        draw_trail(canvas, layout, start, here, y)
    ff.draw_ball(canvas, layout, here, y)

    if share >= FLAG_START:
        _flag(canvas, layout, result, y, share, direction)

    text, color = label(scene, share)
    room = r.width - text_width(r.fonts.tiny, quarter_clock(play)) - 6
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, room, r.fonts.tiny))
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, quarter_clock(play))


def _flag(canvas: Any, layout: FieldLayout, spot: float, y: float, share: float, direction: int):
    """The flag in flight (coming in from the side of the field, falling to the ground) or lying
    on the spot of the foul."""
    foot_x = max(layout.left, min(layout.right - 5, layout.px(spot) - 1))
    foot_y = round(y) + 3
    t = min(1.0, max(0.0, (share - FLAG_START) / (FLAG_END - FLAG_START)))
    if t >= 1.0:
        draw_flag(canvas, foot_x, foot_y)
        return
    side = -direction  # it comes from behind the offence
    x = max(layout.left, min(layout.right - 5, foot_x + side * round(FLAG_APPROACH * (1 - t))))
    drop = round((foot_y - layout.top - 6) * t)
    draw_flag(canvas, x, layout.top + 6 + drop)
