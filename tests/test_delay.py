"""Broadcast delay (#301): the board shows the API as it was N seconds ago."""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import pytest

from nhl_scoreboard.delay import DelayQueue
from nhl_scoreboard.display.matrix import Backend
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_flow import (
    FAV,
    PUCK_DROP,
    Clock,
    FlowClient,
    game,
    make_app,
    scene,
    score,
    tick,
)

# -- the queue itself ---------------------------------------------------------


def test_queue_applies_the_first_result_at_once_and_later_ones_after_the_delay():
    now = [100.0]
    queue = DelayQueue(lambda: now[0])
    seen: list[str] = []
    queue.submit("k", 45, lambda: seen.append("first"))
    queue.submit("k", 45, lambda: seen.append("second"))
    assert seen == ["first"]
    now[0] = 144.0
    queue.drain()
    assert seen == ["first"]
    now[0] = 145.0
    queue.drain()
    assert seen == ["first", "second"]


def test_queue_keys_are_independent():
    now = [0.0]
    queue = DelayQueue(lambda: now[0])
    seen: list[str] = []
    queue.submit("a", 45, lambda: seen.append("a1"))
    queue.submit("b", 45, lambda: seen.append("b1"))
    assert seen == ["a1", "b1"]


def test_lowering_the_delay_never_reorders_one_key():
    now = [0.0]
    queue = DelayQueue(lambda: now[0])
    seen: list[str] = []
    queue.submit("k", 45, lambda: seen.append("first"))
    queue.submit("k", 45, lambda: seen.append("old"))
    now[0] = 1.0
    queue.submit("k", 0, lambda: seen.append("new"))
    assert seen == ["first"]
    now[0] = 45.0
    queue.drain()
    assert seen == ["first", "old", "new"]


# -- the board ---------------------------------------------------------------


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


def live_day(fake_backend, delay: float):
    client = FlowClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=1)]
    clock = Clock(PUCK_DROP + timedelta(minutes=10))
    app = make_app(fake_backend, clock, client, broadcast_delay_seconds=delay)
    app.refresh()
    return app, clock, client


def test_restart_shows_data_immediately_not_blank_for_the_delay(fake_backend):
    app, _, _ = live_day(fake_backend, 45)
    assert scene(app) == ("game", 1)


def test_goal_horn_screen_and_score_all_wait_for_the_delay(fake_backend):
    app, clock, client = live_day(fake_backend, 45)
    client.today[0] = score(client.today[0], home=1)
    app.refresh()  # the API shows the goal now; the board must not
    clock.advance(seconds=44)
    app.draw()
    assert app.horn.calls == []
    assert app.games[0].home.score == 0

    clock.advance(seconds=1)
    app.draw()  # the loop's own tick drains what has come due
    assert app.horn.calls == [FAV]
    assert app.games[0].home.score == 1
    assert scene(app) == ("goal", 1)


def test_scores_arrive_in_order_after_the_delay(fake_backend):
    app, clock, client = live_day(fake_backend, 30)
    client.today[0] = score(client.today[0], home=1)
    app.refresh()
    clock.advance(seconds=10)
    client.today[0] = score(client.today[0], home=2)
    app.refresh()
    assert app.games[0].home.score == 0
    clock.advance(seconds=20)
    app.draw()
    assert app.games[0].home.score == 1
    clock.advance(seconds=10)
    app.draw()
    assert app.games[0].home.score == 2


def test_no_delay_applies_immediately(fake_backend):
    app, clock, client = live_day(fake_backend, 0)
    client.today[0] = score(client.today[0], home=1)
    tick(app, clock, seconds=15)
    assert app.horn.calls == [FAV]
    assert app.games[0].home.score == 1


def test_lowering_the_delay_keeps_order_and_catches_up(fake_backend):
    """Results already waiting keep their due time; new ones queue behind them."""
    app, clock, client = live_day(fake_backend, 45)
    client.today[0] = score(client.today[0], home=1)
    app.refresh()
    app.settings.scoreboard.broadcast_delay_seconds = 0
    clock.advance(seconds=1)
    client.today[0] = score(client.today[0], home=2)
    app.refresh()
    assert app.games[0].home.score == 0

    clock.advance(seconds=44)
    app.draw()
    assert app.games[0].home.score == 2

    client.today[0] = score(client.today[0], home=3)
    app.refresh()
    assert app.games[0].home.score == 3


def test_polling_follows_the_api_not_the_delayed_view(fake_backend):
    """A game live in the API polls at the live cadence before the board shows it live."""
    client = FlowClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "FUT")]
    clock = Clock(PUCK_DROP - timedelta(minutes=1))
    app = make_app(fake_backend, clock, client, broadcast_delay_seconds=45)
    app.refresh()
    client.today[0] = dataclasses.replace(client.today[0], state="LIVE", period=1)
    tick(app, clock, seconds=20)
    assert app.games[0].state == "FUT"
    assert app.poll_interval() == app.settings.scoreboard.live_poll_seconds
