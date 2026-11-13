"""The static football field (#358): turf, end zones, yard lines, logos, markers and the ball.

ASCII snapshots (``--update-snapshots`` after an intentional change) plus structural assertions
that hold whatever the snapshot says. Logos are synthetic discs; no network and no artwork.
"""

from __future__ import annotations

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoSet
from nhl_scoreboard.football.geometry import (
    AWAY,
    FIELD_BOTTOM,
    FIELD_TOP,
    HOME,
    FieldLayout,
    first_down_line,
)
from nhl_scoreboard.football.teams import team_color
from test_football_events import make_game
from test_football_scenes import check_snapshot, renderer

H = 32
WIDE = FieldLayout.for_panel(128)
NARROW = FieldLayout.for_panel(64)


@pytest.fixture
def logos(tmp_path, monkeypatch):
    """Synthetic NFL logos at 12px, found through the environment variable the library reads."""
    write_synthetic_nfl_logos(tmp_path)
    monkeypatch.setenv("NHL_SCOREBOARD_NFL_LOGO_DIR", str(tmp_path / "nfl" / "12" / "dark"))
    return LogoSet("nfl", "dark")


def draw(width=128, possession=HOME, logos=None, yard=28, distance=7, ball=True, markers=True,
         home="NYG", away="WSH", layout=None):  # fmt: skip
    c = AsciiCanvas(width, H)
    r = renderer(width)
    layout = layout or FieldLayout.for_panel(width)
    ff.draw_field(r, c, layout, home, away, possession, logos=logos)
    if markers:
        ff.draw_markers(r, c, layout, yard, distance, possession or HOME)
    if ball:
        ff.draw_ball(c, layout, yard)
    return c, layout


def show(name, c):
    art = c.render()
    print(f"\n[{name}]\n{art}")
    return art


def scale(color, k):
    return tuple(round(v * k) for v in color)


# -- the layout constants, mirrored from football_field.py: change both together -----------------


def test_the_colours_and_sizes():
    assert ff.TURF == (0, 52, 16) and ff.YARD_LINE == (0, 104, 40) and ff.MID_FIELD == (0, 150, 60)
    assert ff.SCRIMMAGE == (70, 130, 255) and ff.FIRST_DOWN == (255, 225, 0)
    assert ff.BALL == (214, 130, 54) and ff.END_ZONE_TINT == 0.30 and ff.DIM_LOGO == 0.45
    assert ff.END_ZONE_LOGO_SIZE == 12


# -- snapshots -----------------------------------------------------------------------------------


CASES = {
    "fb_field_128_home": dict(width=128, possession=HOME, logos=True),
    "fb_field_128_away": dict(width=128, possession=AWAY, logos=True, yard=77, distance=10),
    "fb_field_128_plain": dict(width=128, possession=None, logos=True, ball=False, markers=False),
    "fb_field_128_no_logos": dict(width=128, possession=HOME, logos=False),
    "fb_field_64_home": dict(width=64, possession=HOME, logos=True),
    "fb_field_64_away": dict(width=64, possession=AWAY, logos=True, yard=77, distance=10),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_field_snapshots_and_nothing_off_the_panel(name, logos, update_snapshots):
    spec = dict(CASES[name])
    spec["logos"] = logos if spec["logos"] else None
    c, layout = draw(**spec)
    art = show(name, c)
    assert not c.out_of_bounds, "nothing may be drawn off the panel"
    assert c.row_is_solid(layout.top) and c.row_is_solid(layout.bottom), "turf reaches both edges"
    assert not c.lit(0, 0, layout.right - 1, layout.top - 1), (
        "the band above the field is left alone"
    )
    assert not c.lit(0, layout.bottom + 1, layout.right - 1, H - 1)
    check_snapshot(name, art, update_snapshots)


def test_a_field_in_the_left_half_of_a_wide_panel_stays_in_its_half(logos, update_snapshots):
    """The play-text layout puts the field in the left 64px."""
    layout = FieldLayout.for_panel(128, 0, 64)
    c, _ = draw(width=128, logos=logos, layout=layout)
    art = show("fb_field_region_left_half", c)
    assert not c.out_of_bounds and not c.lit(64, 0, 127, H - 1), "nothing right of the region"
    assert c.bbox().x0 == 0 and c.bbox().x1 == 63
    check_snapshot("fb_field_region_left_half", art, update_snapshots)


# -- the turf, the end zones and the lines -------------------------------------------------------


def test_turf_fills_the_field_and_the_end_zones_are_tinted_in_the_team_colours(logos):
    c, _ = draw(logos=logos, ball=False, markers=False)
    home_tint, away_tint = scale(team_color("NYG"), 0.30), scale(team_color("WSH"), 0.30)
    assert c.lit(0, FIELD_TOP, 0, FIELD_TOP)[(0, FIELD_TOP)] == home_tint  # the home end zone, left
    assert c.lit(127, FIELD_TOP, 127, FIELD_TOP)[(127, FIELD_TOP)] == away_tint
    assert c.lit(20, FIELD_TOP + 1, 20, FIELD_TOP + 1)[(20, FIELD_TOP + 1)] == ff.TURF


def test_yard_lines_every_ten_with_brighter_goal_lines_and_midfield(logos):
    c, _ = draw(logos=logos, ball=False, markers=False)
    y = FIELD_TOP + 1
    for yard in (10, 20, 30, 40, 60, 70, 80, 90):
        assert c.lit(WIDE.px(yard), y, WIDE.px(yard), y)[(WIDE.px(yard), y)] == ff.YARD_LINE
    for yard in (0, 50, 100):
        assert c.lit(WIDE.px(yard), y, WIDE.px(yard), y)[(WIDE.px(yard), y)] == ff.MID_FIELD
    assert WIDE.px(50) == 64


def test_hash_marks_between_the_lines(logos):
    c, _ = draw(logos=logos, ball=False, markers=False)
    for yard in (5, 15, 55, 95):
        for y in (FIELD_TOP + 3, FIELD_BOTTOM - 3):
            assert c.lit(WIDE.px(yard), y, WIDE.px(yard), y)[(WIDE.px(yard), y)] == ff.YARD_LINE


# -- the end-zone logos --------------------------------------------------------------------------


def disc_color(abbrev):
    return team_color(abbrev)  # the synthetic logo is a disc in the team's colour


def logo_pixels(c, side, layout=WIDE):
    first, last = layout.end_zone_columns(side)
    tint = None
    return {p: rgb for p, rgb in c.lit(first, FIELD_TOP, last, FIELD_BOTTOM).items() if rgb != tint}


def test_the_team_with_the_ball_has_its_logo_bright_and_the_other_is_dimmed(logos):
    c, _ = draw(logos=logos, possession=HOME)
    home = c.colors(0, FIELD_TOP, 13, FIELD_BOTTOM)
    away = c.colors(114, FIELD_TOP, 127, FIELD_BOTTOM)
    assert disc_color("NYG") in home, "the home logo, full brightness"
    assert scale(disc_color("WSH"), ff.DIM_LOGO) in away and disc_color("WSH") not in away
    # And the other way round.
    c, _ = draw(logos=logos, possession=AWAY)
    assert disc_color("WSH") in c.colors(114, FIELD_TOP, 127, FIELD_BOTTOM)
    assert scale(disc_color("NYG"), ff.DIM_LOGO) in c.colors(0, FIELD_TOP, 13, FIELD_BOTTOM)


def test_with_nobody_in_possession_both_logos_are_bright(logos):
    c, _ = draw(logos=logos, possession=None, markers=False, ball=False)
    assert disc_color("NYG") in c.colors(0, FIELD_TOP, 13, FIELD_BOTTOM)
    assert disc_color("WSH") in c.colors(114, FIELD_TOP, 127, FIELD_BOTTOM)


def test_a_logo_is_12px_and_centred_in_its_end_zone(logos):
    c, _ = draw(logos=logos, possession=HOME, markers=False, ball=False)
    tint = scale(team_color("NYG"), 0.30)
    lit = [
        p for p, rgb in c.lit(0, FIELD_TOP, 13, FIELD_BOTTOM).items() if rgb == disc_color("NYG")
    ]
    xs, ys = [x for x, _ in lit], [y for _, y in lit]
    assert (max(xs) - min(xs) + 1, max(ys) - min(ys) + 1) == (12, 12)
    assert min(xs) == 1 and max(xs) == 12, "centred in the 14px end zone"
    assert abs((min(ys) + max(ys)) / 2 - WIDE.mid_y) <= 1, "vertically centred on the field"
    assert tint not in {c.lit(x, y, x, y)[(x, y)] for x, y in lit}


def test_a_missing_logo_falls_back_to_the_abbreviation_in_the_team_colour(logos):
    c, _ = draw(logos=None, possession=HOME, markers=False, ball=False)
    home = c.lit(0, FIELD_TOP, 13, FIELD_BOTTOM)
    tint = scale(team_color("NYG"), 0.30)
    text = {p: rgb for p, rgb in home.items() if rgb != tint}
    assert text and set(text.values()) == {team_color("NYG")}, "NYG in its own colour"
    assert min(x for x, _ in text) >= 1 and max(x for x, _ in text) <= 12
    # (column 114 is the away goal line, which belongs to its end-zone columns)
    away = c.colors(115, FIELD_TOP, 127, FIELD_BOTTOM) - {scale(team_color("WSH"), 0.30)}
    assert away == {scale(team_color("WSH"), ff.DIM_LOGO)}, "the other team's abbreviation, dimmed"


def test_an_unknown_team_is_drawn_plain_without_asking_for_a_logo(logos):
    c, _ = draw(logos=logos, home="AFC", away="NFC", markers=False, ball=False)
    assert ff.UNKNOWN_TEAM in c.colors(0, FIELD_TOP, 13, FIELD_BOTTOM)
    assert not c.out_of_bounds


def test_a_64px_field_has_no_logo_and_no_text_in_its_7px_end_zones(logos):
    c, _ = draw(width=64, logos=logos)
    assert c.colors(0, FIELD_TOP, 6, FIELD_BOTTOM) == {scale(team_color("NYG"), 0.30)}
    # (column 57 is the away goal line)
    assert c.colors(58, FIELD_TOP, 63, FIELD_BOTTOM) == {scale(team_color("WSH"), 0.30)}


# -- the markers and the ball --------------------------------------------------------------------


def test_the_scrimmage_and_first_down_lines_follow_the_direction_of_play(logos):
    y = FIELD_TOP + 1
    c, _ = draw(logos=logos, possession=HOME, yard=28, distance=7, ball=False)
    assert c.lit(WIDE.px(28), y, WIDE.px(28), y)[(WIDE.px(28), y)] == ff.SCRIMMAGE
    assert c.lit(WIDE.px(35), y, WIDE.px(35), y)[(WIDE.px(35), y)] == ff.FIRST_DOWN
    # The away team drives the other way: the same distance puts the line on the other side.
    c, _ = draw(logos=logos, possession=AWAY, yard=77, distance=10, ball=False)
    assert c.lit(WIDE.px(77), y, WIDE.px(77), y)[(WIDE.px(77), y)] == ff.SCRIMMAGE
    assert c.lit(WIDE.px(67), y, WIDE.px(67), y)[(WIDE.px(67), y)] == ff.FIRST_DOWN
    assert WIDE.px(67) < WIDE.px(77), "toward the home end zone, on the left"


def test_goal_to_go_puts_the_first_down_line_on_the_goal_line(logos):
    y = FIELD_TOP + 1
    c, _ = draw(logos=logos, possession=HOME, yard=95, distance=10, ball=False)
    assert first_down_line(95, 10, 1) == 100
    assert c.lit(WIDE.px(100), y, WIDE.px(100), y)[(WIDE.px(100), y)] == ff.FIRST_DOWN


def test_markers_span_the_whole_height_of_the_field(logos):
    c, _ = draw(logos=logos, yard=28, distance=7, ball=False)
    for row in range(FIELD_TOP, FIELD_BOTTOM + 1):
        assert c.lit(WIDE.px(28), row, WIDE.px(28), row)[(WIDE.px(28), row)] == ff.SCRIMMAGE


def test_draw_field_can_place_the_markers_itself(logos):
    c = AsciiCanvas(128, H)
    ff.draw_field(renderer(), c, WIDE, "NYG", "WSH", HOME, logos=logos, scrimmage=40, first_down=50)
    y = FIELD_TOP + 1
    assert c.lit(WIDE.px(40), y, WIDE.px(40), y)[(WIDE.px(40), y)] == ff.SCRIMMAGE
    assert c.lit(WIDE.px(50), y, WIDE.px(50), y)[(WIDE.px(50), y)] == ff.FIRST_DOWN


def test_the_ball_is_a_3x2_dot_with_a_highlight_on_the_middle_row_by_default():
    c = AsciiCanvas(128, H)
    ff.draw_ball(c, WIDE, 28)
    bx, by = WIDE.px(28), WIDE.mid_y
    body = {(bx + dx, by + dy) for dx in (-1, 0, 1) for dy in (0, 1)}
    assert body <= set(c.pixels) and all(c.pixels[p] == ff.BALL for p in body)
    assert c.pixels[(bx, by - 1)] == scale(ff.BALL, 0.7) and len(c.pixels) == 7


def test_the_ball_can_be_lifted_off_the_ground_for_an_arc():
    c = AsciiCanvas(128, H)
    ff.draw_ball(c, WIDE, 40, y=12.4, color=(255, 0, 0))
    assert c.pixels[(WIDE.px(40), 12)] == (255, 0, 0) and (WIDE.px(40), WIDE.mid_y) not in c.pixels


def test_the_ball_stays_on_the_panel_at_both_goal_lines():
    for yard in (0, 100):
        c = AsciiCanvas(128, H)
        ff.draw_ball(c, WIDE, yard)
        assert not c.out_of_bounds


def test_possession_of_maps_an_espn_team_id_to_a_side():
    game = make_game("WSH", "NYG")
    assert ff.possession_of(game, 19) == HOME and ff.possession_of(game, 28) == AWAY
    assert ff.possession_of(game, None) is None


# -- everything goes through SetPixel ------------------------------------------------------------


def test_nothing_uses_set_image(logos):
    c, _ = draw(logos=logos)
    assert not hasattr(c, "SetImage"), "the recording canvas has none: drawing must not need one"
    assert c.pixels, "and the field still drew"
