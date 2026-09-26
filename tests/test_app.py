"""Tests for the run loop, using a fake matrix backend.

The real backends need either a Pi or a browser window, so these exercise the
scheduling and selection logic against a stand-in that records draw calls.
"""

from __future__ import annotations

import json
import os
import signal
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nhl_scoreboard.app import (
    DEMO_SCENE_SECONDS,
    FRAME_INTERVAL,
    STALE_AFTER_SECONDS,
    Scene,
    ScoreboardApp,
)
from nhl_scoreboard.config import Settings
from nhl_scoreboard.demo import demo_steps
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import Game, Situation, StandingsRow


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
        self.standings_rows: list[StandingsRow] = []
        self.standings_calls = 0
        self.schedule_calls = 0

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


class FakeStatusServer:
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
    """In 'all' rotation the on-screen game is a second target; nothing else is."""
    games = in_play(games)  # three live games: SEA@CGY, CAR@FLA, UTA@COL
    app = build_app(fake_backend, games, favourite_team="CGY", rotation="all")
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


def test_status_server_off_by_default(fake_backend, games):
    app = build_app(fake_backend, games)
    assert app.status_server is None


def test_status_server_built_when_enabled(fake_backend, games):
    settings = Settings()
    settings.status.enabled = True
    settings.status.port = 9191
    app = ScoreboardApp(settings, client=FakeClient(games), backend=fake_backend)
    assert app.status_server is not None
    assert app.status_server.port == 9191


def test_status_snapshot_reflects_last_success_and_error(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="TOR")
    assert app.status_snapshot()["last successful poll"] == "never"
    assert app.status_snapshot()["last error"] == "(none)"

    app.refresh()
    snapshot = app.status_snapshot()
    assert snapshot["favourite team"] == "TOR"
    assert snapshot["rotation"] == "favourite"
    assert snapshot["last successful poll"] != "never"
    assert snapshot["scene"]

    app.client.fail = True
    app.refresh()
    snapshot = app.status_snapshot()
    assert "score refresh" in snapshot["last error"]
    assert snapshot["last error at"] != ""


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
    status = FakeStatusServer()
    app = ScoreboardApp(
        settings,
        client=FakeClient(_non_live_games(games)),
        backend=fake_backend,
        monotonic=src.monotonic,
        sleep=src.sleep,
        status_server=status,
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
    app = build_app(fake_backend, games, rotation="all", show_clock_when_idle=True)
    app.last_success = app.monotonic()
    calls = []
    app.renderer.draw_clock = lambda canvas, now, favourite=None: calls.append(now)
    app.draw()
    assert len(calls) == 1


def test_draw_dispatches_no_games_when_idle_clock_disabled(fake_backend, games):
    app = build_app(fake_backend, games, rotation="all", show_clock_when_idle=False)
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


def test_reload_builds_status_server_when_enabled(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.status_server is None

    path.write_text("[status]\nenabled = true\nport = 9191\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    # Built but not started: run() never ran, so nothing should bind a socket.
    assert app.status_server is not None
    assert app.status_server.port == 9191


def test_reload_drops_status_server_when_disabled(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    assert app.status_server is not None

    path.write_text("[status]\nenabled = false\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.status_server is None


def test_reload_rebuilds_status_server_on_port_change(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\nport = 9191\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_server = app.status_server

    path.write_text("[status]\nenabled = true\nport = 9292\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.status_server is not old_server
    assert app.status_server is not None
    assert app.status_server.port == 9292


def test_reload_keeps_status_server_when_status_unchanged(fake_backend, games, tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[status]\nenabled = true\n[scoreboard]\nfavourite_team = "NSH"\n')
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    old_server = app.status_server

    path.write_text('[status]\nenabled = true\n[scoreboard]\nfavourite_team = "TOR"\n')
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.status_server is old_server


def test_reload_starts_status_server_when_inside_run_loop(fake_backend, games, tmp_path):
    """run() only starts the server once, before looping; a live rebuild must start itself."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = false\n")
    app = ScoreboardApp(Settings.load(path), client=FakeClient(games), backend=fake_backend)
    app._running = True  # as if inside run()'s loop, without blocking on it

    path.write_text("[status]\nenabled = true\nport = 0\n")
    _touch_later(path, app)
    app.reload_config_if_changed()

    assert app.status_server is not None
    try:
        url = f"http://127.0.0.1:{app.status_server.port}/"
        with urllib.request.urlopen(url, timeout=5) as resp:
            assert resp.status == 200
            assert "NHL Scoreboard status" in resp.read().decode("utf-8")
    finally:
        app.status_server.stop()


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
    status = FakeStatusServer()
    app.status_server = status
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
