"""``Penalty`` (#386): the compressed result, the flag, and the marker moving to the enforced spot.

The text rules are checked on the real penalty plays in ``play_cases.json``; the geometry uses
``football.demo._play`` (NYG home, driving right).
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_penalty as fp_
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_punt as punt
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
FALSE_START = _play(
    "Penalty",
    "(Shotgun) PENALTY on NYG-J.Taylor, False Start, 5 yards, enforced at NYG 40 - No Play.",
    40, 35, "NYG", -5,
)  # fmt: skip
HOLDING = _play(
    "Penalty",
    "(Shotgun) D.Jones scrambles up the middle to NYG 46 for 6 yards (L.London).PENALTY on "
    "NYG-M.Bergeron, Offensive Holding, 10 yards, enforced at NYG 40 - No Play.",
    40, 30, "NYG", -10,
)  # fmt: skip
DECLINED = _play(
    "Penalty",
    "D.Jones pass incomplete short left.Penalty on WSH-N.Muse, Offensive Offside, declined.",
    40, 40, "NYG", 0,
)  # fmt: skip


def scene(play, share):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_stage="play",
                 fb_elapsed=share * 4.0, fb_seconds=4.0, animating=True)  # fmt: skip


def draw(play, share, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share))
    assert not canvas.out_of_bounds
    return canvas


def penalty_play(label, off="NYG"):
    """A real penalty (some are typed as the play they rode on) as a ``Penalty`` play."""
    return make_play(1, label, off=off, ptype="Penalty")


def real(label, off="NYG"):
    return scene(penalty_play(label, off), 0.0)


def ball_x(canvas):
    cells = [p for p, c in canvas.pixels.items() if c == ff.BALL]
    assert cells
    xs = [x for x, _ in cells]
    return (min(xs) + max(xs)) // 2


def flag(canvas):
    return [p for p, c in canvas.pixels.items() if c == punt.FLAG and p[1] >= 8
            and c == punt.FLAG and p[0] not in column(canvas, ff.FIRST_DOWN)]  # fmt: skip


def column(canvas, color):
    cols = {}
    for (x, y), c in canvas.pixels.items():
        if c == color and y >= 8:
            cols[x] = cols.get(x, 0) + 1
    return sorted(x for x, n in cols.items() if n >= 12)


# -- reading the text ----------------------------------------------------------------


@pytest.mark.parametrize(
    "label,how,foul",
    [
        ("penalty_pre_snap", "accepted", "FALSE START 5 YD"),
        ("penalty_after_run", "accepted", "OFFENSIVE HOLDING 10 YD"),
        ("penalty_no_play", "accepted", "DEFENSIVE PASS INTERFERENCE 3 YD"),
        ("penalty_team_only", "accepted", "DELAY OF GAME 5 YD"),
        ("penalty_accepted_and_declined", "accepted", "OFFENSIVE HOLDING 10 YD"),
        ("penalty_offsetting_play", "offsetting", "ILLEGAL MOTION"),
        ("incomplete_penalty_declined", "declined", "INELIGIBLE DOWNFIELD PASS"),
    ],
)
def test_each_real_penalty_is_read_as_accepted_declined_or_offsetting(label, how, foul):
    s = real(label)
    assert fp_.variant(s) == how and fp_.foul_text(s) == foul


def test_a_result_before_the_flag_is_found_and_a_pre_snap_foul_has_none():
    assert fp_.result_gain(real("penalty_pre_snap")) is None
    assert fp_.result_gain(real("penalty_team_only")) is None
    assert fp_.result_gain(real("penalty_after_run")) == 6
    assert fp_.result_gain(real("penalty_no_play")) == 0, "an incompletion: nothing gained"
    assert fp_.result_gain(real("penalty_accepted_and_declined")) == 0


def test_the_accepted_penalty_is_the_one_that_counts_not_the_declined_one():
    pen = fp_.accepted(real("penalty_accepted_and_declined"))
    assert pen.name == "Offensive Holding" and not pen.declined
    assert fp_.accepted(real("incomplete_penalty_declined")) is None


def test_it_is_registered_for_penalty_plays_only_and_takes_four_seconds():
    assert fp.PLAY_SCREENS[PlayKind.PENALTY] is fp_.draw_penalty
    assert pacing.animation_seconds(FALSE_START, 3.0) == 4.0
    assert fp.PLAY_SCREENS.get(PlayKind.KICKOFF) is not fp_.draw_penalty
    assert fp.PLAY_SCREENS.get(PlayKind.PASS_INCOMPLETE) is not fp_.draw_penalty


def test_the_label_goes_from_the_result_to_flag_to_the_foul_to_no_play():
    s = scene(HOLDING, 0)
    assert fp_.label(s, 0.1) == ("6 YD", fp.GAIN)
    assert fp_.label(s, 0.4) == ("FLAG", punt.FLAG)
    assert fp_.label(s, 0.7) == ("OFFENSIVE HOLDING 10 YD", punt.FLAG)
    assert fp_.label(s, 0.95) == ("NO PLAY", fp.LOSS)
    pre = scene(FALSE_START, 0)
    assert fp_.label(pre, 0.1)[0] == "FLAG", "no result to show before a pre-snap foul"


def test_declined_and_offsetting_have_their_own_labels():
    assert fp_.label(scene(DECLINED, 0), 0.95) == ("OFFENSIVE OFFSIDE DECLINED", fp.NEUTRAL)
    off = real("penalty_offsetting_play")
    assert fp_.label(off, 0.95)[0] == "OFFSETTING"
    loss = _play("Penalty", "x sacked for -4 yards.PENALTY on NYG-A.B, Holding, 5 yards - No Play.",
                 40, 35, "NYG", -5)  # fmt: skip
    assert fp_.label(scene(loss, 0), 0.1) == ("4 YD", fp.LOSS)


# -- the animation -------------------------------------------------------------------


def test_the_result_before_the_flag_plays_compressed_then_the_marker_moves_to_the_enforced_spot():
    start, result, end = LAYOUT.px(40), LAYOUT.px(46), LAYOUT.px(30)
    xs = [ball_x(draw(HOLDING, s / 100)) for s in range(0, 100, 5)]
    assert abs(xs[0] - start) <= 1
    assert abs(xs[5] - result) <= 1, "the scramble, compressed into the first quarter"
    assert abs(xs[-1] - end) <= 1, "then back to the enforced spot"
    assert xs[0:6] == sorted(xs[0:6]) and xs[11:] == sorted(xs[11:], reverse=True)


def test_a_pre_snap_foul_has_no_compressed_result_the_ball_stays_until_it_is_moved():
    xs = [ball_x(draw(FALSE_START, s / 100)) for s in range(0, 55, 5)]
    assert set(xs) == {LAYOUT.px(40)}
    assert abs(ball_x(draw(FALSE_START, 1.0)) - LAYOUT.px(35)) <= 1


def test_the_flag_flies_in_and_lands_at_the_spot_of_the_foul():
    def flag_pixels(share):
        c = draw(FALSE_START, share)
        return [p for p, col in c.pixels.items() if col == punt.FLAG and p[1] >= 8
                and p[0] not in column(c, ff.FIRST_DOWN)]  # fmt: skip

    assert not flag_pixels(0.1), "not yet"
    early, mid, landed = flag_pixels(0.3), flag_pixels(0.4), flag_pixels(0.6)
    top = lambda px: min(y for _, y in px)  # noqa: E731
    left = lambda px: min(x for x, _ in px)  # noqa: E731
    assert early and mid and landed
    assert top(early) < top(mid) < top(landed), "falling"
    assert left(early) < left(mid) < left(landed), "coming in from behind the offence"
    assert abs(left(landed) - LAYOUT.px(40)) <= 4, "lying at the spot"
    assert flag_pixels(0.8) == landed, "and it stays there while the marker moves"


def test_a_declined_penalty_shows_the_flag_but_the_ball_does_not_move():
    xs = {ball_x(draw(DECLINED, s / 100)) for s in range(0, 100, 7)}
    assert xs == {LAYOUT.px(40)}
    assert [p for p, c in draw(DECLINED, 0.7).pixels.items() if c == punt.FLAG and p[1] >= 8]


def test_a_declined_penalty_never_moves_the_ball_whatever_end_spot_the_feed_gives():
    odd = _play("Penalty", "D.J pass incomplete.Penalty on WSH-N.M, Offside, declined.",
                40, 35, "NYG", -5)  # fmt: skip
    xs = {ball_x(draw(odd, s / 100)) for s in range(0, 100, 7)}
    assert xs == {LAYOUT.px(40)}


def test_offsetting_penalties_leave_the_ball_alone():
    play = penalty_play("penalty_offsetting_play")
    xs = {ball_x(draw(play, s / 100)) for s in range(0, 100, 9)}
    assert len(xs) == 1


def test_the_markers_are_the_plays_own_until_the_move_then_the_new_ones():
    assert LAYOUT.px(40) in column(draw(FALSE_START, 0.3), ff.SCRIMMAGE)
    assert column(draw(FALSE_START, 1.0), ff.SCRIMMAGE) == [LAYOUT.px(35)]


REAL = ["penalty_no_play", "penalty_after_run", "penalty_pre_snap", "penalty_accepted_and_declined",
        "penalty_offsetting_play", "penalty_team_only", "incomplete_penalty_declined"]  # fmt: skip


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("off", ["NYG", "WSH"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.1, 0.24, 0.3, 0.45, 0.52, 0.7, 0.9, 1.0, 2.0])
def test_every_real_penalty_draws_inside_the_panel_at_every_moment(label, off, width, share):
    play = penalty_play(label, off)
    c = draw(play, share, width)
    assert c.pixels
    assert all(y <= FIELD_BOTTOM for (x, y), col in c.pixels.items() if col == ff.BALL)


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("result", HOLDING, 0.15, 128),
        ("flag", FALSE_START, 0.4, 128),
        ("landed", FALSE_START, 0.7, 128),
        ("no_play", FALSE_START, 1.0, 128),
        ("declined", DECLINED, 0.7, 128),
        ("landed_64", FALSE_START, 0.7, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"penalty_{name}", draw(play, share, width).render(), update_snapshots)
