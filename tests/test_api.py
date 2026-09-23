from __future__ import annotations

import responses

from nhl_scoreboard.nhl.api import BASE_URL, NHLClient


@responses.activate
def test_scores_treats_explicit_null_games_like_absent():
    responses.add(responses.GET, f"{BASE_URL}/score/now", json={"games": None}, status=200)
    with NHLClient() as client:
        assert client.scores() == []


@responses.activate
def test_scores_skips_a_malformed_game_without_losing_the_rest():
    responses.add(
        responses.GET,
        f"{BASE_URL}/score/now",
        json={
            "games": [
                {"id": "not-an-id"},  # malformed: id can't be parsed as int
                {
                    "id": 1,
                    "gameState": "FUT",
                    "startTimeUTC": "2026-09-20T23:00:00Z",
                    "awayTeam": {"abbrev": "AAA"},
                    "homeTeam": {"abbrev": "BBB"},
                },
            ]
        },
        status=200,
    )
    with NHLClient() as client:
        games = client.scores()
    assert [g.id for g in games] == [1]


@responses.activate
def test_scores_ignores_a_null_entry_in_the_games_list():
    responses.add(
        responses.GET,
        f"{BASE_URL}/score/now",
        json={
            "games": [
                None,
                {
                    "id": 1,
                    "gameState": "FUT",
                    "startTimeUTC": "2026-09-20T23:00:00Z",
                    "awayTeam": {"abbrev": "AAA"},
                    "homeTeam": {"abbrev": "BBB"},
                },
            ]
        },
        status=200,
    )
    with NHLClient() as client:
        games = client.scores()
    assert [g.id for g in games] == [1]


@responses.activate
def test_standings_treats_explicit_null_like_absent():
    responses.add(responses.GET, f"{BASE_URL}/standings/now", json={"standings": None}, status=200)
    with NHLClient() as client:
        assert client.standings() == []


@responses.activate
def test_standings_skips_a_malformed_row():
    responses.add(
        responses.GET,
        f"{BASE_URL}/standings/now",
        json={"standings": [None, {"teamAbbrev": "NSH"}]},
        status=200,
    )
    with NHLClient() as client:
        rows = client.standings()
    assert [r.abbrev for r in rows] == ["NSH"]


@responses.activate
def test_situation_returns_none_for_a_malformed_payload():
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/1/landing",
        json={"situation": "not-an-object"},
        status=200,
    )
    with NHLClient() as client:
        assert client.situation(1) is None
