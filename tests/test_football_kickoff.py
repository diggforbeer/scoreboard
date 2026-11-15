"""``Kickoff`` (#382): the tee, the high arc, the landing, then the return or the touchback.

Geometry plays are built with ``football.demo._play`` (NYG home on the left, WSH away on the
right) so the spots are exact; the real kickoffs in ``play_cases.json`` (a return, a touchback,
an onside kick, one with a penalty, one with a lateral) are swept for stray pixels.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_kickoff as fk
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout, lane_y
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
RETURNER = Person("returner", 4, "D. Meyers", "11", "WR", True)
RETURN_TEXT = (
    "N.Folk kicks 60 yards from NYG 35 to WSH 5. D.Meyers to WSH 25 for 20 yards (N.Muse)."
)
# NYG (home) kicks to WSH, who return it to their 25 (yard 75).
RETURN = _play("Kickoff", RETURN_TEXT, 35, 75, "NYG", 0, end_team="WSH")
TOUCHBACK = _play(
    "Kickoff", "A.Szmyt kicks 65 yards from WSH 35 to end zone, Touchback to the NYG 35.",
    65, 35, "WSH", 0, end_team="NYG",
)  # fmt: skip
ONSIDE = _play(
    "Kickoff", "N.Folk kicks onside 19 yards from NYG 35 to WSH 46. M.Nabers to WSH 46, no gain.",
    35, 54, "NYG", 0, end_team="WSH",
)  # fmt: skip


def scene(play, share, people=(RETURNER,)):
    seconds = pacing.animation_seconds(play, 3.0)
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=share * seconds, fb_seconds=seconds, animating=True)  # fmt: skip


def draw(play, share, people=(RETURNER,), width=128):
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


# -- the rules -------------------------------------------------------------------------------------


def test_a_return_takes_five_seconds_and_a_touchback_or_an_onside_kick_four():
    assert pacing.animation_seconds(RETURN, 3.0) == 5.0
    assert pacing.animation_seconds(TOUCHBACK, 3.0) == 4.0
    assert pacing.animation_seconds(ONSIDE, 3.0) == 4.0
    assert PlayKind.KICKOFF in pacing.PLAY_SECONDS, "registered where the director can see it"


def test_the_kicking_team_decides_the_direction_and_a_missing_team_falls_back_to_the_tee():
    game = make_game()
    assert fk.kicker_direction(RETURN, game) == 1, "the home team kicks toward yard 100"
    assert fk.kicker_direction(TOUCHBACK, game) == -1
    blank = _play("Kickoff", "x", 65, 35, "NYG", 0)
    object.__setattr__(blank, "start", None)
    object.__setattr__(blank.end, "team_id", None) if blank.end else None
    assert fk.kicker_direction(blank, game) in (1, -1)


def test_the_ball_comes_down_where_the_kick_distance_says_whatever_team_names_the_text_uses():
    assert fk.landing_spot(RETURN, 35, 1, 75) == 95
    assert fk.landing_spot(TOUCHBACK, 65, -1, 35) == -fk.END_ZONE_DEPTH
    assert fk.landing_spot(RETURN, 35, 1, 75) == 95
    assert fk.landing_spot(make_play(1, "kickoff_touchback", off="NYG"), 35, 1, 35) == 105
    unknown = _play("Kickoff", "Kickoff.", 35, 60, "NYG", 0)
    assert fk.landing_spot(unknown, 35, 1, 60) == 60, "nothing printed: it goes to the end spot"
    far = _play("Kickoff", "X.Y kicks 90 yards from NYG 35 to WSH 0.", 35, 60, "NYG", 0)
    assert fk.landing_spot(far, 35, 1, 60) == 100, "clamped to the goal line"


def test_the_label_follows_the_kick():
    assert fk.kick_label(scene(RETURN, 0.2), 0.2) == ("KICKOFF 60 YD", fp.NEUTRAL)
    assert fk.kick_label(scene(RETURN, 0.7), 0.7) == ("RETURN 20 YD", fp.GAIN)
    assert fk.kick_label(scene(TOUCHBACK, 0.7), 0.7) == ("TOUCHBACK", fp.NEUTRAL)
    assert fk.kick_label(scene(ONSIDE, 0.2), 0.2)[0] == "ONSIDE KICK 19 YD"
    stuck = _play("Kickoff", "A.B kicks 60 yards from NYG 35 to WSH 5. C.D to WSH 4 for -1 yards.",
                  35, 74, "NYG", 0, end_team="WSH")  # fmt: skip
    assert fk.kick_label(scene(stuck, 0.7), 0.7) == ("RETURN -1 YD", fp.LOSS)


def test_the_returners_number_falls_back_to_the_name_in_the_text():
    assert fk.returner_label(scene(RETURN, 0.7)) == "11"
    assert fk.returner_label(scene(RETURN, 0.7, ())) == "MEYERS"
    assert fk.returner_label(scene(TOUCHBACK, 0.7, ())) == ""


# -- the animation -------------------------------------------------------------------------


def test_the_ball_starts_on_the_tee_flies_to_the_landing_spot_and_is_returned_to_the_end_spot():
    pts = path(RETURN)
    assert abs(pts[0][0] - LAYOUT.px(35)) <= 1
    flight = [x for x, _ in pts[3:12]]
    assert flight == sorted(flight) and abs(pts[13][0] - LAYOUT.px(95)) <= 2, "down at WSH 5"
    assert abs(pts[-1][0] - LAYOUT.px(75)) <= 1, "returned to the 25"
    back = [x for x, _ in pts[15:]]
    assert back == sorted(back, reverse=True), "and it runs back toward its own goal"


def test_a_kick_hangs_high_in_the_middle_of_the_flight_and_stays_on_the_field():
    rows = [y for _, y in path(RETURN, range(8, 52, 3))]
    tee_y = round(lane_y("middle", 1, LAYOUT))
    assert min(rows) <= tee_y - 6, "a high arc"
    assert min(rows) >= 8, "never into the band"


def test_an_onside_kick_is_a_low_line_drive_even_next_to_a_normal_kick_of_the_same_length():
    normal = _play("Kickoff", "N.Folk kicks 19 yards from NYG 35 to WSH 46. M.Nabers to WSH 46.",
                   35, 54, "NYG", 0, end_team="WSH")  # fmt: skip
    top = lambda p: min(y for _, y in path(p, range(8, 52, 3)))  # noqa: E731
    assert top(ONSIDE) > top(normal)


def test_a_kick_by_the_away_team_travels_left_and_a_touchback_steps_out_of_the_end_zone():
    pts = path(TOUCHBACK)
    flight = [x for x, _ in pts[3:12]]
    assert flight == sorted(flight, reverse=True)
    assert pts[13][0] < LAYOUT.px(0), "it came down in the home end zone"
    stepped = [x for x, _ in pts[14:]]
    assert stepped == sorted(stepped) and abs(pts[-1][0] - LAYOUT.px(35)) <= 1, "out to the 35"


def test_the_returners_number_runs_with_the_ball_and_a_touchback_has_none():
    ran = draw(RETURN, 0.75)
    whites = [p for p, c in ran.pixels.items() if c == fp.WHITE]
    bx, _ = ball(ran)
    assert whites and all(abs(x - bx) <= 8 for x, _ in whites)
    tb = draw(TOUCHBACK, 0.7, ())
    assert not [p for p, c in tb.pixels.items() if c == fp.WHITE]


def test_the_markers_appear_only_when_the_ball_has_settled_at_the_end_spot():
    nx = LAYOUT.px(75)
    col = lambda c, x: any(c.pixels.get((x, y)) == ff.SCRIMMAGE for y in range(8, 31))  # noqa: E731
    assert not col(draw(RETURN, 0.3), nx) and not col(draw(RETURN, 0.7), nx)
    assert col(draw(RETURN, 1.0), nx)


def test_a_penalty_changes_where_it_ends_not_the_printed_return():
    held = _play(
        "Kickoff", RETURN_TEXT, 35, 65, "NYG", 0, end_team="WSH"
    )  # ... but ended on the 35
    assert abs(path(held)[-1][0] - LAYOUT.px(65)) <= 1
    assert fk.kick_label(scene(held, 0.7), 0.7)[0] == "RETURN 20 YD"


def test_a_trail_follows_the_returner():
    c = draw(RETURN, 0.8)
    row = round(lane_y("middle", 1, LAYOUT))
    greys = [
        x for x in range(70, 118) if c.pixels.get((x, row)) and len(set(c.pixels[(x, row)])) == 1
    ]
    assert len(greys) >= 5


REAL = [
    "kickoff_return",
    "kickoff_touchback",
    "kickoff_onside",
    "kickoff_penalty",
    "kickoff_lateral",
]


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("off,end", [("NYG", "WSH"), ("WSH", "NYG")])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.2, 0.4, 0.52, 0.6, 0.8, 0.95, 1.0, 2.0])
def test_every_real_kickoff_draws_inside_the_panel_at_every_moment(label, off, end, width, share):
    play = make_play(1, label, off=off, end=end)
    c = draw(play, share, width=width)
    assert c.pixels and all(
        y <= FIELD_BOTTOM + 1 for (x, y), col in c.pixels.items() if col == ff.BALL
    )


def test_it_is_registered_for_kickoffs():
    assert fp.PLAY_SCREENS[PlayKind.KICKOFF] is fk.draw_kickoff


# -- snapshots -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("air", RETURN, 0.3, 128),
        ("return", RETURN, 0.75, 128),
        ("touchback", TOUCHBACK, 0.7, 128),
        ("onside", ONSIDE, 0.3, 128),
        ("air_64", RETURN, 0.3, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"kickoff_{name}", draw(play, share, width=width).render(), update_snapshots)
