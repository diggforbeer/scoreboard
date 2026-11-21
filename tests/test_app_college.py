"""The app runs the FBS as a third sport beside hockey and the NFL (#568).

A real college client over fixture payloads is the feed, so the team table, the scoped parsing and
the sport switching are exercised together. Hermetic: no network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scoreboard.app import SPORT_MIN_DWELL_SECONDS, ScoreboardApp
from scoreboard.config import Settings, TeamEntry
from scoreboard.display.matrix import Backend
from scoreboard.football import teams as nfl
from scoreboard.football.api import FootballClient
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_app_priority import FootballFeed, HockeyClient
from test_flow import Clock, RecordingHorn, game
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
START = datetime(2026, 11, 21, 17, 0, tzinfo=UTC)
NSH = "NSH"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def scoreboard(state="in", away=None):
    """The fixture's first game (UGA at home), live by default; ``away`` is (id, abbrev)."""
    payload = load("college_scoreboard.json")
    event = payload["events"][0]
    payload["events"] = [event]
    competition = event["competitions"][0]
    if away is not None:
        side = next(c for c in competition["competitors"] if c["homeAway"] == "away")
        side["id"] = side["team"]["id"] = str(away[0])
        side["team"]["abbreviation"] = away[1]
    status = competition["status"]
    status["type"].update(
        state=state,
        completed=state == "post",
        name={"in": "STATUS_IN_PROGRESS", "pre": "STATUS_SCHEDULED", "post": "STATUS_FINAL"}[state],
        detail="3:12 - 2nd Quarter",
        shortDetail="3:12 - 2nd",
    )
    status["period"] = 2 if state == "in" else status.get("period", 4)
    return payload


@pytest.fixture
def backend():
    return Backend(
        name="fake", RGBMatrix=FakeMatrix, RGBMatrixOptions=FakeOptions, graphics=FakeGraphics
    )


class CollegeRig:
    def __init__(self, backend, teams, payload=None):
        self.clock = Clock(START)
        self.hockey = HockeyClient()
        self.football = FootballFeed()
        self.session = FakeSession(
            FakeResponse(load("college_standings_trimmed.json")),
            FakeResponse(load("college_teams_trimmed.json")),
            FakeResponse(payload or scoreboard()),
        )
        self.college_clients = []

        def college_client():
            client = FootballClient(league="college-football", session=self.session)
            self.college_clients.append(client)
            return client

        settings = Settings()
        settings.teams = [TeamEntry(s, t) for s, t in teams]
        self.settings = settings
        self.app = ScoreboardApp(
            settings,
            client=self.hockey,
            backend=backend,
            clock=lambda: self.clock.now,
            monotonic=lambda: self.clock.mono,
            horn=RecordingHorn(),
            football_client_factory=lambda: self.football,
            college_client_factory=college_client,
        )

    def poll(self, seconds=0):
        if seconds:
            self.clock.advance(seconds=seconds)
        self.app.refresh()
        for mode in self.app._fb_modes():
            mode.worker.poll_once()
        self.app._choose_sport()

    @property
    def sport(self):
        return self.app.current_mode()


# -- when the college mode exists --------------------------------------------------------------


def test_nobody_gets_the_fbs_feed_unasked(backend):
    for teams in (
        [],
        [("hockey", NSH)],
        [("football", "TEN")],
        [("hockey", NSH), ("football", "TEN")],
    ):
        rig = CollegeRig(backend, teams)
        assert rig.app._college is None, teams


def test_a_ranked_college_team_builds_the_college_mode_beside_the_others(backend):
    rig = CollegeRig(backend, [("hockey", NSH), ("football", "TEN"), ("college", "UGA")])
    app = rig.app
    assert app._college is not None and app._college.league == "college-football"
    assert app._football is not None and app._football.league == "nfl"
    assert app._college is not app._football
    assert app._fb("college") is app._college and app._fb("football") is app._football
    assert app._fb("hockey") is None
    # Ranking only a college team does not drag the NFL feed in.
    only = CollegeRig(backend, [("hockey", NSH), ("college", "UGA")]).app
    assert only._football is None and only._college is not None


def test_the_board_starts_on_a_college_team_that_is_ranked_first(backend):
    assert CollegeRig(backend, [("college", "UGA"), ("hockey", NSH)]).sport == "college"
    assert CollegeRig(backend, [("hockey", NSH), ("college", "UGA")]).sport == "hockey"


def test_editing_the_list_starts_and_stops_the_college_mode(backend):
    rig = CollegeRig(backend, [("hockey", NSH)])
    assert rig.app._college is None
    after = Settings()
    after.teams = [TeamEntry("hockey", NSH), TeamEntry("college", "UGA")]
    rig.app._apply_teams_change(after)
    rig.app.settings.teams = after.teams
    assert rig.app._college is not None
    back = Settings()
    back.teams = [TeamEntry("hockey", NSH)]
    rig.app._apply_teams_change(back)
    assert rig.app._college is None


# -- a live college game takes the board by rank ------------------------------------------------


def test_a_live_college_game_of_a_ranked_team_takes_the_board_from_hockeys_idle(backend):
    rig = CollegeRig(backend, [("college", "UGA"), ("hockey", NSH)])
    rig.hockey.today = [game(1, "CHI", NSH, START + timedelta(hours=20))]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "college"
    assert rig.app._owner.sport == "college" and rig.app._owner.team == "UGA"
    assert rig.app.select_scene().kind not in ("fb_connecting", "fb_no_data")


def test_the_better_ranked_sport_wins_when_both_have_a_live_game(backend):
    hockey_live = game(1, "CHI", NSH, START, "LIVE")
    first = CollegeRig(backend, [("hockey", NSH), ("college", "UGA")])
    first.hockey.today = [hockey_live]
    first.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert first.sport == "hockey"
    second = CollegeRig(backend, [("college", "UGA"), ("hockey", NSH)])
    second.hockey.today = [hockey_live]
    second.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert second.sport == "college"


def test_a_college_team_that_is_not_ranked_does_not_take_the_board(backend):
    rig = CollegeRig(backend, [("hockey", NSH), ("college", "ALA")])
    rig.hockey.today = [game(1, "CHI", NSH, START + timedelta(hours=20))]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey", "UGA is live but Alabama is the team that is ranked"


# -- the two football leagues do not mix --------------------------------------------------------


def test_the_nfl_and_college_modes_keep_their_own_games_and_teams(backend):
    rig = CollegeRig(backend, [("college", "UGA"), ("football", "TEN")])
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert [g.home.abbrev for g in rig.app._college.snapshot.games] == ["UGA"]
    assert not rig.app._football.snapshot.games, "the NFL feed is its own: it has no UGA game"


def test_a_college_game_with_a_colliding_id_is_read_as_the_fbs_team(backend):
    # Auburn's ESPN id is the Bills' too: the college mode must read it as Auburn.
    rig = CollegeRig(backend, [("college", "AUB")], scoreboard(away=(2, "AUB")))
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    (g,) = rig.app._college.snapshot.games
    assert g.away.abbrev == "AUB" and g.away.is_football
    assert rig.sport == "college", "the ranked Auburn game owns the board"


# -- drawing -----------------------------------------------------------------------------------


def test_a_college_scene_is_drawn_with_the_college_logos_in_the_fbs_directory(backend):
    """Never the NFL's crests (``CIN`` is a different team in each league): the college set (#541)
    stands in while it is drawn, and the NFL's is put back."""
    rig = CollegeRig(backend, [("college", "UGA")])
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    app = rig.app
    nfl_set, college_set = object(), object()
    app.renderer.football_logos = nfl_set
    app.renderer.college_logos = college_set
    seen = {}

    def spy(scene):
        seen["logos"] = app.renderer.football_logos
        seen["directory"] = nfl.active_directory()
        seen["uga"] = nfl.is_team("UGA")

    app._draw_scene = spy
    app.draw_scene(app.select_scene())
    assert seen["logos"] is college_set and seen["logos"] is not nfl_set
    assert seen["uga"] and seen["directory"].league == "college-football"
    assert app.renderer.football_logos is nfl_set, "put back afterwards"
    assert app.renderer.college_logos is college_set
    assert nfl.active_directory() is nfl.NFL_DIRECTORY


def test_with_logos_off_a_college_scene_is_drawn_without_any(backend):
    rig = CollegeRig(backend, [("college", "UGA")])
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    app = rig.app
    app.renderer.football_logos = object()
    app.renderer.college_logos = None
    seen = {}
    app._draw_scene = lambda scene: seen.update(logos=app.renderer.football_logos)
    app.draw_scene(app.select_scene())
    assert seen["logos"] is None


def test_the_app_builds_a_college_logo_set_beside_the_nfls(backend):
    rig = CollegeRig(backend, [("college", "UGA")])
    renderer = rig.app.renderer
    assert renderer.college_logos is not None and renderer.college_logos.sport == "college"
    assert renderer.football_logos.sport == "football"


def test_an_nfl_scene_is_still_drawn_with_its_logos_and_directory(backend):
    rig = CollegeRig(backend, [("football", "TEN"), ("college", "UGA")])
    app = rig.app
    sentinel = object()
    app.renderer.football_logos = sentinel
    seen = {}
    app._draw_scene = lambda scene: seen.update(
        logos=app.renderer.football_logos, directory=nfl.active_directory()
    )
    assert app.current_mode() == "football"
    app.draw_scene(app.select_scene())
    assert seen["logos"] is sentinel and seen["directory"] is nfl.NFL_DIRECTORY


# -- colours -----------------------------------------------------------------------------------


def test_college_rank_1_colours_the_clock_once_the_table_has_loaded_and_skips_it_before(backend):
    rig = CollegeRig(backend, [("college", "UGA"), ("hockey", NSH)])
    assert rig.app._colour_scheme("x") == ("hockey", NSH), "table not loaded yet: the next team"
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._colour_scheme("x") == ("college", "UGA")
    with rig.app._colour_context("college"):
        assert nfl.is_team("UGA")
        from scoreboard.display import holiday

        assert holiday.team_color("UGA") == nfl.team_color("UGA")
    assert not nfl.is_team("UGA")


def test_a_college_only_board_with_no_table_is_plain_not_broken(backend):
    rig = CollegeRig(backend, [("college", "UGA")])
    assert rig.app._colour_scheme("x") == ("hockey", "")
