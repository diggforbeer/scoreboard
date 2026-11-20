"""The college held final (#550): ``fb_final`` with a ranked team's number under its crest.

The screen, its hold, the overtime label and the loser's dimming are the NFL's (#426, see
``test_football_idle_final``); what is new here is the rank, and that a college game goes through
the same hold with the rules the issue lists: held from the end we watched, never replayed after a
restart, ``Final/OT`` read as an overtime final.
"""

from __future__ import annotations

import dataclasses

import pytest

from scoreboard.display.football_idle import LEFT_X, RANK_BASELINE, RIGHT_DX
from scoreboard.display.football_scenes import RANK_COLOR
from scoreboard.football.idle_screens import IDLE_SCREENS
from scoreboard.football.idle_views import build_final
from scoreboard.football.mode import FootballMode
from test_football_college_listed_only import FakePoll
from test_football_idle import Clock
from test_football_idle_final import draw, final_game, view_of
from test_football_idle_selection import IdleFeed, stand_ins  # noqa: F401 - autouse
from test_football_scenes import H, check_snapshot, game

RIGHT_X = 128 - RIGHT_DX


def ranked(g, away=None, home=None):
    return dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, rank=away),
        home=dataclasses.replace(g.home, rank=home),
    )


def violet(c, x0, x1):
    """The pixels of the rank colour (or its dimmed loser's version) in columns x0..x1."""
    out = {}
    for (x, y), rgb in c.lit(x0, 0, x1, H - 1).items():
        r, g, b = rgb
        if b > 0 and abs(r / b - RANK_COLOR[0] / RANK_COLOR[2]) < 0.02 and g < r:
            out[(x, y)] = rgb
    return out


# -- the screen ---------------------------------------------------------------------------------


@pytest.mark.parametrize("logos", [True, False])
def test_a_ranked_winner_and_an_unranked_loser(logos):
    g = ranked(final_game("WSH", "NYG", 17, 31), home=3)
    c = draw(view_of(g), logos=logos)
    assert not c.out_of_bounds
    mine = violet(c, RIGHT_X - 8, RIGHT_X + 8)
    assert mine and all(RANK_BASELINE - 5 <= y <= RANK_BASELINE for (_, y) in mine)
    xs = [x for x, _ in mine]
    assert abs((min(xs) + max(xs)) / 2 - RIGHT_X) <= 2, "centred under the crest"
    assert max(rgb[2] for rgb in mine.values()) == RANK_COLOR[2], "the winner is at full colour"
    assert not violet(c, 0, 40), "the unranked side has no number"


def test_the_ranked_loser_is_dimmed_with_its_crest():
    g = ranked(final_game("WSH", "NYG", 28, 24), home=3)
    c = draw(view_of(g))
    mine = violet(c, RIGHT_X - 8, RIGHT_X + 8)
    assert mine and max(rgb[2] for rgb in mine.values()) < RANK_COLOR[2] * 0.6


def test_no_rank_no_number_and_the_screen_is_the_nfls():
    c = draw(view_of(final_game("WSH", "NYG", 20, 27)))
    assert not violet(c, 0, 127)


def test_two_digits_fit_clear_of_the_recap(update_snapshots):
    g = ranked(final_game("WSH", "NYG", 24, 27, short="Final/OT", period=5), away=12, home=19)
    view = view_of(g)
    assert view.status == "FINAL/OT"
    c = draw(view, logos=False)
    assert not c.out_of_bounds
    for x in (LEFT_X, RIGHT_X):
        pixels = violet(c, x - 8, x + 8)
        assert pixels and min(xs := [px for px, _ in pixels]) >= x - 5 and max(xs) <= x + 5
    assert all(y <= RANK_BASELINE for _, y in violet(c, 0, 127))
    check_snapshot("fb_final_ranked_ot", c.render(), update_snapshots)


def test_a_ranked_final_snapshot(update_snapshots):
    g = ranked(final_game("WSH", "NYG", 17, 31), home=3)
    c = draw(view_of(g), logos=False)
    check_snapshot("fb_final_ranked", c.render(), update_snapshots)


# -- a college game through the hold ------------------------------------------------------------


def real_final():
    """The real builder in place of the stand-in the selection tests use."""
    IDLE_SCREENS["fb_final"] = build_final


def college(feed, clock, favourite="NYG"):
    from teamcfg import fcfg

    cfg = fcfg(favourite_team=favourite, rotation=[{"screen": "clock", "seconds": 5}])
    mode = FootballMode(
        client_factory=lambda: feed,
        monotonic=clock,
        football=lambda: cfg,
        league="college-football",
    )
    poll = FakePoll({"NYG": 3})
    mode._chosen_poll = lambda: poll
    return mode


def test_a_game_watched_to_its_end_holds_with_its_rank_and_overtime_label():
    real_final()
    clock = Clock(1000.0)
    feed = IdleFeed([game("WSH", "NYG", "in", 24, 24, game_id=3, period=4)])
    mode = college(feed, clock)
    mode.worker.poll_once()
    mode.scene()  # seen live
    feed.games = [
        game(
            "WSH", "NYG", "post", 27, 24, game_id=3, short="Final/OT", name="STATUS_FINAL", period=5
        )
    ]
    mode.worker.poll_once()
    scene = mode.scene()
    assert scene.kind == "fb_final"
    assert scene.fb_idle.status == "FINAL/OT"
    assert scene.fb_game.home.rank == 3 and scene.fb_idle.game.home.rank == 3
    clock.t += 59 * 60
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_final", "held for the final-hold setting"
    clock.t += 2 * 60
    mode.worker.poll_once()
    assert mode.scene().kind != "fb_final"


def test_a_final_already_over_at_startup_is_not_held():
    real_final()
    feed = IdleFeed(
        [game("WSH", "NYG", "post", 27, 24, game_id=3, short="Final", name="STATUS_FINAL")]
    )
    mode = college(feed, Clock(1000.0))
    mode.worker.poll_once()
    assert mode.scene().kind != "fb_final", "a restart never re-celebrates an old final"
