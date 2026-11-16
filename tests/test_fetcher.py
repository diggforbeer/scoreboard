"""NHL fetches run off the render thread (#267).

Two layers: the fetchers on their own (ordering, de-duplication, failure
handling), and the whole app on a ``ThreadedFetcher`` with a client that hangs,
which is the acceptance test the issue asks for: the render loop keeps drawing
while the API is slow, and the staleness guard still trips.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from nhl_scoreboard.app import STALE_AFTER_SECONDS
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.fetcher import InlineFetcher, ThreadedFetcher
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import PlayerSeasonDetail
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_flow import FAV, PUCK_DROP, Clock, FlowClient, game, goal_event, make_app


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


@pytest.fixture
def fetcher():
    worker = ThreadedFetcher()
    yield worker
    worker.close()


class Collected:
    """Records what ``done`` was called with, and from which thread."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, Exception | None, int]] = []

    def __call__(self, result, error) -> None:
        self.calls.append((result, error, threading.get_ident()))


# -- the fetchers on their own --------------------------------------------


def test_inline_runs_and_applies_on_the_calling_thread():
    done = Collected()
    assert InlineFetcher().submit("k", lambda: 7, done) is True
    assert done.calls == [(7, None, threading.get_ident())]


def test_inline_turns_an_api_error_into_a_failed_result():
    done = Collected()
    error = NHLApiError("boom")

    def work():
        raise error

    InlineFetcher().submit("k", work, done)
    assert done.calls[0][:2] == (None, error)


def test_inline_lets_a_bug_propagate_like_the_old_inline_calls_did():
    def work():
        raise KeyError("a parse bug")

    with pytest.raises(KeyError):
        InlineFetcher().submit("k", work, Collected())


def test_threaded_submit_returns_at_once_and_the_result_waits_for_drain(fetcher):
    release = threading.Event()
    done = Collected()
    started = time.monotonic()
    fetcher.submit("k", lambda: release.wait(5) and "answer", done)
    assert time.monotonic() - started < 0.5, "submit must not wait for the request"
    fetcher.drain()
    assert done.calls == [], "nothing has finished yet"

    release.set()
    assert fetcher.wait_idle()
    assert done.calls == [], "a finished result is only applied by drain()"
    fetcher.drain()
    assert [c[:2] for c in done.calls] == [("answer", None)]


def test_threaded_work_runs_off_the_calling_thread_and_done_runs_on_it(fetcher):
    seen: dict[str, int] = {}
    done = Collected()

    def work():
        seen["worker"] = threading.get_ident()

    fetcher.submit("k", work, done)
    assert fetcher.wait_idle()
    fetcher.drain()
    assert seen["worker"] != threading.get_ident()
    assert done.calls[0][2] == threading.get_ident()


def test_a_key_already_in_flight_is_not_queued_again(fetcher):
    release = threading.Event()
    calls = []

    def work():
        calls.append(1)
        release.wait(5)

    assert fetcher.submit("k", work, Collected()) is True
    assert fetcher.pending("k")
    for _ in range(5):
        assert fetcher.submit("k", work, Collected()) is False
    release.set()
    assert fetcher.wait_idle()
    assert len(calls) == 1

    assert fetcher.pending("k"), "still pending until its result is applied"
    fetcher.drain()
    assert not fetcher.pending("k")
    assert fetcher.submit("k", lambda: None, Collected()) is True


def test_results_apply_in_submission_order(fetcher):
    order = []
    for n in range(5):
        fetcher.submit(n, lambda n=n: n, lambda r, e: order.append(r))
    assert fetcher.wait_idle()
    fetcher.drain()
    assert order == [0, 1, 2, 3, 4]


def test_a_failure_is_delivered_and_the_worker_keeps_going(fetcher):
    done = Collected()
    api_error = NHLApiError("503")

    def raises_api():
        raise api_error

    def raises_bug():
        raise KeyError("parse")

    fetcher.submit("a", raises_api, done)
    fetcher.submit("b", raises_bug, done)
    fetcher.submit("c", lambda: "fine", done)
    assert fetcher.wait_idle()
    fetcher.drain()
    assert done.calls[0][:2] == (None, api_error)
    assert done.calls[1][0] is None and isinstance(done.calls[1][1], KeyError)
    assert done.calls[2][:2] == ("fine", None)


def test_close_is_idempotent_and_a_later_submit_restarts_the_worker(fetcher):
    fetcher.close()
    fetcher.close()
    done = Collected()
    fetcher.submit("k", lambda: 1, done)
    assert fetcher.wait_idle()
    fetcher.drain()
    assert done.calls[0][0] == 1


# -- the whole app on a hanging API ----------------------------------------


class HangingClient(FlowClient):
    """Answers like FlowClient, except calls wait on ``release`` first."""

    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()
        self.hang_scores = False
        self.score_calls = 0
        self.schedule_threads: list[int] = []
        #: Set once the worker is inside ``scores()``, so a test can stop racing it.
        self.entered = threading.Event()

    def scores(self, date="now"):
        self.score_calls += 1
        self.entered.set()
        if self.hang_scores:
            self.release.wait(20)
        return super().scores(date)

    def schedule(self, team):
        self.schedule_threads.append(threading.get_ident())
        if self.hang_scores:
            self.release.wait(20)
        return super().schedule(team)


def threaded_app(fake_backend, client, **cfg):
    clock = Clock(PUCK_DROP - timedelta(hours=2))
    app = make_app(fake_backend, clock, client, **cfg)
    app.fetcher = ThreadedFetcher()
    return app, clock


def settle(app) -> None:
    assert app.fetcher.wait_idle()
    app.fetcher.drain()


def test_the_render_loop_keeps_drawing_while_the_api_hangs(fake_backend):
    """The issue's acceptance test: a fetch that never returns must not stop frames."""
    client = HangingClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP)]
    client.hang_scores = True
    app, _clock = threaded_app(fake_backend, client)
    app.sleep = lambda _seconds: time.sleep(0.005)
    app.admin_server = None  # port 80 needs root, and the page isn't under test
    app._apply_boot_volume = lambda: None
    runner = threading.Thread(target=app.run, daemon=True)
    try:
        runner.start()
        deadline = time.monotonic() + 5
        while app.matrix.swaps < 40 and time.monotonic() < deadline:
            time.sleep(0.01)
        # Forty frames drawn, and the one fetch is still stuck inside the API.
        assert app.matrix.swaps >= 40, "the loop stalled behind the hung request"
        assert client.score_calls == 1
        assert app.games == []
    finally:
        app._running = False
        client.release.set()
        runner.join(5)
    assert not runner.is_alive()


def test_a_hung_fetch_is_not_retried_every_poll(fake_backend):
    client = HangingClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP)]
    client.hang_scores = True
    app, clock = threaded_app(fake_backend, client)
    try:
        app.refresh()
        assert client.entered.wait(2), "the worker never started the request"
        for _ in range(5):
            clock.advance(seconds=30)
            app.refresh()
        assert client.score_calls == 1, "a request still in flight must not be re-queued"
    finally:
        client.release.set()
        settle(app)
        app.fetcher.close()


def test_the_result_lands_once_the_api_answers(fake_backend):
    client = HangingClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP)]
    client.hang_scores = True
    app, _clock = threaded_app(fake_backend, client)
    try:
        app.refresh()
        app.fetcher.drain()
        assert app.games == [] and app.last_success is None

        client.release.set()
        settle(app)
        assert [g.id for g in app.games] == [1]
        assert app.last_success is not None
    finally:
        app.fetcher.close()


def test_staleness_still_trips_when_the_worker_hangs(fake_backend):
    """A hung worker must not keep showing the last good score forever."""
    client = HangingClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP)]
    app, clock = threaded_app(fake_backend, client)
    try:
        app.refresh()
        settle(app)
        assert app.select_scene().kind != "no_data"

        client.hang_scores = True
        clock.advance(seconds=STALE_AFTER_SECONDS + 60)
        app.refresh()  # queued behind a request that never returns
        app.fetcher.drain()
        assert app.is_stale()
        assert app.select_scene().kind == "no_data"
    finally:
        client.release.set()
        settle(app)
        app.fetcher.close()


def test_the_schedule_is_fetched_on_the_worker_not_the_render_thread(fake_backend):
    client = HangingClient()
    client.season = [game(2, FAV, "CAR", PUCK_DROP + timedelta(days=2))]
    app, _clock = threaded_app(fake_backend, client)
    try:
        assert app.next_favourite_game() is None  # nothing cached yet, and no waiting
        assert app.fetcher.wait_idle()
        assert client.schedule_threads and client.schedule_threads[0] != threading.get_ident()
        app.fetcher.drain()
        nxt = app.next_favourite_game()
        assert nxt is not None and nxt.id == 2
    finally:
        app.fetcher.close()


def test_a_schedule_for_the_old_favourite_is_dropped_after_a_switch(fake_backend):
    client = HangingClient()
    client.season = [game(2, FAV, "CAR", PUCK_DROP + timedelta(days=2))]
    client.hang_scores = True  # makes schedule() wait too
    app, _clock = threaded_app(fake_backend, client)
    try:
        app.next_favourite_game()  # in flight for NSH
        app.settings.scoreboard.favourite_team = "DAL"
        client.release.set()
        settle(app)
        assert app._schedule is None, "the old team's schedule must not land under the new one"
    finally:
        app.fetcher.close()


def test_a_failed_threaded_fetch_keeps_the_last_good_games_and_records_the_error(fake_backend):
    client = HangingClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP)]
    app, clock = threaded_app(fake_backend, client)
    try:
        app.refresh()
        settle(app)
        assert [g.id for g in app.games] == [1]

        def failing(date="now"):
            raise NHLApiError("503")

        client.scores = failing
        clock.advance(seconds=30)
        app.refresh()
        settle(app)
        assert [g.id for g in app.games] == [1]
        assert "score refresh" in app.last_error
    finally:
        app.fetcher.close()


# -- the scorer's roster rides on the goal fetch ----------------------------


class RosterClient(FlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.roster_calls: list[str] = []

    def team_roster(self, team):
        self.roster_calls.append(team)
        return super().team_roster(team)


def live_favourite(fake_backend, *, threaded: bool):
    client = RosterClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=1)]
    client.team_rosters = {FAV: {8480000: PlayerSeasonDetail(sweater_number=9, points=12)}}
    clock = Clock(PUCK_DROP + timedelta(minutes=10))
    app = make_app(fake_backend, clock, client, live_poll_seconds=0)
    if threaded:
        app.fetcher = ThreadedFetcher()
    app.refresh()
    return app, clock, client


@pytest.mark.parametrize("threaded", [False, True], ids=["inline", "threaded"])
def test_the_roster_is_fetched_lazily_once_and_before_the_scorer_screen(fake_backend, threaded):
    app, _clock, client = live_favourite(fake_backend, threaded=threaded)

    def poll():
        app.refresh_goal_details()
        if threaded:
            settle(app)

    try:
        if threaded:
            settle(app)
        poll()  # baseline: whatever is already scored never shows a screen
        assert client.roster_calls == [], "no roster until a goal is about to show"

        client.goal_events[1] = (goal_event(),)
        poll()
        assert client.roster_calls == [FAV], "fetched with the goal, not on first sight of the game"
        shown = app._goal_detail
        assert shown is not None
        assert shown[2].scorer_sweater_number == 9, "the number is there when the screen is built"
        assert shown[2].scorer_points == 12

        client.goal_events[1] = (goal_event(), goal_event(scorer="J. SMITH", player_id=1))
        poll()
        assert client.roster_calls == [FAV], "a second goal reuses the cached roster"
    finally:
        app.fetcher.close()


def test_a_failed_roster_fetch_still_shows_the_scorer(fake_backend):
    app, _clock, client = live_favourite(fake_backend, threaded=False)

    def failing(team):
        raise NHLApiError("boom")

    client.team_roster = failing
    app.refresh_goal_details()
    client.goal_events[1] = (goal_event(),)
    app.refresh_goal_details()
    shown = app._goal_detail
    assert shown is not None and shown[2].scorer_name == "F. FORSBERG"
    assert shown[2].scorer_sweater_number is None
