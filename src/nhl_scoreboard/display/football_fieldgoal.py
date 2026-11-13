"""``fb_fieldgoal`` (#392): a made field goal, the kick and the celebration.

Two screens, because a field goal is two things on the board:

* the **kick** (``@play_screen(FIELD_GOAL_GOOD)``, 4s): the ball is placed at the kick spot and
  **arcs through the uprights** drawn at the end of the field, the arc's height scaled to the
  distance; the band reads ``FIELD GOAL 31 YD``. This is all a field goal by a team nobody follows
  gets: **the same kick without the celebration**, dim, in the kicking team's colours, which is
  deliberately plainer because a field goal against the favourite is not a celebration;
* the **celebration** (``@event_screen(FieldGoal, EVENT)``, ``fb_score_seconds``): for the favourite
  (``Scope.FULL``: a white flash, the panel strobing in the team's colour, the uprights flashing)
  and, quicker and calmer, a followed team (``Scope.QUICK``: no strobe). ``FIELD GOAL`` in the
  team's colour with ``31 YD`` under it. The detail screen with the kicker follows (#391).

A pure function of the seconds since the stage began. A missed kick is ``fb_fg_miss`` (#393) and
a miss that reaches this event screen falls back to the generic card. The horn is a separate story.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import EVENT
from ..football.events import FieldGoal, Scope
from ..football.geometry import (
    AWAY,
    HOME,
    FieldLayout,
    arc_height,
    arc_point,
    clamp_yard_line,
    drive_direction,
    lane_y,
    possession_side,
)
from ..football.models import PlayKind
from ..football.teams import is_team, team_color
from . import football_field as ff
from .football_pass import draw_dotted_arc
from .football_plays import (
    DIM,
    GAIN,
    WHITE,
    draw_generic_event,
    event_screen,
    play_screen,
    quarter_clock,
    r_fit,
)
from .goal_light import _Buffer, _ease, _scaled

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

YELLOW = (255, 225, 0)
FLASH_SECONDS = 0.12
STROBE_SECONDS, STROBE_PERIOD = 2.0, 0.2
TEXT_START, TEXT_FADE = 0.4, 0.4
UPRIGHT_FLASH = 0.25
#: The posts: top row, the crossbar's row, and the base of the stem.
POST_TOP, CROSSBAR, POST_BASE = 8, 22, 30
#: The ball passes the uprights at this share of its arc, so it is still above the crossbar.
THROUGH = 0.82
KICK_SHARE_START, KICK_SHARE_END = 0.10, 0.80
PLAIN_DIM = 0.5


def kick_side(play: Any, game: Any) -> str:
    """``HOME`` or ``AWAY``: the team kicking, from the team the feed says is on offence."""
    pos = play.start or play.end
    side = possession_side(game, pos.team_id) if pos else None
    return side or HOME


def label(scene: Scene) -> str:
    yards = scene.fb_play.info.fg_yards or scene.fb_play.stat_yardage
    return f"FIELD GOAL {yards} YD" if yards else "FIELD GOAL"


def yards_text(scene: Scene) -> str:
    event = scene.fb_event
    yards = getattr(event, "yards", None) or scene.fb_play.info.fg_yards
    return f"{yards} YD" if yards else ""


def behind_posts(layout: FieldLayout, side: str, x: float) -> float:
    """``x`` held inside the end zone the kicker is attacking: a made kick drops down behind the
    posts, it does not carry on off the panel."""
    first, last = layout.end_zone_columns(AWAY if side == HOME else HOME)
    return max(first + 1.0, min(last - 2.0, x))


def draw_posts(
    r: Renderer, canvas: Any, layout: FieldLayout, side: str, color, flash: bool
) -> None:
    """The uprights at the back of the end zone the kicker is attacking: two posts, a crossbar and
    the stem down to the ground. Left and right are fixed: the home team attacks the right."""
    attacked = AWAY if side == HOME else HOME
    first, last = layout.end_zone_columns(attacked)
    width = last - first + 1
    inset = max(1, width // 7)
    left, right, mid = first + inset, last - inset, (first + last) // 2
    shade = (255, 255, 255) if flash else color
    for x in (left, right):
        r.vline(canvas, x, POST_TOP, CROSSBAR, shade)
    r.hline(canvas, left, right, CROSSBAR, shade)
    r.vline(canvas, mid, CROSSBAR, POST_BASE, shade)


def _kick_geometry(scene: Scene, layout: FieldLayout):
    """The kick spot, which way the ball goes, and the column of the uprights."""
    game, play = scene.fb_game, scene.fb_play
    side = kick_side(play, game)
    direction = drive_direction(side)
    pos = play.start or play.end
    spot = clamp_yard_line(float(pos.yard_line) if pos and pos.yard_line is not None else 50.0)
    attacked = AWAY if side == HOME else HOME
    first, last = layout.end_zone_columns(attacked)
    posts_x = (first + last) // 2
    return side, direction, spot, posts_x


@play_screen(PlayKind.FIELD_GOAL_GOOD)
def draw_kick(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    side, direction, spot, posts_x = _kick_geometry(scene, layout)
    team = game.home.abbrev if side == HOME else game.away.abbrev
    scope = getattr(scene.fb_event, "scope", Scope.PLAIN)
    plain = scope == Scope.PLAIN
    color = team_color(team) if is_team(team) else WHITE
    posts = _scaled(YELLOW, PLAIN_DIM) if plain else YELLOW

    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    draw_posts(r, canvas, layout, side, posts, flash=False)

    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    y = lane_y("middle", direction, layout)
    start_x, upright_x = layout.x(spot), float(posts_x)
    far_x = start_x + (upright_x - start_x) / THROUGH
    height = min(arc_height(abs(upright_x - start_x)) * 1.4, y - POST_TOP - 2)
    ball = _scaled(ff.BALL, PLAIN_DIM) if plain else ff.BALL
    if share < KICK_SHARE_START:
        ff.draw_ball(canvas, layout, spot, y, ball)
    elif share < KICK_SHARE_END:
        t = (share - KICK_SHARE_START) / (KICK_SHARE_END - KICK_SHARE_START)
        x, by = arc_point(start_x, far_x, y, height, t)
        draw_dotted_arc(canvas, layout, spot, layout.yard_at(far_x), y, y, height, t)
        ff.draw_ball(canvas, layout, layout.yard_at(behind_posts(layout, side, x)), by, ball)
    else:
        # Through the posts and down behind them, then it lies still.
        x, by = arc_point(start_x, far_x, y, height, 1.0)
        ff.draw_ball(canvas, layout, layout.yard_at(behind_posts(layout, side, x)), by, ball)
    if share >= (KICK_SHARE_START + KICK_SHARE_END) / 2:
        draw_posts(r, canvas, layout, side, posts, flash=not plain and int(share * 12) % 2 == 0)

    text_color = color if plain else GAIN
    r.text(canvas, r.fonts.tiny, 1, 6, text_color, r_fit(label(scene), r.width - 40, r.fonts.tiny))
    r.text_right(canvas, r.fonts.tiny, r.width - 1, 6, DIM, quarter_clock(play))


@event_screen(FieldGoal, EVENT)
def draw_fieldgoal(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    if not event.made:
        draw_generic_event(r, canvas, scene)  # a miss is #393's screen
        return
    canvas.Clear()
    age = max(0.0, scene.fb_elapsed)
    color = team_color(event.team) if is_team(event.team) else WHITE
    full = event.scope == Scope.FULL
    layout = FieldLayout.for_panel(r.width)
    buf = _Buffer(r.width, r.height)
    if full:
        if age < FLASH_SECONDS:
            buf.wash(WHITE, 0.35 * (1 - age / FLASH_SECONDS))
        elif age < STROBE_SECONDS and int(age / (STROBE_PERIOD / 2)) % 2 == 0:
            buf.wash(color, 0.30)
    buf.flush(canvas)

    game = scene.fb_game
    side = HOME if event.team == game.home.abbrev else AWAY
    flash = int(age / UPRIGHT_FLASH) % 2 == 0
    draw_posts(r, canvas, layout, side, YELLOW, flash=flash)

    fade = _ease((age - TEXT_START) / TEXT_FADE)
    if fade > 0:
        shade = _scaled(color, 0.35 + 0.65 * fade)
        wide = r.width >= 128
        cx = r.width // 2 - (8 if wide else 0)  # the posts take the right-hand edge of a wide panel
        font = r.fonts.large if wide else r.fonts.small
        r.text_center(canvas, font, cx, 15 if wide else 14, shade, "FIELD GOAL")
        yards = yards_text(scene)
        if yards:
            r.text_center(canvas, r.fonts.small, cx, 27, _scaled(WHITE, fade), yards)
