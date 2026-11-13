"""``fb_fieldgoal`` (#392): the kick through the uprights, and the celebration after it.

The events are built at each scope (favourite / followed / opponent); the geometry uses
``football.demo._play`` (NYG home kicking right, WSH away kicking left).
"""

from __future__ import annotations

from itertools import pairwise

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_fieldgoal as ffg
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.director import EVENT
from nhl_scoreboard.football.geometry import FieldLayout
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.teams import team_color
from test_football_director import started
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
NYG = team_color("NYG")
FG = "Field Goal Good"
HOME_KICK = _play(FG, "N.Folk 31 yard field goal is GOOD.", 69, 69, "NYG", 31, (0, 3), True)
AWAY_KICK = _play(FG, "E.Evans 38 yard field goal is GOOD.", 21, 21, "WSH", 38, (3, 0), True)


def event_at(scope, play=HOME_KICK, team="NYG", yards=31, made=True):
    return ev.FieldGoal(
        play=play,
        game_id=1,
        team=team,
        scope=scope,
        made=made,
        yards=yards,
        points=3,
        away_score=play.away_score,
        home_score=play.home_score,
    )


FULL = event_at(ev.Scope.FULL)
QUICK = event_at(ev.Scope.QUICK)
PLAIN = event_at(ev.Scope.PLAIN, AWAY_KICK, "WSH", 38)


def scene(play, share, event=None, stage="play", seconds=4.0):
    return Scene("fb_play" if stage == "play" else "fb_event", fb_game=make_game(), fb_play=play,
                 fb_event=event, fb_stage=stage, fb_elapsed=share * seconds, fb_seconds=seconds,
                 animating=True)  # fmt: skip


def kick(play, share, event, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share, event))
    assert not canvas.out_of_bounds
    return canvas


def celebrate(event, age, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(event.play, age / 6.0, event, "event", 6.0))
    assert not canvas.out_of_bounds
    return canvas


def balls(canvas):
    shades = {ff.BALL, tuple(int(v * ffg.PLAIN_DIM) for v in ff.BALL)}
    return [p for p, c in canvas.pixels.items() if c in shades and p[1] >= 8]


def centre(cells):
    return sum(x for x, _ in cells) // len(cells), min(y for _, y in cells)


def post_columns(canvas, color):
    cols = {}
    for (x, y), c in canvas.pixels.items():
        if c == color and 8 <= y <= 22:
            cols[x] = cols.get(x, 0) + 1
    return sorted(x for x, n in cols.items() if n >= 12)


# -- the kick ------------------------------------------------------------------------


def test_it_is_registered_for_the_kick_and_the_celebration_and_paced_at_four_seconds():
    assert fp.PLAY_SCREENS[PlayKind.FIELD_GOAL_GOOD] is ffg.draw_kick
    assert fp.EVENT_SCREENS[(ev.FieldGoal, EVENT)] is ffg.draw_fieldgoal
    assert pacing.animation_seconds(HOME_KICK, 3.0) == 4.0


def test_the_ball_is_placed_at_the_kick_spot_and_arcs_through_the_uprights_at_the_end_zone():
    spot, posts = LAYOUT.px(69), (post_columns(kick(HOME_KICK, 0.9, FULL), (255, 225, 0)) or [0])
    path = [centre(balls(kick(HOME_KICK, s / 100, FULL))) for s in range(0, 90, 4)]
    assert abs(path[0][0] - spot) <= 1
    xs = [x for x, _ in path]
    assert all(b >= a - 1 for a, b in pairwise(xs)), "toward the posts"
    assert max(xs) >= LAYOUT.px(100), "reaches the end zone"
    assert centre(balls(kick(HOME_KICK, 0.95, FULL)))[0] > 121, "and drops down behind the posts"
    assert min(y for _, y in path) < 22 - 2, "above the crossbar as it passes"
    assert posts


def test_the_posts_are_at_the_end_zone_the_kicker_attacks_and_the_away_team_kicks_left():
    yellow = ffg.YELLOW
    dim = tuple(int(v * ffg.PLAIN_DIM) for v in yellow)
    home, away = kick(HOME_KICK, 0.9, FULL), kick(AWAY_KICK, 0.9, PLAIN)
    right = {x for (x, y), c in home.pixels.items() if c in (yellow, (255, 255, 255)) and y >= 8}
    left = {x for (x, y), c in away.pixels.items() if c == dim and y >= 8}
    assert min(right) >= LAYOUT.px(100) and left and max(left) < LAYOUT.px(0)
    xs = [centre(balls(kick(AWAY_KICK, s / 100, PLAIN)))[0] for s in range(0, 90, 6)]
    assert all(b <= a + 1 for a, b in pairwise(xs))


def test_a_longer_kick_arcs_higher():
    short = _play(FG, "x 25 yard field goal is GOOD.", 85, 85, "NYG", 25, (0, 3), True)
    long = _play(FG, "x 55 yard field goal is GOOD.", 55, 55, "NYG", 55, (0, 3), True)

    def top(play):
        return min(centre(balls(kick(play, s / 100, FULL)))[1] for s in range(15, 70, 4))

    assert top(long) <= top(short)


def test_the_favourites_posts_flash_white_and_the_opponents_kick_is_dim_without_a_flash():
    white = (255, 255, 255)
    assert any(c == white for p, c in kick(HOME_KICK, 0.9, FULL).pixels.items() if p[1] >= 8)
    plain = kick(AWAY_KICK, 0.9, PLAIN)
    assert not any(c == white for p, c in plain.pixels.items() if p[1] >= 8), "no flash"
    assert tuple(int(v * ffg.PLAIN_DIM) for v in ffg.YELLOW) in plain.pixels.values()
    assert ffg.YELLOW not in [c for p, c in plain.pixels.items() if p[1] >= 8]
    assert tuple(int(v * ffg.PLAIN_DIM) for v in ff.BALL) in plain.pixels.values(), "a dim ball"


def test_the_band_says_field_goal_and_the_yards_green_for_a_celebration_else_the_teams_colour():
    assert ffg.label(scene(HOME_KICK, 0, FULL)) == "FIELD GOAL 31 YD"
    band = lambda c: [col for (x, y), col in c.pixels.items() if y < 8 and x < 60]  # noqa: E731
    assert fp.GAIN in band(kick(HOME_KICK, 0.9, FULL))
    plain = band(kick(AWAY_KICK, 0.9, PLAIN))
    assert team_color("WSH") in plain and fp.GAIN not in plain


# -- the celebration -----------------------------------------------------------------


def test_the_favourites_celebration_flashes_strobes_and_stops_and_a_followed_teams_does_not():
    assert any(sum(c) > 300 for c in celebrate(FULL, 0.02).pixels.values()), "the white flash"
    frames = [len(celebrate(FULL, 0.35 + 0.1 * i).pixels) for i in range(6)]
    lit = [n > 3000 for n in frames]
    assert any(lit) and not all(lit), "lit and dark"
    assert all(a != b for a, b in pairwise(lit)), "alternating"
    assert len(celebrate(FULL, 3.0).pixels) < 2000, "the strobe has stopped"
    quiet = [len(celebrate(QUICK, 0.35 + 0.1 * i).pixels) for i in range(6)]
    assert max(quiet) < 2000, "a followed team's version has no strobe"


def test_field_goal_fades_in_in_the_teams_colour_with_the_distance_under_it():
    assert not [c for c in celebrate(QUICK, 0.0).pixels.values() if c == NYG]
    full = celebrate(QUICK, 1.5).pixels
    assert NYG in full.values() and (255, 255, 255) in full.values()
    text = [p for p, c in full.items() if c == NYG and p[0] < 110]
    assert text and max(x for x, _ in text) < 120


def test_the_uprights_flash_between_yellow_and_white():
    a, b = celebrate(QUICK, 1.0), celebrate(QUICK, 1.3)
    cols_a = {c for p, c in a.pixels.items() if p[0] > 110}
    cols_b = {c for p, c in b.pixels.items() if p[0] > 110}
    assert cols_a != cols_b and {(255, 255, 255), ffg.YELLOW} == (cols_a | cols_b)


def test_a_missed_kick_that_reaches_this_screen_falls_back_to_the_generic_card():
    miss = event_at(ev.Scope.QUICK, make_play(1, "fg_miss_left", off="NYG"), made=False, yards=38)
    c = AsciiCanvas(128, 32)
    renderer().draw_fb_play_scene(c, scene(miss.play, 0.2, miss, "event", 3.0))
    g = AsciiCanvas(128, 32)
    fp.draw_generic_event(renderer(), g, scene(miss.play, 0.2, miss, "event", 3.0))
    assert c.pixels == g.pixels


@pytest.mark.parametrize("event", [FULL, QUICK, PLAIN], ids=["full", "quick", "plain"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.15, 0.3, 0.5, 0.7, 0.85, 1.0, 2.0])
def test_every_moment_draws_inside_the_panel(event, width, share):
    assert kick(event.play, share, event, width).pixels
    assert celebrate(event, share * 6, width).pixels


# -- the director's staging ----------------------------------------------------------


def staged(favourite, kicker_offence, follow=()):
    rig = started(make_play(1, "rush", off="NYG"), favourite=favourite, follow=follow)
    score = (0, 3) if kicker_offence == "NYG" else (3, 0)
    kick_play = make_play(2, "fg_good", score=score, off=kicker_offence)
    rig.poll(make_play(1, "rush", off="NYG"), kick_play)
    return rig.run()


def test_a_favourite_field_goal_is_the_kick_then_the_celebration_then_the_detail():
    stages = staged("NYG", "NYG")
    assert [s.stage for s in stages][:3] == ["play", "event", "detail"]
    assert isinstance(stages[0].event, ev.FieldGoal) and stages[0].event.scope == ev.Scope.FULL


def test_an_opponents_field_goal_is_only_the_plain_kick_and_the_kick_knows_it_is_plain():
    stages = staged("NYG", "WSH")
    assert [s.stage for s in stages] == ["play", "playtext"]
    assert stages[0].event.scope == ev.Scope.PLAIN


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,event,share,width,celebration",
    [
        ("kick", HOME_KICK, FULL, 0.5, 128, False),
        ("through", HOME_KICK, FULL, 0.85, 128, False),
        ("opponent", AWAY_KICK, PLAIN, 0.5, 128, False),
        ("celebration", HOME_KICK, FULL, 1.0, 128, True),
        ("quick", HOME_KICK, QUICK, 1.5, 128, True),
        ("kick_64", HOME_KICK, FULL, 0.5, 64, False),
    ],
)
def test_snapshot(name, play, event, share, width, celebration, update_snapshots):
    c = celebrate(event, share, width) if celebration else kick(play, share, event, width)
    check_snapshot(f"fieldgoal_{name}", c.render(), update_snapshots)
