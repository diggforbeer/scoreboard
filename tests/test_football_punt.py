"""``Punt`` (#383): a long, high kick and its endings (fair catch, return, out of bounds,
touchback, downed). Geometry plays use ``football.demo._play`` (NYG home on the left, WSH away on
the right); the six real punts in ``play_cases.json`` are swept for stray pixels and checked for
which ending the parser sees.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_kickoff as fk
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_punt as fpunt
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
CATCHER = Person("returner", 4, "D. Meyers", "11", "WR", True)
FAIR = _play("Punt", "J.Bailey punts 53 yards to WSH 12, Center-L.M, fair catch by D.Meyers.",
             35, 88, "NYG", 0, end_team="WSH")  # fmt: skip
RETURNED = _play("Punt", "R.R punts 51 yards to NYG 27. O.Zaccheaus to NYG 24 for -3 yards.",
                 78, 24, "WSH", -3, end_team="NYG")  # fmt: skip
OOB = _play("Punt", "J.Bailey punts 37 yards to WSH 17, Center-L.M, out of bounds.",
            46, 83, "NYG", 0, end_team="WSH")  # fmt: skip
TOUCHBACK = _play("Punt", "T.Way punts 53 yards to end zone, Center-T.Ott, Touchback.",
                  47, 20, "WSH", 0, end_team="NYG")  # fmt: skip
DOWNED = _play("Punt", "E.Evans punts 58 yards to WSH 18, Center-J.M, downed by NYG-J.W.",
               24, 82, "NYG", 0, end_team="WSH")  # fmt: skip


def scene(play, share, people=(CATCHER,)):
    seconds = pacing.animation_seconds(play, 3.0)
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=share * seconds, fb_seconds=seconds, animating=True)  # fmt: skip


def draw(play, share, people=(CATCHER,), width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share, people))
    assert not canvas.out_of_bounds
    return canvas


def ball(canvas):
    cells = [p for p, c in canvas.pixels.items() if c == ff.BALL]
    assert cells, "no ball drawn"
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return (min(xs) + max(xs)) // 2, max(ys)


def path(play, shares=None):
    return [ball(draw(play, s / 100)) for s in (shares or range(0, 100, 4))]


def flag(canvas):
    return [p for p, c in canvas.pixels.items() if c == fpunt.FLAG and p[1] >= 8]


# -- the endings the text gives ------------------------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [("punt_fair_catch", "fair_catch"), ("punt_return", "returned"),
     ("punt_out_of_bounds", "out_of_bounds"), ("punt_touchback", "touchback"),
     ("punt_downed", "downed"), ("punt_penalty", "returned")],
)  # fmt: skip
def test_each_real_punt_is_read_as_the_ending_its_text_describes(label, expected):
    assert fpunt.ending(scene(make_play(1, label, off="NYG", end="WSH"), 0)) == expected


def test_a_punt_with_nothing_after_the_kick_is_a_plain_one():
    bare = _play("Punt", "X.Y punts 40 yards to WSH 25.", 35, 75, "NYG", 0, end_team="WSH")
    assert fpunt.ending(scene(bare, 0)) == "plain"


def test_a_fair_catch_or_return_takes_five_seconds_and_the_other_endings_four():
    assert [pacing.animation_seconds(p, 3.0) for p in (FAIR, RETURNED, OOB, TOUCHBACK, DOWNED)] == [
        5.0, 5.0, 4.0, 4.0, 4.0,
    ]  # fmt: skip
    assert PlayKind.PUNT in pacing.PLAY_SECONDS


def test_the_label_is_the_kick_in_the_air_and_the_ending_once_it_is_down():
    assert fpunt.punt_label(scene(FAIR, 0.3), 0.3) == ("PUNT 53 YD", fp.NEUTRAL)
    expected = [(FAIR, "FAIR CATCH"), (OOB, "OUT OF BOUNDS"), (TOUCHBACK, "TOUCHBACK"),
                (DOWNED, "DOWNED")]  # fmt: skip
    for play, text in expected:
        assert fpunt.punt_label(scene(play, 0.8), 0.8) == (text, fp.NEUTRAL)
    assert fpunt.punt_label(scene(RETURNED, 0.8), 0.8) == ("RETURN -3", fp.LOSS)
    text = "A.B punts 40 yards to WSH 25. C.D to WSH 40 for 15 yards."
    gain = _play("Punt", text, 35, 60, "NYG", 15, end_team="WSH")
    assert fpunt.punt_label(scene(gain, 0.8), 0.8) == ("RETURN 15", fp.GAIN)


# -- the flight ----------------------------------------------------------------------


def test_the_ball_starts_on_the_punters_spot_and_lands_where_the_distance_says():
    pts = path(FAIR)
    assert abs(pts[0][0] - LAYOUT.px(35)) <= 1
    air = [x for x, _ in pts[3:13]]
    assert air == sorted(air) and abs(pts[14][0] - LAYOUT.px(88)) <= 2


def test_a_punt_hangs_longer_and_higher_than_a_kickoff_of_the_same_length_and_stays_on_the_field():
    same = _play("Kickoff", "N.F kicks 53 yards from NYG 35 to WSH 12. D.M to WSH 12 for no gain.",
                 35, 88, "NYG", 0, end_team="WSH")  # fmt: skip
    top = lambda p: min(y for _, y in path(p, range(8, 52, 2)))  # noqa: E731
    assert top(FAIR) <= top(same) and top(FAIR) >= 8


def test_the_away_team_punts_left():
    pts = path(RETURNED)
    air = [x for x, _ in pts[3:13]]
    assert air == sorted(air, reverse=True) and abs(pts[14][0] - LAYOUT.px(27)) <= 2


# -- each ending ---------------------------------------------------------------------


def test_a_fair_catch_marks_the_catch_with_a_flag_and_the_catchers_number():
    before, after = draw(FAIR, 0.3), draw(FAIR, 0.85)
    assert not flag(before) and flag(after)
    assert [p for p, c in after.pixels.items() if c == fp.WHITE], "the catcher's number"
    pts = path(FAIR, range(60, 100, 4))
    assert len({x for x, _ in pts}) == 1, "the ball stays put"


def test_a_return_runs_back_from_the_landing_spot_to_the_end_spot_with_the_returners_number():
    xs = [x for x, _ in path(RETURNED, range(60, 96, 3))]
    assert xs == sorted(xs, reverse=True) or xs == sorted(xs)
    assert abs(xs[0] - LAYOUT.px(27)) <= 2 and abs(path(RETURNED)[-1][0] - LAYOUT.px(24)) <= 1
    whites = [p for p, c in draw(RETURNED, 0.8).pixels.items() if c == fp.WHITE]
    assert whites


def test_an_out_of_bounds_punt_skips_to_the_sideline_and_stops_there():
    end = ball(draw(OOB, 0.95))
    landed = ball(draw(OOB, 0.57))
    assert end[1] >= FIELD_BOTTOM - 3, "at the sideline"
    assert end[1] > landed[1]
    assert LAYOUT.px(83) <= end[0] <= LAYOUT.px(83) + 6, "a few yards on"
    assert end == ball(draw(OOB, 1.0))


def test_a_touchback_lands_in_the_end_zone_and_the_ball_steps_out_to_the_spot():
    pts = path(TOUCHBACK)
    assert pts[14][0] < LAYOUT.px(0), "down in the home end zone"
    stepped = [x for x, _ in pts[15:]]
    assert stepped == sorted(stepped) and abs(pts[-1][0] - LAYOUT.px(20)) <= 1


def test_a_downed_punt_stops_where_it_landed():
    pts = path(DOWNED, range(60, 100, 4))
    assert len(set(pts)) == 1 and abs(pts[0][0] - LAYOUT.px(82)) <= 2


def test_the_markers_appear_at_the_end_spot_only_when_settled():
    col = lambda c, x: any(c.pixels.get((x, y)) == ff.SCRIMMAGE for y in range(8, 31))  # noqa: E731
    nx = LAYOUT.px(24)
    assert not col(draw(RETURNED, 0.7), nx) and col(draw(RETURNED, 1.0), nx)


def test_it_is_registered_for_punts():
    assert fp.PLAY_SCREENS[PlayKind.PUNT] is fpunt.draw_punt
    assert PlayKind.FIELD_GOAL_GOOD not in fp.PLAY_SCREENS
    assert fk.kicker_direction  # the helpers are shared with the kickoff screen


REAL = ["punt_fair_catch", "punt_out_of_bounds", "punt_return", "punt_downed", "punt_touchback",
        "punt_penalty"]  # fmt: skip


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("off,end", [("NYG", "WSH"), ("WSH", "NYG")])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.2, 0.4, 0.56, 0.62, 0.8, 0.95, 1.0, 2.0])
def test_every_real_punt_draws_inside_the_panel_at_every_moment(label, off, end, width, share):
    play = make_play(1, label, off=off, end=end)
    c = draw(play, share, width=width)
    assert c.pixels and all(
        y <= FIELD_BOTTOM + 1 for (x, y), col in c.pixels.items() if col == ff.BALL
    )


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("air", FAIR, 0.3, 128),
        ("fair_catch", FAIR, 0.8, 128),
        ("return", RETURNED, 0.75, 128),
        ("out_of_bounds", OOB, 0.85, 128),
        ("touchback", TOUCHBACK, 0.75, 128),
        ("downed", DOWNED, 0.8, 128),
        ("air_64", FAIR, 0.3, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"punt_{name}", draw(play, share, width=width).render(), update_snapshots)
