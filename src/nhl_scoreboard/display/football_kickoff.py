"""``Kickoff`` (#382): the kick, the landing, and the return or the touchback.

The ball sits on the tee, **arcs high** to where it comes down, and then the returner's number
**runs it back** to ``end.yardLine``; on a touchback it lands in the end zone and the ball
**steps out** to the spot. An onside kick is the same animation with a short, low arc (it is a
``Kickoff`` to the feed, ``kicks onside 19 yards``). A pure function of the seconds since the
stage began::

    0.00-0.08  the ball on the tee
    0.08-0.50  the kick: a high arc to the landing spot, a dotted path behind it
    0.50-0.55  it lands
    0.55-0.90  the returner's number runs it back to the end spot / the ball steps out
    0.90-1.00  settled; the markers appear at the new spot

The landing spot is the tee plus the kick's distance in the kicking team's direction (that is
how ESPN's own numbers agree: ``kicks 60 yards from ATL 35 to CIN 5``), so no team names need
parsing. A penalty on the play changes where the ball finally sits, not the printed return: the
animation runs the printed return and **finishes at ``end.yardLine``**.
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
from ..football.people import Person, find
from . import football_field as ff
from .football_pass import draw_dotted_arc
from .football_plays import DIM, GAIN, LOSS, NEUTRAL, play_screen, quarter_clock, r_fit
from .football_run import MAX_LABEL, draw_carrier, draw_markers_for, draw_trail, eased

if TYPE_CHECKING:
    from ..app import Scene
    from ..football.models import Play
    from .renderer import Renderer

TEE, LAND, LANDED, RETURN_END = 0.08, 0.50, 0.55, 0.90
#: A kickoff hangs higher than a pass of the same length; an onside kick is a low line drive.
KICK_LIFT, ONSIDE_LIFT = 1.4, 0.7
#: How far past the goal line a touchback lands, in yards.
END_ZONE_DEPTH = 5.0
LANE = "middle"


def kicker_direction(play: Play, game: Any) -> int:
    """+1 if the kicking team kicks toward yard 100 (the home team does), else -1. From the team
    the feed says kicks; when that is unknown, toward the far end from the tee."""
    pos = play.start or play.end
    side = possession_side(game, pos.team_id) if pos else None
    if side is not None:
        return drive_direction(side)
    tee = pos.yard_line if pos and pos.yard_line is not None else 35
    return 1 if tee < 50 else -1


def landing_spot(play: Play, tee: float, direction: int, end: float) -> float:
    """Where the kick came down (0-100, or just past the goal line on a touchback)."""
    info = play.info
    if info.touchback:
        return (100 + END_ZONE_DEPTH) if direction > 0 else -END_ZONE_DEPTH
    if info.kick_yards is not None:
        return clamp_yard_line(tee + direction * info.kick_yards)
    return end  # nothing printed: the ball simply goes to where it ended


def kick_label(scene: Scene, share: float) -> tuple[str, tuple[int, int, int]]:
    """``KICKOFF 59 YD`` in the air, then ``RETURN 24 YD`` or ``TOUCHBACK`` once it is down."""
    info = scene.fb_play.info
    if share < LANDED:
        what = "ONSIDE KICK" if info.onside else "KICKOFF"
        return (f"{what} {info.kick_yards} YD" if info.kick_yards else what), NEUTRAL
    if info.touchback:
        return "TOUCHBACK", NEUTRAL
    if info.return_yards is None:
        return "KICKOFF" if not info.kick_yards else f"KICKOFF {info.kick_yards} YD", NEUTRAL
    yards = info.return_yards
    color = GAIN if yards > 0 else LOSS if yards < 0 else NEUTRAL
    return f"RETURN {yards} YD", color


def returner_label(scene: Scene) -> str:
    person = find(scene.fb_people, "returner")
    if person is None and scene.fb_play.info.returner:
        person = Person("returner", None, scene.fb_play.info.returner, "", "", False)
    return person.label[:MAX_LABEL] if person is not None else ""


@play_screen(PlayKind.KICKOFF)
def draw_kickoff(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    info = play.info
    start_pos, end_pos = play.start, play.end
    direction = kicker_direction(play, game)
    tee = float(start_pos.yard_line) if start_pos and start_pos.yard_line is not None else 35.0
    end = float(end_pos.yard_line) if end_pos and end_pos.yard_line is not None else tee
    tee, end = clamp_yard_line(tee), clamp_yard_line(end)
    landing = landing_spot(play, tee, direction, end)
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    y = lane_y(LANE, direction, layout)
    lift = ONSIDE_LIFT if info.onside else KICK_LIFT
    # The apex stays on the field: a kick hangs as high as the field allows, never into the band.
    height = min(arc_height(abs(landing - tee)) * lift, y - layout.top - 2)

    receiving = possession_side(game, end_pos.team_id) if end_pos else None
    ff.draw_field(
        r, canvas, layout, game.home.abbrev, game.away.abbrev, receiving, logos=r.nfl_logos
    )
    if share >= RETURN_END:
        draw_markers_for(r, canvas, layout, receiving, end_pos, end_pos, True)

    label_at: tuple[float, float] | None = None
    if share < TEE:
        here, by = tee, y
    elif share < LAND:
        t = (share - TEE) / (LAND - TEE)
        x, by = arc_point(layout.x(tee), layout.x(landing), y, height, t)
        here = layout.yard_at(x)
        draw_dotted_arc(canvas, layout, tee, landing, y, y, height, t)
    elif share < LANDED:
        here, by = landing, y
    else:
        moving = (share - LANDED) / (RETURN_END - LANDED)
        t = eased(moving)
        here, by = landing + (end - landing) * t, y
        draw_trail(canvas, layout, landing, here, y)
        if not info.touchback:
            label_at = (here, by)
    ff.draw_ball(canvas, layout, here, by)
    if label_at is not None:
        draw_carrier(r, canvas, layout, label_at[0], label_at[1], returner_label(scene))

    text, color = kick_label(scene, share)
    r.text(canvas, r.fonts.tiny, 1, 6, color, r_fit(text, r.width // 2 + 8, r.fonts.tiny))
    clock = r_fit(quarter_clock(play), r.width // 2 - 12, r.fonts.tiny)
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, clock)
