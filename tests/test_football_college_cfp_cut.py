"""The playoff cut on the CFP rankings screen (#585): a one-pixel line after the last team in the
field, the field size a setting (``[football] cfp_field``, 12 by default, held to 4-16)."""

from __future__ import annotations

import logging

import pytest

from scoreboard.config import CFP_FIELD_MAX, CFP_FIELD_MIN, FootballConfig
from scoreboard.display import college_idle as ci
from scoreboard.football.college_views import build_ap, build_cfp
from scoreboard.football.scroll import ROW_HEIGHT, scroll_range
from test_football_college_ap import ctx, draw
from test_football_scenes import H, check_snapshot

LINE = ci.CUT_LINE


def line_rows(canvas):
    """The panel rows that hold the cut line: any row with a run of its colour."""
    rows = {}
    for (x, y), rgb in canvas.pixels.items():
        if rgb == LINE and 0 <= y < H:
            rows.setdefault(y, []).append(x)
    return rows


# -- the setting ----------------------------------------------------------------------------------


def test_the_field_defaults_to_the_twelve_team_playoff():
    assert FootballConfig().cfp_field == 12


@pytest.mark.parametrize(
    ("value", "kept"),
    [(12, 12), (4, 4), (16, 16), (3, 4), (0, 4), (-5, 4), (17, 16), (99, 16), ("8", 8)],
)
def test_the_field_is_held_to_its_bounds(value, kept):
    assert (CFP_FIELD_MIN, CFP_FIELD_MAX) == (4, 16)
    assert FootballConfig(cfp_field=value).cfp_field == kept


def test_a_field_that_is_not_a_number_warns_and_falls_back(caplog):
    with caplog.at_level(logging.WARNING):
        assert FootballConfig(cfp_field="twelve").cfp_field == 12
    assert "cfp_field" in caplog.text


# -- the view -------------------------------------------------------------------------------------


def test_the_committees_view_carries_the_cut_and_the_aps_has_none():
    assert build_cfp(ctx("TEX")).cut == 12
    assert build_cfp(ctx("TEX", cfp_field=8)).cut == 8
    assert build_ap(ctx("TEX", cfp_field=8)).cut == 0, "the AP has no playoff"


# -- the drawing ----------------------------------------------------------------------------------


def test_the_line_is_one_pixel_between_the_last_team_in_and_the_first_out():
    view = build_cfp(ctx("TEX", cfp_field=4))
    c = draw(view, 0)
    rows = line_rows(c)
    assert list(rows) == [4 * ROW_HEIGHT - 1], "one row, under the fourth team"
    xs = sorted(rows[4 * ROW_HEIGHT - 1])
    assert xs == list(range(ci.LABEL_WIDTH, 128)), "across the table, not under the label"
    # no row's text moved or was covered: the same pixels as without the line, plus the line
    plain = draw(build_cfp(ctx("TEX", cfp_field=4)).__class__(**{**_fields(view), "cut": 0}), 0)
    assert {k: v for k, v in c.pixels.items() if v != LINE} == plain.pixels


def _fields(view):
    return {name: getattr(view, name) for name in view.__dataclass_fields__}


def test_the_line_scrolls_with_the_rows_and_is_not_drawn_off_the_panel():
    view = build_cfp(ctx("TEX"))  # after 12th: y = 71 at rest, well below the 32 rows
    rest = draw(view, 0)
    assert line_rows(rest) == {}, "below the panel at rest"
    assert not [p for p in rest.out_of_bounds if p[1] == 12 * ROW_HEIGHT - 1], "not even tried"
    for px in (44, 56, 66):
        assert list(line_rows(draw(view, px))) == [12 * ROW_HEIGHT - 1 - px]
    off_top = draw(view, 80)
    assert line_rows(off_top) == {}, "scrolled off the top"
    assert not [p for p in off_top.out_of_bounds if p[1] < 0 and p[1] == 12 * ROW_HEIGHT - 81]


def test_no_line_when_the_cut_is_not_inside_the_table():
    view = build_cfp(ctx("TEX"))
    rows = len(view.rows)
    bottom = scroll_range(rows)
    for cut in (0, rows, rows + 3):
        for px in (0, 40, bottom):
            c = draw(view.__class__(**{**_fields(view), "cut": cut}), px)
            assert line_rows(c) == {}, (cut, px)


def test_the_aps_screen_never_draws_one():
    c = draw(build_ap(ctx("TEX", cfp_field=4)), 0)
    assert line_rows(c) == {}


def test_the_line_has_the_hockey_playoff_rules_colour():
    from scoreboard.display.renderer import PLAYOFF_LINE

    assert LINE == PLAYOFF_LINE


def test_snapshot_mid_scroll_with_the_line(update_snapshots):
    c = draw(build_cfp(ctx("TEX")), 56)
    check_snapshot("cfb_cfp_cut_mid", c.render(), update_snapshots)
