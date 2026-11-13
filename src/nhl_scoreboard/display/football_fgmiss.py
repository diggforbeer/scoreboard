"""``fb_fg_miss`` (#393): a missed field goal, for either team in a followed game.

Not a celebration: no sound, **3s**, the same screen for the favourite's miss and the opponent's.
It is the play's own stage (``@play_screen(FIELD_GOAL_MISSED)``): the ball is placed at the kick
spot and arcs toward the posts at the back of the end zone being attacked, then, by what the text
says, **goes wrong**. In red, with the band ``NO GOOD 38 YD`` and, on the right, the reason::

    WIDE LEFT    veers up the panel (the kicker's left when driving right) and passes outside
    WIDE RIGHT   veers down the panel and passes outside
    SHORT        drops onto the field before it reaches the end zone
    BLOCKED      goes up a few pixels and falls back behind the line of scrimmage

Anything else (a miss the feed words differently) is drawn as a plain miss that just fades short of
the posts, and still reads ``NO GOOD`` with the distance. A pure function of the seconds since the
stage began. The detail of which post it hit is not drawn: the feed does not say.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.geometry import (
    FieldLayout,
    arc_height,
    lane_y,
)
from ..football.models import PlayKind
from . import football_field as ff
from .fonts import text_width
from .football_fieldgoal import YELLOW, _kick_geometry, draw_posts
from .football_pass import draw_dotted_arc
from .football_plays import LOSS, play_screen, r_fit
from .football_run import eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

KICK_START, FLIGHT_END, DONE = 0.10, 0.70, 1.0
RED = LOSS
#: How far short a ``Short`` kick comes down, as a share of the way to the posts.
SHORT_SHARE = 0.78
#: How far a ``Blocked`` kick is knocked back, in yards, and how high it goes in pixels.
BLOCK_BACK, BLOCK_UP = 3.0, 6.0
#: A veering kick ends this many pixels from the top/bottom lane.
VEER_MARGIN = 2


def miss_kind(scene: Scene) -> str:
    """``left``, ``right``, ``short``, ``blocked`` or ``other``, from the text's own wording."""
    text = (scene.fb_play.info.fg_miss or "").lower()
    for word in ("wide left", "wide right", "short", "blocked"):
        if word in text:
            return word.split()[-1]
    return "other"


def reason(scene: Scene) -> str:
    """``WIDE LEFT`` / ``WIDE RIGHT`` / ``SHORT`` / ``BLOCKED`` or the feed's own words."""
    text = (scene.fb_play.info.fg_miss or "").strip().upper()
    return text


def label(scene: Scene) -> str:
    yards = scene.fb_play.info.fg_yards or scene.fb_play.stat_yardage
    return f"NO GOOD {yards} YD" if yards else "NO GOOD"


@play_screen(PlayKind.FIELD_GOAL_MISSED)
def draw_fg_miss(r: Renderer, canvas: Any, scene: Scene) -> None:
    game = scene.fb_game
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    side, direction, spot, posts_x = _kick_geometry(scene, layout)
    kind = miss_kind(scene)
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)

    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    draw_posts(r, canvas, layout, side, YELLOW, flash=False)

    base_y = lane_y("middle", direction, layout)
    start_x = layout.x(spot)
    reach_x = float(posts_x) - direction * 2
    # Where the ball ends up, by how it was missed.
    top, bottom = layout.top + VEER_MARGIN + 2, layout.bottom - VEER_MARGIN
    ends = {
        "left": (reach_x, top if direction > 0 else bottom),
        "right": (reach_x, bottom if direction > 0 else top),
        "short": (start_x + (reach_x - start_x) * SHORT_SHARE, base_y),
        "blocked": (start_x - direction * BLOCK_BACK * layout.pixels_per_yard, base_y),
        "other": (start_x + (reach_x - start_x) * SHORT_SHARE, base_y),
    }
    end_x, end_y = ends[kind]
    if kind == "blocked":
        height = BLOCK_UP
    else:
        height = min(arc_height(abs(reach_x - start_x)) * 1.2, base_y - layout.top - 3)

    if share < KICK_START:
        here_x, here_y = start_x, base_y
    else:
        t = eased(min(1.0, (share - KICK_START) / (FLIGHT_END - KICK_START)))
        lift = height * 4 * t * (1 - t)
        here_x = start_x + (end_x - start_x) * t
        veer = (end_y - base_y) * t if kind in ("left", "right") else 0.0
        here_y = base_y + veer - lift
        draw_dotted_arc(
            canvas, layout, layout.yard_at(start_x), layout.yard_at(end_x), base_y, end_y, height, t
        )
    ff.draw_ball(canvas, layout, layout.yard_at(here_x), here_y, RED)

    r.text(canvas, r.fonts.tiny, 1, 6, RED, r_fit(label(scene), r.width - 44, r.fonts.tiny))
    why = reason(scene)
    if why:
        room = r.width - text_width(r.fonts.tiny, label(scene)) - 6
        r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, RED, r_fit(why, room, r.fonts.tiny))
