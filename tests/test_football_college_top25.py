"""Top 25 games earn turns even when neither team is followed (#555).

Driven through ``FootballMode.scene()`` over a fake feed. The tests use NFL abbreviations for the
teams (they only need distinct ESPN ids) and a stand-in poll that ranks some of them, so the rule
is tested apart from the poll's fetching, which ``test_football_college_ranks`` covers.

The rules (also in ``FootballConfig``'s docs):

* a followed team's live game holds the screen; the Top 25 games never take it from one;
* at the half of the followed games (dead air) and when no followed game is live, live games with
  a ranked team take turns, ``top25_seconds`` each, which is also the least a game keeps the board;
* order: two ranked teams before one, then the better rank, then the game id;
* the setting ``top25_turns`` turns it off.
"""

from __future__ import annotations

import pytest

from scoreboard.config import FootballConfig, Settings
from scoreboard.football.teams import TEAMS
from test_football_idle_selection import BASE, build, register, stand_ins  # noqa: F401
from test_football_scenes import game

HALF = {"short": "Halftime", "name": "STATUS_HALFTIME", "period": 2}


class FakePoll:
    def __init__(self, ranks):
        self.by_id = {TEAMS[abbrev].espn_id: rank for abbrev, rank in ranks.items()}

    def rank_of(self, team_id):
        return self.by_id.get(team_id)


def live(away, home, game_id, **kw):
    return game(away, home, "in", 7, 3, game_id=game_id, **kw)


def rig(games, ranks, favourite="NYG", follow=(), **cfg):
    mode, clock = build(games, favourite=favourite, follow=follow, **cfg)
    poll = FakePoll(ranks)
    mode._chosen_poll = lambda: poll
    return mode, clock


def shown(mode, clock, at):
    clock.t = BASE + at
    scene = mode.scene()
    return scene.kind, getattr(scene.fb_game, "id", None)


def update(mode, games):
    mode.worker._client.games = games  # the fake feed's slate
    mode.worker.poll_once()


# -- a game nobody follows ----------------------------------------------------------------------


def test_a_live_top_25_game_takes_the_board_while_the_favourite_is_not_playing():
    register("fb_preview")
    games = [live("MIA", "IND", 2), live("PHI", "DAL", 3)]
    mode, clock = rig(games, {"MIA": 9}, favourite="NYG")
    assert shown(mode, clock, 0) == ("fb_field", 2), "only the ranked game, never DAL-PHI"
    assert shown(mode, clock, 500) == ("fb_field", 2)


def test_with_no_ranked_game_live_the_idle_rotation_is_what_it_was():
    register("fb_preview")
    games = [live("MIA", "IND", 2)]
    mode, clock = rig(games, {}, favourite="NYG", rotation=[("fb_preview", 5.0)])
    assert shown(mode, clock, 0)[0] == "fb_preview"


def test_a_ranked_game_that_is_not_live_earns_no_turn():
    register("fb_preview")
    games = [game("MIA", "IND", "pre", short="x", start="2026-11-22T18:00Z", game_id=2)]
    mode, clock = rig(games, {"MIA": 3}, rotation=[("fb_preview", 5.0)])
    assert shown(mode, clock, 0)[0] == "fb_preview"
    update(mode, [game("MIA", "IND", "post", 20, 17, short="Final", game_id=2)])
    assert shown(mode, clock, 1)[0] == "fb_preview", "a final is not a turn"


def test_it_does_not_make_the_team_followed():
    register("fb_preview")
    mode, _ = rig([live("MIA", "IND", 2)], {"MIA": 9}, favourite="NYG")
    cfg = mode._football()
    assert cfg.followed_teams == ["NYG"] and cfg.horn_team == "NYG"
    assert mode.watched(mode.snapshot.games) == [], "no plays are fetched for it either"


# -- primary first ------------------------------------------------------------------------------


def test_a_followed_live_game_holds_the_screen_against_every_top_25_game():
    games = [live("WSH", "NYG", 1), live("MIA", "IND", 2), live("GB", "SF", 3)]
    mode, clock = rig(games, {"MIA": 1, "GB": 2, "SF": 3})
    for at in range(0, 200, 7):
        assert shown(mode, clock, at) == ("fb_field", 1)


def test_another_followed_team_in_play_also_keeps_the_ranked_games_out():
    games = [live("WSH", "NYG", 1), live("PHI", "DAL", 4), live("MIA", "IND", 2)]
    mode, clock = rig(games, {"MIA": 1}, favourite="NYG", follow=("DAL",))
    seen = {shown(mode, clock, at)[1] for at in range(0, 120, 3)}
    assert seen == {1}, "the favourite holds the screen alone"
    update(
        mode,
        [game("WSH", "NYG", "pre", short="x", start="2026-11-22T20:00Z", game_id=1), *games[1:]],
    )
    assert {shown(mode, clock, at)[1] for at in range(0, 120, 3)} == {4}, "followed live, no ranked"


def test_the_favourites_half_is_dead_air_the_ranked_games_fill():
    games = [live("WSH", "NYG", 1, **HALF), live("MIA", "IND", 2)]
    mode, clock = rig(
        games, {"MIA": 4, "NYG": 2}, top25_seconds=20.0
    )  # the favourite is ranked too
    order = [shown(mode, clock, at)[1] for at in (0, 10, 20, 30, 40, 60)]
    assert order == [1, 1, 2, 2, 1, 2], (
        "the favourite's halftime card, the ranked game, alternating"
    )
    update(mode, [live("WSH", "NYG", 1), live("MIA", "IND", 2)])
    assert {shown(mode, clock, at)[1] for at in (61, 90, 120, 200)} == {1}, "second half: back"


def test_a_halftime_with_no_ranked_game_playing_changes_nothing():
    games = [live("WSH", "NYG", 1, **HALF), live("PHI", "DAL", 3)]
    mode, clock = rig(games, {})
    assert {shown(mode, clock, at)[1] for at in range(0, 100, 5)} == {1}


def test_while_another_followed_game_is_in_play_a_halftime_is_not_dead_air():
    games = [live("WSH", "NYG", 1, **HALF), live("PHI", "DAL", 4), live("MIA", "IND", 2)]
    mode, clock = rig(games, {"MIA": 1}, favourite="NYG", follow=("DAL",))
    assert {shown(mode, clock, at)[1] for at in range(0, 200, 5)} <= {1, 4}


# -- the order and the dwell ---------------------------------------------------------------------


def test_two_ranked_teams_come_before_one_and_the_better_rank_before_the_worse():
    games = [
        live("MIA", "IND", 2),  # #3 vs unranked
        live("GB", "SF", 3),  # #20 vs #19
        live("PHI", "DAL", 4),  # #1 vs unranked
        live("KC", "ATL", 5),  # #12 vs #14
        live("LAR", "SEA", 6),  # unranked
    ]
    ranks = {"MIA": 3, "GB": 20, "SF": 19, "PHI": 1, "KC": 12, "ATL": 14}
    mode, clock = rig(games, ranks, top25_seconds=10.0)
    first_lap = [shown(mode, clock, at)[1] for at in range(0, 50, 10)]
    assert first_lap == [5, 3, 4, 2, 5], "KC-ATL (12), GB-SF (19), then PHI (1), MIA (3); wraps"
    assert 6 not in first_lap


def test_a_game_keeps_the_board_for_its_whole_turn_whatever_happens_to_the_order():
    games = [live("MIA", "IND", 2), live("PHI", "DAL", 4)]
    mode, clock = rig(games, {"MIA": 8, "PHI": 15}, top25_seconds=20.0)
    assert shown(mode, clock, 0)[1] == 2
    mode._chosen_poll = lambda: FakePoll({"MIA": 8, "PHI": 15, "IND": 2})  # IND jumps in
    assert shown(mode, clock, 5)[1] == 2
    mode._chosen_poll = lambda: FakePoll({"MIA": 8, "PHI": 1})  # PHI is now better
    assert shown(mode, clock, 19)[1] == 2, "not before the turn is over"
    assert shown(mode, clock, 20)[1] == 4
    assert shown(mode, clock, 39)[1] == 4
    assert shown(mode, clock, 40)[1] == 2


def test_a_game_that_ends_hands_over_at_once():
    games = [live("MIA", "IND", 2), live("PHI", "DAL", 4)]
    mode, clock = rig(games, {"MIA": 8, "PHI": 15}, top25_seconds=60.0)
    assert shown(mode, clock, 0)[1] == 2
    update(mode, [game("MIA", "IND", "post", 20, 17, short="Final", game_id=2), games[1]])
    assert shown(mode, clock, 3)[1] == 4, "mid-turn, but the game is over"


def test_the_turn_length_is_the_setting():
    games = [live("MIA", "IND", 2), live("PHI", "DAL", 4)]
    mode, clock = rig(games, {"MIA": 8, "PHI": 15}, top25_seconds=9.0)
    assert [shown(mode, clock, at)[1] for at in (0, 8, 9, 17, 18)] == [2, 2, 4, 4, 2]


# -- the setting --------------------------------------------------------------------------------


def test_turned_off_a_ranked_game_does_nothing_for_the_board():
    register("fb_preview")
    mode, clock = rig(
        [live("MIA", "IND", 2)], {"MIA": 1}, top25_turns=False, rotation=[("fb_preview", 5.0)]
    )
    assert shown(mode, clock, 0)[0] == "fb_preview"
    half = [live("WSH", "NYG", 1, **HALF), live("MIA", "IND", 2)]
    mode, clock = rig(half, {"MIA": 1}, top25_turns=False)
    assert {shown(mode, clock, at)[1] for at in range(0, 100, 5)} == {1}


def test_the_defaults_and_the_toml(caplog):
    cfg = FootballConfig()
    assert cfg.top25_turns is True and cfg.top25_seconds == 20.0
    loaded = Settings.from_dict({"football": {"top25_turns": False, "top25_seconds": 30}}).football
    assert loaded.top25_turns is False and loaded.top25_seconds == 30.0


@pytest.mark.parametrize("given,held", [(1, 8.0), (500, 60.0), (8, 8.0), (60, 60.0)])
def test_the_turn_length_is_held_to_its_range(given, held):
    assert FootballConfig(top25_seconds=given).top25_seconds == held


def test_a_bad_turn_length_falls_back_with_a_warning(caplog):
    with caplog.at_level("WARNING"):
        assert FootballConfig(top25_seconds="long").top25_seconds == 20.0
    assert "football.top25_seconds" in caplog.text


# -- a Saturday ---------------------------------------------------------------------------------


def test_a_saturday_noon_to_night():
    """The board's day: idle, the early ranked game takes it, the favourite kicks off and holds
    it, its half is dead air for the late ranked game, the favourite's final gives way."""
    register("fb_preview", "fb_final")
    early, late = [live("MIA", "IND", 2), live("PHI", "DAL", 4)]
    ranks = {"MIA": 6, "DAL": 11}
    pre_fav = game("WSH", "NYG", "pre", short="x", start="2026-11-22T20:00Z", game_id=1)
    pre_late = game("PHI", "DAL", "pre", short="x", start="2026-11-22T21:00Z", game_id=4)
    pre_early = game("MIA", "IND", "pre", short="x", start="2026-11-22T17:00Z", game_id=2)
    mode, clock = rig(
        [pre_early, pre_fav, pre_late], ranks, rotation=[("fb_preview", 5.0)], top25_seconds=20.0
    )
    assert shown(mode, clock, 0)[0] == "fb_preview", "nothing is playing"
    update(mode, [early, pre_fav, pre_late])
    assert shown(mode, clock, 10) == ("fb_field", 2), "the early ranked game"
    update(mode, [early, live("WSH", "NYG", 1), pre_late])
    assert {shown(mode, clock, at)[1] for at in range(20, 200, 10)} == {1}, "the favourite's"
    update(mode, [early, live("WSH", "NYG", 1, **HALF), live("PHI", "DAL", 4)])
    seen = [shown(mode, clock, at)[1] for at in range(200, 320, 10)]
    assert set(seen) == {1, 2, 4}, "the half is shared with both ranked games"
    update(mode, [early, live("WSH", "NYG", 1), live("PHI", "DAL", 4)])
    assert {shown(mode, clock, at)[1] for at in range(330, 400, 10)} == {1}, "second half"
    update(mode, [early, game("WSH", "NYG", "post", 20, 17, short="Final", game_id=1), late])
    assert shown(mode, clock, 410)[0] == "fb_final", "the favourite's final keeps its place"
