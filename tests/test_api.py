from __future__ import annotations

import time

import pytest
import requests
import responses

from nhl_scoreboard.nhl.api import BASE_URL, NHLApiError, NHLClient


@pytest.fixture(autouse=True)
def _no_real_backoff(monkeypatch):
    """Retry tests below hit the real Retry(backoff_factor=0.5); skip the sleep."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)


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


# -- URL construction ------------------------------------------------------


@responses.activate
def test_scores_hits_score_date_and_returns_display_order(score_payload):
    """score.json lists finals first, then lives, then a future game; the
    client must re-sort to live -> upcoming -> final, each by start time."""
    responses.add(responses.GET, f"{BASE_URL}/score/now", json=score_payload, status=200)
    with NHLClient() as client:
        games = client.scores()
    assert [g.id for g in games] == [
        2026010010,
        2026010012,
        2026010014,
        2026020999,
        2026010008,
        2026010009,
        2026010011,
        2026010013,
    ]


@responses.activate
def test_scores_follows_the_score_now_redirect():
    """api-web.nhle.com 307-redirects /score/now -> /score/{date}; the app
    relies on this on every poll (see CLAUDE.md's NHL API notes)."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/score/now",
        status=307,
        headers={"Location": f"{BASE_URL}/score/2026-09-23"},
    )
    responses.add(responses.GET, f"{BASE_URL}/score/2026-09-23", json={"games": []}, status=200)
    with NHLClient() as client:
        assert client.scores() == []
    assert [c.request.url for c in responses.calls] == [
        f"{BASE_URL}/score/now",
        f"{BASE_URL}/score/2026-09-23",
    ]


@responses.activate
def test_schedule_upper_cases_and_strips_the_team_abbrev():
    responses.add(
        responses.GET, f"{BASE_URL}/club-schedule-season/NSH/now", json={"games": []}, status=200
    )
    with NHLClient() as client:
        assert client.schedule(" nsh ") == []
    assert responses.calls[0].request.url == f"{BASE_URL}/club-schedule-season/NSH/now"


@responses.activate
def test_schedule_sorts_by_start_time_regardless_of_payload_order():
    def game(game_id: int, start: str) -> dict:
        return {
            "id": game_id,
            "gameState": "FUT",
            "startTimeUTC": start,
            "awayTeam": {"abbrev": "AAA"},
            "homeTeam": {"abbrev": "BBB"},
        }

    responses.add(
        responses.GET,
        f"{BASE_URL}/club-schedule-season/NSH/now",
        json={
            "games": [
                game(3, "2026-10-03T00:00:00Z"),
                game(1, "2026-10-01T00:00:00Z"),
                game(2, "2026-10-02T00:00:00Z"),
            ]
        },
        status=200,
    )
    with NHLClient() as client:
        games = client.schedule("NSH")
    assert [g.id for g in games] == [1, 2, 3]


@responses.activate
def test_situation_url_and_parsed_payload():
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/42/landing",
        json={
            "situation": {
                "awayTeam": {"strength": 5, "situationDescriptions": ["PP"]},
                "homeTeam": {"strength": 4, "situationDescriptions": []},
                "timeRemaining": "1:23",
                "secondsRemaining": 83,
            }
        },
        status=200,
    )
    with NHLClient() as client:
        situation = client.situation(42)
    assert responses.calls[0].request.url == f"{BASE_URL}/gamecenter/42/landing"
    assert situation is not None
    assert situation.power_play_side() == "away"


@responses.activate
def test_situation_returns_none_when_key_is_absent():
    """No ``situation`` key at all -- the shape at even strength."""
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/landing", json={}, status=200)
    with NHLClient() as client:
        assert client.situation(1) is None


@responses.activate
def test_goal_scoring_url_and_parsed_payload():
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/42/landing",
        json={
            "summary": {
                "scoring": [
                    {
                        "goals": [
                            {
                                "teamAbbrev": "NSH",
                                "name": {"default": "F. Forsberg"},
                                "goalsToDate": 12,
                                "assists": [{"name": {"default": "J. Smith"}, "assistsToDate": 5}],
                                "strength": "pp",
                            }
                        ]
                    }
                ]
            }
        },
        status=200,
    )
    with NHLClient() as client:
        events = client.goal_scoring(42)
    assert responses.calls[0].request.url == f"{BASE_URL}/gamecenter/42/landing"
    assert [e.scorer_name for e in events] == ["F. Forsberg"]
    assert events[0].team_abbrev == "NSH"
    assert events[0].strength == "pp"


@responses.activate
def test_goal_scoring_returns_empty_when_scoring_is_absent():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/landing", json={}, status=200)
    with NHLClient() as client:
        assert client.goal_scoring(1) == ()


@responses.activate
def test_standings_hits_standings_date():
    responses.add(responses.GET, f"{BASE_URL}/standings/now", json={"standings": []}, status=200)
    with NHLClient() as client:
        assert client.standings() == []
    assert responses.calls[0].request.url == f"{BASE_URL}/standings/now"


# -- error wrapping ----------------------------------------------------------


@responses.activate
def test_get_wraps_a_4xx_status_as_nhl_api_error():
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=404)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


@responses.activate
def test_get_wraps_a_5xx_status_as_nhl_api_error():
    for _ in range(10):
        responses.add(responses.GET, f"{BASE_URL}/score/now", status=500)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


@responses.activate
def test_get_wraps_a_connection_error():
    responses.add(
        responses.GET, f"{BASE_URL}/score/now", body=requests.exceptions.ConnectionError("boom")
    )
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


@responses.activate
def test_get_wraps_a_timeout():
    responses.add(responses.GET, f"{BASE_URL}/score/now", body=requests.exceptions.Timeout("boom"))
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


@responses.activate
def test_get_wraps_invalid_json_body():
    responses.add(
        responses.GET,
        f"{BASE_URL}/score/now",
        body="not json",
        status=200,
        content_type="application/json",
    )
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


@responses.activate
def test_get_wraps_a_valid_json_but_non_object_body():
    responses.add(responses.GET, f"{BASE_URL}/score/now", json=[1, 2, 3], status=200)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()


# -- retry policy --------------------------------------------------------


@responses.activate
def test_get_retries_5xx_then_succeeds():
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=503)
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=503)
    responses.add(responses.GET, f"{BASE_URL}/score/now", json={"games": []}, status=200)
    with NHLClient() as client:
        assert client.scores() == []
    assert len(responses.calls) == 3


@responses.activate
def test_get_retries_429_then_succeeds():
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=429)
    responses.add(responses.GET, f"{BASE_URL}/score/now", json={"games": []}, status=200)
    with NHLClient() as client:
        assert client.scores() == []
    assert len(responses.calls) == 2


@responses.activate
def test_get_raises_once_retries_are_exhausted():
    for _ in range(10):
        responses.add(responses.GET, f"{BASE_URL}/score/now", status=503)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()
    # total=3 retries -> 1 initial attempt + 3 retries, then give up.
    assert len(responses.calls) == 4


@responses.activate
def test_get_does_not_retry_a_404():
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=404)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()
    assert len(responses.calls) == 1
