"""``fb_pass``, a completed pass (#381): the quarterback, the arc, the catch and the run after it.

Geometry plays are built with ``football.demo._play`` so the spots and yards after the catch are
exact; the parser-dependent cases (direction, depth, names, touchdowns) use the real plays.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_pass as fpass
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FIELD_TOP, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
QB = Person("passer", 9, "M. Penix", "9", "QB", True)
WR = Person("receiver", 1, "J. Dotson", "81", "WR", True)
TEXT = "(Shotgun) M.Penix pass short right to J.Dotson to WSH 40 for {y} yards."
HOME_PASS = _play("Pass Reception", TEXT.format(y=20), 30, 50, "NYG", 20, yac=6)
AWAY_PASS = _play("Pass Reception", TEXT.format(y=12), 45, 33, "WSH", 12, yac=4)


def scene(play, elapsed, people=(QB, WR)):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=elapsed, fb_seconds=pacing.animation_seconds(play, 3.0),
                 animating=True)  # fmt: skip


def draw(play, elapsed, people=(QB, WR), width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, elapsed, people))
    assert not canvas.out_of_bounds
    return canvas


def at(play, share, **kw):
    """The screen ``share`` (0-1) of the way through the play's stage."""
    return draw(play, share * pacing.animation_seconds(play, 3.0), **kw)


def ball(canvas):
    cells = [p for p, c in canvas.pixels.items() if c == ff.BALL]
    assert cells, "no ball drawn"
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return (min(xs) + max(xs)) // 2, max(ys)


def whites(canvas):
    return [p for p, c in canvas.pixels.items() if c == fp.WHITE]


# -- the pieces ----------------------------------------------------------------------------------


def test_the_label_says_the_yards_in_green_red_or_amber():
    assert fpass.pass_label(scene(HOME_PASS, 0)) == ("PASS +20", fp.GAIN)
    loss = _play("Pass Reception", "x", 50, 48, "NYG", -2)
    assert fpass.pass_label(scene(loss, 0)) == ("PASS -2", fp.LOSS)
    flat = _play("Pass Reception", "x", 50, 50, "NYG", 0)
    assert fpass.pass_label(scene(flat, 0)) == ("PASS 0", fp.NEUTRAL)


def test_the_catch_is_the_end_spot_less_the_yards_after_the_catch_in_the_drive_direction():
    assert fpass.catch_spot(30, 50, 6, 1) == 44
    assert fpass.catch_spot(45, 33, 4, -1) == 37
    assert fpass.catch_spot(30, 50, None, 1) == 50, "no yards after the catch: caught at the end"


def test_the_catch_is_never_behind_the_quarterback_or_past_the_end():
    assert fpass.catch_spot(30, 50, 99, 1) == 30, "a screen caught at the line"
    assert fpass.catch_spot(30, 50, -5, 1) == 50


def test_numbers_fall_back_to_the_name_and_then_to_nothing():
    assert fpass.receiver_label(scene(HOME_PASS, 0)) == "81"
    assert fpass.passer_label(scene(HOME_PASS, 0)) == "9"
    nameless = Person("receiver", 1, "J. Dotson", "", "WR", True)
    assert fpass.receiver_label(scene(HOME_PASS, 0, (nameless,))) == "DOTSON"
    assert fpass.receiver_label(scene(HOME_PASS, 0, ())) == "DOTSON", "from the play text"
    blank = make_play(1, "pass_complete", off="NYG", text="Pass complete.")
    assert fpass.receiver_label(scene(blank, 0, ())) == ""


# -- the timeline ---------------------------------------------------------------------------------


def test_the_quarterbacks_number_is_shown_at_his_spot_before_the_throw():
    c = at(HOME_PASS, 0.05)
    assert abs(ball(c)[0] - LAYOUT.px(30)) <= 1 and whites(c)


def test_the_ball_arcs_to_the_catch_spot_and_the_receivers_number_appears_on_the_catch():
    mid = at(HOME_PASS, 0.38)
    caught = at(HOME_PASS, 0.62)
    assert LAYOUT.px(30) < ball(mid)[0] < LAYOUT.px(44)
    assert abs(ball(caught)[0] - LAYOUT.px(44)) <= 2
    assert whites(caught), "the receiver's number"


def test_the_air_ball_flies_forward_and_the_run_after_the_catch_carries_it_to_the_end_spot():
    xs = [ball(at(HOME_PASS, s / 100))[0] for s in range(0, 100, 3)]
    assert xs == sorted(xs)
    assert abs(xs[-1] - LAYOUT.px(50)) <= 1 and len(set(xs[-4:])) == 1, "and it rests"


def test_an_away_pass_goes_left():
    xs = [ball(at(AWAY_PASS, s / 100))[0] for s in range(0, 100, 3)]
    assert xs == sorted(xs, reverse=True) and abs(xs[-1] - LAYOUT.px(33)) <= 1


def test_the_ball_rises_in_the_air_and_comes_down_at_the_catch():
    play = _play("Pass Reception", "M.Penix pass deep middle to J.Dotson for 30 yards.",
                 20, 50, "NYG", 30, yac=0)  # fmt: skip
    qb_y = ball(at(play, 0.02))[1]
    rows = [ball(at(play, s / 100))[1] for s in range(20, 60, 4)]
    assert min(rows) <= qb_y - 4, "an arc, not a line"
    assert rows[0] > min(rows) and ball(at(play, 0.62))[1] >= min(rows)


def test_a_deep_pass_arcs_higher_than_a_short_one_of_the_same_length():
    short = _play(
        "Pass Reception",
        "M.Penix pass short middle to J.Dotson for 20 yards.",
        30,
        50,
        "NYG",
        20,
        yac=0,
    )
    deep = _play(
        "Pass Reception",
        "M.Penix pass deep middle to J.Dotson for 20 yards.",
        30,
        50,
        "NYG",
        20,
        yac=0,
    )
    top = lambda p: min(ball(at(p, s / 100))[1] for s in range(15, 60, 3))  # noqa: E731
    assert top(deep) < top(short)


def test_the_catch_lands_in_the_lane_the_text_names_and_it_flips_with_the_drive_direction():
    def lane(direction_word, offence="NYG", start=30, end=50):
        text = f"M.Penix pass short {direction_word} to J.Dotson for 20 yards."
        play = _play("Pass Reception", text, start, end, offence, 20, yac=0)
        return ball(at(play, 0.7))[1]

    left, middle, right = lane("left"), lane("middle"), lane("right")
    assert left < middle < right, "driving right, the offence's left is up the panel"
    assert lane("left", "WSH", 50, 30) > lane("middle", "WSH", 50, 30), "driving left, left is down"


def test_the_markers_move_when_the_ball_has_landed_and_not_before():
    sx, nx = LAYOUT.px(30), LAYOUT.px(50)
    col = lambda c, x: any(c.pixels.get((x, y)) == ff.SCRIMMAGE for y in range(8, 31))  # noqa: E731
    assert col(at(HOME_PASS, 0.4), sx) and not col(at(HOME_PASS, 0.4), nx)
    assert col(at(HOME_PASS, 1.0), nx) and not col(at(HOME_PASS, 1.0), sx)


def test_a_touchdown_pass_ends_in_the_end_zone_and_is_registered():
    td = _play("Passing Touchdown", "M.Penix pass short right to C.Woerner for 4 yards, TOUCHDOWN.",
               96, 100, "NYG", 4, scoring=True, yac=1)  # fmt: skip
    assert abs(ball(at(td, 1.0))[0] - LAYOUT.px(100)) <= 1
    assert fp.PLAY_SCREENS[PlayKind.PASSING_TOUCHDOWN] is fpass.draw_pass


def test_a_pass_is_paced_by_its_yardage():
    assert pacing.animation_seconds(HOME_PASS, 3.0) == pytest.approx(4.0)
    short = _play("Pass Reception", "x", 30, 33, "NYG", 3)
    assert pacing.animation_seconds(short, 3.0) == pytest.approx(2.3)


def test_incompletions_and_other_plays_are_not_this_screen():
    assert fp.PLAY_SCREENS[PlayKind.PASS_COMPLETE] is fpass.draw_pass
    assert fp.PLAY_SCREENS.get(PlayKind.PASS_INCOMPLETE) is not fpass.draw_pass


def test_a_pass_with_no_end_spot_uses_the_yardage():
    play = _play("Pass Reception", "x", 50, 50, "NYG", 9)
    object.__setattr__(play, "end", None)
    assert ball(at(play, 1.0))[0] > LAYOUT.px(50)


REAL = ["pass_complete", "pass_complete_deep_ob", "pass_complete_lateral", "pass_td_pat",
        "pass_td_two_point_fail", "pass_complete_two_letter_initial"]  # fmt: skip


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.1, 0.3, 0.55, 0.65, 0.8, 0.9, 1.0, 3.0])
def test_every_real_completion_draws_inside_the_panel_at_every_moment(label, width, share):
    play = make_play(1, label, off="NYG")
    c = at(play, share, width=width)
    assert c.pixels and all(FIELD_TOP - 1 <= y <= FIELD_BOTTOM for (x, y), col in c.pixels.items()
                            if col == ff.BALL)  # fmt: skip


# -- snapshots -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("snap", HOME_PASS, 0.05, 128),
        ("air", HOME_PASS, 0.38, 128),
        ("catch", HOME_PASS, 0.7, 128),
        ("settled", HOME_PASS, 1.0, 128),
        ("away_air", AWAY_PASS, 0.38, 128),
        ("air_64", HOME_PASS, 0.38, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"fb_pass_{name}", at(play, share, width=width).render(), update_snapshots)
