"""``fb_run``, a rush (#380): the ball and its carrier run from the start spot to the end spot
along the text's lane, leaving a fading trail, then settle with the markers moved.

Geometry plays are built with ``football.demo._play`` so the spots are exact; the parser-dependent
cases (gap, scramble, kneel, touchdown) use the real plays in ``play_cases.json``.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_run as fr
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FIELD_TOP, FieldLayout, lane_y
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
HOME_RUN = _play(
    "Rush", "D.Singletary up the middle to WSH 29 for 9 yards (J.Smith).", 62, 71, "NYG", 9
)
AWAY_RUN = _play("Rush", "B.Robinson right end to NYG 33 for 7 yards (T.Smith).", 40, 33, "WSH", 7)
HENRY = Person("rusher", 22, "D. Singletary", "22", "RB", True)


def scene(play, elapsed, people=(), seconds=None, width=128):
    seconds = pacing.animation_seconds(play, 3.0) if seconds is None else seconds
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=elapsed, fb_seconds=seconds, animating=True)  # fmt: skip


def draw(play, elapsed, people=(), width=128, seconds=None):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, elapsed, people, seconds, width))
    assert not canvas.out_of_bounds
    return canvas


def ball_center(canvas, width=128):
    """The column and row of the ball's centre (the brown dot)."""
    cells = [p for p, c in canvas.pixels.items() if c == ff.BALL]
    assert cells, "no ball drawn"
    xs = [x for x, _ in cells]
    ys = [y for _, y in cells]
    return (min(xs) + max(xs)) // 2, max(ys)


# -- how long ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "yards,expected", [(0, 2.0), (4, 2.4), (9, 2.9), (20, 4.0), (-3, 2.3), (80, 4.0)]
)
def test_a_run_lasts_longer_the_further_it_goes_within_two_to_four_seconds(yards, expected):
    play = _play("Rush", "x", 40, 40 + yards, "NYG", yards)
    assert pacing.run_seconds(play) == pytest.approx(expected)


def test_only_runs_are_paced_by_yardage_and_everything_else_keeps_the_default():
    assert pacing.animation_seconds(HOME_RUN, 3.0) == pytest.approx(2.9)
    assert pacing.animation_seconds(make_play(1, "rush_td_pat", off="NYG"), 3.0) >= 2.0
    punt = make_play(1, "punt_return", off="WSH")
    assert pacing.animation_seconds(punt, 3.0) == 3.0


def test_the_director_uses_the_runs_own_length():
    from test_football_director import started

    rig = started(make_play(1, "rush", off="WSH"))
    long_run = _play("Rush", "x", 20, 60, "WSH", 40)
    rig.poll(make_play(1, "rush", off="WSH"), long_run)
    assert rig.run()[0].seconds == 4.0


# -- the label and the number ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "play,label,color",
    [
        (HOME_RUN, "RUSH +9", fp.GAIN),
        (_play("Rush", "x", 50, 48, "NYG", -2), "RUSH -2", fp.LOSS),
        (_play("Rush", "x", 50, 50, "NYG", 0), "RUSH 0", fp.NEUTRAL),
    ],
)
def test_the_label_says_the_yards_and_is_green_red_or_amber(play, label, color):
    assert fr.run_label(scene(play, 0)) == (label, color)


def test_a_scramble_and_a_kneel_are_read_off_the_play():
    assert fr.run_label(scene(make_play(1, "rush_scramble", off="NYG"), 0))[0].startswith(
        "SCRAMBLE"
    )
    assert fr.run_label(scene(make_play(1, "rush_kneel", off="NYG"), 0)) == ("KNEEL", fp.NEUTRAL)


def test_the_carriers_number_goes_on_the_ball_and_a_missing_one_falls_back_to_the_name():
    assert fr.carrier_label(scene(HOME_RUN, 0, (HENRY,))) == "22"
    nameless = Person("rusher", 5, "D. Singletary", "", "RB", True)
    assert fr.carrier_label(scene(HOME_RUN, 0, (nameless,))) == "SINGLE"[: fr.MAX_LABEL]
    assert fr.carrier_label(scene(HOME_RUN, 0)) == "SINGLE"[: fr.MAX_LABEL], "from the text"
    assert fr.carrier_label(scene(make_play(1, "rush_kneel", off="NYG", text="Kneel."), 0)) == ""


def test_the_scorer_carries_the_ball_on_a_touchdown_run():
    scorer = Person("scorer", 7, "D. Singletary", "22", "RB", True)
    assert fr.carrier_label(scene(HOME_RUN, 0, (scorer,))) == "22"


# -- the run ---------------------------------------------------------------------------------------


def test_the_ball_starts_on_the_start_spot_and_ends_on_the_end_spot():
    start = ball_center(draw(HOME_RUN, 0.0, (HENRY,)))[0]
    end = ball_center(draw(HOME_RUN, 9.0, (HENRY,)))[0]
    assert abs(start - LAYOUT.px(62)) <= 1 and abs(end - LAYOUT.px(71)) <= 1


def test_the_ball_only_moves_forward_and_then_rests():
    xs = [ball_center(draw(HOME_RUN, t / 10, (HENRY,)))[0] for t in range(0, 40)]
    assert xs == sorted(xs) and xs[0] < xs[-1]
    assert len(set(xs[-8:])) == 1, "settled for the last part of the stage"


def test_a_run_by_the_away_team_goes_left():
    xs = [ball_center(draw(AWAY_RUN, t / 10))[0] for t in range(0, 40)]
    assert xs == sorted(xs, reverse=True) and abs(xs[-1] - LAYOUT.px(33)) <= 1


def test_the_ball_runs_on_the_lane_the_text_names_and_it_flips_with_the_drive_direction():
    centre = ball_center(draw(HOME_RUN, 1.0))[1]
    left_end = _play("Rush", "A.Back left end to WSH 29 for 9 yards.", 62, 71, "NYG", 9)
    right_end = _play("Rush", "A.Back right end to WSH 29 for 9 yards.", 62, 71, "NYG", 9)
    up, down = ball_center(draw(left_end, 1.0))[1], ball_center(draw(right_end, 1.0))[1]
    assert up < centre < down, "driving right, the offence's left is up the panel"
    away_left = _play("Rush", "A.Back left end to NYG 33 for 7 yards.", 40, 33, "WSH", 7)
    assert ball_center(draw(away_left, 1.0))[1] > centre, "driving left, its left is down"
    assert abs(lane_y("left end", 1, LAYOUT) - up) <= 2


def test_the_trail_is_dim_at_the_start_and_brightest_next_to_the_ball():
    c = draw(HOME_RUN, 1.6)
    bx, _ = ball_center(c)
    row = round(lane_y("up the middle", 1, LAYOUT))
    greys = [c.pixels[(x, row)] for x in range(LAYOUT.px(62) + 1, bx - 2) if (x, row) in c.pixels
             and len(set(c.pixels[(x, row)])) == 1 and c.pixels[(x, row)][0] < 200]  # fmt: skip
    assert len(greys) >= 3 and [g[0] for g in greys] == sorted(g[0] for g in greys)


def test_the_number_is_drawn_beside_the_ball_and_stays_inside_the_field():
    c = draw(HOME_RUN, 1.0, (HENRY,))
    whites = [p for p, col in c.pixels.items() if col == fp.WHITE]
    bx, _ = ball_center(c)
    assert whites and all(FIELD_TOP <= y <= FIELD_BOTTOM for _, y in whites)
    assert all(abs(x - bx) <= 8 for x, _ in whites)


def test_the_markers_are_the_plays_own_until_the_ball_arrives_then_the_new_ones():
    before, after = draw(HOME_RUN, 0.2), draw(HOME_RUN, 9.0)
    sx = LAYOUT.px(62)
    assert any(c.pixels.get((sx, y)) == ff.SCRIMMAGE for c in [before] for y in range(8, 31))
    nx = LAYOUT.px(71)
    assert any(after.pixels.get((nx, y)) == ff.SCRIMMAGE for y in range(8, 31))
    assert not any(after.pixels.get((sx, y)) == ff.SCRIMMAGE for y in range(8, 31))


def test_a_touchdown_run_ends_in_the_end_zone():
    td = _play(
        "Rushing Touchdown",
        "A.Back up the middle to WSH 0 for 3 yards, TOUCHDOWN.",
        97,
        100,
        "NYG",
        3,
        scoring=True,
    )
    assert abs(ball_center(draw(td, 9.0))[0] - LAYOUT.px(100)) <= 1
    assert fp.PLAY_SCREENS[PlayKind.RUSHING_TOUCHDOWN] is fr.draw_run


def test_a_run_with_no_end_spot_still_draws_using_the_yardage():
    play = _play("Rush", "x", 50, 50, "NYG", 6)
    object.__setattr__(play, "end", None)
    assert ball_center(draw(play, 9.0))[0] > LAYOUT.px(50)


def test_it_is_registered_for_runs_only():
    assert fp.PLAY_SCREENS[PlayKind.RUSH] is fr.draw_run
    assert PlayKind.PASS_INCOMPLETE not in fp.PLAY_SCREENS


REAL_RUNS = ["rush", "rush_up_the_middle", "rush_no_gain", "rush_kneel", "rush_scramble",
             "rush_td_pat", "rush_td_two_point_good"]  # fmt: skip


@pytest.mark.parametrize("label", REAL_RUNS)
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("elapsed", [0.0, 0.7, 1.5, 2.4, 9.0])
def test_every_real_run_draws_inside_the_panel_at_every_moment(label, width, elapsed):
    play = make_play(1, label, off="NYG")
    assert draw(play, elapsed, width=width).pixels


# -- snapshots -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,elapsed,width",
    [
        ("mid", HOME_RUN, 1.0, 128),
        ("settled", HOME_RUN, 9.0, 128),
        ("away_outside", AWAY_RUN, 1.2, 128),
        ("mid_64", HOME_RUN, 1.0, 64),
    ],
)
def test_snapshot(name, play, elapsed, width, update_snapshots):
    c = draw(play, elapsed, (HENRY,), width)
    check_snapshot(f"fb_run_{name}", c.render(), update_snapshots)
