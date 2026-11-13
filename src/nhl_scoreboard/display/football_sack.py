"""``Sack`` (#385): the quarterback drops back, a burst at the sack spot, the marker slides back.

The quarterback's number **drops back** from the line, a **burst** goes off at the sack spot
(``end.yardLine``), and the line of scrimmage and the ball **slide backwards** to it while the
first-down line stays where it was. The label is ``SACK -6`` and the sacker's number (or last name)
stands at the spot, in red. A sack for no loss (``for 0 yards``) plays the burst with no slide. A
sack that ends in a fumble is ``Sack Opp Fumble Recovery``: the turnover story's. A pure function
of the seconds since the stage began (3s)::

    0.00-0.35  the quarterback's number drops back
    0.35-0.65  the burst at the sack spot, growing and fading
    0.55-0.85  the marker and the ball slide back to the sack spot
    0.85-1.00  settled; the sacker's number stays at the spot
"""

from __future__ import annotations

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
from ..football.pacing import yards_gained
from ..football.people import Person, find
from . import football_field as ff
from .football_pass import passer_label
from .football_plays import DIM, LOSS, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_run import MAX_LABEL, draw_carrier, eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

DROP_END, BURST_START, BURST_END, SLIDE_END = 0.35, 0.35, 0.65, 0.85
SLIDE_START = 0.55
#: Yards the quarterback drops back behind the line, and the burst's largest radius in pixels.
DROP_YARDS, BURST_RADIUS = 5.0, 5
BURST = (255, 255, 255)
SACKER = (255, 70, 70)
QB_LANE = "middle"


def sack_label(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    yards = scene.fb_play.info.sack_yards
    if yards is None:
        yards = yards_gained(scene.fb_play)
    color = LOSS if yards < 0 else NEUTRAL
    return (f"SACK {yards}" if yards else "SACK 0"), color


def sacker_label(scene: Scene) -> str:
    """The sacker's number, else his last name, else nothing."""
    person = find(scene.fb_people, "sackedBy")
    names = scene.fb_play.info.sackers
    if person is None and names:
        person = Person("sackedBy", None, names[0], "", "", False)
    return person.label[:MAX_LABEL] if person is not None else ""


def draw_burst(canvas: Any, x: int, y: int, progress: float) -> None:
    """Eight short spokes that grow and fade: the hit."""
    radius = 1 + round((BURST_RADIUS - 1) * progress)
    shade = max(0.0, 1.0 - progress * 0.8)
    color = tuple(round(c * shade) for c in BURST)
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
        for step in (radius, max(1, radius - 1)):
            canvas.SetPixel(x + dx * step, y + dy * step, *color)


@play_screen(PlayKind.SACK)
def draw_sack(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    pos = play.start or play.end
    side = possession_side(game, pos.team_id) if pos else None
    direction = drive_direction(side) if side else 1
    start = clamp_yard_line(float(pos.yard_line) if pos and pos.yard_line is not None else 50.0)
    yards = play.info.sack_yards if play.info.sack_yards is not None else yards_gained(play)
    if play.end is not None and play.end.yard_line is not None and not play.info.sack_yards:
        end = float(play.end.yard_line)
    else:
        end = start - direction * abs(yards)  # a loss is backwards, against the drive
    end = clamp_yard_line(end)
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    y = lane_y(QB_LANE, direction, layout)
    distance = pos.distance if pos and pos.distance is not None else 0

    slide = eased((share - SLIDE_START) / (SLIDE_END - SLIDE_START))
    line = start + (end - start) * slide
    fixed_first_down = first_down_line(start, distance, direction) if distance else None
    ff.draw_field(
        r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos,
        scrimmage=line, first_down=fixed_first_down,
    )  # fmt: skip

    qb_label, at = "", (line, y)
    if share < BURST_START:
        t = eased(share / DROP_END)
        drop = start - direction * DROP_YARDS * t
        ff.draw_ball(canvas, layout, start, y, (110, 70, 30))  # the snap: the ball stays
        qb_label, at = passer_label(scene), (drop, y)
    else:
        ff.draw_ball(canvas, layout, line, y)
        if share < BURST_END:
            progress = (share - BURST_START) / (BURST_END - BURST_START)
            draw_burst(canvas, layout.px(end), round(y), progress)
    draw_carrier(r, canvas, layout, at[0], at[1], qb_label)
    if share >= SLIDE_END:
        draw_carrier(r, canvas, layout, end, y, sacker_label(scene), SACKER)

    text, color = sack_label(scene)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, r.width // 2 - 2, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 2, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)
