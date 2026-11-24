"""The college mode fetches the polls and puts a rank on each team of each game (#547 and friends).

Driven through the real worker and client over fixture payloads. The clock is pinned inside the
fixture polls' week, so the tests do not age.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scoreboard.config import ScoreboardConfig
from scoreboard.football.api import FootballClient
from scoreboard.football.mode import FootballMode
from scoreboard.football.models import FbTeam
from teamcfg import fcfg
from test_football_plays import FakeResponse

FIXTURES = Path(__file__).parent / "fixtures" / "football"
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
GEORGIA, NOTRE_DAME = 61, 87


def load(name):
    return json.loads((FIXTURES / name).read_text())


def scoreboard(away=(142, "MIZ"), state="post"):
    payload = load("college_scoreboard.json")
    event = payload["events"][0]
    payload["events"] = [event]
    competition = event["competitions"][0]
    side = next(c for c in competition["competitors"] if c["homeAway"] == "away")
    side["id"] = side["team"]["id"] = str(away[0])
    side["team"]["abbreviation"] = away[1]
    if state == "in":
        competition["status"]["type"].update(
            state="in", completed=False, name="STATUS_IN_PROGRESS", shortDetail="3:12 - 2nd"
        )
        competition["status"]["period"] = 2
    return payload


class RoutedSession:
    """Answers by URL, as the real server does: a request is never given another's payload."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        for tail, response in self.routes.items():
            if url.endswith(tail):
                return response
        return FakeResponse(status=404)

    def close(self):
        pass


class Feed(FootballClient):
    def __init__(self, board, rankings):
        routes = {
            "/standings": FakeResponse(load("college_standings_trimmed.json")),
            "/teams": FakeResponse(load("college_teams_trimmed.json")),
            "/scoreboard": FakeResponse(board),
        }
        if rankings is not None:
            routes["/rankings"] = rankings
        super().__init__(league="college-football", session=RoutedSession(routes))

    def schedule(self, team_id):
        return None

    def requested(self, tail):
        return sum(1 for url, _ in self.session.calls if url.endswith(tail))


def make(board=None, rankings="fixture", poll="ap", now=NOW, favourite="UGA", league="college"):
    if rankings == "fixture":
        rankings = FakeResponse(load("college_rankings_trimmed.json"))
    client = Feed(board or scoreboard(), rankings)
    cfg = fcfg(favourite_team=favourite, college_poll=poll)
    clock = {"now": now, "mono": 1000.0}
    mode = FootballMode(
        lambda: ScoreboardConfig(),
        client_factory=lambda: client,
        football=lambda: cfg,
        monotonic=lambda: clock["mono"],
        utc_now=lambda: clock["now"],
        league="college-football" if league == "college" else "nfl",
    )
    mode.clock = clock
    return mode, client


def test_a_team_has_no_rank_until_one_is_applied():
    assert FbTeam.from_api({"team": {"id": "61", "abbreviation": "UGA"}}).rank is None


def test_the_ranks_come_from_the_polls_and_not_the_game_feed():
    mode, _client = make()
    mode.worker.poll_once()
    (raw,) = mode.snapshot.games
    assert raw.home.rank is None and raw.away.rank is None, "the snapshot carries no ranks"
    (game,) = mode.ranked(mode.snapshot.games)
    assert game.home.rank == 1, "Georgia is #1"
    assert game.away.rank is None, "Missouri is not in this week's Top 25"
    assert mode.rank_of(GEORGIA) == 1 and mode.rank_of(142) is None and mode.rank_of(None) is None


def test_the_poll_setting_decides_which_number_a_team_has():
    ranks = {}
    for poll in ("ap", "cfp"):
        mode, _client = make(scoreboard(away=(NOTRE_DAME, "ND")), poll=poll)
        mode.worker.poll_once()
        (game,) = mode.ranked(mode.snapshot.games)
        ranks[poll] = game.away.rank
    assert ranks == {"ap": 3, "cfp": 6}


def test_polls_are_fetched_once_and_reused_while_fresh():
    mode, client = make()
    for _ in range(3):
        mode.worker.poll_once()
    assert client.requested("/rankings") == 1


def test_the_rank_survives_across_polls_and_the_idle_snapshot_keeps_the_polls():
    mode, _client = make()
    mode.worker.poll_once()
    mode.worker.poll_once()
    assert mode.snapshot.idle.polls() is not None
    assert mode.rank_of(GEORGIA) == 1


def test_polls_are_fetched_even_with_a_followed_game_live_but_only_the_first_time():
    # The idle fetches pause while a followed game is live; the badges still need the polls.
    mode, client = make(board=scoreboard(state="in"))
    mode.worker.poll_once()
    assert client.requested("/rankings") == 1 and mode.rank_of(GEORGIA) == 1
    mode.clock["now"] += timedelta(hours=2)
    mode.clock["mono"] += 7200  # past the poll's own window, and a followed game is still live
    mode.worker.poll_once()
    assert client.requested("/rankings") == 1, "not refetched mid-game"
    assert mode.rank_of(GEORGIA) == 1, "and the ranks do not vanish with it"


def test_a_poll_from_last_season_gives_nobody_a_rank():
    mode, _client = make(now=NOW + timedelta(days=200))
    mode.worker.poll_once()
    assert mode.rank_of(GEORGIA) is None
    (game,) = mode.ranked(mode.snapshot.games)
    assert game.home.rank is None


def test_no_polls_yet_means_no_ranks_and_no_crash():
    mode, _client = make(rankings=FakeResponse(status=500))
    mode.worker.poll_once()
    assert mode.snapshot.has_data and mode.snapshot.idle.polls() is None
    assert mode.rank_of(GEORGIA) is None
    assert [g.home.rank for g in mode.ranked(mode.snapshot.games)] == [None]


def test_the_scene_is_built_from_ranked_games():
    mode, _client = make(board=scoreboard(state="in"))
    mode.worker.poll_once()
    scene = mode.scene()
    assert scene.fb_game is not None and scene.fb_game.home.rank == 1


def test_an_nfl_mode_never_asks_for_the_polls_and_ranks_nobody():
    mode, client = make(league="nfl", rankings=None)
    mode.worker.poll_once()
    assert client.requested("/rankings") == 0 and mode.rank_of(1) is None
    assert all(g.home.rank is None for g in mode.ranked(mode.snapshot.games))
