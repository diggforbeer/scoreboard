"""The idle screens' data (#421): parsers over the recorded responses, the cache, the client's
requests, and the feed worker publishing it without ever blocking the render loop.

Fixtures are the trimmed real responses in ``tests/fixtures/football/`` (see ``football_api.md``,
"Between games" and "Leaders and the playoffs")."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.api import STANDINGS_URL, NflClient
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.teams import TEAMS
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
NYG_ID = TEAMS["NYG"].espn_id


def load(name):
    return json.loads((FIXTURES / name).read_text())


def games_of(payload):
    return [FbGame.from_api(e) for e in payload["events"]]


# -- the scoreboard's week, byes and calendar ----------------------------------------


def test_the_week_and_the_teams_on_a_bye_come_from_the_scoreboard():
    payload = load("scoreboard_week8_byes_trimmed.json")
    board = idle.scoreboard_from_payload(payload, games_of(payload))
    assert (board.season_type, board.season_year, board.week) == (2, 2026, 8)
    assert board.teams_on_bye == ("NO", "NYG", "SF", "HOU")
    assert board.on_bye("nyg") and not board.on_bye("DAL")
    assert len(board.games) == 2


def test_the_calendar_has_every_week_and_the_postseason_rounds_and_the_off_season():
    cal = idle.calendar_from_payload({"leagues": [{"calendar": load("season_calendar.json")}]})
    assert len(cal) == 4 + 18 + 4 + 1
    week12 = next(c for c in cal if c.season_type == 2 and c.week == 12)
    assert (week12.label, week12.short_label) == ("Week 12", "Week 12")
    assert week12.start == datetime(2026, 11, 25, 8, 0, tzinfo=UTC)
    rounds = [c.short_label for c in cal if c.season_type == 3]
    assert rounds == ["Wild Card", "Div Rd", "Conf Champ", "Super Bowl"]
    off = next(c for c in cal if c.season_type == 4)
    assert off.week is None and off.label == "Off Season" and off.start < off.end


def test_an_empty_day_has_no_week_or_byes():
    payload = load("scoreboard_offseason_empty.json")
    board = idle.scoreboard_from_payload(payload, [])
    assert (board.week, board.season_type, board.teams_on_bye) == (None, None, ())
    assert board.games == ()
    assert board.calendar, "the calendar is still on the response (last season's, here)"


# -- the extra game fields -----------------------------------------------------------


def test_a_game_has_its_season_type_broadcast_and_records():
    final = games_of(load("scoreboard_leaders_trimmed.json"))[0]
    assert final.season_type == 2 and final.week == 10
    assert final.broadcasts == ("Prime Video",)
    assert final.home.record == "5-3-1" and final.home.abbrev == "NYG"


def test_only_a_finals_leaders_are_read_because_a_scheduled_games_are_season_totals():
    final, scheduled = games_of(load("scoreboard_leaders_trimmed.json"))
    assert final.is_final and [x.category for x in final.leaders] == [
        "passingYards", "rushingYards", "receivingYards",
    ]  # fmt: skip
    passing = final.leaders[0]
    assert (passing.name, passing.jersey, passing.position) == ("J.J. McCarthy", "18", "QB")
    assert passing.team_id == NYG_ID and passing.display.startswith("23/36, 293 YDS")
    assert scheduled.state == "pre" and scheduled.leaders == (), "season totals are never kept"


def test_a_game_with_no_broadcast_or_leaders_is_fine():
    final = load("scoreboard_leaders_trimmed.json")["events"][0]
    final["competitions"][0].pop("broadcasts")
    final["competitions"][0].pop("leaders")
    game = FbGame.from_api(final)
    assert game.broadcasts == () and game.leaders == ()


# -- a team's schedule ---------------------------------------------------------------


def schedule():
    return idle.schedule_from_payload(NYG_ID, load("schedule_NYG_trimmed.json"))


def test_a_schedule_has_the_bye_week_and_each_game_with_who_played_where():
    s = schedule()
    assert (s.team_id, s.season_year, s.bye_week) == (NYG_ID, 2026, 8)
    first = s.games[0]
    assert (first.week, first.home, first.away) == (1, "NYG", "DAL")
    assert (first.home_score, first.away_score, first.completed) == (28, 20, True)
    assert first.opponent("NYG") == "DAL" and first.is_home("NYG") and not first.is_home("DAL")
    last = s.games[-1]
    assert (last.week, last.status_name, last.completed) == (18, "STATUS_SCHEDULED", False)
    assert last.home_score is None and last.away_score is None


def test_games_come_in_date_order_and_the_next_game_is_the_first_not_yet_over():
    s = schedule()
    assert [g.week for g in s.games] == sorted(g.week for g in s.games)
    now = datetime(2026, 11, 14, tzinfo=UTC)
    assert [g.week for g in s.upcoming(now)] == [18]
    assert s.next_game(now).week == 18
    assert s.next_game(datetime(2027, 6, 1, tzinfo=UTC)) is None


def test_a_schedule_with_no_events_is_none_and_a_bad_event_is_skipped():
    assert idle.schedule_from_payload(NYG_ID, {"events": [], "byeWeek": 8}) is None
    payload = load("schedule_NYG_trimmed.json")
    payload["events"].insert(0, {"id": "x", "competitions": [{"competitors": []}]})
    assert len(idle.schedule_from_payload(NYG_ID, payload).games) == 3


# -- the standings -------------------------------------------------------------------


def standings():
    return idle.standings_from_payload(load("standings_trimmed.json"))


def test_the_standings_have_each_conferences_divisions_in_order_with_the_numbers_a_screen_needs():
    st = standings()
    assert [c.abbreviation for c in st.conferences] == ["AFC"]  # the fixture keeps one conference
    division = st.conferences[0].divisions[0]
    assert division.name == "AFC East"
    assert [r.team for r in division.rows] == ["BUF", "NE", "NYJ", "MIA"]
    buf = division.rows[0]
    assert (buf.overall, buf.wins, buf.losses, buf.ties) == ("7-1", 7, 1, 0)
    assert (buf.win_pct, buf.seed, buf.streak) == (".875", 1, "W4")
    assert (buf.points_for, buf.points_against) == (256, 187)


def test_seeds_are_in_seed_order_and_a_team_with_no_seed_is_unseeded_best_record_first():
    conf = standings().conferences[0]
    assert [r.seed for r in conf.seeds()] == sorted(r.seed for r in conf.seeds())
    assert all(r.seed is None for r in conf.unseeded())
    pcts = [r.win_pct for r in conf.unseeded()]
    assert pcts == sorted(pcts, reverse=True)


def test_a_team_finds_its_own_division_and_conference():
    st = standings()
    assert st.division_of("buf").name == "AFC East" and st.conference_of("NE").abbreviation == "AFC"
    assert st.division_of("NYG") is None and st.conference_of("NYG") is None


def test_no_conferences_means_no_standings():
    assert idle.standings_from_payload({}) is None
    assert idle.standings_from_payload({"children": [{"name": "AFC", "children": []}]}) is None


# -- the cache -----------------------------------------------------------------------


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_a_value_is_fetched_once_per_window_and_again_after_it():
    clock, calls = Clock(), []
    cache = idle.IdleCache(clock)

    def fetch():
        calls.append(clock.t)
        return len(calls)

    assert cache.refresh("k", 100.0, fetch).value == 1
    clock.t += 99
    assert cache.refresh("k", 100.0, fetch).value == 1 and len(calls) == 1
    clock.t += 2
    assert cache.refresh("k", 100.0, fetch).value == 2 and len(calls) == 2


def test_a_failure_keeps_the_last_good_value_and_is_not_retried_every_call():
    clock, calls = Clock(), []
    cache = idle.IdleCache(clock)
    cache.refresh("k", 10.0, lambda: "good")
    clock.t += 11

    def fail():
        calls.append(1)
        return None

    assert cache.refresh("k", 10.0, fail).value == "good"
    assert cache.refresh("k", 10.0, fail).value == "good" and len(calls) == 1, "not hammered"
    clock.t += idle.RETRY_SECONDS + 1
    cache.refresh("k", 10.0, fail)
    assert len(calls) == 2, "retried after the pause"


def test_an_exception_in_a_fetch_is_a_failure_not_a_crash():
    cache = idle.IdleCache(Clock())

    def boom():
        raise RuntimeError("feed exploded")

    assert cache.refresh("k", 10.0, boom) is None
    assert cache.refresh("k", 10.0, lambda: "later") is None, "still in the retry pause"


def test_with_nothing_good_yet_a_failure_returns_nothing():
    assert idle.IdleCache(Clock()).refresh("k", 10.0, lambda: None) is None


def test_forget_drops_what_is_no_longer_wanted_and_clear_drops_everything():
    cache = idle.IdleCache(Clock())
    cache.refresh(("schedule", 1), 10.0, lambda: "a")
    cache.refresh(("schedule", 2), 10.0, lambda: "b")
    cache.forget(lambda key: key[1] == 1)
    assert cache.refresh(("schedule", 2), 10.0, lambda: "fresh").value == "fresh"
    cache.clear()
    assert cache.refresh(("schedule", 1), 10.0, lambda: "again").value == "again"


def test_the_snapshot_reports_old_data_as_missing_rather_than_fresh():
    snap = idle.IdleSnapshot(
        schedules={1: idle.Cached("sched", 0.0)},
        standings_cached=idle.Cached("table", 0.0),
        week_cached=idle.Cached("week", 0.0),
    )
    assert (snap.schedule(1, 100.0), snap.standings(100.0), snap.week(100.0)) == (
        "sched", "table", "week",
    )  # fmt: skip
    stale = idle.STANDINGS_TTL * idle.STALE_FACTOR + 1
    assert snap.standings(stale) is None
    assert snap.week(idle.WEEK_TTL * idle.STALE_FACTOR + 1) is None
    assert snap.schedule(1, idle.SCHEDULE_TTL * idle.STALE_FACTOR - 1) == "sched"
    assert snap.schedule(2, 0.0) is None, "a team never fetched"


# -- the client's requests -----------------------------------------------------------


def client(*responses):
    return NflClient(session=FakeSession(*responses))


def test_the_client_asks_for_a_whole_week_with_its_season_type():
    c = client(FakeResponse(load("scoreboard_week8_byes_trimmed.json")))
    board = c.week(8, 2)
    url, params = c.session.calls[0]
    assert url.endswith("/scoreboard") and params == {"week": "8", "seasontype": "2"}
    assert board.week == 8 and board.teams_on_bye[0] == "NO"
    c = client(FakeResponse(load("scoreboard_postseason_w2.json")))
    assert c.week(2, 3).season_type == 3 and c.session.calls[0][1]["seasontype"] == "3"


def test_scores_is_still_the_games_and_none_for_no_data():
    c = client(FakeResponse(load("scoreboard_leaders_trimmed.json")))
    assert [g.home.abbrev for g in c.scores()] == ["NYG", "NE"] or len(c.scores()) == 2
    assert client(FakeResponse(status=500)).scores() is None
    assert client(FakeResponse(load("scoreboard_offseason_empty.json"))).scores() == []


def test_the_schedule_request_and_a_season_with_no_events():
    c = client(FakeResponse(load("schedule_NYG_trimmed.json")))
    s = c.schedule(NYG_ID)
    assert c.session.calls[0][0].endswith(f"/teams/{NYG_ID}/schedule") and s.bye_week == 8
    assert client(FakeResponse({"events": []})).schedule(NYG_ID) is None
    assert client(FakeResponse(status=404)).schedule(NYG_ID) is None


def test_the_standings_come_from_the_v2_base_with_level_three():
    c = client(FakeResponse(load("standings_trimmed.json")))
    st = c.standings()
    url, params = c.session.calls[0]
    assert url == f"{STANDINGS_URL}/standings" and params == {"level": "3"}
    assert "/apis/v2/" in url and "/apis/site/" not in url
    assert st.conferences and client(FakeResponse(status=500)).standings() is None


# -- the worker publishes it, the render loop only reads it --------------------------


class IdleFeed:
    """A fake ESPN client with the idle endpoints, counting each call."""

    def __init__(self, games, week=10):
        self.games = games
        self.week_number = week
        self.calls = []
        self.fail = set()
        self.last_error = ""

    def scoreboard(self):
        self.calls.append("scoreboard")
        return idle.Scoreboard(tuple(self.games), 2, 2026, self.week_number, ("CHI",), ())

    def schedule(self, team_id):
        self.calls.append(("schedule", team_id))
        return None if "schedule" in self.fail else idle.TeamSchedule(team_id, 2026, 8, ())

    def standings(self):
        self.calls.append("standings")
        return None if "standings" in self.fail else idle.Standings(())

    def week_games(self, number, kind):  # pragma: no cover - the name the client uses is ``week``
        raise AssertionError

    def close(self):
        pass

    def count(self, what):
        return sum(1 for c in self.calls if c == what or (isinstance(c, tuple) and c[0] == what))


def _week(self, number, kind):
    self.calls.append(("week", number, kind))
    return None if "week" in self.fail else idle.Scoreboard((), kind, 2026, number, (), ())


IdleFeed.week = _week


def pregame(game_id=1, home="NYG", away="WSH"):
    from test_football_scenes import game

    return game(away, home, "pre", short="x", start="2026-11-22T18:00Z", name="STATUS_SCHEDULED",
                game_id=game_id)  # fmt: skip


def live(game_id=2):
    from test_football_scenes import SIT, game

    return game("DAL", "PHI", "in", 3, 0, situation=SIT, game_id=game_id)


def make_mode(feed, clock, favourite="NYG", follow=()):
    cfg = FootballConfig(favourite_team=favourite, also_follow=list(follow))
    return NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)


def test_an_idle_poll_fetches_the_favourites_schedule_the_standings_and_the_week_once():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    assert feed.count("schedule") == 1 and feed.count("standings") == 1 and feed.count("week") == 1
    snap = mode.snapshot.idle
    assert snap.scoreboard.week == 10 and snap.scoreboard.teams_on_bye == ("CHI",)
    assert snap.schedule(NYG_ID, clock()) is not None and snap.standings(clock()) is not None
    assert snap.week(clock()).week == 10
    mode.worker.poll_once()
    mode.worker.poll_once()
    assert (feed.count("schedule"), feed.count("standings"), feed.count("week")) == (1, 1, 1)


def test_each_kind_of_data_is_fetched_again_on_its_own_cadence():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    clock.t += idle.WEEK_TTL + 1
    mode.worker.poll_once()
    assert (feed.count("week"), feed.count("standings"), feed.count("schedule")) == (2, 1, 1)
    clock.t += idle.STANDINGS_TTL
    mode.worker.poll_once()
    assert feed.count("standings") == 2 and feed.count("schedule") == 1
    clock.t += idle.SCHEDULE_TTL
    mode.worker.poll_once()
    assert feed.count("schedule") == 2


def test_followed_teams_schedules_are_fetched_too_and_a_team_that_is_not_nfl_is_skipped():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock, "NYG", ["DAL", "NSH"])  # NSH is NHL-only: dropped by the config
    mode.worker.poll_once()
    asked = sorted(c[1] for c in feed.calls if isinstance(c, tuple) and c[0] == "schedule")
    assert asked == sorted([NYG_ID, TEAMS["DAL"].espn_id])


def test_with_nobody_followed_only_the_scoreboards_extras_and_the_week_are_fetched():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock, favourite="")
    mode.worker.poll_once()
    assert feed.count("schedule") == 0 and feed.count("standings") == 0
    assert feed.count("week") == 1 and mode.snapshot.idle.scoreboard.week == 10


def test_nothing_is_fetched_while_a_game_is_live_and_the_last_data_is_kept():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    fetched = len(feed.calls)
    feed.games = [pregame(), live()]
    feed.week_number = 11
    clock.t += idle.SCHEDULE_TTL * 3
    mode.worker.poll_once()
    assert feed.calls[fetched:] == ["scoreboard"], "only the scoreboard poll itself"
    snap = mode.snapshot.idle
    assert snap.scoreboard.week == 11, "the week still follows the scoreboard"
    assert snap.schedules and snap.standings_cached is not None, "the old data is kept"


def test_a_failed_fetch_keeps_the_last_good_data_and_a_later_one_replaces_it():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    feed.fail = {"standings", "schedule", "week"}
    clock.t += idle.WEEK_TTL + idle.STANDINGS_TTL + idle.SCHEDULE_TTL
    mode.worker.poll_once()
    snap = mode.snapshot.idle
    assert snap.schedules[NYG_ID].fetched_at < clock.t and snap.standings_cached is not None
    assert snap.standings(clock.t) is None, "but old enough to be reported stale, not fresh"
    feed.fail = set()
    clock.t += idle.RETRY_SECONDS + 1
    mode.worker.poll_once()
    assert mode.snapshot.idle.standings(clock.t) is not None


def test_a_client_without_the_idle_endpoints_is_simply_skipped():
    from test_football_scenes import Feed

    clock = Clock()
    mode = NflMode(client_factory=lambda: Feed([pregame()]), monotonic=clock,
                   football=lambda: FootballConfig(favourite_team="NYG"))  # fmt: skip
    mode.worker.poll_once()
    assert mode.snapshot.games and mode.snapshot.idle.scoreboard is None
    assert mode.snapshot.idle.schedules == {}


def test_reading_the_scene_never_touches_the_client():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    before = len(feed.calls)
    for _ in range(50):
        mode.scene()
        _ = mode.snapshot.idle.week(clock())
    assert len(feed.calls) == before, "the render loop only reads the snapshot"


def test_stopping_the_mode_forgets_the_cache_so_a_restart_fetches_afresh():
    clock, feed = Clock(), IdleFeed([pregame()])
    mode = make_mode(feed, clock)
    mode.worker.poll_once()
    mode.stop()
    mode.worker.poll_once()
    assert feed.count("standings") == 2


def test_the_snapshots_default_has_nothing_and_does_not_raise():
    snap = idle.IdleSnapshot()
    assert snap.schedule(1, 0.0) is None and snap.standings(0.0) is None and snap.week(0.0) is None
    assert snap.scoreboard is None
    later = datetime(2026, 11, 14, tzinfo=UTC) + timedelta(days=1)
    assert later > datetime(2026, 11, 14, tzinfo=UTC)
