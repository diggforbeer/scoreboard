"""The NFL feed worker and NFL mode over it (#351).

Deterministic where it can be (``poll_once`` with a fake clock) and real threads
only where the point is threading: a fetch in flight, stop/restart, many switches.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import threading
import time
from pathlib import Path

import pytest

from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.football import worker as worker_mod
from nhl_scoreboard.football.api import MIN_POLL_SECONDS
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.worker import (
    STALE_AFTER_SECONDS,
    FeedSnapshot,
    FeedWorker,
)
from test_app import FakeGraphics, FakeMatrix, FakeOptions

FIXTURES = Path(__file__).parent / "fixtures" / "football"


def fixture_games() -> list[FbGame]:
    events = json.loads((FIXTURES / "scoreboard_live.json").read_text())["events"]
    return [FbGame.from_api(e) for e in events]


GAMES = fixture_games()  # a live game first, then two upcoming
UPCOMING = [g for g in GAMES if g.is_pregame]


class Clock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


class ScriptedClient:
    """Returns, raises or reports failure per call, from a script; the last item repeats."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0
        self.closed = False
        self.last_error = ""

    def scores(self, date=None):
        self.calls += 1
        item = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(item, Exception):
            raise item
        if item is None:
            self.last_error = "feed down"
        else:
            self.last_error = ""
        return item

    def close(self):
        self.closed = True


def make_worker(client, interval=15.0, clock=None):
    return FeedWorker(lambda: client, lambda snap: interval, clock or Clock())


def wait_for(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


def feed_threads():
    return [t for t in threading.enumerate() if t.name == "nfl-feed" and t.is_alive()]


# -- poll_once: publishing, errors, backoff --------------------------------------


def test_a_good_fetch_publishes_the_games_and_when():
    clock = Clock(1000.0)
    w = make_worker(ScriptedClient(GAMES), clock=clock)
    assert not w.snapshot().has_data and w.snapshot().games is None
    clock.now = 1005.0
    delay = w.poll_once()
    snap = w.snapshot()
    assert snap.games == tuple(GAMES) and snap.has_data
    assert snap.fetched_at == 1005.0 and snap.last_error == "" and snap.failures == 0
    assert snap.attempts == 1 and delay == 15.0


def test_an_empty_slate_is_data_not_no_data():
    w = make_worker(ScriptedClient([]))
    w.poll_once()
    assert w.snapshot().games == () and w.snapshot().has_data


def test_a_failed_fetch_keeps_the_last_good_games_and_records_the_error():
    client = ScriptedClient(GAMES, None)
    clock = Clock(1000.0)
    w = make_worker(client, clock=clock)
    w.poll_once()
    clock.now = 1030.0
    w.poll_once()
    snap = w.snapshot()
    assert snap.games == tuple(GAMES), "a blip must not blank the panel"
    assert snap.fetched_at == 1000.0, "the age of the data is the last SUCCESS"
    assert snap.last_error == "feed down" and snap.last_error_at == 1030.0
    assert snap.failures == 1 and snap.attempts == 2


def test_failures_back_off_exponentially_up_to_a_cap_and_recovery_resets():
    client = ScriptedClient(None, None, None, None, None, None, GAMES)
    w = make_worker(client, interval=15.0)
    delays = [w.poll_once() for _ in range(7)]
    assert delays[:6] == [15.0, 30.0, 60.0, 120.0, 120.0, 120.0]
    assert delays[6] == 15.0
    assert w.snapshot().failures == 0 and w.snapshot().last_error == ""


def test_backoff_never_goes_below_the_normal_interval_or_to_zero():
    w = make_worker(ScriptedClient(None), interval=0.0)
    for _ in range(50):
        assert w.poll_once() >= worker_mod.MIN_DELAY_SECONDS


def test_a_client_that_raises_is_caught_and_recorded(caplog):
    w = make_worker(ScriptedClient(RuntimeError("kaboom")))
    with caplog.at_level(logging.WARNING):
        w.poll_once()
    snap = w.snapshot()
    assert "RuntimeError: kaboom" in snap.last_error and snap.failures == 1
    assert any("kaboom" in r.message for r in caplog.records)


def test_a_client_factory_that_raises_is_retried_next_time():
    made = []

    def factory():
        made.append(1)
        if len(made) == 1:
            raise OSError("no sessions")
        return ScriptedClient(GAMES)

    w = FeedWorker(factory, lambda s: 15.0, Clock())
    w.poll_once()
    assert "no sessions" in w.snapshot().last_error and not w.snapshot().has_data
    w.poll_once()
    assert w.snapshot().has_data and len(made) == 2


def test_a_broken_interval_callback_falls_back_instead_of_killing_the_worker():
    def bad(snap):
        raise ValueError("nope")

    w = FeedWorker(lambda: ScriptedClient(GAMES), bad, Clock())
    assert w.poll_once() == 60.0 and w.snapshot().has_data


def test_a_slow_fetch_is_logged_with_its_duration(caplog):
    clock = Clock(0.0)

    class Slow(ScriptedClient):
        def scores(self, date=None):
            clock.now += 5.0
            return super().scores(date)

    w = make_worker(Slow(GAMES), clock=clock)
    with caplog.at_level(logging.DEBUG, logger="nhl_scoreboard.football.worker"):
        w.poll_once()
    assert w.snapshot().fetch_seconds == 5.0
    assert any("slow" in r.message and "5.0s" in r.message for r in caplog.records)
    caplog.clear()
    w2 = make_worker(ScriptedClient(GAMES), clock=Clock())
    with caplog.at_level(logging.DEBUG, logger="nhl_scoreboard.football.worker"):
        w2.poll_once()
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


# -- staleness -------------------------------------------------------------------


def test_staleness_is_about_the_last_success_not_the_last_attempt():
    snap = FeedSnapshot(games=tuple(GAMES), fetched_at=1000.0)
    assert not snap.is_stale(1000.0 + STALE_AFTER_SECONDS)
    assert snap.is_stale(1000.0 + STALE_AFTER_SECONDS + 0.1)
    assert snap.age(1060.0) == 60.0


def test_before_the_first_success_it_is_connecting_not_stale():
    snap = FeedSnapshot()
    assert snap.age(5000.0) is None and not snap.is_stale(5000.0)
    assert not FeedSnapshot(last_error="boom", failures=9).is_stale(99999.0)


def test_the_stale_window_matches_the_nhl_side():
    from nhl_scoreboard.app import STALE_AFTER_SECONDS as NHL

    assert STALE_AFTER_SECONDS == NHL == 15 * 60


# -- the thread ------------------------------------------------------------------


def test_the_thread_polls_and_publishes_without_the_caller_waiting():
    client = ScriptedClient(GAMES)
    w = FeedWorker(lambda: client, lambda s: 0.01)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().attempts >= 3)
        assert w.snapshot().games == tuple(GAMES)
    finally:
        w.stop()
    assert not feed_threads() and client.closed


def test_start_and_stop_are_idempotent():
    w = FeedWorker(lambda: ScriptedClient(GAMES), lambda s: 0.01)
    w.stop()  # stopping a worker that never started is fine
    w.start()
    w.start()
    assert len(feed_threads()) == 1
    w.stop()
    w.stop()
    assert not feed_threads() and not w.running


def test_a_stopped_worker_can_be_started_again_from_a_clean_snapshot():
    w = FeedWorker(lambda: ScriptedClient(GAMES), lambda s: 0.01)
    w.start()
    assert wait_for(lambda: w.snapshot().has_data)
    w.stop()
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().attempts >= 1)
        assert len(feed_threads()) == 1
    finally:
        w.stop()
    assert not feed_threads()


def test_an_exception_in_the_client_does_not_kill_the_thread():
    client = ScriptedClient(RuntimeError("one"), RuntimeError("two"), GAMES)
    w = FeedWorker(lambda: client, lambda s: 0.001)
    w.start()
    try:
        assert wait_for(lambda: w.snapshot().has_data), "the thread must survive and recover"
    finally:
        w.stop()
    assert w.snapshot().last_error == ""


class BlockingClient:
    """A fetch that takes as long as the test says (stands in for a slow request)."""

    def __init__(self, games):
        self.games = games
        self.entered = threading.Event()
        self.release = threading.Event()
        self.last_error = ""
        self.closed = False

    def scores(self, date=None):
        self.entered.set()
        assert self.release.wait(10), "the test never released the fetch"
        return self.games

    def close(self):
        self.closed = True


def test_a_slow_fetch_never_blocks_a_reader():
    client = BlockingClient(GAMES)
    w = FeedWorker(lambda: client, lambda s: 0.01)
    w.start()
    try:
        assert client.entered.wait(2), "the fetch should be in flight"
        started = time.monotonic()
        for _ in range(2000):
            assert w.snapshot().games is None  # still connecting; no waiting
        assert time.monotonic() - started < 0.5
        client.release.set()
        assert wait_for(lambda: w.snapshot().has_data)
    finally:
        client.release.set()
        w.stop()


def test_stop_returns_promptly_even_with_a_fetch_in_flight(monkeypatch):
    monkeypatch.setattr(worker_mod, "STOP_JOIN_SECONDS", 0.2)
    client = BlockingClient(GAMES)
    w = FeedWorker(lambda: client, lambda s: 0.01)
    w.start()
    assert client.entered.wait(2)
    started = time.monotonic()
    w.stop()
    assert time.monotonic() - started < 2.0
    client.release.set()


def test_a_result_that_lands_after_stop_is_never_published():
    first, second = BlockingClient(GAMES), ScriptedClient(UPCOMING)
    clients = iter([first, second])
    w = FeedWorker(lambda: next(clients), lambda s: 0.01)
    w.start()
    assert first.entered.wait(2)
    old = w._thread
    w.stop()
    w.start()  # a new generation, on the second client
    try:
        assert wait_for(lambda: w.snapshot().has_data)
        first.release.set()  # the old request finally returns
        old.join(3)
        assert not old.is_alive()
        assert w.snapshot().games == tuple(UPCOMING), "the stale generation must not publish"
    finally:
        first.release.set()
        w.stop()
    assert not feed_threads()


# -- NflMode ---------------------------------------------------------------------


def settings_with(poll=60.0, live=15.0):
    from nhl_scoreboard.config import ScoreboardConfig

    return dataclasses.replace(ScoreboardConfig(), poll_seconds=poll, live_poll_seconds=live)


def test_mode_polls_fast_while_live_and_slow_otherwise_never_below_the_feed_cache():
    cfg = [settings_with(poll=60, live=15)]
    mode = NflMode(lambda: cfg[0], client_factory=lambda: ScriptedClient(GAMES))
    live_snap = FeedSnapshot(games=tuple(GAMES))
    quiet_snap = FeedSnapshot(games=tuple(UPCOMING))
    assert mode._interval(live_snap) == 15.0
    assert mode._interval(quiet_snap) == 60.0
    assert mode._interval(FeedSnapshot()) == 60.0
    cfg[0] = settings_with(poll=60, live=2)  # a settings change applies at the next poll
    assert mode._interval(live_snap) == MIN_POLL_SECONDS
    cfg[0] = settings_with(poll=1, live=1)
    assert mode._interval(quiet_snap) == MIN_POLL_SECONDS


def test_mode_shows_connecting_until_the_first_result_then_the_stub():
    mode = NflMode(client_factory=lambda: ScriptedClient(GAMES))
    assert mode.scene().kind == "fb_connecting" and not mode.ready
    mode.refresh()  # the app's poll hook is a no-op
    assert mode.scene().kind == "fb_connecting"
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_stub" and mode.ready
    assert mode.snapshot.games == tuple(GAMES)


def test_mode_start_and_stop_run_the_worker_thread():
    mode = NflMode(client_factory=lambda: ScriptedClient(GAMES))
    mode.start()
    try:
        assert wait_for(lambda: mode.ready)
    finally:
        mode.stop()
    assert not feed_threads()


# -- in the app ------------------------------------------------------------------


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


@pytest.fixture
def app_factory(fake_backend):
    from nhl_scoreboard.app import ScoreboardApp
    from nhl_scoreboard.config import Settings

    made = []

    def make(client_factory):
        settings = Settings()
        settings.status.enabled = False
        app = ScoreboardApp(
            settings,
            client=_NhlStub(),
            backend=fake_backend,
            nfl_client_factory=client_factory,
        )
        made.append(app)
        return app

    yield make
    for app in made:
        if app._nfl is not None:
            app._nfl.stop()


class _NhlStub:
    def scores(self, *a, **k):
        return []

    def close(self):
        pass


def switch_sport(app, sport):
    new = dataclasses.replace(app.settings.scoreboard, sport=sport)
    app._apply_reloaded_settings(dataclasses.replace(app.settings, scoreboard=new))


def test_the_render_loop_keeps_drawing_while_a_fetch_is_in_flight(app_factory):
    client = BlockingClient(GAMES)
    app = app_factory(lambda: client)
    app._running = True  # as in run(): a switch now starts the feed thread
    switch_sport(app, "nfl")
    try:
        assert client.entered.wait(2)
        started = time.monotonic()
        for _ in range(50):
            app.draw()  # the whole scene path, through the real renderer
        assert time.monotonic() - started < 2.0, "drawing must not wait for the feed"
        assert app.select_scene().kind == "fb_connecting"
        client.release.set()
        assert wait_for(lambda: app.select_scene().kind == "fb_stub")
        app.draw()
    finally:
        client.release.set()


def test_switching_sport_starts_and_stops_the_feed_thread(app_factory):
    app = app_factory(lambda: ScriptedClient(GAMES))
    app._running = True
    base = len(feed_threads())
    switch_sport(app, "nfl")
    assert wait_for(lambda: app._nfl.ready) and len(feed_threads()) == base + 1
    switch_sport(app, "nhl")
    assert app._nfl is None and len(feed_threads()) == base


def test_rapid_switching_with_a_live_loop_leaves_no_threads(app_factory):
    app = app_factory(lambda: ScriptedClient(GAMES))
    app._running = True
    before = threading.active_count()
    for i in range(60):
        switch_sport(app, "nfl" if i % 2 == 0 else "nhl")
    assert app.current_mode() == "nhl"
    assert wait_for(lambda: threading.active_count() == before)
    assert not feed_threads()


def test_nothing_starts_a_thread_until_the_loop_runs(app_factory):
    """Constructing the app, or switching while it is not running, must not fetch."""
    made = []
    app = app_factory(lambda: made.append(1) or ScriptedClient(GAMES))
    switch_sport(app, "nfl")
    assert not feed_threads() and made == []


def test_shutdown_stops_the_feed_thread(app_factory):
    app = app_factory(lambda: ScriptedClient(GAMES))
    app._running = True
    switch_sport(app, "nfl")
    assert wait_for(lambda: app._nfl.ready)
    app.shutdown()
    assert not feed_threads()
