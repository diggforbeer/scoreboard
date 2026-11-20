"""The football client speaking to ESPN's college feed (#539).

Hermetic: ``tests/fixtures/football/college_scoreboard.json`` is a trimmed real capture
(2026-11-14: a ranked final, an overtime final and an unranked final).
"""

import json
from pathlib import Path

import pytest

from scoreboard.football import api
from scoreboard.football.api import FootballClient
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
COLLEGE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"


def college_payload():
    return json.loads((FIXTURES / "college_scoreboard.json").read_text())


def college_client(*responses):
    return FootballClient(league="college-football", session=FakeSession(*responses))


def test_the_default_league_is_the_nfl_with_the_urls_it_always_had():
    c = FootballClient(session=FakeSession())
    assert c.league == "nfl"
    assert (c.base_url, c.core_url, c.standings_url) == (
        api.BASE_URL,
        api.CORE_URL,
        api.STANDINGS_URL,
    )
    assert api.BASE_URL.endswith("/football/nfl") and api.CORE_URL.endswith("/leagues/nfl")


def test_the_college_league_builds_every_url_from_its_slug():
    c = college_client()
    assert c.base_url == COLLEGE
    assert c.core_url.endswith("/football/leagues/college-football")
    assert c.standings_url == "https://site.api.espn.com/apis/v2/sports/football/college-football"


def test_an_explicit_url_still_wins_over_the_league():
    c = FootballClient(
        base_url="http://fake/site/", core_url="http://fake/core/", session=FakeSession()
    )
    assert (c.base_url, c.core_url) == ("http://fake/site", "http://fake/core")


def test_an_unknown_league_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown football league"):
        FootballClient(league="cfl", session=FakeSession())


def test_the_college_scoreboard_asks_for_fbs_and_every_game():
    # Without groups=80 ESPN returns a curated 24 games, not the slate.
    c = college_client(FakeResponse(college_payload()))
    c.scores()
    url, params = c.session.calls[0]
    assert url == f"{COLLEGE}/scoreboard"
    assert params == {"groups": "80", "limit": "300"}


def test_a_date_and_a_week_are_added_to_the_college_parameters():
    c = college_client(FakeResponse(college_payload()))
    c.scores("20261114")
    assert c.session.calls[0][1] == {"groups": "80", "limit": "300", "dates": "20261114"}
    c = college_client(FakeResponse(college_payload()))
    c.week(12, 2)
    assert c.session.calls[0][1] == {
        "groups": "80",
        "limit": "300",
        "week": "12",
        "seasontype": "2",
    }


def test_the_college_parameters_are_not_shared_between_calls():
    c = college_client(FakeResponse(college_payload()))
    c.scores("20261114")
    c.scores()
    assert "dates" not in c.session.calls[1][1], "the first call's date leaked into the next"
    assert api.COLLEGE_SCOREBOARD_PARAMS == {"groups": "80", "limit": "300"}


def test_the_nfl_scoreboard_sends_no_college_parameters():
    c = FootballClient(session=FakeSession(FakeResponse(college_payload())))
    c.scores()
    assert c.session.calls[0][1] is None


def test_a_real_college_scoreboard_parses_into_games():
    games = college_client(FakeResponse(college_payload())).scores()
    # Best-first ordering is the client's own business; this test is about parsing.
    assert sorted((g.away.abbrev, g.home.abbrev) for g in games) == [
        ("CIN", "ISU"),
        ("MIZ", "UGA"),
        ("NMSU", "MOST"),
    ]
    by_id = {g.id: g for g in games}
    uga = by_id[401856883]
    assert (uga.home.score, uga.away.score) == (48, 21) and uga.is_final
    assert not uga.is_live and not uga.is_pregame


def test_an_overtime_final_is_still_a_final():
    games = college_client(FakeResponse(college_payload())).scores()
    ot = next(g for g in games if g.home.abbrev == "MOST")
    assert ot.is_final and "OT" in ot.detail


def test_college_standings_say_they_are_not_built_rather_than_returning_nfl_garbage():
    with pytest.raises(NotImplementedError, match="#553"):
        college_client(FakeResponse({})).standings()
