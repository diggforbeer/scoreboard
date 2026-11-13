"""``fb_field``, the resting screen (#378): the field between plays, with its band.

The drawing primitives are tested in ``test_football_field.py``; this checks the screen built on
them: the markers' direction for each team, goal to go, the red-zone tint, the band, the 64px
layout, and which games rest on the field (a live one) rather than the text scoreboard.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FIELD_TOP, FieldLayout
from nhl_scoreboard.football.teams import TEAMS
from test_football_scenes import (
    Clock,
    Feed,
    H,
    check_snapshot,
    feed_mode,
    game,
    renderer,
)

NYG, WSH = TEAMS["NYG"].espn_id, TEAMS["WSH"].espn_id


def situation(yard, distance=10, down=1, offence="NYG", red=False, text=None):
    short = text or f"{down}{('st', 'nd', 'rd', 'th')[down - 1]} & {distance}"
    return {
        "down": down, "distance": distance, "yardLine": yard, "isRedZone": red,
        "downDistanceText": short, "shortDownDistanceText": short,
        "possession": str(TEAMS[offence].espn_id),
    }  # fmt: skip


def field(sit=None, width=128, **kw):
    """The ``fb_field`` screen for WSH (away, right) at NYG (home, left)."""
    g = game("WSH", "NYG", "in", 10, 17, situation=sit, **kw)
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_field(c, g)
    assert not c.out_of_bounds
    return c, FieldLayout.for_panel(width)


def column(c, layout, yard, color):
    """Rows of the field on ``yard``'s column lit in ``color``."""
    x = layout.px(yard)
    return [y for y in range(FIELD_TOP, FIELD_BOTTOM + 1) if c.pixels.get((x, y)) == color]


# -- the markers follow the offence ---------------------------------------------------------------


def test_the_home_team_drives_right_so_the_first_down_line_is_ahead_to_the_right():
    c, layout = field(situation(40, 10, offence="NYG"))
    assert len(column(c, layout, 40, ff.SCRIMMAGE)) >= layout.height - 4  # (the ball covers some)
    assert len(column(c, layout, 50, ff.FIRST_DOWN)) == layout.height
    assert (layout.px(40), layout.mid_y) in c.pixels and c.pixels[
        (layout.px(40) + 1, layout.mid_y)
    ] == ff.BALL


def test_the_away_team_drives_left_so_the_line_is_ahead_to_the_left():
    c, layout = field(situation(40, 10, offence="WSH"))
    assert len(column(c, layout, 30, ff.FIRST_DOWN)) == layout.height
    assert not column(c, layout, 50, ff.FIRST_DOWN)


def test_goal_to_go_puts_the_first_down_line_on_the_goal_line():
    c, layout = field(situation(95, 10, offence="NYG"))
    assert len(column(c, layout, 100, ff.FIRST_DOWN)) == layout.height
    c, layout = field(situation(4, 10, offence="WSH"))
    assert len(column(c, layout, 0, ff.FIRST_DOWN)) == layout.height


def test_no_situation_is_the_plain_field_with_no_markers_or_ball():
    c, _ = field(None)
    colors = {rgb for (x, y), rgb in c.pixels.items() if y >= FIELD_TOP}
    assert ff.SCRIMMAGE not in colors and ff.FIRST_DOWN not in colors and ff.BALL not in colors


def test_an_unknown_offence_still_shows_the_ball_but_no_markers():
    sit = {**situation(40), "possession": "9999"}
    c, _ = field(sit)
    colors = {rgb for (x, y), rgb in c.pixels.items() if y >= FIELD_TOP}
    assert ff.BALL in colors and ff.SCRIMMAGE not in colors and ff.FIRST_DOWN not in colors


# -- the red zone ---------------------------------------------------------------------------------


def tinted(c, layout, yard):
    return c.pixels.get((layout.px(yard), FIELD_TOP + 1)) == ff.RED_ZONE_TINT


def test_the_red_zone_is_tinted_in_front_of_the_goal_the_offence_attacks():
    c, layout = field(situation(88, 10, offence="NYG", red=True))
    assert tinted(c, layout, 85) and tinted(c, layout, 99) and not tinted(c, layout, 60)
    assert not tinted(c, layout, 5), "not the end the offence is leaving"
    c, layout = field(situation(12, 10, offence="WSH", red=True))
    assert tinted(c, layout, 15) and tinted(c, layout, 1) and not tinted(c, layout, 40)


def test_no_red_tint_outside_the_red_zone():
    c, layout = field(situation(88, 10, offence="NYG", red=False))
    assert not any(tinted(c, layout, y) for y in (5, 45, 85, 95))


# -- the band ---------------------------------------------------------------------------


def band_colors(c):
    return {rgb for (x, y), rgb in c.pixels.items() if y < FIELD_TOP}


def test_the_band_shows_the_clock_the_score_and_the_down(capsys):
    c, _ = field(situation(40, 10, offence="NYG"))
    colors = band_colors(c)
    assert ff.FIRST_DOWN not in colors  # (the field's marker colours are not the band's)
    from nhl_scoreboard.display import football_scenes as fs

    assert fs.LIVE in colors and fs.SITUATION in colors and fs.WHITE in colors


def test_the_band_turns_red_in_the_red_zone():
    from nhl_scoreboard.display import football_scenes as fs

    c, _ = field(situation(88, 10, offence="NYG", red=True))
    assert fs.RED_ZONE in band_colors(c) and fs.SITUATION not in band_colors(c)


@pytest.mark.parametrize(
    "detail,expected",
    [("12:24 - 3rd", "3RD 12:24"), ("2:01 - 4th", "4TH 2:01"), ("0:05 - 1st", "1ST 0:05"),
     ("15:00 - 2nd", "2ND 15:00"), ("Halftime", "HALFTIME")],
)  # fmt: skip
def test_the_band_clock_is_short_so_the_score_fits(detail, expected):
    from nhl_scoreboard.display import football_scenes as fs

    g = game("WSH", "NYG", "in", 0, 0, short=detail)
    assert fs.band_clock(g, renderer()) == expected


def test_goal_to_go_text_is_tightened_to_leave_room_for_the_score():
    from nhl_scoreboard.display import football_scenes as fs

    c, _ = field(situation(5, 5, offence="NYG", red=True, text="1st & Goal"))
    down = [x for (x, y), rgb in c.pixels.items() if y < FIELD_TOP and rgb == fs.RED_ZONE]
    score = [x for (x, y), rgb in c.pixels.items() if y < FIELD_TOP and rgb == fs.WHITE]
    assert min(down) > max(score) + 3, "the down and distance clears the score"


def test_the_band_never_draws_off_the_panel_even_with_long_text():
    c, _ = field(situation(40, 10, text="3rd & 10 at the opponent's 35 yard line"))
    assert not c.out_of_bounds


# -- 64px -------------------------------------------------------------------------------


def test_a_64px_panel_has_narrow_end_zones_no_score_and_a_compact_down():
    c, layout = field(situation(40, 7, down=2, offence="NYG"), width=64)
    assert layout.end_zone == 7 and len(column(c, layout, 40, ff.SCRIMMAGE)) >= layout.height - 4
    abbreviation_pixels = c.lit(0, FIELD_TOP, 6, FIELD_BOTTOM)

    tint = ff.team_rgb("NYG")
    assert set(abbreviation_pixels.values()) == {tuple(round(v * ff.END_ZONE_TINT) for v in tint)}
    wide, _ = field(situation(40, 7, down=2, offence="NYG"))
    assert len([p for p in c.pixels if p[1] < FIELD_TOP]) < len(
        [p for p in wide.pixels if p[1] < FIELD_TOP]
    )


# -- which games rest on the field ----------------------------------------------------------------


def rest_kind(state, **kw):
    clock = Clock()
    m = feed_mode(Feed([game("WSH", "NYG", state, 10, 17, **kw)]), clock)
    m.worker.poll_once()
    return m.scene().kind


def test_a_live_game_rests_on_the_field_and_everything_else_on_the_text_scoreboard():
    assert rest_kind("in", situation=situation(40)) == "fb_field"
    assert rest_kind("in") == "fb_field", "a live game with no situation yet (a kickoff)"
    assert rest_kind("in", short="Halftime", name="STATUS_HALFTIME") == "fb_halftime"
    assert rest_kind("post", short="Final", name="STATUS_FINAL") == "fb_scores"
    assert rest_kind("pre", short="x", name="STATUS_SCHEDULED") == "fb_scores"


# -- snapshots --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,sit,width",
    [
        ("home_drives", situation(40, 10, offence="NYG"), 128),
        ("away_red_zone", situation(12, 6, offence="WSH", red=True), 128),
        ("goal_to_go", situation(96, 4, down=1, offence="NYG", red=True, text="1st & Goal"), 128),
        ("no_situation", None, 128),
        ("home_drives_64", situation(40, 7, down=2, offence="NYG"), 64),
    ],
)
def test_snapshot(name, sit, width, update_snapshots):
    c, _ = field(sit, width)
    check_snapshot(f"fb_field_{name}", c.render(), update_snapshots)
