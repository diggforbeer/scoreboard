from __future__ import annotations

import time
from datetime import date

import pytest
import requests
import responses

from nhl_scoreboard.nhl.api import BASE_URL, NHLApiError, NHLClient
from nhl_scoreboard.nhl.models import (
    ClubStats,
    GoalieLine,
    SeasonSeriesRecord,
    SeriesMeeting,
    SkaterLine,
)


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
def test_team_roster_combines_roster_and_club_stats():
    """Two calls, one lookup (#124) -- neither endpoint alone has both
    sweaterNumber and points, confirmed live against the real API."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/roster/NSH/current",
        json={
            "forwards": [{"id": 1, "sweaterNumber": 9}],
            "defensemen": [{"id": 2, "sweaterNumber": 55}],
            "goalies": [{"id": 3, "sweaterNumber": 74}],
        },
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE_URL}/club-stats/NSH/now",
        json={
            "skaters": [{"playerId": 1, "points": 40}, {"playerId": 2, "points": 20}],
            "goalies": [{"playerId": 3, "points": 0}],
        },
        status=200,
    )
    with NHLClient() as client:
        roster = client.team_roster("nsh")
    urls = [c.request.url for c in responses.calls]
    assert f"{BASE_URL}/roster/NSH/current" in urls
    assert f"{BASE_URL}/club-stats/NSH/now" in urls
    assert roster[1].sweater_number == 9
    assert roster[1].points == 40
    assert roster[2].sweater_number == 55
    assert roster[2].points == 20
    assert roster[3].sweater_number == 74
    assert roster[3].points == 0


@responses.activate
def test_team_roster_omits_a_player_missing_from_either_side():
    responses.add(
        responses.GET,
        f"{BASE_URL}/roster/NSH/current",
        json={"forwards": [{"id": 1, "sweaterNumber": 9}, {"id": 2, "sweaterNumber": 55}]},
        status=200,
    )
    responses.add(
        responses.GET,
        f"{BASE_URL}/club-stats/NSH/now",
        json={"skaters": [{"playerId": 1, "points": 40}]},
        status=200,
    )
    with NHLClient() as client:
        roster = client.team_roster("NSH")
    assert set(roster) == {1}


@responses.activate
def test_three_stars_url_and_parsed_payload():
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/42/landing",
        json={
            "threeStars": [
                {
                    "star": 1,
                    "playerId": 8484392,
                    "teamAbbrev": "CAR",
                    "name": {"default": "F. Unger Sorum"},
                    "sweaterNo": 36,
                    "position": "R",
                    "goals": 1,
                    "assists": 0,
                    "points": 1,
                }
            ]
        },
        status=200,
    )
    with NHLClient() as client:
        stars = client.three_stars(42)
    assert responses.calls[0].request.url == f"{BASE_URL}/gamecenter/42/landing"
    assert [(s.star, s.name, s.team_abbrev, s.goals) for s in stars] == [
        (1, "F. Unger Sorum", "CAR", 1)
    ]


@responses.activate
def test_three_stars_empty_until_named():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/landing", json={}, status=200)
    with NHLClient() as client:
        assert client.three_stars(1) == ()


@responses.activate
def test_season_series_url_and_parsed_payload():
    """Trimmed from a real right-rail response (CGY @ NSH, 2025-10-18): NSH 3-0 at home."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/2025020183/right-rail",
        json={
            "seasonSeriesWins": {"awayTeamWins": 0, "homeTeamWins": 3},
            "seasonSeries": [
                {
                    "id": 2025020183,
                    "gameDate": "2025-10-18",
                    "gameType": 2,
                    "gameState": "OFF",
                    "awayTeam": {"abbrev": "CGY", "score": 1},
                    "homeTeam": {"abbrev": "NSH", "score": 4},
                    "gameOutcome": {"lastPeriodType": "REG"},
                }
            ],
        },
        status=200,
    )
    with NHLClient() as client:
        record = client.season_series(2025020183)
    assert (record.away_wins, record.home_wins) == (0, 3)
    assert record.meetings == (
        SeriesMeeting(2025020183, date(2025, 10, 18), "CGY", "NSH", 1, 4, "REG"),
    )
    assert responses.calls[0].request.url == f"{BASE_URL}/gamecenter/2025020183/right-rail"


@responses.activate
def test_season_series_preseason_zero_zero_is_a_real_answer():
    """Verified live: before any regular-season meeting finishes, 0-0, not absent."""
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/1/right-rail",
        json={"seasonSeriesWins": {"awayTeamWins": 0, "homeTeamWins": 0}, "seasonSeries": []},
        status=200,
    )
    with NHLClient() as client:
        assert client.season_series(1) == SeasonSeriesRecord(0, 0)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"seasonSeriesWins": None},
        {"seasonSeriesWins": "2-1"},
        {"seasonSeriesWins": {"awayTeamWins": 2}},
        {"seasonSeriesWins": {"awayTeamWins": "2", "homeTeamWins": 1}},
        {"seasonSeriesWins": {"awayTeamWins": True, "homeTeamWins": 1}},
        {"seasonSeriesWins": {"awayTeamWins": -1, "homeTeamWins": 1}},
    ],
)
@responses.activate
def test_season_series_returns_none_for_missing_or_malformed_wins(payload):
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/right-rail", json=payload, status=200)
    with NHLClient() as client:
        assert client.season_series(1) is None


def _meeting(gid, day, state="OFF", away=("NSH", 2), home=("MIN", 3), period="REG", **extra):
    entry = {
        "id": gid,
        "gameDate": day,
        "gameType": 2,
        "gameState": state,
        "awayTeam": {"abbrev": away[0], "score": away[1]},
        "homeTeam": {"abbrev": home[0], "score": home[1]},
        "gameOutcome": {"lastPeriodType": period},
    }
    entry.update(extra)
    return entry


@responses.activate
def test_season_series_meetings_finished_regular_season_only_oldest_first():
    """Shape from real 2025-26 right-rail responses (#168): a future meeting
    has no scores but still reads lastPeriodType REG, so it must not count."""
    future = _meeting(5, "2026-03-01", state="FUT")
    del future["awayTeam"]["score"], future["homeTeam"]["score"]
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/1/right-rail",
        json={
            "seasonSeriesWins": {"awayTeamWins": 1, "homeTeamWins": 2},
            "seasonSeries": [
                _meeting(4, "2026-01-10", away=("MIN", 2), home=("NSH", 3), period="OT"),
                _meeting(2, "2025-10-14", away=("NSH", 4), home=("MIN", 1)),
                future,
                _meeting(6, "2026-04-20", gameType=3),  # a playoff game: not the series
                _meeting(7, "2026-02-01", state="LIVE"),  # in progress: no result yet
                _meeting(3, "2025-12-02"),
            ],
        },
        status=200,
    )
    with NHLClient() as client:
        meetings = client.season_series(1).meetings
    assert [m.game_id for m in meetings] == [2, 3, 4]
    assert meetings[2].last_period_type == "OT"


@pytest.mark.parametrize(
    "entry",
    [
        None,
        "2-1",
        {"gameType": 2, "gameState": "OFF"},
        _meeting(1, "not a date"),
        _meeting(1, "2025-10-14", away=("NSH", None)),
        _meeting(1, "2025-10-14", away=("NSH", True)),
        _meeting(1, "2025-10-14", away=(None, 2)),
        _meeting(1, "2025-10-14", away=("NSH", 3)),  # 3-3 is no finished game
    ],
)
@responses.activate
def test_season_series_skips_malformed_meetings_but_keeps_the_tally(entry):
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/1/right-rail",
        json={
            "seasonSeriesWins": {"awayTeamWins": 1, "homeTeamWins": 0},
            "seasonSeries": [entry, _meeting(2, "2025-11-01")],
        },
        status=200,
    )
    with NHLClient() as client:
        record = client.season_series(1)
    assert (record.away_wins, record.home_wins) == (1, 0)
    assert [m.game_id for m in record.meetings] == [2]


@responses.activate
def test_season_series_without_a_meetings_list_still_has_the_tally():
    responses.add(
        responses.GET,
        f"{BASE_URL}/gamecenter/1/right-rail",
        json={"seasonSeriesWins": {"awayTeamWins": 0, "homeTeamWins": 0}},
        status=200,
    )
    with NHLClient() as client:
        assert client.season_series(1) == SeasonSeriesRecord(0, 0)


@responses.activate
def test_season_series_wraps_http_errors():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/right-rail", status=404)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.season_series(1)


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


def test_a_stalled_server_gets_one_retry_not_three():
    """Every fetch blocks the render loop: a server that accepts and never
    answers must cost two timeouts, not four (2026-10-10's ~44s freezes)."""
    import socket
    import threading

    accepted = []
    stop = threading.Event()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(0.1)

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            accepted.append(conn)  # hold it open, never reply

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        port = listener.getsockname()[1]
        with (
            NHLClient(base_url=f"http://127.0.0.1:{port}", timeout=(1.0, 0.2)) as client,
            pytest.raises(NHLApiError),
        ):
            client.scores()
        assert len(accepted) == 2
    finally:
        stop.set()
        thread.join(timeout=2)
        for conn in accepted:
            conn.close()
        listener.close()


def test_default_timeout_is_short_enough_for_the_render_loop():
    from nhl_scoreboard.nhl.api import TIMEOUT

    connect, read = TIMEOUT
    assert read <= 5.0 and connect <= 5.0
    assert NHLClient().timeout == TIMEOUT


@responses.activate
def test_get_does_not_retry_a_404():
    responses.add(responses.GET, f"{BASE_URL}/score/now", status=404)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.scores()
    assert len(responses.calls) == 1


@responses.activate
def test_club_stats_url_and_parsed_payload():
    responses.add(
        responses.GET,
        f"{BASE_URL}/club-stats/NSH/now",
        json={
            "season": "20252026",
            "gameType": 2,
            "skaters": [
                {
                    "playerId": 1,
                    "firstName": {"default": "Filip"},
                    "lastName": {"default": "Forsberg"},
                    "gamesPlayed": 70,
                    "goals": 30,
                    "assists": 20,
                    "points": 50,
                },
                {"garbage": True, "playerId": "x"},
            ],
            "goalies": [
                {
                    "playerId": 3,
                    "firstName": {"default": "Juuse"},
                    "lastName": {"default": "Saros"},
                    "gamesPlayed": 60,
                    "wins": 30,
                    "losses": 20,
                    "overtimeLosses": 5,
                    "savePercentage": 0.9151,
                }
            ],
        },
        status=200,
    )
    with NHLClient() as client:
        stats = client.club_stats("nsh")
    assert stats == ClubStats(
        skaters=(SkaterLine(1, "F. Forsberg", 30, 20, 50),),
        goalies=(GoalieLine(3, "J. Saros", 60, 30, 20, 5, 0.9151),),
    )


@responses.activate
def test_club_stats_empty_preseason_arrays():
    responses.add(
        responses.GET,
        f"{BASE_URL}/club-stats/NSH/now",
        json={"season": "20262027", "gameType": 2, "skaters": [], "goalies": []},
        status=200,
    )
    with NHLClient() as client:
        assert client.club_stats("NSH") == ClubStats((), ())


@responses.activate
def test_club_stats_wraps_http_errors():
    responses.add(responses.GET, f"{BASE_URL}/club-stats/NSH/now", status=404)
    with NHLClient() as client, pytest.raises(NHLApiError):
        client.club_stats("NSH")


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _landing_calls(game_id: int) -> int:
    url = f"{BASE_URL}/gamecenter/{game_id}/landing"
    return sum(1 for call in responses.calls if call.request.url == url)


@responses.activate
def test_situation_scoring_and_stars_share_one_landing_request():
    """One request per game per poll, not one per feature (#263)."""
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/42/landing", json={}, status=200)
    clock = _Clock()
    with NHLClient(monotonic=clock) as client:
        client.situation(42)
        clock.now += 4
        client.goal_scoring(42)
        client.three_stars(42)
    assert _landing_calls(42) == 1


@responses.activate
def test_landing_is_refetched_once_the_reuse_window_passes():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/42/landing", json={}, status=200)
    clock = _Clock()
    with NHLClient(monotonic=clock) as client:
        client.situation(42)
        clock.now += 5
        client.situation(42)
    assert _landing_calls(42) == 2


@responses.activate
def test_landing_reuse_is_per_game():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/landing", json={}, status=200)
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/2/landing", json={}, status=200)
    with NHLClient(monotonic=_Clock()) as client:
        client.situation(1)
        client.situation(2)
        client.goal_scoring(1)
        client.goal_scoring(2)
    assert (_landing_calls(1), _landing_calls(2)) == (1, 1)


@responses.activate
def test_a_failed_landing_fetch_is_not_reused():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/42/landing", status=404)
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/42/landing", json={}, status=200)
    with NHLClient(monotonic=_Clock()) as client:
        with pytest.raises(NHLApiError):
            client.situation(42)
        assert client.goal_scoring(42) == ()
    assert _landing_calls(42) == 2


@responses.activate
def test_stale_landings_for_other_games_are_dropped():
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/1/landing", json={}, status=200)
    responses.add(responses.GET, f"{BASE_URL}/gamecenter/2/landing", json={}, status=200)
    clock = _Clock()
    with NHLClient(monotonic=clock) as client:
        client.situation(1)
        clock.now += 60
        client.situation(2)
        assert set(client._landings) == {2}
