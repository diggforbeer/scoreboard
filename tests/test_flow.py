"""Favourite-mode flow: preview -> countdown -> live -> final (held) -> next preview.

The app takes an injectable wall clock and monotonic clock, so a whole game
day can be walked in a few lines without sleeping.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nhl_scoreboard.app import (
    LEADERS_TTL_SECONDS,
    SCHEDULE_TTL_SECONDS,
    SEASON_SERIES_TTL_SECONDS,
    STANDINGS_TTL_SECONDS,
    ScoreboardApp,
)
from nhl_scoreboard.config import RotationEntry, Settings
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import (
    ClubStats,
    Game,
    GoalEvent,
    SeasonSeriesRecord,
    SkaterLine,
    StandingsRow,
    Star,
)
from test_app import FakeGraphics, FakeMatrix, FakeOptions

FAV = "NSH"
PUCK_DROP = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)  # 7:00 PM Chicago on the 22nd
NEXT_DROP = datetime(2026, 9, 24, 23, 0, tzinfo=UTC)


def game(gid: int, away: str, home: str, start: datetime, state: str = "FUT", **extra) -> Game:
    raw = {
        "id": gid,
        "gameState": state,
        "startTimeUTC": start.isoformat().replace("+00:00", "Z"),
        "awayTeam": {"abbrev": away, "score": extra.get("away_score", 0)},
        "homeTeam": {"abbrev": home, "score": extra.get("home_score", 0)},
        "period": extra.get("period", 0),
        "periodDescriptor": {"number": extra.get("period", 1), "periodType": "REG"},
        "clock": {"timeRemaining": "12:34", "inIntermission": extra.get("intermission", False)},
    }
    return Game.from_api(raw)


def score(g: Game, *, home: int | None = None, away: int | None = None) -> Game:
    """Return g with an updated score -- Game.home/away are nested TeamSide."""
    changes = {}
    if home is not None:
        changes["home"] = dataclasses.replace(g.home, score=home)
    if away is not None:
        changes["away"] = dataclasses.replace(g.away, score=away)
    return dataclasses.replace(g, **changes)


def tick(app: ScoreboardApp, clock: Clock, **delta) -> None:
    """Advance time and poll, as the real loop would have every minute."""
    clock.advance(**delta)
    app.refresh()


class Clock:
    """Wall and monotonic time that advance together."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.mono = 1000.0

    def advance(self, **kwargs) -> None:
        delta = timedelta(**kwargs)
        self.now += delta
        self.mono += delta.total_seconds()


class RecordingHorn:
    """Fake GoalHornPlayer: records what would have played, plays nothing."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def play(self, abbrev: str) -> bool:
        self.calls.append(abbrev)
        return True


class FlowClient:
    def __init__(self) -> None:
        self.today: list[Game] = []
        self.season: list[Game] = []
        self.schedule_calls = 0
        self.fail_schedule = False
        self.standings_rows: list[StandingsRow] = []
        self.standings_calls = 0
        self.fail_standings = False
        self.goal_events: dict[int, tuple[GoalEvent, ...]] = {}
        #: game id -> tally; a missing id answers None, like a malformed payload.
        self.series: dict[int, SeasonSeriesRecord | None] = {}
        self.season_series_calls: list[int] = []
        self.fail_season_series = False
        self.club = ClubStats(skaters=(), goalies=())
        self.club_stats_calls: list[str] = []
        self.fail_club_stats = False
        self.stars: dict[int, tuple[Star, ...]] = {}
        self.three_stars_calls: list[int] = []
        self.fail_three_stars = False

    def club_stats(self, team, date="now"):
        self.club_stats_calls.append(team)
        if self.fail_club_stats:
            raise NHLApiError("boom")
        return self.club

    def season_series(self, game_id):
        self.season_series_calls.append(game_id)
        if self.fail_season_series:
            raise NHLApiError("boom")
        return self.series.get(game_id)

    def scores(self, date="now"):
        return list(self.today)

    def situation(self, game_id):
        return None

    def goal_scoring(self, game_id):
        return self.goal_events.get(game_id, ())

    def three_stars(self, game_id):
        self.three_stars_calls.append(game_id)
        if self.fail_three_stars:
            raise NHLApiError("boom")
        return self.stars.get(game_id, ())

    def schedule(self, team):
        self.schedule_calls += 1
        if self.fail_schedule:
            raise NHLApiError("boom")
        return sorted(self.season, key=lambda g: g.start_utc)

    def standings(self, date="now"):
        self.standings_calls += 1
        if self.fail_standings:
            raise NHLApiError("boom")
        return list(self.standings_rows)

    def close(self):
        pass


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


def make_app(fake_backend, clock: Clock, client: FlowClient, horn=None, **cfg) -> ScoreboardApp:
    settings = Settings()
    settings.scoreboard.favourite_team = FAV
    for k, v in cfg.items():
        setattr(settings.scoreboard, k, v)
    return ScoreboardApp(
        settings,
        client=client,
        backend=fake_backend,
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
        horn=horn or RecordingHorn(),
    )


@pytest.fixture
def day(fake_backend):
    """A game day: the favourite hosts TBL tonight, plays CAR in two days."""
    client = FlowClient()
    tonight = game(1, "TBL", FAV, PUCK_DROP)
    client.today = [
        game(9, "SEA", "CGY", PUCK_DROP - timedelta(hours=1), "LIVE", period=2),
        tonight,
    ]
    client.season = [
        game(0, FAV, "DAL", PUCK_DROP - timedelta(days=3), "OFF"),
        tonight,
        game(2, FAV, "CAR", NEXT_DROP),
        game(3, "COL", FAV, NEXT_DROP + timedelta(days=2)),
    ]
    clock = Clock(PUCK_DROP - timedelta(hours=6))
    app = make_app(fake_backend, clock, client)
    app.refresh()
    return app, clock, client


def scene(app):
    s = app.select_scene()
    return s.kind, (s.game.id if s.game else None)


def test_morning_of_the_game_is_a_preview(day):
    app, _, _ = day
    assert scene(app) == ("preview", 1)


def test_inside_the_countdown_window(day):
    app, clock, _ = day
    tick(app, clock, hours=4, minutes=30)  # 90 minutes to puck drop
    assert scene(app) == ("countdown", 1)


def test_countdown_window_is_configurable(day):
    app, _, _ = day
    app.settings.scoreboard.countdown_hours = 8
    assert scene(app) == ("countdown", 1)


def test_live_game_takes_priority(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)


def test_watched_final_holds_from_the_moment_it_ended(day):
    """Live -> final while running: the hold starts when we saw it end."""
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=2)
    tick(app, clock, hours=7)  # 1h into the game
    assert scene(app) == ("game", 1)

    client.today[1] = dataclasses.replace(client.today[1], state="FINAL", period=3)
    tick(app, clock, hours=1, minutes=40)  # we watch it finish
    assert scene(app) == ("game", 1)

    tick(app, clock, minutes=29)
    assert scene(app) == ("game", 1), "still inside final_hold_minutes"

    tick(app, clock, minutes=2)
    assert scene(app) == ("preview", 2), "hold expired: preview the next game"
    assert client.schedule_calls == 1


def test_startup_hours_after_the_game_does_not_hold_the_final(fake_backend):
    """The bug: booting at 11 PM after a 7 PM game showed FINAL for 30 minutes."""
    client = FlowClient()
    finished = game(1, "TBL", FAV, PUCK_DROP, "FINAL", period=3)
    client.today = [finished]
    client.season = [finished, game(2, FAV, "CAR", NEXT_DROP)]
    app = make_app(fake_backend, Clock(PUCK_DROP + timedelta(hours=4)), client)
    app.refresh()
    assert scene(app) == ("preview", 2)


def test_startup_shortly_after_the_game_still_holds_the_final(fake_backend):
    """Estimated end = start + 2h30; booting 10 minutes after that is inside the hold."""
    client = FlowClient()
    finished = game(1, "TBL", FAV, PUCK_DROP, "FINAL", period=3)
    client.today = [finished]
    client.season = [finished, game(2, FAV, "CAR", NEXT_DROP)]
    clock = Clock(PUCK_DROP + timedelta(hours=2, minutes=40))
    app = make_app(fake_backend, clock, client)
    app.refresh()
    assert scene(app) == ("game", 1)

    tick(app, clock, minutes=25)  # 35 minutes past the estimated end
    assert scene(app) == ("preview", 2)


def test_startup_during_a_game_that_ran_long_is_not_cut_short(fake_backend):
    """A game still final-less at start+2h30 is live; the estimate never applies."""
    client = FlowClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=3)]
    clock = Clock(PUCK_DROP + timedelta(hours=2, minutes=50))
    app = make_app(fake_backend, clock, client)
    app.refresh()
    assert scene(app) == ("game", 1)

    client.today[0] = dataclasses.replace(client.today[0], state="FINAL")
    tick(app, clock, minutes=5)  # watched it end at start+2h55
    tick(app, clock, minutes=25)
    assert scene(app) == ("game", 1), "hold runs from the observed end, not the estimate"


def test_final_hold_is_configurable(day):
    app, clock, client = day
    app.settings.scoreboard.final_hold_minutes = 5
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, minutes=6)
    assert scene(app) == ("preview", 2)


def test_next_preview_becomes_countdown_in_its_own_window(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)  # hold expired
    clock.now = NEXT_DROP - timedelta(minutes=45)
    app.refresh()
    assert scene(app) == ("countdown", 2)


def test_no_game_today_previews_the_next_one(fake_backend):
    client = FlowClient()
    client.today = [game(9, "SEA", "CGY", PUCK_DROP, "LIVE")]  # someone else's game
    client.season = [game(2, FAV, "CAR", NEXT_DROP)]
    app = make_app(fake_backend, Clock(PUCK_DROP), client)
    app.refresh()
    assert scene(app) == ("preview", 2)


def test_schedule_is_cached_for_an_hour(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)
    for _ in range(5):
        app.select_scene()
    assert client.schedule_calls == 1
    tick(app, clock, hours=1, seconds=1)
    app.select_scene()
    assert client.schedule_calls == 2


def test_schedule_failure_falls_back_to_rotation(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    client.fail_schedule = True
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)
    kind, gid = scene(app)
    assert kind == "game" and gid in {9, 1}, "no schedule: fall back to today's rotation"


def test_schedule_failure_backs_off_instead_of_polling_every_frame(day):
    """A schedule outage must not be re-hit on every select_scene() call (#60)."""
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    client.fail_schedule = True
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)  # hold expired: first schedule attempt happens here
    scene(app)
    assert client.schedule_calls == 1

    for _ in range(20):  # simulate ~10s of FRAME_INTERVAL polling with no time passing
        app.select_scene()
    assert client.schedule_calls == 1, "retries should back off, not fire every frame"

    tick(app, clock, seconds=SCHEDULE_TTL_SECONDS + 1)  # keeps refresh() fresh, unlike advance()
    app.select_scene()
    assert client.schedule_calls == 2, "a retry is still expected once the backoff elapses"


def test_draw_renders_every_scene_kind(day):
    """Each scene kind reaches the renderer without error."""
    app, clock, client = day
    app.draw()  # preview
    tick(app, clock, hours=5)
    app.draw()  # countdown
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE")
    app.refresh()
    app.draw()  # game
    assert app.matrix.swaps == 3


def test_fixture_file_still_parses_for_schedule_shape():
    """Season-schedule entries lack clock/period; from_api must cope."""
    raw = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())["games"][0]
    for key in ("clock", "period", "periodDescriptor", "goals"):
        raw.pop(key, None)
    g = Game.from_api(raw)
    assert g.is_final and g.period == 0


# --------------------------------------------------------------------------
# goal detection and the goal scene
# --------------------------------------------------------------------------


def test_goal_fires_horn_and_scene_on_a_favourite_score_increase(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)
    assert app.horn.calls == []

    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, minutes=1)
    assert app.horn.calls == [FAV]
    assert scene(app) == ("goal", 1)


def test_first_sighting_of_a_game_never_fires_a_goal(fake_backend):
    """A game already 3-1 at startup must not celebrate on the first poll."""
    client = FlowClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=2, home_score=3, away_score=1)]
    app = make_app(fake_backend, Clock(PUCK_DROP + timedelta(hours=1)), client)
    app.refresh()
    assert app.horn.calls == []
    assert scene(app) == ("game", 1)


def test_opponent_goal_does_not_fire(day):
    """The away team (TBL) scoring is not a home-team (NSH) celebration."""
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)

    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), away=1)
    tick(app, clock, minutes=1)
    assert app.horn.calls == []
    assert scene(app)[0] == "game"


def test_score_correction_downward_does_not_fire(day):
    app, clock, client = day
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=2)
    tick(app, clock, hours=6, minutes=5)  # 0 -> 2 against the fixture's baseline: a real goal
    assert app.horn.calls == [FAV]
    app.horn.calls.clear()

    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, minutes=1)  # a correction downward, not a goal
    assert app.horn.calls == []


def test_goal_scene_reverts_after_goal_flash_seconds(day):
    app, clock, client = day
    app.settings.scoreboard.goal_flash_seconds = 10
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    assert scene(app) == ("goal", 1)

    clock.advance(seconds=9)
    assert scene(app) == ("goal", 1), "still inside the flash window"

    clock.advance(seconds=2)
    assert scene(app) == ("game", 1), "flash window elapsed: back to the normal scene"


def test_goal_override_does_not_leak_onto_a_different_game(day):
    """A goal in game 1 must not paint a goal screen over some other game."""
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    assert app.last_goal is not None and app.last_goal[0] == 1

    from nhl_scoreboard.app import Scene

    unrelated = Scene("game", client.today[0])  # SEA @ CGY, unrelated game
    assert app._apply_goal_override(unrelated) is unrelated


def test_goal_does_not_override_countdown_or_preview(day):
    """A goal can only ever replace the exact 'game' scene it belongs to."""
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)

    from nhl_scoreboard.app import Scene

    preview = Scene("preview", client.season[2])
    assert app._apply_goal_override(preview) is preview
    countdown = Scene("countdown", client.season[2])
    assert app._apply_goal_override(countdown) is countdown


def test_no_favourite_team_never_detects_goals(fake_backend):
    client = FlowClient()
    client.today = [game(1, "TBL", "NSH", PUCK_DROP, "LIVE")]
    settings_app = ScoreboardApp(
        Settings.from_dict({"scoreboard": {"favourite_team": ""}}),
        client=client,
        backend=fake_backend,
        clock=lambda: PUCK_DROP,
        monotonic=lambda: 1000.0,
        horn=RecordingHorn(),
    )
    settings_app.refresh()
    client.today[0] = score(client.today[0], home=1)
    settings_app.refresh()
    assert settings_app.horn.calls == []


def test_draw_dispatches_goal_scene(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    assert scene(app) == ("goal", 1)
    app.draw()  # must not raise; exercises Renderer.draw_goal via the real dispatch
    assert app.matrix.swaps >= 1


# --------------------------------------------------------------------------
# goal detail (#122 phase 2) -- fires later, decoupled from the goal scene
# --------------------------------------------------------------------------


def goal_event(team=FAV, scorer="F. FORSBERG", goals=1, strength="ev") -> GoalEvent:
    return GoalEvent(
        team_abbrev=team,
        scorer_name=scorer,
        scorer_goals_to_date=goals,
        assists=(),
        strength=strength,
    )


def _score_the_favourite(client) -> None:
    """Live the tonight game and bump its score by one, as the earlier goal tests do."""
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)


def test_goal_detail_fires_after_the_goal_scene_once_landing_catches_up(day):
    """The score ticks up (score/now) before scoring (landing) has the entry -- #122's
    whole reason for two phases: goal detail must not wait on, or require, that."""
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    assert scene(app) == ("goal", 1)

    app.refresh_goal_details()  # landing still hasn't caught up: baseline only
    assert scene(app) == ("goal", 1)

    event = goal_event()
    client.goal_events[1] = (event,)
    app.refresh_goal_details()

    assert scene(app) == ("goal_detail", 1)
    assert app.select_scene().goal_event == event


def test_goal_detail_wins_over_the_goal_flash_when_both_are_pending(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    app.refresh_goal_details()  # baseline
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()  # landing already caught up within the same flash window

    assert scene(app) == ("goal_detail", 1)


def test_goal_detail_reverts_to_the_game_scene_after_goal_detail_seconds(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    app.settings.scoreboard.goal_detail_seconds = 10
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    app.refresh_goal_details()  # baseline
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()
    assert scene(app) == ("goal_detail", 1)

    clock.advance(seconds=9)
    assert scene(app) == ("goal_detail", 1), "still inside the detail window"

    clock.advance(seconds=2)
    assert scene(app) == ("game", 1), "detail window elapsed: back to the normal scene"


def test_goal_detail_override_does_not_leak_onto_a_different_game(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    app.refresh_goal_details()  # baseline
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()
    assert app._goal_detail is not None and app._goal_detail[0] == 1

    from nhl_scoreboard.app import Scene

    unrelated = Scene("game", client.today[0])  # SEA @ CGY, unrelated game
    assert app._apply_goal_override(unrelated) is unrelated


def test_goal_detail_does_not_override_countdown_or_preview(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    app.refresh_goal_details()  # baseline
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()

    from nhl_scoreboard.app import Scene

    preview = Scene("preview", client.season[2])
    assert app._apply_goal_override(preview) is preview
    countdown = Scene("countdown", client.season[2])
    assert app._apply_goal_override(countdown) is countdown


def test_draw_dispatches_goal_detail_scene(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _score_the_favourite(client)
    tick(app, clock, hours=6)
    client.today[1] = score(dataclasses.replace(client.today[1], state="LIVE", period=1), home=1)
    tick(app, clock, seconds=1)
    app.refresh_goal_details()  # baseline
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()
    assert scene(app) == ("goal_detail", 1)
    app.draw()  # must not raise; exercises Renderer.draw_goal_detail via the real dispatch
    assert app.matrix.swaps >= 1


# --------------------------------------------------------------------------
# three stars of the game -- #156
# --------------------------------------------------------------------------


def star(rank: int, team: str = FAV, name: str = "F. Forsberg", goals=1, assists=0) -> Star:
    return Star(
        star=rank,
        player_id=8470000 + rank,
        team_abbrev=team,
        name=name,
        sweater_no=9,
        position="L",
        goals=goals,
        assists=assists,
        points=goals + assists,
    )


STARS = (star(1), star(2, "TBL", "N. Kucherov", 0, 2), star(3, name="J. Saros", goals=0))


def _watch_the_favourite_go_final(app, clock, client) -> None:
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=2)
    tick(app, clock, hours=7)
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL", period=3)
    tick(app, clock, hours=1, minutes=40)


def test_three_stars_shows_once_landing_names_them(day):
    """FINAL can land in score/now before landing's threeStars -- poll until it's there."""
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 15
    _watch_the_favourite_go_final(app, clock, client)

    app.refresh_three_stars()  # landing hasn't named them yet
    assert client.three_stars_calls == [1]
    assert scene(app) == ("game", 1)

    client.stars[1] = STARS
    app.refresh_three_stars()  # inside live_poll_seconds: no refetch yet
    assert client.three_stars_calls == [1]

    clock.advance(seconds=15)
    app.refresh_three_stars()
    assert client.three_stars_calls == [1, 1]
    assert scene(app) == ("three_stars", 1)
    assert app.select_scene().stars == STARS


def test_three_stars_fetch_failure_is_retried(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    client.fail_three_stars = True
    app.refresh_three_stars()
    assert scene(app) == ("game", 1)

    client.fail_three_stars = False
    app.refresh_three_stars()
    assert scene(app) == ("three_stars", 1)


def test_three_stars_reverts_to_the_held_final_after_three_stars_seconds(day):
    app, clock, client = day
    app.settings.scoreboard.three_stars_seconds = 10
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    app.refresh_three_stars()
    assert scene(app) == ("three_stars", 1)

    clock.advance(seconds=9)
    assert scene(app) == ("three_stars", 1), "still inside the three-stars window"

    clock.advance(seconds=2)
    assert scene(app) == ("game", 1), "window elapsed: the normal held final takes over"


def test_three_stars_never_fires_twice_for_the_same_game(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    app.refresh_three_stars()
    assert app._three_stars is not None

    app._three_stars = None  # as if the on-screen window already elapsed
    tick(app, clock, seconds=30)
    app.refresh_three_stars()

    assert app._three_stars is None
    assert client.three_stars_calls == [1], "fetched once, never re-armed"


def test_three_stars_not_shown_after_a_restart_mid_hold(fake_backend, day):
    """Found already final at startup is a first sighting, not a transition -- a
    restart after the screen already showed (or should have) must not show it again."""
    _, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL", period=3)
    client.stars[1] = STARS
    clock.now = PUCK_DROP + timedelta(hours=2, minutes=40)  # inside the estimated hold
    restarted = make_app(fake_backend, clock, client)
    restarted.refresh()
    restarted.refresh_three_stars()

    assert scene(restarted) == ("game", 1)
    assert client.three_stars_calls == []


def test_three_stars_ignores_a_non_favourite_game_going_final(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    client.stars[9] = STARS
    client.today[0] = dataclasses.replace(client.today[0], state="FINAL")  # SEA @ CGY, watched
    tick(app, clock, minutes=5)
    app.refresh_three_stars()

    assert client.three_stars_calls == []
    assert app._three_stars is None


def test_three_stars_keeps_an_all_opponent_selection(day):
    """Stars are whoever the NHL named -- nothing filters them to the favourite."""
    app, clock, client = day
    _watch_the_favourite_go_final(app, clock, client)
    opponents = tuple(star(i, "TBL", f"P. Opponent{i}") for i in (1, 2, 3))
    client.stars[1] = opponents
    app.refresh_three_stars()

    assert app.select_scene().stars == opponents


def test_three_stars_stops_polling_once_the_final_hold_is_over(day):
    app, clock, client = day
    app.settings.scoreboard.live_poll_seconds = 0
    _watch_the_favourite_go_final(app, clock, client)
    app.refresh_three_stars()  # never named
    assert app._three_stars_pending

    tick(app, clock, minutes=31)
    app.refresh_three_stars()
    assert app._three_stars_pending == {}
    assert client.three_stars_calls == [1]


def test_three_stars_state_pruned_once_the_game_leaves_the_slate(day):
    app, clock, client = day
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    app.refresh_three_stars()
    assert app._three_stars_shown == {1}

    client.today = [g for g in client.today if g.id != 1]
    tick(app, clock, minutes=1)
    assert app._three_stars_shown == set()
    assert app._three_stars_pending == {}


def test_three_stars_pending_pruned_once_the_game_leaves_the_slate(day):
    app, clock, client = day
    _watch_the_favourite_go_final(app, clock, client)
    assert 1 in app._three_stars_pending

    client.today = [g for g in client.today if g.id != 1]
    tick(app, clock, minutes=1)
    app.refresh_three_stars()
    assert app._three_stars_pending == {}
    assert client.three_stars_calls == []


def test_three_stars_does_not_override_a_different_game(day):
    app, clock, client = day
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    app.refresh_three_stars()

    from nhl_scoreboard.app import Scene

    unrelated = Scene("game", client.today[0])
    assert app._apply_goal_override(unrelated) is unrelated


def test_draw_dispatches_three_stars_scene(day):
    app, clock, client = day
    _watch_the_favourite_go_final(app, clock, client)
    client.stars[1] = STARS
    app.refresh_three_stars()
    assert scene(app) == ("three_stars", 1)
    app.draw()  # must not raise; exercises Renderer.draw_three_stars via the real dispatch
    assert app.matrix.swaps >= 1


# --------------------------------------------------------------------------
# standings (playoff picture) scene -- #40
# --------------------------------------------------------------------------


def standings_row(abbrev, seq, points=20, games_played=19, conference="W"):
    return StandingsRow(
        abbrev=abbrev,
        conference=conference,
        division="C",
        division_sequence=1,
        wildcard_sequence=0,
        conference_sequence=seq,
        clinch_indicator="",
        points=points,
        games_played=games_played,
        wins=8,
        losses=8,
        ot_losses=3,
    )


def west_standings():
    """Ranked 4th-10th in a synthetic Western conference; NSH sits 6th."""
    return [
        standings_row("STL", 4, 45),
        standings_row("WPG", 5, 43),
        standings_row(FAV, 6, 42),
        standings_row("DAL", 7, 40),
        standings_row("COL", 8, 38),
        standings_row("CGY", 9, 36),
        standings_row("VGK", 10, 34),
    ]


def test_standings_suppressed_before_favourite_has_played(day):
    """games_played == 0 is the only signal the off-season final table isn't current (#40)."""
    app, clock, client = day
    client.standings_rows = [standings_row(FAV, 6, 42, games_played=0)]
    app.settings.scoreboard.rotate_seconds = 10
    tick(app, clock, seconds=10)  # lands in the "standings" half of the cadence
    assert scene(app)[0] == "preview"


def test_standings_suppressed_when_favourite_missing_from_standings(day):
    app, clock, client = day
    client.standings_rows = [standings_row("STL", 1, 45)]
    app.settings.scoreboard.rotate_seconds = 10
    tick(app, clock, seconds=10)
    assert scene(app)[0] == "preview"


def test_standings_suppressed_when_disabled(day):
    app, clock, client = day
    app.settings.scoreboard.show_standings = False
    app.settings.scoreboard.rotate_seconds = 10
    client.standings_rows = west_standings()
    tick(app, clock, seconds=10)
    assert scene(app)[0] == "preview"


def test_standings_alternates_with_preview_on_rotate_cadence(day):
    app, clock, client = day
    app.settings.scoreboard.rotate_seconds = 10
    client.standings_rows = west_standings()

    assert scene(app)[0] == "preview"

    tick(app, clock, seconds=10)
    s = app.select_scene()
    assert s.kind == "standings"
    assert [r.abbrev for r in s.standings] == ["STL", "WPG", FAV, "DAL", "COL"]

    tick(app, clock, seconds=10)
    assert scene(app)[0] == "preview"


def test_clock_stays_out_of_rotation_by_default(day):
    """show_clock_between_games is off by default -- existing installs see no change."""
    app, clock, _client = day
    for _ in range(6):
        assert scene(app)[0] != "clock"
        tick(app, clock, seconds=8)  # default rotate_seconds


def test_clock_joins_idle_rotation_when_enabled(day):
    app, clock, _client = day
    app.settings.scoreboard.show_clock_between_games = True
    app.settings.scoreboard.rotate_seconds = 10

    assert scene(app)[0] == "preview"

    tick(app, clock, seconds=10)
    assert scene(app)[0] == "clock"

    tick(app, clock, seconds=10)
    assert scene(app)[0] == "preview"


def test_clock_rotates_alongside_standings_and_preview(day):
    app, clock, client = day
    app.settings.scoreboard.show_clock_between_games = True
    app.settings.scoreboard.rotate_seconds = 10
    client.standings_rows = west_standings()

    kinds = []
    for _ in range(4):
        kinds.append(scene(app)[0])
        tick(app, clock, seconds=10)
    assert set(kinds) == {"preview", "standings", "clock"}, kinds
    # A full cycle is 3 slots wide; the 4th sample must repeat the 1st.
    assert kinds[3] == kinds[0]


def test_clock_between_games_never_interrupts_a_live_or_final_held_game(day):
    app, clock, client = day
    app.settings.scoreboard.show_clock_between_games = True
    app.settings.scoreboard.rotate_seconds = 10
    client.standings_rows = west_standings()
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)


def test_explicit_rotation_overrides_derived_default_with_per_entry_seconds(day):
    """An explicit [[rotation]] (#150) replaces the show_*/rotate_seconds-derived list entirely."""
    from nhl_scoreboard.config import RotationEntry

    app, clock, _client = day
    app.settings.rotation = [RotationEntry("clock", 3), RotationEntry("countdown_preview", 7)]

    assert scene(app)[0] == "clock"
    tick(app, clock, seconds=3)
    assert scene(app)[0] == "preview"
    tick(app, clock, seconds=7)
    assert scene(app)[0] == "clock"


def test_explicit_rotation_skips_unavailable_entries_and_falls_back(day):
    """An entry with nothing to show right now is skipped, not shown blank (#150 decision 2).

    Only "standings" is configured here -- not "countdown_preview" -- so even
    though there is an upcoming favourite game, it never appears; with
    standings itself ineligible (no rows), nothing in the rotation can be
    shown at all and the board falls back to cycling today's games by index.
    """
    from nhl_scoreboard.config import RotationEntry

    app, _clock, client = day
    client.standings_rows = []
    app.settings.rotation = [RotationEntry("standings", 5)]

    kind, gid = scene(app)
    assert kind == "game" and gid in {9, 1}


def test_standings_shown_when_no_more_games_are_scheduled(fake_backend):
    client = FlowClient()
    client.today = []
    client.season = []
    client.standings_rows = west_standings()
    app = make_app(fake_backend, Clock(PUCK_DROP), client)
    app.refresh()
    assert scene(app) == ("standings", None)


def test_standings_never_interrupts_a_live_or_final_held_game(day):
    app, clock, client = day
    client.standings_rows = west_standings()
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)


def test_standings_cached_for_an_hour(day):
    app, clock, client = day
    client.standings_rows = west_standings()
    for _ in range(5):
        app.select_scene()
    assert client.standings_calls == 1

    tick(app, clock, hours=1, seconds=1)
    app.select_scene()
    assert client.standings_calls == 2


def test_standings_fetch_failure_falls_back_to_preview(day):
    app, _clock, client = day
    client.fail_standings = True
    assert scene(app)[0] == "preview"


def test_standings_failure_backs_off_instead_of_polling_every_frame(day):
    """A standings outage must not be re-hit on every select_scene() call (#60)."""
    app, clock, client = day
    client.fail_standings = True
    app.settings.scoreboard.rotate_seconds = 10

    scene(app)  # first attempt
    assert client.standings_calls == 1

    for _ in range(20):  # simulate ~10s of FRAME_INTERVAL polling with no time passing
        app.select_scene()
    assert client.standings_calls == 1, "retries should back off, not fire every frame"

    tick(app, clock, seconds=STANDINGS_TTL_SECONDS + 1)  # keeps refresh() fresh, unlike advance()
    app.select_scene()
    assert client.standings_calls == 2, "a retry is still expected once the backoff elapses"


# -- matchup / season series (#157) -------------------------------------------


def test_matchup_never_in_the_implicit_default_rotation(day):
    """Opt-in only: a board with no [[rotation]] never shows it, or even fetches it."""
    app, clock, client = day
    app.settings.scoreboard.show_clock_between_games = True
    app.settings.scoreboard.rotate_seconds = 10
    client.standings_rows = west_standings()
    client.series[1] = SeasonSeriesRecord(2, 1)
    for _ in range(8):
        assert scene(app)[0] != "matchup"
        tick(app, clock, seconds=10)
    assert client.season_series_calls == []


def test_matchup_shown_when_listed_in_rotation(day):
    app, clock, client = day
    client.series[1] = SeasonSeriesRecord(away_wins=1, home_wins=2)
    app.settings.rotation = [RotationEntry("countdown_preview", 5), RotationEntry("matchup", 5)]

    assert scene(app) == ("preview", 1)
    tick(app, clock, seconds=5)
    s = app.select_scene()
    assert (s.kind, s.game.id) == ("matchup", 1)
    assert s.season_series == SeasonSeriesRecord(1, 2)
    assert client.season_series_calls == [1], "keyed on the upcoming game's own id"
    tick(app, clock, seconds=5)
    assert scene(app) == ("preview", 1)


def test_matchup_preseason_zero_zero_still_shows(day):
    """0-0 is a real answer (preseason, or no meeting finished yet), not "nothing to show"."""
    app, _clock, client = day
    client.series[1] = SeasonSeriesRecord(0, 0)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    s = app.select_scene()
    assert s.kind == "matchup"
    assert s.season_series == SeasonSeriesRecord(0, 0)


def test_matchup_skipped_when_api_has_no_usable_tally(day):
    app, clock, client = day
    client.series = {}  # season_series() -> None, as for a missing/malformed payload
    app.settings.rotation = [RotationEntry("countdown_preview", 5), RotationEntry("matchup", 5)]
    for _ in range(4):
        assert scene(app) == ("preview", 1)
        tick(app, clock, seconds=5)


def test_matchup_skipped_with_no_upcoming_game(fake_backend):
    client = FlowClient()
    client.today = []
    client.season = []
    app = make_app(fake_backend, Clock(PUCK_DROP), client)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    app.refresh()
    assert scene(app)[0] == "clock"  # show_clock_when_idle's fallback, not a blank matchup
    assert client.season_series_calls == []
    assert app._matchup_scene(None) is None


def test_matchup_not_shown_before_fetch_has_completed(day):
    """The status page (allow_fetch=False) with nothing cached: skipped, and no fetch."""
    app, _clock, client = day
    client.series[1] = SeasonSeriesRecord(2, 1)
    app.settings.rotation = [RotationEntry("countdown_preview", 5), RotationEntry("matchup", 5)]
    for _ in range(3):
        assert app.select_scene(allow_fetch=False).kind == "preview"
    assert client.season_series_calls == []


def test_matchup_cached_for_its_ttl(day):
    app, clock, client = day
    client.series[1] = SeasonSeriesRecord(2, 1)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    for _ in range(20):
        app.select_scene()
    assert client.season_series_calls == [1]

    client.series[1] = SeasonSeriesRecord(3, 1)
    tick(app, clock, seconds=SEASON_SERIES_TTL_SECONDS + 1)
    assert app.select_scene().season_series == SeasonSeriesRecord(3, 1)
    assert client.season_series_calls == [1, 1]


def test_matchup_failure_backs_off_instead_of_polling_every_frame(day):
    app, clock, client = day
    client.fail_season_series = True
    app.settings.rotation = [RotationEntry("countdown_preview", 5), RotationEntry("matchup", 5)]

    for _ in range(20):
        assert scene(app)[0] == "preview"
    assert client.season_series_calls == [1]

    client.fail_season_series = False
    client.series[1] = SeasonSeriesRecord(2, 1)
    tick(app, clock, seconds=SEASON_SERIES_TTL_SECONDS + 5)  # past backoff, on the matchup slot
    assert scene(app) == ("matchup", 1)
    assert client.season_series_calls == [1, 1]


def test_matchup_failed_refresh_keeps_serving_the_cached_tally(day):
    app, clock, client = day
    client.series[1] = SeasonSeriesRecord(2, 1)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    assert app.select_scene().season_series == SeasonSeriesRecord(2, 1)

    client.fail_season_series = True
    tick(app, clock, seconds=SEASON_SERIES_TTL_SECONDS + 1)
    assert app.select_scene().season_series == SeasonSeriesRecord(2, 1)
    assert len(client.season_series_calls) == 2


def test_matchup_cache_follows_the_upcoming_game(day):
    """A new upcoming matchup fetches its own tally; the old one isn't kept around."""
    app, _clock, client = day
    client.series = {1: SeasonSeriesRecord(2, 1), 2: SeasonSeriesRecord(0, 1)}
    tonight, next_game = client.season[1], client.season[2]
    assert app._matchup_scene(tonight).season_series == SeasonSeriesRecord(2, 1)
    assert app._matchup_scene(next_game).season_series == SeasonSeriesRecord(0, 1)
    assert client.season_series_calls == [1, 2]
    assert set(app._season_series) == {2}


def test_matchup_never_interrupts_a_live_game(day):
    app, clock, client = day
    client.series[1] = SeasonSeriesRecord(2, 1)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)


def test_draw_dispatches_matchup_scene(day):
    app, _clock, client = day
    client.series[1] = SeasonSeriesRecord(2, 1)
    app.settings.rotation = [RotationEntry("matchup", 5)]
    assert scene(app)[0] == "matchup"
    app.draw()  # must not raise; exercises Renderer.draw_matchup via the real dispatch
    assert app.matrix.swaps == 1


def test_draw_dispatches_standings_scene(fake_backend):
    client = FlowClient()
    client.today = []
    client.season = []
    client.standings_rows = west_standings()
    app = make_app(fake_backend, Clock(PUCK_DROP), client)
    app.refresh()
    assert scene(app)[0] == "standings"
    app.draw()  # must not raise; exercises Renderer.draw_standings via the real dispatch
    assert app.matrix.swaps == 1


# -- leaders / favourite's top players (#201) ---------------------------------


def _club() -> ClubStats:
    return ClubStats(
        skaters=(SkaterLine(1, "A. One", 0, 0, 0), SkaterLine(2, "B. Two", 0, 0, 0)),
        goalies=(),
    )


def test_leaders_never_in_the_implicit_default_rotation(day):
    app, clock, client = day
    client.club = _club()
    for _ in range(6):
        tick(app, clock, seconds=7)
        assert scene(app)[0] != "leaders"
    assert client.club_stats_calls == []


def test_leaders_shown_when_listed_even_with_everyone_at_zero(day):
    app, _, client = day
    client.club = _club()
    app.settings.rotation = [RotationEntry("leaders", 5)]
    s = app.select_scene()
    assert s.kind == "leaders"
    assert s.leaders.goals.name in {"A. One", "B. Two"}
    assert client.club_stats_calls == [FAV]


def test_leaders_pick_is_stable_between_frames(day):
    app, _, client = day
    client.club = ClubStats(tuple(SkaterLine(i, f"P. {i}", 0, 0, 0) for i in range(30)), ())
    app.settings.rotation = [RotationEntry("leaders", 5)]
    first = app.select_scene().leaders
    assert all(app.select_scene().leaders == first for _ in range(5))
    assert len(client.club_stats_calls) == 1


def test_leaders_skipped_before_the_season_has_any_players(day):
    app, _, _client = day
    app.settings.rotation = [RotationEntry("countdown_preview", 5), RotationEntry("leaders", 5)]
    assert scene(app)[0] == "preview"  # empty arrays: skipped, not drawn blank
    assert app._leaders_scene() is None


def test_leaders_cached_then_refetched_after_ttl(day):
    app, clock, client = day
    client.club = _club()
    app.settings.rotation = [RotationEntry("leaders", 5)]
    app.select_scene()
    app.select_scene()
    assert len(client.club_stats_calls) == 1
    tick(app, clock, seconds=LEADERS_TTL_SECONDS + 1)
    app.select_scene()
    assert len(client.club_stats_calls) == 2


def test_leaders_failure_backs_off_and_keeps_cached(day):
    app, clock, client = day
    client.club = _club()
    app.settings.rotation = [RotationEntry("leaders", 5)]
    first = app.select_scene().leaders
    client.fail_club_stats = True
    tick(app, clock, seconds=LEADERS_TTL_SECONDS + 1)
    assert app.select_scene().leaders == first
    app.select_scene()
    assert len(client.club_stats_calls) == 2, "failure must not retry every frame"


def test_leaders_skipped_with_no_favourite(day):
    app, _, client = day
    client.club = _club()
    app.settings.scoreboard.favourite_team = ""
    app.settings.rotation = [RotationEntry("leaders", 5)]
    assert app._leaders_scene() is None
    assert client.club_stats_calls == []
