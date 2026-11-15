"""The pure field geometry (#358): yards to pixels, direction, first-down line, lanes, arcs.

No canvas and no renderer here: this is the maths every field screen shares.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.football import geometry as g
from nhl_scoreboard.football.geometry import AWAY, HOME, FieldLayout
from test_football_events import make_game

WIDE = FieldLayout.for_panel(128)
NARROW = FieldLayout.for_panel(64)


# -- the layout constants, mirrored from geometry.py: change both together -----------------------


def test_the_layout_constants():
    assert (g.FIELD_TOP, g.FIELD_BOTTOM) == (8, 30)
    assert (g.EZ_WIDE, g.EZ_NARROW, g.WIDE_MIN_WIDTH) == (14, 7, 112)
    assert g.LANE_MARGIN == 2


# -- yards and pixels ----------------------------------------------------------------------------


def test_on_a_128px_panel_100_yards_are_exactly_100_pixels():
    assert (WIDE.end_zone, WIDE.x0, WIDE.span) == (14, 14, 100)
    assert WIDE.pixels_per_yard == 1.0
    for yard in (0, 1, 28, 50, 77, 99, 100):
        assert WIDE.x(yard) == 14 + yard
    assert (WIDE.px(0), WIDE.px(50), WIDE.px(100)) == (14, 64, 114)


def test_on_a_64px_panel_the_end_zones_are_7px_and_a_yard_is_half_a_pixel():
    assert (NARROW.end_zone, NARROW.x0, NARROW.span) == (7, 7, 50)
    assert NARROW.pixels_per_yard == 0.5
    assert (NARROW.px(0), NARROW.px(50), NARROW.px(100)) == (7, 32, 57)


def test_the_end_zones_sit_at_each_end_and_never_overlap_the_field():
    assert WIDE.end_zone_columns(HOME) == (0, 13)
    assert WIDE.end_zone_columns(AWAY) == (114, 127)
    assert NARROW.end_zone_columns(HOME) == (0, 6) and NARROW.end_zone_columns(AWAY) == (57, 63)
    with pytest.raises(ValueError):
        WIDE.end_zone_columns("both")


def test_a_region_of_a_wider_panel_gets_the_same_rules():
    left_half = FieldLayout.for_panel(128, 0, 64)
    right_half = FieldLayout.for_panel(128, 64, 128)
    assert (left_half.end_zone, left_half.x0, left_half.span) == (7, 7, 50)
    assert (right_half.end_zone, right_half.x0, right_half.span) == (7, 71, 50)
    assert right_half.px(100) == 121 and right_half.end_zone_columns(AWAY) == (121, 127)


def test_the_wide_end_zone_starts_at_112_pixels():
    assert FieldLayout.for_panel(112).end_zone == 14 and FieldLayout.for_panel(111).end_zone == 7
    assert FieldLayout.for_panel(112).span == 84


@pytest.mark.parametrize("layout", [WIDE, NARROW, FieldLayout.for_panel(128, 64, 128)])
def test_yards_and_columns_invert_each_other(layout):
    for yard in (0, 12.5, 50, 99):
        assert layout.yard_at(layout.x(yard)) == pytest.approx(yard)


def test_the_rows():
    assert (WIDE.top, WIDE.bottom, WIDE.height, WIDE.mid_y) == (8, 30, 23, 19)
    assert (WIDE.left, WIDE.right, WIDE.width) == (0, 128, 128)


# -- which way a team drives ---------------------------------------------------------------------


def test_the_home_team_drives_right_and_the_away_team_left():
    assert g.drive_direction(HOME) == 1 and g.drive_direction(AWAY) == -1
    with pytest.raises(ValueError):
        g.drive_direction("nobody")


def test_the_first_down_line_is_ahead_of_the_ball_in_the_direction_of_play():
    assert g.first_down_line(28, 7, g.drive_direction(HOME)) == 35  # NYG (home) at its own 28
    assert g.first_down_line(77, 10, g.drive_direction(AWAY)) == 67  # WSH (away) driving left
    assert g.first_down_line(50, 10, 1) == 60 and g.first_down_line(50, 10, -1) == 40


def test_in_goal_to_go_the_marker_is_the_goal_line_itself():
    assert g.first_down_line(95, 10, 1) == 100 and g.first_down_line(4, 10, -1) == 0
    assert g.goal_to_go(95, 10, 1) and g.goal_to_go(4, 10, -1) and g.goal_to_go(90, 10, 1)
    assert not g.goal_to_go(80, 10, 1) and not g.goal_to_go(20, 10, -1)


def test_a_yard_line_is_clamped_to_the_field():
    assert (
        g.clamp_yard_line(-3) == 0 and g.clamp_yard_line(104) == 100 and g.clamp_yard_line(42) == 42
    )


def test_yard_line_is_from_the_home_goal_line_whoever_has_the_ball():
    """ESPN's "WSH 20" for the away team is yard line 80, "NYG 25" for the home team is 25."""
    assert WIDE.px(80) - WIDE.px(25) == 55  # the two spots, on a panel with NYG at the left
    assert WIDE.px(25) < WIDE.px(80), "the home team's own side is the left"


def test_the_team_with_the_ball_from_its_espn_id():
    game = make_game("WSH", "NYG")  # home NYG = 19, away WSH = 28
    assert g.possession_side(game, 19) == HOME and g.possession_side(game, 28) == AWAY
    assert g.possession_side(game, 99) is None and g.possession_side(game, None) is None


# -- lanes ---------------------------------------------------------------------------------------


def test_the_middle_is_the_middle_of_the_field():
    centre = (WIDE.top + g.LANE_MARGIN + WIDE.bottom - g.LANE_MARGIN) / 2
    assert g.lane_y("up the middle", 1, WIDE) == centre == g.lane_y("middle", -1, WIDE)


def test_left_is_up_the_panel_when_driving_right_and_down_when_driving_left():
    """The offence faces the goal it attacks, so its left hand is north when it faces east."""
    assert g.lane_y("left", 1, WIDE) < g.lane_y("middle", 1, WIDE) < g.lane_y("right", 1, WIDE)
    assert g.lane_y("left", -1, WIDE) > g.lane_y("middle", -1, WIDE) > g.lane_y("right", -1, WIDE)
    for name in (
        "left end",
        "left tackle",
        "left guard",
        "right guard",
        "right tackle",
        "right end",
    ):
        assert g.lane_y(name, 1, WIDE) + g.lane_y(name, -1, WIDE) == pytest.approx(
            2 * g.lane_y("middle", 1, WIDE)
        ), "driving the other way mirrors every lane"


def test_the_run_gaps_are_in_order_across_the_field():
    gaps = ["left end", "left tackle", "left guard", "up the middle", "right guard",
            "right tackle", "right end"]  # fmt: skip
    ys = [g.lane_y(gap, 1, WIDE) for gap in gaps]
    assert ys == sorted(ys) and len(set(ys)) == 7


def test_every_lane_stays_inside_the_field():
    for lane in [*g.LANES, 0.0, 1.0]:
        for direction in (1, -1):
            for layout in (WIDE, NARROW):
                y = g.lane_y(lane, direction, layout)
                assert layout.top + g.LANE_MARGIN <= y <= layout.bottom - g.LANE_MARGIN


def test_an_unknown_lane_goes_up_the_middle_and_a_fraction_is_clamped():
    assert g.lane_y("around the corner", 1, WIDE) == g.lane_y("middle", 1, WIDE)
    assert g.lane_y(5.0, 1, WIDE) == g.lane_y(1.0, 1, WIDE) and g.lane_y(-2, 1, WIDE) == g.lane_y(
        0.0, 1, WIDE
    )


# -- arcs ----------------------------------------------------------------------------------------


def test_an_arc_starts_and_ends_on_the_ground_and_peaks_in_the_middle():
    assert g.arc_point(10, 90, 20, 12, 0) == (10, 20)
    assert g.arc_point(10, 90, 20, 12, 1) == (90, 20)
    x, y = g.arc_point(10, 90, 20, 12, 0.5)
    assert (x, y) == (50, 8), "12 pixels above the base at the middle"


def test_an_arc_is_symmetric_and_t_is_clamped():
    a = g.arc_point(0, 100, 30, 10, 0.25)
    b = g.arc_point(0, 100, 30, 10, 0.75)
    assert a[1] == b[1] and a[0] + b[0] == 100
    assert g.arc_point(0, 100, 30, 10, -1) == (0, 30) and g.arc_point(0, 100, 30, 10, 9) == (
        100,
        30,
    )


def test_an_arc_works_right_to_left_too():
    assert g.arc_point(90, 10, 20, 12, 0.5) == (50, 8)
    xs = [x for x, _ in g.arc_points(90, 10, 20, 12)]
    assert xs == sorted(xs, reverse=True) and xs[0] == 90 and xs[-1] == 10


def test_a_longer_kick_arcs_higher_within_limits():
    assert g.arc_height(10) < g.arc_height(40) < g.arc_height(60)
    assert (
        g.arc_height(0) == 3.0
        and g.arc_height(1000) == 14.0
        and g.arc_height(-40) == g.arc_height(40)
    )


def test_the_points_along_an_arc_are_about_one_a_pixel_and_can_be_set():
    pts = g.arc_points(0, 100, 30, 10)
    assert len(pts) == 101 and pts[0] == (0, 30) and pts[-1] == (100, 30)
    assert len(g.arc_points(0, 100, 30, 10, steps=4)) == 5
    assert len(g.arc_points(0, 3, 30, 5)) == 9, "never fewer than 8 steps"
