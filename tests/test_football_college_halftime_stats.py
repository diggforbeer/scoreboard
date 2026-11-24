"""Halftime and quarter-end team stats for a college game (#549, owner's call 2026-11-22).

A quarter end (the 1st and 3rd) is a break like a timeout: both pages of the stats, held until
the next play. The half alternates the halftime card with the stats' pages for as long as it
lasts. The 2nd and 4th quarter ends add nothing of their own (the half has its card, the 4th is
the game's end). College only: the NFL keeps what it had.
"""

from __future__ import annotations

import dataclasses

import pytest

from scoreboard.config import ScoreboardConfig
from scoreboard.football import director as dr
from scoreboard.football.director import Director
from scoreboard.football.mode import HALFTIME_CARD_SECONDS, FootballMode
from scoreboard.football.worker import FeedSnapshot
from test_football_college_timeout_stats import STATS, college_rig
from test_football_events import make_play
from test_football_scenes import GAMES
from test_football_stats import run_to_next_play

RUSH = make_play(0, "rush", off="WSH")


def end_period(n, period):
    return make_play(n, "end_period", off="WSH", period=period)


# -- quarter ends -------------------------------------------------------------------------------


@pytest.mark.parametrize("period", [1, 3])
def test_the_end_of_the_first_and_third_quarters_get_the_team_stats(period):
    rig = college_rig()
    names = [s.stage for s in run_to_next_play(rig, RUSH, end_period(1, period))]
    assert names == [dr.STATS], "held until the next play, like a timeout"


@pytest.mark.parametrize("period", [2, 4])
def test_the_end_of_the_second_and_fourth_get_nothing(period):
    rig = college_rig()
    assert [s.stage for s in run_to_next_play(rig, RUSH, end_period(1, period))] == []


def test_a_quarter_end_without_stats_shows_nothing():
    rig = college_rig(stats=None)
    assert [s.stage for s in run_to_next_play(rig, RUSH, end_period(1, 1))] == []


def test_the_nfl_director_keeps_a_quarter_end_as_it_was():
    from test_football_college_events import ScoresRig

    rig = ScoresRig()
    rig.director = Director(
        lambda: rig.cfg, rig.clock, lambda: rig.delay, rig.clock.utc,
        scores_only=True, stats=lambda _id: STATS,
    )  # fmt: skip
    rig.poll(RUSH)
    rig.run()
    assert [s.stage for s in run_to_next_play(rig, RUSH, end_period(1, 1))] == []


# -- the halftime cycle -------------------------------------------------------------------------


def half_mode(league="college-football", stats=STATS, wide=True):
    mode = FootballMode(
        lambda: dataclasses.replace(ScoreboardConfig()),
        client_factory=lambda: None,
        league=league,
        wide=lambda: wide,
    )
    game = GAMES["halftime"]
    mode._stats = {game.id: stats} if stats is not None else {}
    return mode, game


def cycle(mode, game, now):
    from scoreboard.app import Scene

    return mode._halftime_cycle(game, Scene("fb_halftime", fb_game=game), now)


def test_the_half_opens_on_the_card_then_the_pages_take_turns_and_it_goes_round():
    mode, game = half_mode()
    page = mode.director.stats_page_seconds()
    assert cycle(mode, game, 100.0) is None, "the card first (the half has just begun)"
    assert cycle(mode, game, 100.0 + HALFTIME_CARD_SECONDS - 1) is None
    first = cycle(mode, game, 100.0 + HALFTIME_CARD_SECONDS + 1)
    assert first is not None and first.fb_stage == dr.STATS and first.fb_stats is STATS
    assert first.fb_seconds == page
    assert 0 <= first.fb_elapsed < page, "page 1"
    second = cycle(mode, game, 100.0 + HALFTIME_CARD_SECONDS + page + 1)
    assert page <= second.fb_elapsed < 2 * page, "page 2"
    round_ = HALFTIME_CARD_SECONDS + STATS.pages * page
    assert cycle(mode, game, 100.0 + round_ + 1) is None, "and back to the card"


def test_no_stats_yet_keeps_the_plain_card():
    mode, game = half_mode(stats=None)
    assert cycle(mode, game, 100.0) is None
    assert cycle(mode, game, 100.0 + HALFTIME_CARD_SECONDS + 5) is None


def test_the_nfl_halftime_and_a_narrow_panel_keep_the_plain_card():
    for mode, game in (half_mode(league="nfl"), half_mode(wide=False)):
        cycle(mode, game, 100.0)
        assert cycle(mode, game, 100.0 + HALFTIME_CARD_SECONDS + 5) is None


def test_a_game_that_is_not_at_the_half_gets_nothing_and_forgets_the_half():
    mode, game = half_mode()
    cycle(mode, game, 100.0)
    assert game.id in mode._half_since
    live = GAMES["live"]
    mode._stats[live.id] = STATS
    assert cycle(mode, live, 101.0) is None
    live_after = dataclasses.replace(game, state="in", status_name="STATUS_IN_PROGRESS")
    live_after = dataclasses.replace(live_after, short_detail="12:00 - 3rd", detail="12:00 - 3rd")
    cycle(mode, live_after, 200.0)
    assert game.id not in mode._half_since, "a second half starts the next halftime afresh"


def test_the_scene_goes_through_the_mode(monkeypatch):
    mode, game = half_mode()
    mode.worker._snapshot = FeedSnapshot(games=(game,), plays={})
    # The listing rules have their own tests; here the game is simply the one on screen.
    monkeypatch.setattr(mode, "pick_game", lambda games, now: game)
    monkeypatch.setattr(mode, "_idle_kind", lambda games, snap, now: None)
    monkeypatch.setattr(mode, "_monotonic", lambda: 100.0)
    assert mode.scene().kind == "fb_halftime"
    monkeypatch.setattr(mode, "_monotonic", lambda: 100.0 + HALFTIME_CARD_SECONDS + 1)
    scene = mode.scene()
    assert scene.kind == "fb_event" and scene.fb_stage == dr.STATS
