"""The scoreboard's games wait out the broadcast delay, as the plays do.

The scoreboard feed runs ahead of the play-by-play, so the resting field (possession, spot, score)
showed the new state before the play that caused it. Delaying the games by the same
``broadcast_delay_seconds`` keeps the field and its animations in step; a delay of 0 changes
nothing.
"""

from __future__ import annotations

from dataclasses import replace

from scoreboard.football.mode import FootballMode
from scoreboard.football.worker import FeedSnapshot
from test_football_events import make_game
from test_football_queue import Clock

OLD = (make_game("WSH", "NYG", game_id=1),)
NEW = (make_game("WSH", "NYG", game_id=1), make_game("PHI", "DAL", game_id=2))
LATER = (make_game("PHI", "DAL", game_id=2),)


class Rig:
    def __init__(self, delay: float) -> None:
        self.clock = Clock()
        self.delay = delay
        self.mode = FootballMode(
            monotonic=self.clock,
            delay_seconds=lambda: self.delay,
            utc_now=self.clock.utc,
        )
        self.raw = FeedSnapshot()
        self.mode.worker.snapshot = lambda: self.raw  # the worker thread is not started

    def fetch(self, games, at):
        self.raw = replace(self.raw, games=games, fetched_at=at, plays={1: ()})


def test_no_delay_passes_the_latest_games_straight_through():
    rig = Rig(0.0)
    rig.fetch(OLD, 1.0)
    assert rig.mode.snapshot.games == OLD
    rig.fetch(NEW, 2.0)
    assert rig.mode.snapshot.games == NEW


def test_the_first_result_is_shown_at_once_then_later_ones_wait():
    rig = Rig(45.0)
    rig.fetch(OLD, 1.0)
    assert rig.mode.snapshot.games == OLD  # a fresh start is not blank for 45 s
    rig.fetch(NEW, 2.0)
    assert rig.mode.snapshot.games == OLD
    rig.clock.advance(44.0)
    assert rig.mode.snapshot.games == OLD
    rig.clock.advance(1.5)
    assert rig.mode.snapshot.games == NEW


def test_everything_else_in_the_snapshot_is_the_live_one():
    rig = Rig(45.0)
    rig.fetch(OLD, 1.0)
    _ = rig.mode.snapshot
    rig.fetch(NEW, 2.0)
    snap = rig.mode.snapshot
    assert snap.games == OLD
    assert snap.fetched_at == 2.0  # staleness still follows the real fetch
    assert snap.plays == {1: ()}


def test_results_apply_in_order_even_if_the_delay_is_lowered():
    rig = Rig(45.0)
    rig.fetch(OLD, 1.0)
    _ = rig.mode.snapshot
    rig.fetch(NEW, 2.0)
    _ = rig.mode.snapshot
    rig.delay = 0.0
    rig.fetch(LATER, 3.0)
    assert rig.mode.snapshot.games == OLD  # NEW is due first; the later result never jumps it
    rig.clock.advance(46.0)
    assert rig.mode.snapshot.games == LATER


def test_no_data_yet_is_passed_through():
    rig = Rig(45.0)
    assert rig.mode.snapshot.games is None
