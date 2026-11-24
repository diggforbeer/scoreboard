"""A college FootballMode: its feed, its team lookups and its scenes resolve in the FBS (#568).

Driven through the real worker and client with fixture payloads, so the scoping is exercised on
the path it takes in the app (the worker's collect and idle callbacks, then the render loop).
"""

import dataclasses
import json
from pathlib import Path

from scoreboard.config import ScoreboardConfig
from scoreboard.football import teams as nfl
from scoreboard.football.api import FootballClient
from scoreboard.football.mode import FootballMode
from teamcfg import fcfg
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
AUBURN_ID = 2


def load(name):
    return json.loads((FIXTURES / name).read_text())


def scoreboard_with(away_id, away_abbrev):
    """The fixture's first game (a final, UGA at home) with its away team replaced."""
    payload = load("college_scoreboard.json")
    event = payload["events"][0]
    payload["events"] = [event]
    away = next(c for c in event["competitions"][0]["competitors"] if c["homeAway"] == "away")
    away["id"] = away["team"]["id"] = str(away_id)
    away["team"]["abbreviation"] = away_abbrev
    return payload


class SchedulingClient(FootballClient):
    """A real college client over canned payloads that also records which schedules it was asked
    for: ``schedule`` is what the idle data fetches by *ESPN id*, the thing that collides."""

    def __init__(self, scoreboard):
        super().__init__(
            league="college-football",
            session=FakeSession(
                FakeResponse(load("college_standings_trimmed.json")),
                FakeResponse(load("college_teams_trimmed.json")),
                FakeResponse(scoreboard),
            ),
        )
        self.schedule_ids = []

    def scoreboard(self, *a, **k):
        # The session replays its last response: after the table loads, every poll is a scoreboard.
        return super().scoreboard(*a, **k)

    def schedule(self, team_id):
        self.schedule_ids.append(int(team_id))
        return None


def college_mode(scoreboard, favourite="UGA", league="college-football"):
    client = SchedulingClient(scoreboard)
    config = dataclasses.replace(ScoreboardConfig(), rotate_seconds=8.0)
    football = fcfg(favourite_team=favourite)
    mode = FootballMode(
        lambda: config, client_factory=lambda: client, football=lambda: football, league=league
    )
    return mode, client


def test_an_nfl_mode_is_unchanged_and_its_scope_does_nothing():
    mode = FootballMode(lambda: ScoreboardConfig(), client_factory=lambda: None)
    assert mode.league == "nfl"
    with mode.scope():
        assert nfl.active_directory() is nfl.NFL_DIRECTORY and nfl.is_team("BUF")


def test_before_the_table_has_loaded_a_college_mode_knows_no_team():
    mode, _client = college_mode(scoreboard_with(AUBURN_ID, "AUB"))
    with mode.scope():
        assert nfl.active_directory() is nfl.EMPTY_DIRECTORY
        assert not nfl.is_team("UGA") and not nfl.is_team("BUF"), "nor the NFL's teams"
    assert mode.scene().kind == "fb_connecting"


def test_after_the_first_poll_the_mode_resolves_teams_in_the_fbs():
    mode, _client = college_mode(scoreboard_with(AUBURN_ID, "AUB"))
    mode.worker.poll_once()
    assert mode.snapshot.has_data and mode.league == "college-football"
    with mode.scope():
        assert nfl.is_team("UGA") and not nfl.is_team("BUF")
        assert nfl.team_by_id(AUBURN_ID).abbrev == "AUB", (
            "id 2 is Auburn here, the Bills in the NFL"
        )
    assert nfl.team_by_id(AUBURN_ID).abbrev == "BUF", "and the scope does not leak out of the block"
    game = mode.snapshot.games[0]
    assert (game.away.abbrev, game.home.abbrev) == ("AUB", "UGA")
    assert game.away.is_football and game.home.is_football


def test_the_scene_is_built_from_the_snapshot_and_the_game_picked_is_the_favourites():
    mode, _client = college_mode(scoreboard_with(AUBURN_ID, "AUB"))
    mode.worker.poll_once()
    assert mode.scene().kind not in ("fb_connecting", "fb_no_data")
    picked = mode.pick_game(list(mode.snapshot.games), 0.0)
    assert picked.home.abbrev == "UGA" and picked.home.is_football


def test_the_idle_data_asks_for_the_college_teams_schedule_by_the_college_id():
    # The favourite's schedule is fetched by ESPN id. Cincinnati's college id is not the Bengals':
    # an NFL lookup here would ask ESPN for the wrong team's schedule.
    standings = load("college_standings_trimmed.json")
    cincinnati = next(
        e["team"]
        for c in standings["children"]
        for e in c.get("standings", {}).get("entries", [])
        if e["team"]["abbreviation"] == "CIN"
    )
    bengals_id = nfl.team("CIN").espn_id
    assert int(cincinnati["id"]) != bengals_id
    mode, client = college_mode(scoreboard_with(int(cincinnati["id"]), "CIN"), favourite="CIN")
    mode.worker.poll_once()
    assert client.schedule_ids == [int(cincinnati["id"])]
    assert bengals_id not in client.schedule_ids


def test_a_college_mode_with_a_football_nfl_favourite_name_ignores_it():
    # "BUF" is an NFL club, not an FBS team: in the college scope it is not a team to follow.
    mode, client = college_mode(scoreboard_with(AUBURN_ID, "AUB"), favourite="BUF")
    mode.worker.poll_once()
    assert client.schedule_ids == []


def test_a_failed_table_load_leaves_a_college_mode_connecting_not_resolving_as_the_nfl():
    client = FootballClient(
        league="college-football", session=FakeSession(FakeResponse(status=500))
    )
    mode = FootballMode(
        lambda: ScoreboardConfig(), client_factory=lambda: client, league="college-football"
    )
    mode.worker.poll_once()
    assert not mode.snapshot.has_data
    with mode.scope():
        assert not nfl.is_team("BUF")
