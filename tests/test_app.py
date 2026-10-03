"""Tests for the run loop, using a fake matrix backend.

The real backends need either a Pi or a browser window, so these exercise the
scheduling and selection logic against a stand-in that records draw calls.
"""

from __future__ import annotations

import dataclasses
import json
import os
import signal
import threading
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from websockets.sync.client import connect

from nhl_scoreboard import updater
from nhl_scoreboard.app import (
    DEMO_SCENE_SECONDS,
    FRAME_INTERVAL,
    STALE_AFTER_SECONDS,
    Scene,
    ScoreboardApp,
)
from nhl_scoreboard.button import Button
from nhl_scoreboard.config import Settings
from nhl_scoreboard.demo import demo_steps
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import (
    Game,
    GoalEvent,
    PlayerSeasonDetail,
    SeasonSeriesRecord,
    Situation,
    StandingsRow,
    Star,
)
from nhl_scoreboard.wifi_join import WifiJoinAttempt


class FakeCanvas:
    def __init__(self) -> None:
        self.cleared = 0
        self.pixels = 0

    def Clear(self) -> None:  # noqa: N802 - mirrors the C++ binding's API
        self.cleared += 1

    def SetPixel(self, x, y, r, g, b) -> None:  # noqa: N802
        self.pixels += 1


class FakeMatrix:
    def __init__(self, options=None) -> None:
        self.options = options
        self.swaps = 0

    def CreateFrameCanvas(self):  # noqa: N802
        return FakeCanvas()

    def SwapOnVSync(self, canvas):  # noqa: N802
        self.swaps += 1
        return canvas

    def Clear(self) -> None:  # noqa: N802
        pass


class FakeOptions:
    pass


class FakeFont:
    def LoadFont(self, path: str) -> None:  # noqa: N802
        self.path = path

    def CharacterWidth(self, _codepoint: int) -> int:  # noqa: N802
        return 5


class FakeGraphics:
    Font = FakeFont

    @staticmethod
    def Color(r, g, b):  # noqa: N802
        return (r, g, b)

    @staticmethod
    def DrawText(canvas, font, x, y, color, text):  # noqa: N802
        return len(text) * 5

    @staticmethod
    def DrawLine(canvas, x0, y0, x1, y1, color):  # noqa: N802
        return None


class FakeClient:
    def __init__(self, games: list[Game], fail: bool = False) -> None:
        self._games = games
        self.fail = fail
        self.calls = 0
        self.closed = False
        self.situation_calls: list[int] = []
        self.situations: dict[int, Situation | None] = {}
        self.goal_scoring_calls: list[int] = []
        self.goal_events: dict[int, tuple[GoalEvent, ...]] = {}
        self.team_roster_calls: list[str] = []
        self.team_rosters: dict[str, dict[int, PlayerSeasonDetail]] = {}
        self.three_stars_calls: list[int] = []
        self.stars: dict[int, tuple[Star, ...]] = {}
        self.standings_rows: list[StandingsRow] = []
        self.standings_calls = 0
        self.schedule_calls = 0
        self.series: dict[int, SeasonSeriesRecord | None] = {}
        self.season_series_calls: list[int] = []

    def scores(self, date: str = "now") -> list[Game]:
        self.calls += 1
        if self.fail:
            raise NHLApiError("boom")
        return list(self._games)

    def situation(self, game_id: int) -> Situation | None:
        self.situation_calls.append(game_id)
        if self.fail:
            raise NHLApiError("boom")
        return self.situations.get(game_id)

    def goal_scoring(self, game_id: int) -> tuple[GoalEvent, ...]:
        self.goal_scoring_calls.append(game_id)
        if self.fail:
            raise NHLApiError("boom")
        return self.goal_events.get(game_id, ())

    def team_roster(self, team: str) -> dict[int, PlayerSeasonDetail]:
        self.team_roster_calls.append(team)
        if self.fail:
            raise NHLApiError("boom")
        return self.team_rosters.get(team, {})

    def three_stars(self, game_id: int) -> tuple[Star, ...]:
        self.three_stars_calls.append(game_id)
        if self.fail:
            raise NHLApiError("boom")
        return self.stars.get(game_id, ())

    def schedule(self, team: str) -> list[Game]:
        self.schedule_calls += 1
        if self.fail:
            raise NHLApiError("boom")
        return [g for g in self._games if g.involves(team)]

    def standings(self, date: str = "now") -> list[StandingsRow]:
        self.standings_calls += 1
        if self.fail:
            raise NHLApiError("boom")
        return list(self.standings_rows)

    def season_series(self, game_id: int) -> SeasonSeriesRecord | None:
        self.season_series_calls.append(game_id)
        if self.fail:
            raise NHLApiError("boom")
        return self.series.get(game_id)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_backend() -> Backend:
    return Backend(
        name="fake",
        RGBMatrix=FakeMatrix,
        RGBMatrixOptions=FakeOptions,
        graphics=FakeGraphics,
    )


@pytest.fixture
def games() -> list[Game]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())
    return [Game.from_api(raw) for raw in payload["games"]]


def build_app(fake_backend, games, **scoreboard_kwargs) -> ScoreboardApp:
    settings = Settings()
    for key, value in scoreboard_kwargs.items():
        setattr(settings.scoreboard, key, value)
    return ScoreboardApp(settings, client=FakeClient(games), backend=fake_backend)


class FakeClockSource:
    """A monotonic clock that only advances when told to -- by a fake sleep."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeAdminServer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def run_for_frames(app: ScoreboardApp, src: FakeClockSource, frames: int) -> None:
    """Run the real loop for exactly ``frames`` iterations, then stop it.

    Piggybacks the frame count on the fake sleep so the loop body (refresh,
    advance, brightness, draw) actually executes ``frames`` times -- the
    only way to exercise run()'s scheduling without a real time.sleep.
    """
    remaining = frames

    def sleep(seconds: float) -> None:
        nonlocal remaining
        src.sleep(seconds)
        remaining -= 1
        if remaining <= 0:
            app._running = False

    app.sleep = sleep
    app.run()


def test_favourite_team_is_pinned_to_the_front(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="TOR")
    app.refresh()
    assert app.games[0].involves("TOR")


def test_ordering_untouched_when_no_favourite(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="")
    app.refresh()
    assert app.games[0].is_live


def test_poll_interval_speeds_up_for_live_games(fake_backend, games):
    app = build_app(fake_backend, games, poll_seconds=60, live_poll_seconds=15)
    app.refresh()
    assert app.poll_interval() == 15

    app.games = [g for g in app.games if g.is_final]
    assert app.poll_interval() == 60


def test_intermission_does_not_count_as_live_for_polling(fake_backend, games):
    app = build_app(fake_backend, games, poll_seconds=60, live_poll_seconds=15)
    app.games = [g for g in games if g.in_intermission]
    assert app.games, "fixture should contain an intermission game"
    assert app.poll_interval() == 60


def test_rotation_wraps(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    for _ in range(len(app.games)):
        app.advance()
    assert app.index == 0


def test_api_failure_keeps_previous_games(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    assert app.games

    app.client.fail = True
    app.refresh()
    assert app.games, "stale data should stay on the board"


def test_refresh_prunes_state_for_games_no_longer_in_todays_slate(fake_backend, games):
    """_seen_live/ended_at/_known_favourite_score must not grow forever (#64)."""
    app = build_app(fake_backend, games, favourite_team="CGY")
    app.refresh()
    live_ids = {g.id for g in app.games if g.is_live}
    assert live_ids, "fixture should contain a live game"
    assert app._seen_live == live_ids
    assert app._known_favourite_score, "favourite's game should have been scored"

    # Tomorrow: none of today's games are on the schedule any more.
    app.client._games = []
    app.refresh()

    assert app._seen_live == set()
    assert app.ended_at == {}
    assert app._known_favourite_score == {}


def test_draw_swaps_the_canvas(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    app.draw()
    assert app.matrix.swaps == 1


def test_draws_without_data_before_first_success(fake_backend, games):
    app = build_app(fake_backend, games)
    app.draw()
    assert app.matrix.swaps == 1


def test_shutdown_closes_the_client(fake_backend, games):
    app = build_app(fake_backend, games)
    app.shutdown()
    assert app.client.closed


# -- special teams: only the favourite's game and the on-screen game ----------


def home_pp() -> Situation:
    return Situation.from_api(
        {
            "awayTeam": {"strength": 4},
            "homeTeam": {"strength": 5, "situationDescriptions": ["PP"]},
            "timeRemaining": "1:23",
        }
    )


def in_play(games: list[Game]) -> list[Game]:
    """The fixture's intermission games, made live-in-play so they are fetchable."""
    import dataclasses

    return [dataclasses.replace(g, in_intermission=False) if g.is_live else g for g in games]


def test_situations_fetched_only_for_favourite_and_on_screen(fake_backend, games):
    """The on-screen game is always a second situation target; nothing else is."""
    games = in_play(games)  # three live games: SEA@CGY, CAR@FLA, UTA@COL
    app = build_app(fake_backend, games, favourite_team="CGY")
    app.refresh()
    favourite_game = next(g for g in app.games if g.involves("CGY"))
    assert app.games[app.index] == favourite_game, "favourite is pinned first: targets coincide"

    app.refresh_situations()
    assert app.client.situation_calls == [favourite_game.id]

    # Rotate: the newly on-screen live game joins the favourite as a target.
    app.advance()
    app.refresh_situations()
    now_showing = app.games[app.index]
    assert now_showing.is_live and now_showing.id != favourite_game.id
    assert set(app.client.situation_calls) == {favourite_game.id, now_showing.id}

    # The third live game is never on screen and never the favourite: never fetched.
    live_ids = {g.id for g in app.games if g.is_live}
    assert len(live_ids) == 3
    assert live_ids - {favourite_game.id, now_showing.id}, "a live game must remain unfetched"
    assert not (live_ids - {favourite_game.id, now_showing.id}) & set(app.client.situation_calls)


def test_situation_not_refetched_within_live_interval(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=15)
    app.refresh()
    app.refresh_situations()
    app.refresh_situations()
    assert len(app.client.situation_calls) == 1


def test_intermission_games_are_not_fetched(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CAR")  # CAR @ FLA is in intermission
    app.refresh()
    app.refresh_situations()
    assert app.client.situation_calls == []
    car = next(g for g in app.games if g.involves("CAR"))
    assert app.with_situation(car).situation is None


def test_with_situation_attaches_and_stale_entries_are_dropped(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY")
    app.refresh()
    game = next(g for g in app.games if g.involves("CGY"))
    app.client.situations[game.id] = home_pp()
    app.refresh_situations()

    shown = app.with_situation(game)
    assert shown.situation is not None
    assert shown.situation.label() == "PP 1:23"
    assert shown.id == game.id

    # Change favourite and move on: the CGY entry is no longer a target.
    app.settings.scoreboard.favourite_team = "NYI"  # final, not live
    while app.games[app.index].involves("CGY"):
        app.advance()
    app.refresh_situations()
    assert game.id not in app.situations


def test_situation_fetch_failure_keeps_last_value(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    game = next(g for g in app.games if g.involves("CGY"))
    app.client.situations[game.id] = home_pp()
    app.refresh_situations()
    app.client.fail = True
    app.refresh_situations()
    assert app.with_situation(game).situation is not None


# -- goal detail polling: favourite's live game only (#122) ------------------


def goal_event(
    team="CGY", scorer="F. FORSBERG", goals=1, strength="ev", player_id=8480000
) -> GoalEvent:
    return GoalEvent(
        team_abbrev=team,
        scorer_name=scorer,
        scorer_goals_to_date=goals,
        scorer_player_id=player_id,
        assists=(),
        strength=strength,
    )


def test_goal_detail_first_sighting_does_not_fire(fake_backend, games):
    """A game already several goals in at startup must not dump a backlog (baseline)."""
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY")
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.client.goal_events[cgy_game.id] = (goal_event(), goal_event(scorer="B. JOHNSON"))

    app.refresh_goal_details()

    assert app._goal_detail is None
    assert app._shown_goal_events[cgy_game.id] == 2


def test_goal_detail_fires_once_for_a_new_scoring_entry(fake_backend, games):
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.refresh_goal_details()  # baseline: no events yet
    assert app._goal_detail is None

    event = goal_event()
    app.client.goal_events[cgy_game.id] = (event,)
    app.refresh_goal_details()

    assert app._goal_detail is not None
    detail_game_id, _fired_at, detail_event = app._goal_detail
    assert detail_game_id == cgy_game.id
    assert detail_event == event


def test_goal_detail_never_fires_twice_for_the_same_goal(fake_backend, games):
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.refresh_goal_details()

    app.client.goal_events[cgy_game.id] = (goal_event(),)
    app.refresh_goal_details()
    assert app._goal_detail is not None

    app._goal_detail = None  # as if the on-screen window already elapsed
    app.refresh_goal_details()  # same single entry, e.g. a late correction

    assert app._goal_detail is None, "must not refire for a goal already shown"


def test_goal_detail_fires_again_for_a_second_new_entry(fake_backend, games):
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.refresh_goal_details()

    first = goal_event(scorer="F. FORSBERG")
    app.client.goal_events[cgy_game.id] = (first,)
    app.refresh_goal_details()
    assert app._goal_detail[2] == first

    second = goal_event(scorer="B. JOHNSON")
    app.client.goal_events[cgy_game.id] = (first, second)
    app.refresh_goal_details()
    assert app._goal_detail[2] == second


def test_goal_detail_skipped_during_intermission(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CAR")  # CAR @ FLA is in intermission
    app.refresh()
    app.refresh_goal_details()
    assert app.client.goal_scoring_calls == []


def test_goal_detail_not_refetched_within_live_interval(fake_backend, games):
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=15)
    app.refresh()
    app.refresh_goal_details()
    app.refresh_goal_details()
    assert len(app.client.goal_scoring_calls) == 1


def test_goal_detail_fetch_failure_keeps_previous_state(fake_backend, games):
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.client.goal_events[cgy_game.id] = (goal_event(),)
    app.refresh_goal_details()
    assert app._shown_goal_events[cgy_game.id] == 1

    app.client.fail = True
    app.refresh_goal_details()

    assert app._shown_goal_events[cgy_game.id] == 1
    assert app._goal_detail is None


def test_goal_detail_noop_without_a_favourite_team(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="")
    app.refresh()
    app.refresh_goal_details()
    assert app.client.goal_scoring_calls == []


def test_goal_detail_state_pruned_with_the_rest(fake_backend, games):
    """_goal_events/_shown_goal_events must not grow forever either (#64)."""
    games = in_play(games)
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    cgy_game = next(g for g in app.games if g.involves("CGY"))
    app.client.goal_events[cgy_game.id] = (goal_event(),)
    app.refresh_goal_details()
    assert app._goal_events and app._shown_goal_events

    app.client._games = []
    app.refresh()

    assert app._goal_events == {}
    assert app._shown_goal_events == {}


def test_admin_server_built_by_default(fake_backend, games):
    app = build_app(fake_backend, games)
    assert app.admin_server is not None
    assert app.admin_server.port == 8080


def test_admin_server_not_built_when_disabled(fake_backend, games):
    settings = Settings()
    settings.status.enabled = False
    app = ScoreboardApp(settings, client=FakeClient(games), backend=fake_backend)
    assert app.admin_server is None


def test_status_snapshot_reflects_last_success_and_error(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="TOR")
    assert app.status_snapshot()["last successful poll"] == "never"
    assert app.status_snapshot()["last error"] == "(none)"

    app.refresh()
    snapshot = app.status_snapshot()
    assert snapshot["favourite team"] == "TOR"
    assert snapshot["last successful poll"] != "never"
    assert snapshot["scene"]

    app.client.fail = True
    app.refresh()
    snapshot = app.status_snapshot()
    assert "score refresh" in snapshot["last error"]
    assert snapshot["last error at"] != ""


def test_status_snapshot_shows_the_installed_version(fake_backend, games, tmp_path, monkeypatch):
    """A factory image (never hot-updated) has no VERSION file at all --
    installed_version() reads it fresh every call, so this must never go
    stale even if [update]'s own daily check hasn't run yet (#32)."""
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    app = build_app(fake_backend, games, favourite_team="TOR")
    assert app.status_snapshot()["version"] == "unknown (factory image)"

    (tmp_path / "VERSION").write_text("v2026.09.29.4\n")
    assert app.status_snapshot()["version"] == "v2026.09.29.4"


def test_status_snapshot_never_fetches_or_mutates_shared_state(fake_backend, games):
    """#61: the status page's select_scene() must not race the main loop's.

    EDM has no game today in the fixture, so a fetch-allowed select_scene()
    would hit both the schedule and standings endpoints to find the next
    game / conference window. status_snapshot() must not: it is called from
    the status server's own request thread and must answer from whatever is
    already cached, never trigger a network call or mutate _schedule/
    _standings/last_error concurrently with the main loop.
    """
    app = build_app(fake_backend, games, favourite_team="EDM")
    app.refresh()
    assert app.favourite_game_today() is None, "fixture should have no EDM game today"

    snapshot = app.status_snapshot()
    assert snapshot["scene"]
    assert app.client.schedule_calls == 0
    assert app.client.standings_calls == 0
    assert app._schedule is None
    assert app._standings is None
    assert app.last_error is None

    # The main loop's own path is untouched: it still fetches and caches.
    app.select_scene()
    assert app.client.schedule_calls == 1
    assert app.client.standings_calls == 1

    # A second status_snapshot() reads the now-cached values without refetching.
    app.status_snapshot()
    assert app.client.schedule_calls == 1
    assert app.client.standings_calls == 1


# -- config reload (#51) ---------------------------------------------------


def _touch_later(path: Path, app: ScoreboardApp) -> None:
    """Bump path's mtime past what app last recorded, regardless of FS resolution."""
    new_mtime = (app._config_mtime or 0) + 5
    os.utime(path, (new_mtime, new_mtime))


def test_reload_noop_without_a_source_file(fake_backend, games):
    app = build_app(fake_backend, games)
    assert app.settings.source_path is None
    assert app.reload_config_if_changed() is False


def test_reload_noop_when_file_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.reload_config_if_changed() is False


def test_reload_picks_up_a_changed_setting(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)

    path.write_text('[scoreboard]\nfavourite_team = "TOR"\n')
    _touch_later(path, app)

    assert app.reload_config_if_changed() is True
    assert app.settings.scoreboard.favourite_team == "TOR"


def test_reload_invalidates_schedule_cache_on_favourite_team_change(fake_backend, games, tmp_path):
    """next_favourite_game()'s _schedule cache is keyed purely by elapsed
    time, not by which team it was fetched for -- a favourite switch must
    force a fresh fetch, or the countdown/preview/matchup screens keep
    showing the *previous* team's next game for up to an hour. Confirmed
    live (#178's admin-page work): this is exactly why the matchup/
    season-series screen (#157) kept showing the old opponent after a
    favourite switch -- it's fed straight from next_favourite_game()."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    # Simulate an already-fetched, still-fresh schedule cache for the old favourite.
    app._schedule = (app.monotonic(), games)
    app._schedule_retry_after = app.monotonic() + 100

    path.write_text('[scoreboard]\nfavourite_team = "TOR"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app._schedule is None
    assert app._schedule_retry_after == 0.0


def test_reload_keeps_schedule_cache_when_favourite_team_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\ntimezone = "UTC"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    app._schedule = (app.monotonic(), games)
    app._schedule_retry_after = app.monotonic() + 100
    cached = app._schedule

    # Change something unrelated -- the schedule cache must survive.
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\ntimezone = "America/Chicago"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app._schedule is cached


def test_favourite_team_switch_triggers_a_fresh_schedule_fetch(fake_backend, games, tmp_path):
    """End-to-end: neither EDM nor WPG has a game in the fixture (today's
    slate), so favourite_game_today() answers None for both and
    next_favourite_game() must consult the season schedule -- proving the
    invalidation actually changes real fetch behaviour, not just internal
    bookkeeping."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "EDM"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    app.refresh()
    assert app.favourite_game_today() is None

    app.next_favourite_game()
    assert app.client.schedule_calls == 1

    # Still within the 1-hour TTL -- a second call with no favourite
    # change must not refetch.
    app.next_favourite_game()
    assert app.client.schedule_calls == 1

    path.write_text('[scoreboard]\nfavourite_team = "WPG"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    app.next_favourite_game()
    assert app.client.schedule_calls == 2, "switching favourite must force a fresh schedule fetch"


def test_reload_keeps_previous_settings_on_parse_error(fake_backend, games, tmp_path, caplog):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)

    path.write_text("this is not valid toml [[[")
    _touch_later(path, app)

    assert app.reload_config_if_changed() is False
    assert app.settings.scoreboard.favourite_team == "NSH"
    assert "reload failed" in caplog.text.lower()


def test_reload_rebuilds_horn_on_audio_change(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[audio]\nenabled = true\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_horn = app.horn

    path.write_text("[audio]\nenabled = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.horn is not old_horn
    assert app.horn.enabled is False


def test_reload_rebuilds_logos_on_show_logos_change(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[scoreboard]\nshow_logos = true\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.renderer.logos is not None

    path.write_text("[scoreboard]\nshow_logos = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.renderer.logos is None


def test_reload_updates_timezone_on_renderer_too(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\ntimezone = "America/Chicago"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)

    path.write_text('[scoreboard]\ntimezone = "America/New_York"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert str(app.tz) == "America/New_York"
    assert str(app.renderer.tz) == "America/New_York"


def test_boot_with_unknown_timezone_falls_back_instead_of_crashing(fake_backend, games, tmp_path):
    """A typo must not stop the board booting (#80) -- same rule as unknown keys."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\ntimezone = "America/Chicagoo"\n')

    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)

    assert str(app.tz) == "America/Chicago"
    app.draw()  # does not raise
    assert app.matrix.swaps == 1


def test_reload_with_unknown_timezone_keeps_the_previous_one(fake_backend, games, tmp_path):
    """A bad live-edit keeps the board on whatever timezone already worked, not the default."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\ntimezone = "America/New_York"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert str(app.tz) == "America/New_York"

    path.write_text('[scoreboard]\ntimezone = "America/New_Yorkk"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert str(app.tz) == "America/New_York"
    assert str(app.renderer.tz) == "America/New_York"
    # The rest of the reload still applies -- a bad timezone doesn't roll back
    # unrelated settings from the same edit.
    assert app.settings.scoreboard.timezone == "America/New_Yorkk"


def test_reload_does_not_touch_the_already_built_matrix(fake_backend, games, tmp_path):
    """[panel] geometry is baked into RGBMatrix at construction; reload must not rebuild it."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[panel]\nchain_length = 2\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_matrix = app.matrix

    path.write_text("[panel]\nchain_length = 1\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.matrix is old_matrix
    assert app.settings.panel.chain_length == 1


# -- run() loop scheduling (#76) -------------------------------------------
#
# run() itself calls time.sleep(); these drive it for real via an injected
# sleep that advances a fake monotonic clock, so the actual scheduling
# (poll/rotate/brightness cadence, config reload, signal shutdown) executes
# under test instead of only refresh()/advance()/draw() called by hand.


def _non_live_games(games: list[Game]) -> list[Game]:
    """Games that never bump poll_interval() to live_poll_seconds, so a test's
    expected poll count doesn't depend on which games happen to be live."""
    return [g for g in games if not g.is_live]


def test_run_polls_at_poll_interval_not_every_frame(fake_backend, games):
    final_games = _non_live_games(games)
    assert final_games
    settings = Settings()
    settings.scoreboard.poll_seconds = 3 * FRAME_INTERVAL
    settings.scoreboard.rotate_seconds = 1_000_000
    settings.panel.brightness_poll_seconds = 1_000_000
    src = FakeClockSource()
    app = ScoreboardApp(
        settings,
        client=FakeClient(final_games),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    run_for_frames(app, src, 7)
    # Frame 1 always polls (next_poll starts at 0); then every 3 frames: 4, 7.
    assert app.client.calls == 3


def test_run_rotates_at_rotate_seconds(fake_backend, games):
    final_games = _non_live_games(games)
    assert len(final_games) >= 2
    settings = Settings()
    settings.scoreboard.poll_seconds = 1_000_000
    settings.scoreboard.rotate_seconds = 3 * FRAME_INTERVAL
    settings.panel.brightness_poll_seconds = 1_000_000
    src = FakeClockSource()
    app = ScoreboardApp(
        settings,
        client=FakeClient(final_games),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    advances = []
    original_advance = app.advance

    def counting_advance():
        advances.append(app.index)
        original_advance()

    app.advance = counting_advance
    run_for_frames(app, src, 7)
    assert len(advances) == 3


def test_run_samples_brightness_at_brightness_poll_seconds(fake_backend, games):
    final_games = _non_live_games(games)
    settings = Settings()
    settings.scoreboard.poll_seconds = 1_000_000
    settings.scoreboard.rotate_seconds = 1_000_000
    settings.panel.brightness_poll_seconds = 3 * FRAME_INTERVAL
    src = FakeClockSource()
    app = ScoreboardApp(
        settings,
        client=FakeClient(final_games),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    calls = []
    original = app.refresh_brightness

    def counting_refresh_brightness():
        calls.append(True)
        original()

    app.refresh_brightness = counting_refresh_brightness
    run_for_frames(app, src, 7)
    assert len(calls) == 3


def test_run_reloads_config_every_iteration(fake_backend, games):
    settings = Settings()
    settings.scoreboard.poll_seconds = 1_000_000
    settings.scoreboard.rotate_seconds = 1_000_000
    settings.panel.brightness_poll_seconds = 1_000_000
    src = FakeClockSource()
    app = ScoreboardApp(
        settings,
        client=FakeClient(_non_live_games(games)),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    calls = []
    original = app.reload_config_if_changed

    def counting_reload():
        calls.append(True)
        return original()

    app.reload_config_if_changed = counting_reload
    run_for_frames(app, src, 5)
    assert len(calls) == 5


def test_run_stops_on_sigterm_and_shuts_down(fake_backend, games):
    settings = Settings()
    settings.scoreboard.poll_seconds = 1_000_000
    settings.scoreboard.rotate_seconds = 1_000_000
    settings.panel.brightness_poll_seconds = 1_000_000
    src = FakeClockSource()
    status = FakeAdminServer()
    app = ScoreboardApp(
        settings,
        client=FakeClient(_non_live_games(games)),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
        admin_server=status,
    )
    frame_count = 0

    def sleep(seconds: float) -> None:
        nonlocal frame_count
        src.sleep(seconds)
        frame_count += 1
        if frame_count == 2:
            app._handle_signal(signal.SIGTERM, None)

    app.sleep = sleep
    app.run()

    assert frame_count == 2, "loop should stop right after the signal, not run extra frames"
    assert status.started
    assert status.stopped
    assert app.client.closed


# -- draw() scene dispatch (#76) --------------------------------------------


def test_draw_dispatches_no_data_when_stale(fake_backend, games):
    app = build_app(fake_backend, games)
    app.last_success = app.monotonic() - (STALE_AFTER_SECONDS + 1)
    calls = []
    app.renderer.draw_message = lambda canvas, *args: calls.append(args)
    app.draw()
    assert calls == [("NO DATA", "CHECK NETWORK")]


def test_draw_dispatches_clock_when_idle(fake_backend, games):
    app = build_app(fake_backend, games, show_clock_when_idle=True)
    app.last_success = app.monotonic()
    calls = []
    app.renderer.draw_clock = lambda canvas, now, favourite=None: calls.append(now)
    app.draw()
    assert len(calls) == 1


def test_draw_dispatches_no_games_when_idle_clock_disabled(fake_backend, games):
    app = build_app(fake_backend, games, show_clock_when_idle=False)
    app.last_success = app.monotonic()
    calls = []
    app.renderer.draw_message = lambda canvas, *args: calls.append(args)
    app.draw()
    assert calls == [("NO GAMES",)]


# -- night mode (#92) ---------------------------------------------------------

#: 23:00 in America/Chicago (CDT), inside the default 22:30-07:00 window. The
#: fixture's NSH@TBL final is estimated to have ended hours before this.
NIGHT = datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
#: 08:00 CDT, outside it.
MORNING = datetime(2026, 9, 21, 13, 0, tzinfo=UTC)


class NightClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class LuxSensor:
    def __init__(self, lux: float) -> None:
        self.lux = lux

    def read_lux(self) -> float:
        return self.lux


def night_app(
    fake_backend, games, now=NIGHT, sensor=None, favourite="NSH", **night_kwargs
) -> ScoreboardApp:
    settings = Settings()
    settings.scoreboard.favourite_team = favourite
    settings.night_mode.enabled = True
    for key, value in night_kwargs.items():
        setattr(settings.night_mode, key, value)
    app = ScoreboardApp(
        settings,
        client=FakeClient(games),
        backend=fake_backend,
        clock=NightClock(now),
        light_sensor=sensor,
    )
    app.refresh()
    return app


def at_local(hour: int, minute: int = 0) -> datetime:
    """A UTC instant that is hour:minute on 2026-09-21 in America/Chicago (UTC-5)."""
    return datetime(2026, 9, 21, hour, minute, tzinfo=UTC) + timedelta(hours=5)


@pytest.mark.parametrize(
    ("hour", "minute", "inside"),
    [(22, 29, False), (22, 30, True), (23, 59, True), (0, 0, True), (6, 59, True), (7, 0, False)],
)
def test_night_window_wraps_midnight(fake_backend, games, hour, minute, inside):
    app = night_app(fake_backend, [], now=at_local(hour, minute))
    assert app._in_night_window() is inside


@pytest.mark.parametrize(
    ("hour", "minute", "inside"),
    [(12, 59, False), (13, 0, True), (14, 30, True), (15, 0, False), (23, 0, False)],
)
def test_night_window_same_day(fake_backend, games, hour, minute, inside):
    from nhl_scoreboard.config import NightModeConfig

    app = night_app(fake_backend, [], now=at_local(hour, minute))
    app.settings.night_mode = NightModeConfig(enabled=True, start_time="13:00", end_time="15:00")
    assert app._in_night_window() is inside


def test_night_window_uses_local_time_not_utc(fake_backend, games):
    """Each instant below lands on the opposite side of the window if read as UTC."""
    app = night_app(fake_backend, [], now=datetime(2026, 9, 21, 3, 0, tzinfo=UTC))
    assert app._in_night_window() is False  # 22:00 local
    app.clock = NightClock(datetime(2026, 9, 21, 11, 59, tzinfo=UTC))
    assert app._in_night_window() is True  # 06:59 local


def test_tracked_scope_live_favourite_game_suppresses_dimming(fake_backend, games):
    app = night_app(fake_backend, games, favourite="CAR")  # CAR@FLA is live
    assert app._in_night_window()
    assert app._night_mode_suppressed()
    assert not app._night_mode_active()


def test_tracked_scope_other_live_games_do_not_suppress(fake_backend, games):
    """NSH's game is long over; three other live games must not hold off dimming."""
    app = night_app(fake_backend, games, favourite="NSH", suppress_scope="tracked")
    assert any(g.is_live for g in app.games)
    assert not app._night_mode_suppressed()
    assert app._night_mode_active()


def test_all_scope_any_live_game_suppresses(fake_backend, games):
    app = night_app(fake_backend, games, favourite="NSH", suppress_scope="all")
    assert app._night_mode_suppressed()
    assert not app._night_mode_active()


def test_tracked_scope_without_favourite_behaves_as_all(fake_backend, games, caplog):
    app = night_app(fake_backend, games, favourite="", suppress_scope="tracked")
    assert app._night_mode_suppressed()
    assert "suppress_scope" not in caplog.text

    finals_only = [g for g in games if not g.is_live]
    app = night_app(fake_backend, finals_only, favourite="", suppress_scope="tracked")
    assert not app._night_mode_suppressed()


def test_cooldown_holds_off_dimming_after_the_favourite_goes_final(fake_backend, games):
    app = night_app(fake_backend, games, favourite="NSH", cooldown_minutes=15)
    nsh = next(g for g in app.games if g.involves("NSH"))
    app.ended_at[nsh.id] = NIGHT - timedelta(minutes=10)
    assert app._night_mode_suppressed()

    app.clock = NightClock(NIGHT + timedelta(minutes=5))  # exactly 15 minutes after
    assert not app._night_mode_suppressed()
    assert app._night_mode_active()


def test_zero_cooldown_dims_at_the_final(fake_backend, games):
    app = night_app(fake_backend, games, favourite="NSH", cooldown_minutes=0)
    nsh = next(g for g in app.games if g.involves("NSH"))
    app.ended_at[nsh.id] = NIGHT
    assert not app._night_mode_suppressed()


def test_no_games_dims_on_schedule(fake_backend):
    app = night_app(fake_backend, [])
    assert app._night_mode_active()


def test_disabled_night_mode_is_never_active(fake_backend, games):
    app = night_app(fake_backend, [], enabled=False)
    assert app._in_night_window()
    assert not app._night_mode_active()


def test_night_mode_overrides_the_ambient_sensor(fake_backend, games):
    sensor = LuxSensor(lux=5000)  # a bright room would map to max_brightness
    app = night_app(fake_backend, games, sensor=sensor, dim_brightness=20)
    app.refresh_brightness()
    assert app.matrix.brightness == 20


def test_ambient_sensor_drives_brightness_outside_the_window(fake_backend, games):
    sensor = LuxSensor(lux=5000)
    app = night_app(fake_backend, games, now=MORNING, sensor=sensor, dim_brightness=20)
    app.refresh_brightness()
    assert app.matrix.brightness == app.settings.panel.max_brightness


def test_brightness_restores_without_a_sensor_when_night_ends(fake_backend, games):
    app = night_app(fake_backend, games, dim_brightness=20)
    assert app.light_sensor is None
    app.refresh_brightness()
    assert app.matrix.brightness == 20

    app.clock = NightClock(MORNING)
    app.refresh_brightness()
    assert app.matrix.brightness == app.settings.panel.brightness


def test_zero_brightness_blanks_without_rendering_a_scene(fake_backend, games, monkeypatch):
    app = night_app(fake_backend, games, dim_brightness=0)

    def no_scene(**_kwargs):
        pytest.fail("a blanked board must not select or render a scene")

    monkeypatch.setattr(app, "select_scene", no_scene)
    canvas = app.canvas
    app.draw()
    assert canvas.cleared == 1
    assert canvas.pixels == 0
    assert app.matrix.swaps == 1


def test_nonzero_dim_brightness_still_renders_the_scene(fake_backend, games, monkeypatch):
    app = night_app(fake_backend, games, dim_brightness=20)
    calls = []
    original = app.select_scene

    def spy(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(app, "select_scene", spy)
    app.draw()
    assert calls, "dimmed but not blanked: the normal scene is still drawn"
    assert app.matrix.swaps == 1


def test_reload_opens_light_sensor_when_auto_brightness_turned_on(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[panel]\nauto_brightness = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.light_sensor is None

    path.write_text("[panel]\nauto_brightness = true\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.light_sensor is not None


def test_reload_drops_light_sensor_when_auto_brightness_turned_off(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[panel]\nauto_brightness = true\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.light_sensor is not None

    path.write_text("[panel]\nauto_brightness = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.light_sensor is None


def test_reload_keeps_light_sensor_when_auto_brightness_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[panel]\nauto_brightness = true\n[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_sensor = app.light_sensor

    path.write_text('[panel]\nauto_brightness = true\n[scoreboard]\nfavourite_team = "TOR"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.light_sensor is old_sensor


def test_reload_builds_admin_server_when_enabled(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.admin_server is None

    path.write_text("[status]\nenabled = true\nport = 9191\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    # Built but not started: run() never ran, so nothing should bind a socket.
    assert app.admin_server is not None
    assert app.admin_server.port == 9191


def test_reload_drops_admin_server_when_disabled(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.admin_server is not None

    path.write_text("[status]\nenabled = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.admin_server is None


def test_reload_rebuilds_admin_server_on_port_change(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\nport = 9191\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_server = app.admin_server

    path.write_text("[status]\nenabled = true\nport = 9292\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.admin_server is not old_server
    assert app.admin_server is not None
    assert app.admin_server.port == 9292


def test_reload_keeps_admin_server_when_status_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[status]\nenabled = true\n[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_server = app.admin_server

    path.write_text('[status]\nenabled = true\n[scoreboard]\nfavourite_team = "TOR"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.admin_server is old_server


def test_reload_starts_admin_server_when_inside_run_loop(fake_backend, games, tmp_path):
    """run() only starts the server once, before looping; a live rebuild must start itself."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    app._running = True  # as if inside run()'s loop, without blocking on it

    path.write_text("[status]\nenabled = true\nport = 0\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.admin_server is not None
    try:
        # A real WebSocket round trip, not just "did something bind the
        # port" -- proves the server rebuilt inside the live loop is
        # actually serving admin_server.py's real protocol, not merely
        # listening. No frontend/dist on disk in this test environment, so
        # a plain HTTP GET (the other half of what this server does, #178
        # story 10) isn't checked here -- test_admin_server.py covers that.
        with connect(f"ws://127.0.0.1:{app.admin_server.port}/", open_timeout=5) as ws:
            message = json.loads(ws.recv(timeout=5))
            assert message["type"] == "version"
    finally:
        app.admin_server.stop()


# -- physical button (#50) -------------------------------------------------
#
# Presses go through the real button.Button + gpiozero.Button on gpiozero's
# MockFactory (conftest's mock_pins), so what reaches the app is exactly what
# gpiozero's own press/hold/release logic produced. The reload tests only
# care whether the button was rebuilt or closed, so they use a spy instead.

BUTTON_PIN = 26
BUTTON_HOLD = 0.1


class SpyButton:
    def __init__(self) -> None:
        self.closed = False

    def consume_short_press(self) -> bool:
        return False

    def consume_long_press(self) -> bool:
        return False

    def close(self) -> None:
        self.closed = True


def button_app(fake_backend, games, mock_pins, **button_kwargs):
    src = FakeClockSource()
    settings = Settings()
    for key, value in button_kwargs.items():
        setattr(settings.button, key, value)
    button = Button.open(BUTTON_PIN, hold_seconds=BUTTON_HOLD)
    assert button is not None
    app = ScoreboardApp(
        settings,
        client=FakeClient(games),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
        horn=RecordingHorn(),
        button=button,
    )
    return app, src, mock_pins.pin(BUTTON_PIN)


def tap(pin) -> None:
    pin.drive_low()
    pin.drive_high()


def hold(app: ScoreboardApp, pin) -> None:
    pin.drive_low()
    deadline = time.monotonic() + 2
    while not app.button._long_press and time.monotonic() < deadline:
        time.sleep(0.01)
    pin.drive_high()


def test_button_is_not_opened_when_disabled(fake_backend, games):
    app = build_app(fake_backend, games)
    assert app.settings.button.enabled is False
    assert app.button is None
    app.handle_button()  # no button: a no-op, not an AttributeError


def test_button_is_opened_from_settings_when_enabled(fake_backend, games, mock_pins):
    settings = Settings()
    settings.button.enabled = True
    app = ScoreboardApp(settings, client=FakeClient(games), backend=fake_backend)
    assert app.button is not None


def test_short_press_mutes_the_next_goal_horn(fake_backend, games, mock_pins):
    app, _src, pin = button_app(fake_backend, games, mock_pins)
    app.refresh()
    game = app.games[0]

    tap(pin)
    app.handle_button()
    app._on_goal(game)

    assert app.horn.calls == []
    assert app.last_goal is not None, "muting the horn must not suppress the goal scene"


def test_horn_plays_again_once_mute_minutes_pass(fake_backend, games, mock_pins):
    app, src, pin = button_app(fake_backend, games, mock_pins, mute_minutes=30)
    app.refresh()
    game = app.games[0]

    tap(pin)
    app.handle_button()
    src.now += 30 * 60 - 1
    app._on_goal(game)
    assert app.horn.calls == []

    src.now += 1
    app._on_goal(game)
    assert app.horn.calls == [app.settings.scoreboard.favourite_team]


def test_mute_minutes_zero_never_mutes(fake_backend, games, mock_pins):
    app, _src, pin = button_app(fake_backend, games, mock_pins, mute_minutes=0)
    app.refresh()

    tap(pin)
    app.handle_button()
    app._on_goal(app.games[0])

    assert len(app.horn.calls) == 1


def test_long_press_advances_the_rotation_exactly_once(fake_backend, games, mock_pins):
    app, _src, pin = button_app(fake_backend, games, mock_pins)
    app.refresh()
    assert len(app.games) > 1
    assert app.index == 0

    hold(app, pin)
    app.handle_button()
    assert app.index == 1
    assert app._horn_muted_until is None, "a long press is not also a mute"

    app.handle_button()  # the same press, consumed already
    assert app.index == 1


def test_short_press_is_consumed_once(fake_backend, games, mock_pins):
    app, src, pin = button_app(fake_backend, games, mock_pins)

    tap(pin)
    app.handle_button()
    first = app._horn_muted_until
    assert first is not None

    src.now += 10
    app.handle_button()  # nothing new pressed: the mute window isn't pushed out
    assert app._horn_muted_until == first


def test_run_loop_handles_button_presses(fake_backend, games, mock_pins):
    app, src, pin = button_app(fake_backend, games, mock_pins, mute_minutes=5)
    tap(pin)

    run_for_frames(app, src, 1)

    assert app._horn_muted_until == 5 * 60


def test_shutdown_releases_the_button(fake_backend, games):
    spy = SpyButton()
    app = ScoreboardApp(Settings(), client=FakeClient(games), backend=fake_backend, button=spy)
    app.shutdown()
    assert spy.closed


def test_reload_opens_button_when_enabled(fake_backend, games, tmp_path, mock_pins):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[button]\nenabled = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.button is None

    path.write_text("[button]\nenabled = true\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.button is not None


def test_reload_closes_button_when_disabled(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[button]\nenabled = true\n")
    spy = SpyButton()
    app = ScoreboardApp(
        Settings.load(path), client=FakeClient(games), backend=fake_backend, button=spy
    )

    path.write_text("[button]\nenabled = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert spy.closed
    assert app.button is None


@pytest.mark.parametrize("change", ["pin = 16", "hold_seconds = 2.0"])
def test_reload_rebuilds_button_on_pin_or_hold_change(
    fake_backend, games, tmp_path, mock_pins, change
):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[button]\nenabled = true\n")
    spy = SpyButton()
    app = ScoreboardApp(
        Settings.load(path), client=FakeClient(games), backend=fake_backend, button=spy
    )

    path.write_text(f"[button]\nenabled = true\n{change}\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert spy.closed
    assert app.button is not spy
    assert app.button is not None


def test_reload_keeps_button_when_button_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[button]\nenabled = true\n[scoreboard]\nfavourite_team = "NSH"\n')
    spy = SpyButton()
    app = ScoreboardApp(
        Settings.load(path), client=FakeClient(games), backend=fake_backend, button=spy
    )

    # mute_minutes is read per press, so changing it alone needs no rebuild either.
    path.write_text(
        '[button]\nenabled = true\nmute_minutes = 5\n[scoreboard]\nfavourite_team = "TOR"\n'
    )
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.button is spy
    assert not spy.closed


# -- admin page config editor (#110, #178 story 10) -------------------------


def _save_data_for(settings: Settings, section: str, **overrides: object) -> dict[str, object]:
    """A full save payload for ``section``, same helper role _form_for had
    for status_server.py's HTML forms -- JSON keeps real types, so unlike
    that helper there's no bool->string encoding to do."""
    data = dataclasses.asdict(getattr(settings, section))
    if section == "scoreboard":
        # show_standings is a real field (so it's in the asdict above) but
        # no longer part of the Scoreboard section's own save contract --
        # see admin_server.py's _SCOREBOARD_FIELDS and App.tsx's
        # saveScoreboard, which strip it the same way for the same reason.
        del data["show_standings"]
    data.update(overrides)
    return data


def _ws_save(port: int, section: str, data: dict[str, object]) -> dict[str, object]:
    """Connect, send one save, and return the saved/error ack -- draining
    and discarding every message ahead of it (the initial per-section config
    dump; see admin_server.py's _handle), since this only cares about the
    one save's own outcome, not the connect-time payload."""
    with connect(f"ws://127.0.0.1:{port}/", open_timeout=5) as ws:
        ws.send(json.dumps({"type": "save", "section": section, "data": data}))
        while True:
            message = json.loads(ws.recv(timeout=5))
            if message["type"] in ("saved", "error"):
                return message


def test_admin_page_save_writes_file_and_reload_picks_it_up(fake_backend, games, tmp_path):
    """A save (#110, #178 story 10) only ever writes the file;
    reload_config_if_changed() (#51) -- polled every main-loop tick -- is
    what actually applies the change to the running app."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[status]\nenabled = true\nport = 0\n[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.admin_server is not None
    app.admin_server.start()
    try:
        data = _save_data_for(app.settings, "scoreboard", favourite_team="TOR")
        ack = _ws_save(app.admin_server.port, "scoreboard", data)
        assert ack["type"] == "saved"
    finally:
        app.admin_server.stop()

    # Not applied yet -- the admin server's own thread never touches the
    # live Settings.
    assert app.settings.scoreboard.favourite_team == "NSH"
    _touch_later(path, app)
    assert app.reload_config_if_changed() is True
    assert app.settings.scoreboard.favourite_team == "TOR"


def test_admin_page_save_disabling_status_does_not_crash_in_flight_request(
    fake_backend, games, tmp_path
):
    """The admin page can disable itself (#110 SS4); the in-flight response must still
    complete normally -- the teardown only happens on the next reload tick."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\nport = 0\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.admin_server is not None
    app.admin_server.start()
    try:
        data = _save_data_for(app.settings, "status", enabled=False)
        ack = _ws_save(app.admin_server.port, "status", data)
        assert ack["type"] == "saved"
    finally:
        app.admin_server.stop()

    _touch_later(path, app)
    assert app.reload_config_if_changed() is True
    assert app.admin_server is None


def test_admin_page_save_concurrent_with_reload_does_not_raise(fake_backend, games, tmp_path):
    """A save from the admin server's own thread and reload_config_if_changed() on the
    main thread running at the same time must not raise or deadlock (#110 SS1)."""
    path = tmp_path / "scoreboard.toml"
    path.write_text('[status]\nenabled = true\nport = 0\n[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    app.admin_server.start()
    errors: list[Exception] = []

    def hammer_reload() -> None:
        for _ in range(20):
            try:
                app.reload_config_if_changed()
            except Exception as exc:
                errors.append(exc)

    try:
        thread = threading.Thread(target=hammer_reload)
        thread.start()
        for i in range(20):
            team = "TOR" if i % 2 else "NSH"
            data = _save_data_for(app.settings, "scoreboard", favourite_team=team)
            _ws_save(app.admin_server.port, "scoreboard", data)
        thread.join(timeout=5)
    finally:
        app.admin_server.stop()

    assert errors == []


# -- demo mode (#47) ----------------------------------------------------------


class RecordingHorn:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def play(self, abbrev: str) -> bool:
        self.calls.append(abbrev)
        return True


DEMO_NOW = datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
TICKS_PER_SCENE = round(DEMO_SCENE_SECONDS / FRAME_INTERVAL)


def demo_app(fake_backend, games, **panel_kwargs) -> tuple[ScoreboardApp, FakeClockSource]:
    src = FakeClockSource()
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        clock=lambda: DEMO_NOW,
        monotonic=src.monotonic,
        sleep=src.sleep,
        horn=RecordingHorn(),
    )
    return app, src


def spy_draw_scene(app: ScoreboardApp) -> list[tuple]:
    """Record (scene, renderer.logos, monotonic time) at every draw_scene call."""
    calls = []
    original = app.draw_scene

    def spy(scene):
        calls.append((scene, app.renderer.logos, app.monotonic()))
        original(scene)

    app.draw_scene = spy
    return calls


def stub_renderer(app: ScoreboardApp) -> None:
    # The fake graphics can't lay out real glyphs, and pregame labels use
    # "%-I" (which Windows rejects); the real rendering of every step is
    # covered by test_demo.py. These tests are about the loop.
    for name in (
        "draw_game",
        "draw_goal",
        "draw_countdown",
        "draw_preview",
        "draw_standings",
        "draw_matchup",
        "draw_conference_leaders",
        "draw_leaders",
        "draw_message",
        "draw_clock",
    ):
        setattr(app.renderer, name, lambda *args: None)


def run_demo_for_frames(app: ScoreboardApp, src: FakeClockSource, frames: int) -> None:
    remaining = frames

    def sleep(seconds: float) -> None:
        nonlocal remaining
        src.sleep(seconds)
        remaining -= 1
        if remaining <= 0:
            app._running = False

    app.sleep = sleep
    app.run_demo()


def test_demo_draws_each_step_in_order_for_demo_scene_seconds(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, 3 * TICKS_PER_SCENE)

    assert [c[0] for c in calls] == [s.scene for s in steps[:3]]
    assert [c[2] for c in calls] == [0.0, DEMO_SCENE_SECONDS, 2 * DEMO_SCENE_SECONDS]
    assert app.matrix.swaps == 3


def test_demo_loops_back_to_the_first_step(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, (len(steps) + 1) * TICKS_PER_SCENE)

    assert [c[0] for c in calls] == [s.scene for s in steps] + [steps[0].scene]


def test_demo_never_touches_the_real_state_machine(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    forbidden = []
    for name in (
        "refresh",
        "select_scene",
        "refresh_situations",
        "refresh_brightness",
        "reload_config_if_changed",
        "_on_goal",
    ):
        setattr(app, name, lambda *a, _name=name, **k: forbidden.append(_name))
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, len(steps) * TICKS_PER_SCENE)

    assert forbidden == []
    assert app.client.calls == 0
    assert app.client.situation_calls == []
    assert app.client.schedule_calls == 0
    assert app.client.standings_calls == 0


def test_demo_goal_scenes_never_play_the_horn(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, 2 * len(steps) * TICKS_PER_SCENE)

    assert any(c[0].kind == "goal" for c in calls), "the cycle should include a goal"
    assert app.horn.calls == []
    assert app.last_goal is None


def test_demo_stops_within_one_frame_of_a_signal(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    status = FakeAdminServer()
    app.admin_server = status
    frames = 0

    def sleep(seconds: float) -> None:
        nonlocal frames
        src.sleep(seconds)
        frames += 1
        if frames == 2:
            app._handle_signal(signal.SIGINT, None)

    app.sleep = sleep
    app.run_demo()

    assert frames == 2, "should stop mid-scene, not wait out DEMO_SCENE_SECONDS"
    assert src.now == 2 * FRAME_INTERVAL
    assert app.client.closed
    assert status.stopped


def test_demo_toggles_logos_per_step_and_restores_them(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    library = object()
    app.renderer.logos = library
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, len(steps) * TICKS_PER_SCENE)

    assert len(calls) == len(steps)
    for step, (_scene, logos, _t) in zip(steps, calls, strict=True):
        assert logos is (library if step.use_logos else None)
    assert {c[1] is None for c in calls} == {True, False}, "both layouts must be drawn"
    assert app.renderer.logos is library


def test_demo_without_a_logo_library_draws_everything_as_text(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    app.renderer.logos = None  # show_logos = false
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    run_demo_for_frames(app, src, len(steps) * TICKS_PER_SCENE)

    assert len(calls) == len(steps)
    assert all(c[1] is None for c in calls)


def test_draw_scene_dispatches_goal_without_the_horn(fake_backend, games):
    app, _src = demo_app(fake_backend, games)
    drawn = []
    app.renderer.draw_goal = lambda canvas, game: drawn.append(game)
    live = next(g for g in games if g.is_live)

    app.draw_scene(Scene("goal", live))

    assert drawn == [live]
    assert app.horn.calls == []
    assert app.matrix.swaps == 1


# --------------------------------------------------------------------------
# AP setup scene (#131 follow-up): nhl-scoreboard-setup-ap's state file
# --------------------------------------------------------------------------


def test_no_ap_state_file_leaves_normal_scene_selection_untouched(fake_backend, games, tmp_path):
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        ap_setup_state_path=tmp_path / "does-not-exist.json",
    )
    app.refresh()
    assert app.select_scene().kind != "ap_setup"


def test_ap_state_file_overrides_even_a_live_game(fake_backend, games, tmp_path):
    """Not just the idle/connecting cases -- unconditional, per select_scene's
    own docstring: nobody can see a live game if the only way to reach the
    board at all is the AP the state file describes."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "NHL-Scoreboard-Setup", "password": "scoreboard"}))
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )
    app.refresh()
    assert any(g.is_live for g in app.games), "fixture should have a live game"

    scene = app.select_scene()
    assert scene.kind == "ap_setup"
    assert scene.ap_ssid == "NHL-Scoreboard-Setup"
    assert scene.ap_password == "scoreboard"
    assert scene.ap_qr_matrix is not None


def test_ap_state_file_open_network_has_no_password(fake_backend, games, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestNet", "password": None, "open": True}))
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )

    scene = app.select_scene()
    assert scene.kind == "ap_setup"
    assert scene.ap_password is None
    assert scene.ap_qr_matrix is not None


def test_malformed_ap_state_file_degrades_to_normal_scene_selection(fake_backend, games, tmp_path):
    """A typo/partial write must not crash the board -- same config-typo
    tolerance CLAUDE.md documents for scoreboard.toml itself."""
    state_path = tmp_path / "state.json"
    state_path.write_text("not valid json{{{")
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )
    app.refresh()
    assert app.select_scene().kind != "ap_setup"


def test_ap_qr_matrix_is_cached_across_calls(fake_backend, games, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestNet", "password": "hunter2"}))
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )

    first = app.select_scene().ap_qr_matrix
    second = app.select_scene().ap_qr_matrix
    assert first is second


# --------------------------------------------------------------------------
# WiFi setup page (#132): started/stopped in step with the AP state file
# --------------------------------------------------------------------------


def test_setup_server_not_started_without_ap_state_file(fake_backend, games, tmp_path):
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        ap_setup_state_path=tmp_path / "does-not-exist.json",
    )
    app._sync_setup_server()
    assert app.setup_server is None


def test_setup_server_starts_when_ap_state_file_present(fake_backend, games, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestSetupNet", "password": None}))
    settings = Settings()
    settings.wifi_setup.port = 0
    app = ScoreboardApp(
        settings,
        client=FakeClient(games),
        backend=fake_backend,
        ap_setup_state_path=state_path,
    )
    app._sync_setup_server()
    try:
        assert app.setup_server is not None
        url = f"http://127.0.0.1:{app.setup_server.port}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            assert "WiFi network" in resp.read().decode("utf-8")
    finally:
        if app.setup_server is not None:
            app.setup_server.stop()


def test_setup_server_repeated_sync_keeps_the_same_instance(fake_backend, games, tmp_path):
    """Nothing changed between two ticks -- must not tear down and rebuild
    (and thus rebind) a perfectly healthy running server every frame."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestSetupNet", "password": None}))
    settings = Settings()
    settings.wifi_setup.port = 0
    app = ScoreboardApp(
        settings, client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )
    app._sync_setup_server()
    first = app.setup_server
    try:
        app._sync_setup_server()
        assert app.setup_server is first
    finally:
        if app.setup_server is not None:
            app.setup_server.stop()


def test_setup_server_stops_when_ap_state_file_disappears(fake_backend, games, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestSetupNet", "password": None}))
    settings = Settings()
    settings.wifi_setup.port = 0
    app = ScoreboardApp(
        settings, client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )
    app._sync_setup_server()
    assert app.setup_server is not None

    state_path.unlink()
    app._sync_setup_server()
    assert app.setup_server is None


def test_setup_server_disabled_via_config_never_starts(fake_backend, games, tmp_path):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"ssid": "TestSetupNet", "password": None}))
    settings = Settings()
    settings.wifi_setup.enabled = False
    app = ScoreboardApp(
        settings, client=FakeClient(games), backend=fake_backend, ap_setup_state_path=state_path
    )
    app._sync_setup_server()
    assert app.setup_server is None


def test_cached_setup_networks_reads_the_scan_state_file(fake_backend, games, tmp_path):
    scan_path = tmp_path / "networks.json"
    scan_path.write_text(json.dumps(["Home Wifi", "Guest"]))
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_scan_state_path=scan_path
    )
    assert app._cached_setup_networks() == ["Home Wifi", "Guest"]


def test_cached_setup_networks_missing_file_is_an_empty_list(fake_backend, games, tmp_path):
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        ap_scan_state_path=tmp_path / "does-not-exist.json",
    )
    assert app._cached_setup_networks() == []


def test_cached_setup_networks_malformed_file_is_an_empty_list(fake_backend, games, tmp_path):
    scan_path = tmp_path / "networks.json"
    scan_path.write_text("not valid json{{{")
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_scan_state_path=scan_path
    )
    assert app._cached_setup_networks() == []


def test_cached_setup_networks_non_list_json_is_an_empty_list(fake_backend, games, tmp_path):
    scan_path = tmp_path / "networks.json"
    scan_path.write_text(json.dumps({"unexpected": "shape"}))
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, ap_scan_state_path=scan_path
    )
    assert app._cached_setup_networks() == []


def test_setup_submission_is_written_to_the_state_file(fake_backend, games, tmp_path):
    submission_path = tmp_path / "submission.json"
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        ap_submission_state_path=submission_path,
    )
    app._on_setup_submission("Home Wifi", "hunter2")
    assert json.loads(submission_path.read_text()) == {"ssid": "Home Wifi", "password": "hunter2"}


def test_setup_submission_open_network_records_null_password(fake_backend, games, tmp_path):
    submission_path = tmp_path / "submission.json"
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        ap_submission_state_path=submission_path,
    )
    app._on_setup_submission("Open Net", None)
    assert json.loads(submission_path.read_text()) == {"ssid": "Open Net", "password": None}


def test_qr_escape_backslash_escapes_wifi_qr_special_characters():
    from nhl_scoreboard.app import _qr_escape

    assert _qr_escape('a;b,c:d"e\\f') == 'a\\;b\\,c\\:d\\"e\\\\f'
    assert _qr_escape("plain") == "plain"


# --------------------------------------------------------------------------
# WiFi join outcome scene (#133)
# --------------------------------------------------------------------------


def _wifi_join(tmp_path, **kwargs) -> WifiJoinAttempt:
    return WifiJoinAttempt(
        config_path=tmp_path / "scoreboard.toml",
        connect_timeout=1.0,
        submission_path=tmp_path / "submission.json",
        outcome_path=tmp_path / "outcome.json",
        **kwargs,
    )


def test_no_outcome_file_leaves_normal_scene_selection_untouched(fake_backend, games, tmp_path):
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, wifi_join=_wifi_join(tmp_path)
    )
    app.refresh()
    assert app.select_scene().kind != "wifi_join"


def test_wifi_join_outcome_overrides_even_a_live_game(fake_backend, games, tmp_path):
    join = _wifi_join(tmp_path)
    join.outcome_path.write_text(json.dumps({"status": "attempting", "ssid": "HomeNet"}))
    app = ScoreboardApp(Settings(), client=FakeClient(games), backend=fake_backend, wifi_join=join)
    app.refresh()
    assert any(g.is_live for g in app.games), "fixture should have a live game"

    scene = app.select_scene()
    assert scene.kind == "wifi_join"
    assert scene.wifi_join_status == "attempting"
    assert scene.wifi_join_ssid == "HomeNet"


def test_wifi_join_outcome_wins_over_ap_setup_scene(fake_backend, games, tmp_path):
    """A failed attempt restarts the AP, recreating the ap_setup state file
    underneath the still-showing "Failed..." message -- wifi_join must win
    for as long as its own outcome file exists."""
    join = _wifi_join(tmp_path)
    join.outcome_path.write_text(json.dumps({"status": "failed", "ssid": "HomeNet"}))
    ap_setup_path = tmp_path / "ap-setup.json"
    ap_setup_path.write_text(json.dumps({"ssid": "NHL-Scoreboard-Setup", "password": "scoreboard"}))
    app = ScoreboardApp(
        Settings(),
        client=FakeClient(games),
        backend=fake_backend,
        wifi_join=join,
        ap_setup_state_path=ap_setup_path,
    )
    assert app.select_scene().kind == "wifi_join"


def test_malformed_outcome_file_degrades_to_normal_scene_selection(fake_backend, games, tmp_path):
    join = _wifi_join(tmp_path)
    join.outcome_path.write_text("not valid json{{{")
    app = ScoreboardApp(Settings(), client=FakeClient(games), backend=fake_backend, wifi_join=join)
    app.refresh()
    assert app.select_scene().kind != "wifi_join"


def test_wifi_join_built_from_settings_picks_up_connect_timeout(fake_backend, games, tmp_path):
    config_path = tmp_path / "scoreboard.toml"
    config_path.write_text("[wifi]\nconnect_timeout_seconds = 45\n")
    app = ScoreboardApp(Settings.load(config_path), client=FakeClient(games), backend=fake_backend)
    assert app.wifi_join.connect_timeout == 45.0


def test_config_reload_updates_wifi_join_connect_timeout_in_place(fake_backend, games, tmp_path):
    join = _wifi_join(tmp_path)
    app = ScoreboardApp(Settings(), client=FakeClient(games), backend=fake_backend, wifi_join=join)
    assert app.wifi_join.connect_timeout == 1.0

    config_path = tmp_path / "scoreboard.toml"
    config_path.write_text("[wifi]\nconnect_timeout_seconds = 20\n")
    app._apply_reloaded_settings(Settings.load(config_path))
    assert app.wifi_join is join, "reload updates the existing object, not a new one"
    assert app.wifi_join.connect_timeout == 20.0


def test_boot_volume_is_applied_off_the_render_thread(fake_backend, games):
    seen = []

    class VolumeHorn(RecordingHorn):
        def apply_volume(self) -> bool:
            seen.append(threading.current_thread())
            return True

    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, horn=VolumeHorn()
    )
    app._apply_boot_volume().join(timeout=5)

    assert len(seen) == 1
    assert seen[0] is not threading.main_thread()


def test_boot_volume_failure_does_not_raise(fake_backend, games):
    app = ScoreboardApp(
        Settings(), client=FakeClient(games), backend=fake_backend, horn=RecordingHorn()
    )
    app._apply_boot_volume().join(timeout=5)  # RecordingHorn has no apply_volume


# -- live demo toggle (#204) -------------------------------------------------


def test_live_demo_steps_through_scenes_then_returns_to_real_scenes(fake_backend, games):
    app, src = demo_app(fake_backend, games)
    stub_renderer(app)
    calls = spy_draw_scene(app)
    steps = demo_steps(app.settings.scoreboard.favourite_team, DEMO_NOW)

    app.set_demo_mode(True)
    app.draw()
    src.sleep(DEMO_SCENE_SECONDS)
    app.draw()
    assert [c[0] for c in calls] == [s.scene for s in steps[:2]]
    assert app.status_snapshot()["demo mode"] == "on"
    assert app.status_snapshot()["scene"] == "demo"

    app.set_demo_mode(False)
    calls.clear()
    app.draw()
    # This fixture's app never called refresh(), so real-mode select_scene()
    # legitimately falls through to the same "connecting" scene demo step 0
    # also uses (Scene equality is by value, not by which mode produced it)
    # -- asserting non-membership in the demo step list is flaky by
    # coincidence, not a real signal. What actually proves demo mode is off
    # is the real select_scene() value itself, and status_snapshot's "scene"
    # field (which reports the literal string "demo" while it's on,
    # regardless of the underlying Scene kind -- see status_snapshot's own
    # docstring/implementation).
    assert calls[0][0] == Scene("connecting")
    assert app.status_snapshot()["demo mode"] == "off"
    assert app.status_snapshot()["scene"] == "connecting"


def test_live_demo_does_not_override_night_blanking(fake_backend, games):
    app = night_app(fake_backend, games, dim_brightness=0)
    calls = spy_draw_scene(app)
    app.set_demo_mode(True)
    app.draw()
    assert calls == []
