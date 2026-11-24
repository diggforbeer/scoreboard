"""The opt-in college scores grid (#556): ``cfb_scores``, its filter, its pages and its drawing.

Hermetic: games are built with the shared ``game()`` helper over the FBS directory, ranks written
in as ``FootballMode.ranked`` would.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import UTC, datetime

from scoreboard.config import COLLEGE_SCREENS, VALID_ROTATION_SCREENS, FootballConfig
from scoreboard.display import college_idle as ci
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_scenes import FINAL, LIVE, RANK_COLOR, WHITE
from scoreboard.football.college_views import (
    SCORES_PER_PAGE,
    ScoresView,
    build_scores,
    scores_order,
)
from scoreboard.football.idle import IdleSnapshot
from scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from scoreboard.football.teams import use_directory
from teamcfg import fcfg
from test_football_college import _fbs_directory
from test_football_college_ap import college_mode
from test_football_scenes import H, check_snapshot, game, renderer

FBS = _fbs_directory()
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def g(away, home, state="in", a=0, h=0, gid=1, ranks=(None, None), start=None, **kw):
    kw.setdefault("short", "3:12 - 3rd")
    if state == "pre":
        kw.update(name="STATUS_SCHEDULED", period=0)
    if state == "post":
        kw.update(name="STATUS_FINAL")
    if start:
        kw["start"] = start
    with use_directory(FBS):
        built = game(away, home, state, a, h, game_id=gid, **kw)
    return dataclasses.replace(
        built,
        away=dataclasses.replace(built.away, rank=ranks[0]),
        home=dataclasses.replace(built.home, rank=ranks[1]),
    )


def slate():
    return [
        g("UTSA", "TEX", gid=1, ranks=(None, 8), start="2026-11-21T19:00Z"),
        g("UTAH", "UCLA", gid=2, ranks=(2, 4), start="2026-11-21T20:00Z"),
        g("UGA", "IU", gid=3, ranks=(None, None), start="2026-11-21T17:00Z"),
        g("OSU", "MICH", gid=4, ranks=(1, 12), start="2026-11-21T18:00Z"),
        g("ND", "MIA", "post", 31, 28, gid=5, ranks=(3, 5), start="2026-11-21T16:00Z"),
    ]


def ctx(games, **cfg):
    return IdleContext(0.0, NOW, games, IdleSnapshot(), fcfg(favourite_team="UGA", **cfg))


def abbrevs(view):
    return [(x.away.abbrev, x.home.abbrev) for x in view.games]


# -- the view -------------------------------------------------------------------------------------


def test_ranked_games_come_first_best_rank_leading_then_the_rest_by_kickoff():
    order = scores_order(slate(), ranked_only=False)
    assert [x.id for x in order] == [4, 2, 5, 1, 3]  # ranks 1, 2, 3, 8, then unranked UGA-IU


def test_the_ranked_filter_drops_games_with_no_ranked_team():
    order = scores_order(slate(), ranked_only=True)
    assert [x.id for x in order] == [4, 2, 5, 1]


def test_the_order_does_not_move_when_a_score_changes():
    before = [x.id for x in scores_order(slate(), False)]
    changed = slate()
    changed[0] = dataclasses.replace(
        changed[0], away=dataclasses.replace(changed[0].away, score=40)
    )
    assert [x.id for x in scores_order(changed, False)] == before


def test_four_games_a_page_and_a_short_last_page():
    view = ScoresView(scores_order(slate(), False))
    assert SCORES_PER_PAGE == 4
    assert view.pages == 2
    assert len(view.page(0)) == 4 and len(view.page(1)) == 1


def test_an_empty_slate_is_skipped_not_blank():
    assert build_scores(ctx([])) is None
    assert build_scores(ctx([g("UGA", "IU")], college_scores="ranked")) is None


def test_the_filter_comes_from_the_setting():
    assert len(build_scores(ctx(slate())).games) == 5
    assert len(build_scores(ctx(slate(), college_scores="ranked")).games) == 4


def test_the_screen_is_registered_and_opt_in():
    from scoreboard.config import DEFAULT_COLLEGE_ROTATION

    assert "cfb_scores" in IDLE_SCREENS and "cfb_scores" in COLLEGE_SCREENS
    assert "cfb_scores" in VALID_ROTATION_SCREENS
    assert "cfb_scores" not in [name for name, _ in DEFAULT_COLLEGE_ROTATION]
    assert IDLE_SCREENS["cfb_scores"](ctx(slate())).pages == 2
    assert not IDLE_SCREENS["cfb_scores"](ctx([]))


# -- the setting ----------------------------------------------------------------------------------


def test_the_setting_defaults_to_all_and_normalises_case():
    assert FootballConfig().college_scores == "all"
    assert FootballConfig(college_scores=" Ranked ").college_scores == "ranked"


def test_an_unknown_value_warns_and_falls_back_to_all(caplog):
    with caplog.at_level(logging.WARNING):
        assert FootballConfig(college_scores="top10").college_scores == "all"
    assert "college_scores" in caplog.text


# -- the drawing ----------------------------------------------------------------------------------


def draw(view, page=0):
    c = AsciiCanvas(128, H)
    with use_directory(FBS):
        ci.draw_cfb_scores(renderer(), c, view, page)
    return c


def lit(c, x0, x1, y0, y1, color):
    return any(c.pixels.get((x, y)) == color for x in range(x0, x1) for y in range(y0, y1))


def test_nothing_is_drawn_off_the_panel_on_either_page():
    view = ScoresView(scores_order(slate(), False))
    for page in (0, 1):
        assert not draw(view, page).out_of_bounds


def test_a_short_last_page_is_centred():
    c = draw(ScoresView(scores_order(slate(), False)), 1)
    xs = [x for (x, y) in c.pixels if y < 28]
    assert min(xs) >= 32 and max(xs) <= 95, "one 32px column in the middle of 128"
    assert abs((min(xs) + max(xs)) / 2 - 63.5) <= 12


def test_status_colours_follow_the_state():
    live = draw(ScoresView((g("UTAH", "UCLA", ranks=(2, 4)),)))
    final = draw(ScoresView((g("ND", "MIA", "post", 31, 28),)))
    assert lit(live, 0, 128, 17, 25, LIVE)
    assert lit(final, 0, 128, 17, 25, FINAL)


def test_the_rank_sits_beside_the_name_when_it_fits_else_on_the_bottom_line():
    roomy = draw(ScoresView((g("ND", "MIA", "post", 3, 5, ranks=(3, 5)),)))
    tight = draw(ScoresView((g("UTAH", "UCLA", a=17, h=14, ranks=(2, 4)),)))
    assert lit(roomy, 0, 128, 1, 16, RANK_COLOR) and not lit(roomy, 0, 128, 25, 32, RANK_COLOR)
    assert lit(tight, 0, 128, 25, 32, RANK_COLOR) and not lit(tight, 0, 128, 1, 16, RANK_COLOR)


def test_an_unranked_game_draws_no_rank_colour_anywhere():
    c = draw(ScoresView((g("UGA", "IU", a=3, h=0),)))
    assert not lit(c, 0, 128, 0, 32, RANK_COLOR)


def test_a_game_to_come_shows_no_score_and_a_kickoff_time():
    c = draw(ScoresView((g("TEX", "ALA", "pre", start="2026-11-22T17:00Z", ranks=(8, 7)),)))
    assert not lit(c, 0, 128, 1, 16, WHITE), "no score digits before the game"
    assert lit(c, 0, 128, 17, 25, ci.GREY)


def test_halftime_and_overtime_are_labelled():
    half = draw(ScoresView((g("OSU", "MICH", "in", 24, 21, name="STATUS_HALFTIME", period=2),)))
    assert lit(half, 0, 128, 17, 25, ci.AMBER)
    ot = draw(ScoresView((g("IU", "UTSA", "post", 30, 27, period=5),)))
    assert lit(ot, 0, 128, 25, 32, tuple(round(c * 0.5) for c in FINAL))


def test_the_page_dots_show_only_with_more_than_one_page():
    def upcoming(n):  # nothing else lands on the bottom row: no ranks, no detail
        return [g("UGA", "IU", "pre", gid=i, start="2026-11-22T17:00Z") for i in range(n)]

    one = draw(ScoresView(tuple(upcoming(3))))
    two = draw(ScoresView(tuple(upcoming(6))), 0)
    assert not any(y == H - 1 for (_, y) in one.pixels)
    assert two.pixels[(60, H - 1)] == ci.DIM, "the current page's dot is bright"
    assert two.pixels[(66, H - 1)] != ci.DIM, "the other page's dot is dimmer"


def test_snapshots(update_snapshots):
    view = ScoresView(scores_order(slate(), False))
    check_snapshot("college_scores_page1", draw(view, 0).render(), update_snapshots)
    check_snapshot("college_scores_page2_centred", draw(view, 1).render(), update_snapshots)


# -- in the mode ----------------------------------------------------------------------------------


def test_a_college_board_lists_the_grid_only_when_the_row_is_in_the_rotation():
    mode, _ = college_mode(rows=(("cfb_scores", 8.0),))
    scene = mode.scene()
    assert scene.kind == "cfb_scores"
    assert isinstance(scene.fb_idle, ScoresView) and scene.fb_page == 0
    off, _ = college_mode(rows=(("cfb_ap", 8.0),))
    assert off.scene().kind == "cfb_ap"


def test_the_grid_reads_the_scoreboard_already_polled_and_asks_for_nothing_new():
    mode, clock = college_mode(rows=(("cfb_scores", 8.0),))
    asked = len(mode._client_factory().session.calls)
    for step in range(5):
        clock["mono"] = 1000.0 + step
        assert mode.scene().kind == "cfb_scores"
    assert len(mode._client_factory().session.calls) == asked
