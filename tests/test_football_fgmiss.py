"""``fb_fg_miss`` (#393): a missed field goal for either team in a followed game, in one 3s screen.
The text rules use the two real missed kicks; the geometry uses ``football.demo._play`` (NYG home
kicking right, WSH away kicking left)."""

from __future__ import annotations

from itertools import pairwise

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_fgmiss as fm
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from test_football_director import started
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
MISS = "Field Goal Missed"
TEXT = "{} yard field goal is No Good, {}."


def kick(how, yards=40, start=60, offence="NYG"):
    return _play(MISS, TEXT.format(f"X.Y {yards}", how), start, start, offence, yards)


LEFT, RIGHT = kick("Wide Left"), kick("Wide Right")
SHORT, BLOCKED = kick("Short", 55, 45), kick("Blocked")
OTHER = kick("Doinked off the upright")
AWAY_LEFT = kick("Wide Left", 38, 40, "WSH")


def scene(play, share, event=None):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_event=event, fb_stage="play",
                 fb_elapsed=share * 3.0, fb_seconds=3.0, animating=True)  # fmt: skip


def draw(play, share, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share))
    assert not canvas.out_of_bounds
    return canvas


def ball(canvas):
    cells = [p for p, c in canvas.pixels.items() if c == fm.RED and p[1] >= 8]
    assert cells, "no ball"
    xs, ys = [x for x, _ in cells], [y for _, y in cells]
    return (min(xs) + max(xs)) // 2, max(ys)


def path(play, shares=None):
    return [ball(draw(play, s / 100)) for s in (shares or range(0, 100, 5))]


# -- the rules -----------------------------------------------------------------------


def test_it_is_registered_for_missed_kicks_and_takes_three_seconds():
    assert fp.PLAY_SCREENS[PlayKind.FIELD_GOAL_MISSED] is fm.draw_fg_miss
    assert (
        pacing.animation_seconds(LEFT, 3.0) == 3.0
        and pacing.PLAY_SECONDS[PlayKind.FIELD_GOAL_MISSED]
    )


@pytest.mark.parametrize(
    "label,kind,reason",
    [("fg_miss_left", "left", "WIDE LEFT"), ("fg_miss_right", "right", "WIDE RIGHT")],
)
def test_the_real_misses_are_read_from_the_text(label, kind, reason):
    s = scene(make_play(1, label, off="NYG"), 0)
    assert fm.miss_kind(s) == kind and fm.reason(s) == reason
    assert fm.label(s).startswith("NO GOOD ") and fm.label(s).endswith(" YD")


def test_short_blocked_and_unfamiliar_wording():
    assert fm.miss_kind(scene(SHORT, 0)) == "short" and fm.reason(scene(SHORT, 0)) == "SHORT"
    assert fm.miss_kind(scene(BLOCKED, 0)) == "blocked"
    assert fm.miss_kind(scene(OTHER, 0)) == "other"
    assert fm.reason(scene(OTHER, 0)) == "DOINKED OFF THE UPRIGHT", "the feed's own words"
    assert fm.label(scene(kick("Wide Left", 38), 0)) == "NO GOOD 38 YD"


# -- the animation -------------------------------------------------------------------


def test_the_ball_is_red_and_starts_at_the_kick_spot():
    pts = path(LEFT)
    assert abs(pts[0][0] - LAYOUT.px(60)) <= 1
    for share in (0.0, 0.3, 0.6, 1.0):
        assert fm.RED in draw(LEFT, share).pixels.values()


def test_wide_left_veers_up_and_wide_right_down_for_a_team_driving_right():
    left, right = path(LEFT)[-1], path(RIGHT)[-1]
    mid = round(LAYOUT.mid_y)
    assert left[1] < mid < right[1]
    assert left[0] > LAYOUT.px(100) and right[0] > LAYOUT.px(100), "it reaches the end zone"


def test_the_veer_flips_for_a_team_driving_left():
    away_left = path(AWAY_LEFT)[-1]
    assert away_left[1] > round(LAYOUT.mid_y), "the visitors' left is down the panel"
    assert away_left[0] < LAYOUT.px(0), "it reaches the home end zone"


def test_a_short_kick_comes_down_before_the_end_zone_and_a_blocked_one_falls_back():
    short_end = path(SHORT)[-1]
    assert LAYOUT.px(45) < short_end[0] < LAYOUT.px(100)
    blocked = path(BLOCKED)
    assert min(x for x, _ in blocked) < LAYOUT.px(60) - 1, "knocked back behind the line"
    assert min(y for _, y in blocked) < round(LAYOUT.mid_y) - 3, "up in the air first"


def test_the_ball_only_ever_moves_toward_where_it_ends_for_a_veering_kick():
    xs = [x for x, _ in path(LEFT, range(10, 75, 5))]
    assert all(b >= a - 1 for a, b in pairwise(xs))


def test_once_missed_the_picture_holds_until_the_end():
    assert draw(LEFT, 0.8).pixels == draw(LEFT, 1.0).pixels


def test_the_band_is_red_with_the_distance_on_the_left_and_the_reason_on_the_right():
    c = draw(LEFT, 1.0)
    band = [(x, col) for (x, y), col in c.pixels.items() if y < 8]
    assert band and {col for _, col in band} == {fm.RED}
    assert min(x for x, _ in band) < 5 and max(x for x, _ in band) > 110


def test_the_goalposts_are_at_the_end_zone_being_attacked_with_no_flash_or_celebration():
    c = draw(LEFT, 1.0)
    assert (255, 255, 255) not in c.pixels.values()
    assert [p for p, col in c.pixels.items() if col == (255, 225, 0) and p[0] >= LAYOUT.px(100)]


# -- the director --------------------------------------------------------------------


@pytest.mark.parametrize("favourite,kicker", [("NYG", "NYG"), ("NYG", "WSH"), ("DAL", "WSH")])
def test_either_teams_miss_is_the_same_single_stage_whoever_kicked(favourite, kicker):
    follow = ["NYG"] if favourite == "DAL" else []
    rig = started(make_play(1, "rush", off="NYG"), favourite=favourite, follow=follow)
    rig.poll(make_play(1, "rush", off="NYG"), make_play(2, "fg_miss_left", off=kicker))
    stages = rig.run()
    assert [s.stage for s in stages] == ["play", "playtext"]
    assert isinstance(stages[0].event, ev.FieldGoal) and not stages[0].event.made
    assert stages[0].seconds == 3.0


# -- sweeps and snapshots ------------------------------------------------------------


@pytest.mark.parametrize("play", [LEFT, RIGHT, SHORT, BLOCKED, OTHER, AWAY_LEFT],
                         ids=["left", "right", "short", "blocked", "other", "away"])  # fmt: skip
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.1, 0.3, 0.5, 0.7, 0.85, 1.0, 2.0])
def test_every_miss_draws_inside_the_panel_at_every_moment(play, width, share):
    c = draw(play, share, width)
    assert c.pixels
    assert all(
        y <= FIELD_BOTTOM + 1 for (x, y), col in c.pixels.items() if col == fm.RED and y >= 8
    )


@pytest.mark.parametrize("label", ["fg_miss_left", "fg_miss_right"])
@pytest.mark.parametrize("off", ["NYG", "WSH"])
def test_the_real_missed_kicks_draw_for_either_team(label, off):
    assert draw(make_play(1, label, off=off), 0.8).pixels


@pytest.mark.parametrize(
    "name,play,share,width",
    [("left", LEFT, 0.6, 128), ("right", RIGHT, 0.7, 128), ("short", SHORT, 0.7, 128),
     ("blocked", BLOCKED, 0.5, 128), ("away", AWAY_LEFT, 0.7, 128), ("left_64", LEFT, 0.7, 64)],
)  # fmt: skip
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"fg_miss_{name}", draw(play, share, width).render(), update_snapshots)
