"""``Pass Incompletion`` (#384): the quick arc, the drop and bounce short of the receiver, and the
ball marker that does not move. Also a spike and an intentional grounding (both are incompletions
to the feed). Geometry plays use ``football.demo._play`` (NYG home, driving right); the real
incompletions in ``play_cases.json`` are swept for stray pixels.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_incomplete as fi
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
QB = Person("passer", 9, "M. Penix", "9", "QB", True)
TARGET = Person("target", 7, "K. Pitts", "8", "TE", True)


def inc(text, start=40, offence="NYG"):
    return _play("Pass Incompletion", text, start, start, offence, 0)


SHORT_LEFT = inc("(Shotgun) M.Penix pass incomplete short left to K.Pitts.")
DEEP_RIGHT = inc("(Shotgun) D.Jones pass incomplete deep right.")
SPIKE = inc("(No Huddle) D.Jones spiked the ball to stop the clock.")


def scene(play, share, people=(QB, TARGET)):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=share * 3.0, fb_seconds=3.0, animating=True)  # fmt: skip


def draw(play, share, people=(QB, TARGET), width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share, people))
    assert not canvas.out_of_bounds
    return canvas


def balls(canvas):
    """Centres of the bright ball and the dim resting marker."""
    bright = [p for p, c in canvas.pixels.items() if c == ff.BALL]
    dim = [p for p, c in canvas.pixels.items() if c == fi.RESTING_BALL]
    return bright, dim


def bright_ball(canvas):
    cells, _ = balls(canvas)
    assert cells, "no ball in the air"
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return (min(xs) + max(xs)) // 2, max(ys)


def whites(canvas):
    return [p for p, c in canvas.pixels.items() if c == fp.WHITE]


# -- the rules -------------------------------------------------------------------------------------


def test_it_is_quick_and_registered_for_incompletions_only():
    assert pacing.animation_seconds(SHORT_LEFT, 3.0) == 3.0
    assert fp.PLAY_SCREENS[PlayKind.PASS_INCOMPLETE] is fi.draw_incomplete
    assert (
        PlayKind.SACK not in fp.PLAY_SCREENS
        or fp.PLAY_SCREENS[PlayKind.SACK] is not fi.draw_incomplete
    )


def test_the_label_is_incomplete_or_spike():
    assert fi.label(scene(SHORT_LEFT, 0)) == ("INCOMPLETE", fp.NEUTRAL)
    assert fi.label(scene(SPIKE, 0)) == ("SPIKE", fp.NEUTRAL)


def test_the_targets_number_falls_back_to_the_name_in_the_text_and_a_spike_has_none():
    assert fi.target_label(scene(SHORT_LEFT, 0)) == "8"
    assert fi.target_label(scene(SHORT_LEFT, 0, ())) == "PITTS"
    assert fi.target_label(scene(DEEP_RIGHT, 0, ())) == "", "no one is named"
    assert fi.target_label(scene(SPIKE, 0, (QB, TARGET))) == ""


def test_the_intended_spot_follows_the_depth_in_the_drive_direction():
    assert fi.intended_spot(40, "short", 1) == 48
    assert fi.intended_spot(40, "deep", 1) == 65
    assert fi.intended_spot(40, "", 1) == 54
    assert fi.intended_spot(40, "deep", -1) == 15
    assert fi.intended_spot(90, "deep", 1) == 100, "clamped to the goal line"


# -- the animation ---------------------------------------------------------------------------


def test_the_quarterbacks_number_shows_before_the_throw_then_the_targets_takes_over():
    early, later = draw(SHORT_LEFT, 0.05), draw(SHORT_LEFT, 0.4)
    assert whites(early) and whites(later)
    assert {p for p in whites(early)} != {p for p in whites(later)}


def test_the_ball_arcs_toward_the_receiver_and_comes_down_short_of_him():
    target_x = LAYOUT.px(fi.intended_spot(40, "short", 1))
    xs = [bright_ball(draw(SHORT_LEFT, s / 100))[0] for s in range(15, 54, 4)]
    assert xs == sorted(xs) and xs[-1] < target_x, "short of the receiver"
    assert xs[-1] > LAYOUT.px(40)


def test_the_ball_rises_in_the_air_then_bounces_smaller_and_lies_still():
    deep = [bright_ball(draw(DEEP_RIGHT, s / 100))[1] for s in range(12, 100, 2)]
    assert min(deep[:20]) < deep[0] or min(deep[:20]) < max(deep), "it rises"
    rest = [bright_ball(draw(DEEP_RIGHT, s / 100)) for s in range(84, 100, 3)]
    assert len(set(rest)) == 1, "lying still"
    bounce = [bright_ball(draw(DEEP_RIGHT, s / 100))[1] for s in range(55, 80, 2)]
    assert max(bounce) - min(bounce) >= 2, "it hops"


def test_the_ball_marker_stays_put_and_the_lines_do_not_move():
    col = lambda c, x: any(c.pixels.get((x, y)) == ff.SCRIMMAGE for y in range(8, 31))  # noqa: E731
    for share in (0.4, 0.7, 1.0):
        c = draw(SHORT_LEFT, share)
        assert col(c, LAYOUT.px(40)), share
        assert balls(c)[1], "the resting ball stays at the line"
    full = set(balls(draw(SHORT_LEFT, 1.0))[1])
    for share in (0.4, 0.7):  # the ball in the air may cover some of it, but never moves it
        assert set(balls(draw(SHORT_LEFT, share))[1]) <= full


def test_a_deep_pass_goes_further_than_a_short_one_and_the_lane_follows_the_direction():
    deep_end = bright_ball(draw(DEEP_RIGHT, 1.0))
    short_end = bright_ball(draw(SHORT_LEFT, 1.0))
    assert deep_end[0] > short_end[0]
    left = inc("M.P pass incomplete short left to K.Pitts.")
    right = inc("M.P pass incomplete short right to K.Pitts.")
    assert bright_ball(draw(left, 0.53))[1] < bright_ball(draw(right, 0.53))[1]


def test_the_away_team_throws_left():
    away = inc("(Shotgun) M.Penix pass incomplete short middle to K.Pitts.", 60, "WSH")
    xs = [bright_ball(draw(away, s / 100))[0] for s in range(15, 54, 4)]
    assert xs == sorted(xs, reverse=True)


def test_a_spike_throws_the_ball_into_the_ground_at_the_quarterback():
    xs = [bright_ball(draw(SPIKE, s / 100))[0] for s in range(12, 100, 8)]
    assert max(xs) - min(xs) <= 4 and not [p for p in whites(draw(SPIKE, 0.7))]


REAL = ["incomplete_target", "incomplete_no_target", "incomplete_deflected", "incomplete_spike",
        "incomplete_grounding", "incomplete_penalty_declined"]  # fmt: skip


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("off", ["NYG", "WSH"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.08, 0.2, 0.4, 0.56, 0.65, 0.8, 1.0, 2.0])
def test_every_real_incompletion_draws_inside_the_panel_at_every_moment(label, off, width, share):
    play = make_play(1, label, off=off)
    c = draw(play, share, width=width)
    assert c.pixels
    assert all(y <= FIELD_BOTTOM for (x, y), col in c.pixels.items() if col == ff.BALL)


# -- snapshots -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("air", SHORT_LEFT, 0.37, 128),
        ("bounce", SHORT_LEFT, 0.63, 128),
        ("deep", DEEP_RIGHT, 0.63, 128),
        ("spike", SPIKE, 0.63, 128),
        ("bounce_64", SHORT_LEFT, 0.63, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"incomplete_{name}", draw(play, share, width=width).render(), update_snapshots)
