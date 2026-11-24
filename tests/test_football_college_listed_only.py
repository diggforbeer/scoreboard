"""Only the ranked list's teams take the college board (#587, the owner's standing rule).

A live game between teams nobody follows never gets screen time: not as a turn when nothing
else is on (the NFL's "every game takes a turn" fallback), not at a followed game's halftime, not
as a red zone alert, not because both teams are in the Top 25. This replaces the Top 25 turns of
#555, which built the opposite. The NFL's own behaviour is pinned unchanged beside it.

The games use NFL abbreviations: the mode only needs distinct teams, and ``league`` decides.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest

from scoreboard.config import FootballConfig, Settings
from scoreboard.football.mode import FootballMode
from scoreboard.football.teams import TEAMS
from teamcfg import fcfg
from test_football_idle import Clock
from test_football_idle_selection import (
    BASE,
    IdleFeed,
    Utc,
    nyg_game,
    register,
    stand_ins,  # noqa: F401 - the autouse fixture that puts the idle screens back after each test
)
from test_football_redzone import elsewhere, with_situation
from test_football_scenes import game

HALF = {"short": "Halftime", "name": "STATUS_HALFTIME", "period": 2}
KC = TEAMS["KC"].espn_id


class FakePoll:
    """A poll that ranks some teams (by abbreviation), for ``mode._chosen_poll``."""

    def __init__(self, ranks):
        self.by_id = {TEAMS[abbrev].espn_id: rank for abbrev, rank in ranks.items()}

    def rank_of(self, team_id):
        return self.by_id.get(team_id)


def live(away, home, game_id, **kw):
    return game(away, home, "in", 7, 3, game_id=game_id, **kw)


def mode_for(games, *, league="college-football", favourite="NYG", follow=(), rows=None, **cfg):
    clock = Clock(BASE)
    rotation = [{"screen": s, "seconds": 8} for s in (rows if rows is not None else ())]
    config = fcfg(favourite_team=favourite, also_follow=list(follow), rotation=rotation, **cfg)
    feed = IdleFeed(games)
    mode = FootballMode(
        client_factory=lambda: feed,
        monotonic=clock,
        football=lambda: config,
        utc_now=Utc(datetime(2026, 11, 22, 9, 0, tzinfo=UTC)),
        league=league,
    )
    mode._feed = feed
    mode.worker.poll_once()
    return mode, clock


def ranked(mode, **ranks):
    poll = FakePoll(ranks)
    mode._chosen_poll = lambda: poll


def far():
    return nyg_game("pre")  # the favourite, kicking off hours away


# -- a game that involves nobody on the list ----------------------------------------------------


def test_a_live_unlisted_game_never_takes_the_idle_rotation():
    register("cfb_preview")
    mode, clock = mode_for([far(), live("MIA", "IND", 2)], rows=["cfb_preview"])
    ranked(mode, MIA=3, IND=9)  # both in the Top 25: still not the owner's
    for at in range(0, 200, 7):
        clock.t = BASE + at
        scene = mode.scene()
        assert scene.kind == "cfb_preview", (at, scene.kind)


def test_with_no_rotation_to_show_the_board_says_so_rather_than_show_an_unlisted_game():
    """The NFL's fallback was "none of them playing: every game takes a turn"."""
    mode, clock = mode_for([live("MIA", "IND", 2), live("PHI", "DAL", 3)])  # NYG has no game
    ranked(mode, MIA=3, PHI=11)
    for at in range(0, 100, 5):
        clock.t = BASE + at
        assert mode.scene().kind == "fb_no_games"


def test_with_nobody_followed_no_college_game_takes_the_board():
    """The NFL's "with nobody followed, any live game takes the screen" does not apply."""
    register("cfb_preview")
    mode, clock = mode_for(
        [live("MIA", "IND", 2), live("PHI", "DAL", 3)], favourite="", rows=["cfb_preview"]
    )
    ranked(mode, MIA=1, IND=2)
    kinds = set()
    for at in range(0, 100, 5):
        clock.t = BASE + at
        kinds.add(mode.scene().kind)
    assert kinds <= {"fb_no_games", "cfb_preview", "clock"}, kinds
    nfl, _ = mode_for([live("MIA", "IND", 2)], league="nfl", favourite="", rows=[])
    assert nfl.scene().kind in ("fb_field", "fb_scores"), "the NFL still shows the live game"


def test_at_a_followed_games_halftime_an_unlisted_game_does_not_fill_the_dead_air():
    mode, clock = mode_for([live("WSH", "NYG", 1, **HALF), live("MIA", "IND", 2)])
    ranked(mode, MIA=1, IND=2, NYG=5)
    for at in range(0, 120, 6):
        clock.t = BASE + at
        scene = mode.scene()
        assert scene.kind == "fb_halftime" and scene.fb_game.id == 1, at


def test_the_favourites_live_game_holds_the_screen_alone_again():
    mode, clock = mode_for([live("WSH", "NYG", 1), live("MIA", "IND", 2)])
    ranked(mode, MIA=1, IND=2)
    for at in range(0, 120, 6):
        clock.t = BASE + at
        assert mode.scene().fb_game.id == 1, at


def test_the_favourite_holds_the_screen_against_another_followed_teams_live_game_too():
    games = [live("WSH", "NYG", 1), live("PHI", "DAL", 3), live("MIA", "IND", 2)]
    mode, clock = mode_for(games, follow=["DAL"])
    for at in range(0, 120, 4):
        clock.t = BASE + at
        assert mode.scene().fb_game.id == 1, at


def test_a_followed_teams_live_game_still_takes_the_board_and_the_unlisted_one_does_not():
    mode, clock = mode_for([far(), live("MIA", "IND", 2), live("PHI", "DAL", 3)], follow=["DAL"])
    ranked(mode, MIA=1, IND=2)
    seen = set()
    for at in range(0, 120, 4):
        clock.t = BASE + at
        scene = mode.scene()
        seen.add(scene.fb_game.id if scene.fb_game else None)
    assert seen == {3}, "the followed team's game, never MIA-IND"


def test_pick_game_only_ever_returns_a_listed_game():
    mode, _ = mode_for([far(), live("MIA", "IND", 2)])
    unlisted = [live("MIA", "IND", 2), live("PHI", "DAL", 3)]
    assert mode.pick_game(unlisted, 0.0) is None
    both = [*unlisted, live("WSH", "NYG", 1)]
    assert {mode.pick_game(both, t).id for t in (0.0, 8.0, 99.0)} == {1}
    assert mode.pick_game([], 0.0) is None
    assert [g.id for g in mode.listed(both)] == [1]


def test_the_nfls_fallback_is_unchanged():
    """The NFL with nobody followed, or none of them playing, still shows every game in turn."""
    nfl, _ = mode_for([live("MIA", "IND", 2)], league="nfl", favourite="", follow=())
    games = [live("MIA", "IND", 2), live("PHI", "DAL", 3)]
    assert {nfl.pick_game(games, t).id for t in (0.0, 8.0, 16.0)} == {2, 3}
    nfl2, _ = mode_for([far()], league="nfl", favourite="NYG")
    assert nfl2.pick_game(games, 0.0).id in (2, 3), "NYG is not playing: every game takes a turn"
    assert nfl2.listed(games) == []


# -- the red zone alert is a takeover too -------------------------------------------------------


def test_a_red_zone_in_an_unlisted_college_game_raises_no_alert():
    register("cfb_preview")
    mode, clock = mode_for([far(), elsewhere()], rows=["cfb_preview"])
    assert mode.scene().kind == "cfb_preview"
    mode._feed.games = [far(), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().kind == "cfb_preview", "the NFL would show fb_redzone here"


def test_the_same_red_zone_still_alerts_in_the_nfl():
    register("fb_preview")
    mode, clock = mode_for([far(), elsewhere()], league="nfl", rows=["fb_preview"])
    assert mode.scene().kind == "fb_preview"
    mode._feed.games = [far(), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_redzone"


def test_a_listed_college_games_red_zone_is_shown_by_its_own_field_not_an_alert():
    mine = with_situation(nyg_game("in"), TEAMS["NYG"].espn_id, red=False)
    mode, clock = mode_for([mine, elsewhere()])
    mode.scene()
    mode._feed.games = [
        with_situation(nyg_game("in"), TEAMS["NYG"].espn_id, red=True),
        elsewhere(True),
    ]
    clock.t += 15
    mode.worker.poll_once()
    scene = mode.scene()
    assert scene.kind != "fb_redzone" and scene.fb_game.id == 7


# -- the Top 25 turns are gone ------------------------------------------------------------------


def test_the_top_25_settings_are_retired_and_ignored(caplog):
    cfg = FootballConfig()
    assert not hasattr(cfg, "top25_turns") and not hasattr(cfg, "top25_seconds")
    with caplog.at_level(logging.WARNING):
        loaded = Settings.from_dict({"football": {"top25_turns": True, "top25_seconds": 30}})
    assert not hasattr(loaded.football, "top25_turns")
    assert "unknown" not in caplog.text.lower(), "a retired key, not a typo"


def test_a_saved_football_section_drops_the_retired_keys(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[football]\ntop25_turns = true\ntop25_seconds = 30\nfinal_hold_minutes = 30\n")
    settings = Settings.from_toml(path)
    settings.save({"football": {"final_hold_minutes": 45}})
    text = path.read_text()
    assert "top25" not in text and "final_hold_minutes = 45" in text


@pytest.mark.parametrize("name", ["_top25_games", "_top25_pick", "_top25_turn"])
def test_the_mode_has_no_top_25_machinery_left(name):
    mode, _ = mode_for([far()])
    assert not hasattr(mode, name)
