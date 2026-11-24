"""The CFP rankings idle screen (#552): the AP screen's layout over the committee's poll.

The committee publishes from about week 10, so the screen exists only once its poll does, and is
skipped (never blank) before and after the season. Hermetic: the trimmed real capture.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from scoreboard.display import college_idle as ci
from scoreboard.display.college_idle import COLLEGE_DRAWERS
from scoreboard.football import scroll
from scoreboard.football.college_views import build_ap, build_cfp, short_conference
from scoreboard.football.idle_screens import IDLE_SCREENS
from test_football_college_ap import NOW, POLLS, college_mode, ctx, draw
from test_football_scenes import check_snapshot


def no_cfp():
    return dataclasses.replace(POLLS, polls={k: v for k, v in POLLS.polls.items() if k != "cfp"})


# -- the view -----------------------------------------------------------------------------------


def test_the_view_is_the_committees_rankings_with_each_teams_conference():
    view = build_cfp(ctx("TEX"))
    assert view.title == "CFP RANKINGS" and view.label == ("CFP", "RANK", "25")
    assert len(view.rows) == 25 and view.scroll_rows == 25 and view.team == "TEX"
    assert [r.abbrev for r in view.rows[:3]] == ["UGA", "UTAH", "ALA"], "not the AP's order"
    first = view.rows[0]
    assert (first.conference, first.points) == ("SEC", 0), "no voting points, a conference"
    assert build_ap(ctx()).rows[0].conference == "", "the AP's have none"


def test_the_conference_is_shortened_to_fit_beside_the_record():
    cases = {
        "SEC": "SEC",
        "ACC": "ACC",
        "Big Ten": "B1G",
        "Big 12": "B12",
        "Pac-12": "PAC",
        "FBS Indep.": "IND",
        "Mountain West": "MWC",
        "Some New League": "SOME",
        "": "",
    }
    for name, short in cases.items():
        assert short_conference(name) == short, name
    view = build_cfp(ctx())
    assert {r.conference for r in view.rows} <= {"SEC", "ACC", "B1G", "B12", "PAC", "IND"}
    assert all(len(r.conference) <= 4 for r in view.rows)


def test_shown_only_once_the_committee_has_published_and_while_it_is_current():
    assert IDLE_SCREENS["cfb_cfp"](ctx()) is not None
    assert build_cfp(ctx(polls=no_cfp())) is None, "before week 10 ESPN sends none"
    assert IDLE_SCREENS["cfb_cfp"](ctx(polls=no_cfp())) is None
    assert build_cfp(ctx(polls=None)) is None, "nothing fetched yet"
    assert build_cfp(ctx(now=NOW + timedelta(days=60))) is None, "last season's, next season"
    assert build_ap(ctx(polls=no_cfp())) is not None, "the AP's does not depend on it"


# -- the drawing --------------------------------------------------------------------------------


def test_snapshots_at_rest_and_mid_scroll(update_snapshots):
    view = build_cfp(ctx("TEX"))
    for name, px in (("cfb_cfp_top", 0), ("cfb_cfp_mid", 24)):
        c = draw(view, px)
        check_snapshot(name, c.render(), update_snapshots)
        assert all(0 <= x < 128 for x, _ in c.out_of_bounds), name


def test_the_label_names_the_poll_and_the_conference_sits_at_the_right_edge():
    view = build_cfp(ctx("TEX"))
    cfp, ap = draw(view, 0), draw(build_ap(ctx("TEX")), 0)
    label = (0, 0, ci.LABEL_WIDTH - 2, 31)
    assert cfp.lit(*label) != ap.lit(*label), "its own label"
    right = (96, 0, 127, 5)
    assert cfp.lit(*right) and cfp.lit(*right) != ap.lit(*right)
    assert 120 <= max(x for x, _ in cfp.lit(*right)) <= 127, "right-aligned, on the panel"


@pytest.mark.parametrize("name", ["cfb_ap", "cfb_cfp"])
def test_both_polls_are_drawn_by_the_same_drawer(name):
    assert COLLEGE_DRAWERS[name] is COLLEGE_DRAWERS["cfb_ap"]


# -- in the mode --------------------------------------------------------------------------------


def test_the_slot_scrolls_like_the_aps_and_is_skipped_without_the_poll():
    mode, clock = college_mode(rows=(("cfb_cfp", 8.0),))
    total = scroll.scroll_seconds(25, 8.0)
    clock["mono"] = 1000.0 + total / 2
    scene = mode.scene()
    assert scene.kind == "cfb_cfp" and scene.scrolling and 0 < scene.scroll_px < 119
    clock["mono"] = 1000.0 + total - 0.5  # in the rest at the bottom, before the wrap
    assert mode.scene().scroll_px == 119
    away, _ = college_mode(rows=(("cfb_cfp", 8.0),), now=NOW + timedelta(days=60))
    assert away.scene().kind != "cfb_cfp"
