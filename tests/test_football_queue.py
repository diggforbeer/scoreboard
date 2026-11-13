"""The play queue, its delay hand-off and ``--watch-nfl`` (#355).

Plays are real ones from ``play_cases.json`` given fresh ids, sequence numbers and
wallclock times, so a feed can be scripted exactly. Time is a fake clock throughout.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nhl_scoreboard import __main__ as cli
from nhl_scoreboard.football import queue as q
from nhl_scoreboard.football import watch as w
from nhl_scoreboard.football.models import Play, PlayKind
from nhl_scoreboard.football.queue import PlayQueue, PlayWatcher

FIXTURES = Path(__file__).parent / "fixtures" / "football"
BASE = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
K = PlayKind


def case(label: str) -> dict:
    data = json.loads((FIXTURES / "play_cases.json").read_text())
    return next(c["play"] for c in data["cases"] if c["label"] == label)


def play(n: int, label: str = "rush", at: float | None = None) -> Play:
    """A real play of kind ``label`` as the ``n``-th of a game, ``at`` seconds after BASE."""
    raw = copy.deepcopy(case(label))
    raw["id"] = f"play{n:04d}"
    raw["sequenceNumber"] = str(n * 100)
    when = BASE + timedelta(seconds=n * 40 if at is None else at)
    raw["wallclock"] = when.strftime("%Y-%m-%dT%H:%M:%SZ")
    return Play.from_api(raw)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds

    def utc(self):
        return BASE + timedelta(seconds=self.t - 1000.0)


def make_queue(clock=None, **kw):
    clock = clock or Clock()
    return PlayQueue(clock, clock.utc, label="g", **kw), clock


def drain(queue):
    out = []
    while (shown := queue.next()) is not None:
        out.append(shown)
    return out


# -- baseline, de-duplication, order ----------------------------------------------


def test_a_trickle_of_plays_is_shown_one_at_a_time_in_order():
    queue, clock = make_queue()
    assert queue.offer([]) == [] and queue.baselined
    p1, p2, p3 = play(1, "kickoff_return"), play(2, "rush"), play(3, "pass_complete")
    assert queue.offer([p1]) == [p1]
    shown = queue.next()
    assert shown.play is p1 and shown.speed == 1.0 and shown.depth == 1 and shown.skipped == ()
    assert queue.next() is None
    assert queue.offer([p1, p2]) == [p2]  # the poll repeats p1: only p2 is new
    clock.advance(40)
    assert queue.offer([p1, p2, p3]) == [p3]
    assert [s.play.id for s in drain(queue)] == [p2.id, p3.id]


def test_a_repeated_poll_adds_nothing():
    queue, _ = make_queue()
    queue.offer([])
    plays = [play(1), play(2)]
    assert len(queue.offer(plays)) == 2
    assert queue.offer(plays) == [] and queue.depth == 2
    assert len(drain(queue)) == 2
    assert queue.offer(plays) == [] and queue.next() is None, "a shown play is never shown again"


def test_a_start_mid_game_animates_nothing_from_before_it_started():
    queue, _ = make_queue()
    history = [play(n) for n in range(1, 11)]
    assert queue.offer(history) == []
    assert queue.next() is None and queue.depth == 0
    assert queue.latest is history[-1], "but the board still knows where the ball is"
    fresh = play(11, "pass_complete")
    assert queue.offer([*history, fresh]) == [fresh]
    assert queue.next().play is fresh


def test_a_game_watched_from_before_the_first_play_animates_from_the_opening_kickoff():
    queue, _ = make_queue()
    queue.offer([])  # pre-game: the feed has no plays yet
    kickoff = play(1, "kickoff_return")
    assert queue.offer([kickoff]) == [kickoff]
    assert queue.next().play is kickoff


def test_plays_listed_out_of_order_are_shown_in_sequence_order():
    queue, _ = make_queue(backlog=5)
    queue.offer([])
    a, b, c = play(1), play(2, "pass_complete"), play(3, "sack")
    queue.offer([c, a, b])
    assert [s.play.id for s in drain(queue)] == [a.id, b.id, c.id]


def test_a_play_that_arrives_late_is_slotted_in_if_still_waiting_and_dropped_if_passed(caplog):
    queue, _ = make_queue(backlog=5)
    queue.offer([])
    p1, p4 = play(1), play(4)
    queue.offer([p1, p4])
    p3 = play(3, "pass_complete")
    queue.offer([p1, p3, p4])  # p3 turns up between two plays that are still waiting
    assert [s.play.id for s in drain(queue)] == [p1.id, p3.id, p4.id]
    with caplog.at_level(logging.INFO):
        stale = play(0, "sack")
        assert queue.offer([stale, p1, p3, p4]) == []  # the board has already moved past it
    assert queue.depth == 0 and any("late play" in r.message for r in caplog.records)
    assert queue.latest is p4


def test_a_play_rewritten_after_a_review_keeps_its_id_and_is_not_shown_twice():
    queue, _ = make_queue()
    queue.offer([])
    original = play(1, "pass_td_pat")
    queue.offer([original])
    assert queue.next().play is original
    rewritten = Play.from_api({**case("review_reversed_touchdown"), "id": original.id,
                               "sequenceNumber": "100"})  # fmt: skip
    assert queue.offer([rewritten]) == [] and queue.next() is None


# -- catching up --------------------------------------------------------------------


def test_a_burst_drops_stoppages_first_then_the_oldest_and_shows_the_newest():
    queue, _ = make_queue()
    queue.offer([])
    burst = [
        play(1, "kickoff_return"),
        play(2, "rush"),
        play(3, "timeout"),
        play(4, "pass_complete"),
        play(5, "end_period"),
    ]
    queue.offer(burst)
    first = queue.next()
    # 5 waiting, backlog 2: both stoppages go, then the oldest ball play.
    assert first.depth == 5 and first.speed == q.SPEEDUP
    assert {p.kind for p in first.skipped} == {K.TIMEOUT, K.END_PERIOD, K.KICKOFF}
    assert [p.id for p in first.skipped] == ["play0001", "play0003", "play0005"]
    assert first.play.id == "play0002"
    second = queue.next()
    assert second.play.id == "play0004", "the newest ball-moving play is always shown"
    assert second.speed == 1.0 and second.depth == 1 and queue.next() is None


def test_stoppages_are_dropped_before_any_ball_movement():
    queue, _ = make_queue()
    queue.offer([])
    plays = [play(1, "rush"), play(2, "timeout"), play(3, "pass_complete"), play(4, "sack")]
    queue.offer(plays)
    first = queue.next()  # 4 waiting: dropping the one timeout leaves 3, then the oldest rush goes
    assert [p.kind for p in first.skipped] == [K.RUSH, K.TIMEOUT]
    assert [first.play.kind, queue.next().play.kind] == [K.PASS_COMPLETE, K.SACK]


def test_no_catch_up_while_the_backlog_is_within_bounds():
    queue, _ = make_queue()
    queue.offer([])
    queue.offer([play(1, "timeout"), play(2, "rush")])  # 2 waiting == backlog
    first = queue.next()
    assert first.speed == 1.0 and first.skipped == () and first.play.kind == K.TIMEOUT


def test_halftime_and_the_end_of_the_game_are_never_dropped_even_when_far_behind():
    queue, _ = make_queue()
    queue.offer([])
    queue.offer(
        [play(1, "rush"), play(2, "end_half"), play(3, "end_game"), play(4, "pass_complete")]
    )
    first = queue.next()
    assert [p.kind for p in first.skipped] == [K.RUSH], "only the old ball play goes"
    shown = [first, *drain(queue)]
    assert [s.play.kind for s in shown] == [K.END_HALF, K.END_GAME, K.PASS_COMPLETE]
    assert shown[0].depth == 4 and shown[0].speed == q.SPEEDUP


def test_the_newest_ball_play_survives_even_when_only_keepers_are_left_to_drop():
    queue, _ = make_queue(backlog=1)
    queue.offer([])
    queue.offer([play(1, "end_half"), play(2, "end_game"), play(3, "rush")])
    shown = drain(queue)
    assert [s.play.kind for s in shown] == [K.END_HALF, K.END_GAME, K.RUSH]


def test_a_long_burst_of_ball_plays_skips_to_the_last_two():
    queue, _ = make_queue()
    queue.offer([])
    queue.offer([play(n, "rush") for n in range(1, 9)])
    first = queue.next()
    assert len(first.skipped) == 6 and first.play.id == "play0007" and first.speed == q.SPEEDUP
    assert queue.next().play.id == "play0008" and queue.next() is None


def test_a_custom_backlog_and_speedup():
    queue, _ = make_queue(backlog=4, speedup=3.0)
    queue.offer([])
    queue.offer([play(n) for n in range(1, 5)])
    assert queue.next().speed == 1.0  # 4 waiting == backlog
    queue2, _ = make_queue(backlog=4, speedup=3.0)
    queue2.offer([])
    queue2.offer([play(n) for n in range(1, 7)])
    first = queue2.next()
    assert first.speed == 3.0 and len(first.skipped) == 2


def test_catching_up_never_loses_where_the_ball_is():
    queue, _ = make_queue()
    queue.offer([])
    plays = [play(n, "rush") for n in range(1, 8)] + [play(8, "timeout")]
    queue.offer(plays)
    assert queue.latest is plays[-1]  # even though that last play is a dropped stoppage
    shown = drain(queue)
    assert shown[-1].play.kind == K.RUSH and shown[-1].play.id == "play0007"


# -- time and the log ------------------------------------------------------------------


def test_a_play_is_timed_from_when_it_is_shown_not_from_its_wallclock():
    queue, clock = make_queue()
    queue.offer([])
    p = play(1, "rush", at=0)
    queue.offer([p])
    clock.advance(25)  # the board noticed it 25s after it happened
    shown = queue.next()
    assert shown.shown_at == clock.t and shown.lag_seconds == pytest.approx(25.0)
    assert queue.current is shown
    queue.finish()
    assert queue.current is None


def test_a_play_without_a_wallclock_has_no_lag():
    queue, _ = make_queue()
    queue.offer([])
    raw = copy.deepcopy(case("rush"))
    raw["id"], raw["sequenceNumber"] = "x", "5"
    del raw["wallclock"]
    queue.offer([Play.from_api(raw)])
    assert queue.next().lag_seconds is None


def test_every_play_logs_its_depth_lag_speed_and_how_long_it_ran(caplog):
    queue, clock = make_queue()
    with caplog.at_level(logging.INFO, logger="nhl_scoreboard.football.queue"):
        queue.offer([])
        queue.offer([play(n, "rush", at=0) for n in range(1, 5)])
        clock.advance(12)
        first = queue.next()
        clock.advance(1.5)
        queue.next()  # finishing the first logs how long it was animated
    messages = [r.getMessage() for r in caplog.records]
    shown = next(m for m in messages if "play shown" in m)
    for field in ("id=play0003", "seq=300", "kind=rush", "depth=4", "lag=12.0s", "speed=2.0",
                  "skipped=2"):  # fmt: skip
        assert field in shown, field
    done = next(m for m in messages if "play animated" in m)
    assert "id=play0003" in done and "took=1.50s" in done and "speed=2.0" in done
    assert first.lag_seconds == pytest.approx(12.0)


def test_the_baseline_is_logged_so_a_mid_game_start_is_visible(caplog):
    queue, _ = make_queue()
    with caplog.at_level(logging.INFO, logger="nhl_scoreboard.football.queue"):
        queue.offer([play(n) for n in range(1, 4)])
    assert any("baseline: 3 plays" in r.getMessage() for r in caplog.records)


# -- the broadcast delay -----------------------------------------------------------------


def make_watcher(delay=30.0):
    clock = Clock()
    return PlayWatcher(clock, lambda: delay, clock.utc), clock


def test_with_a_30s_delay_the_first_new_play_is_shown_30s_after_it_arrives():
    watcher, clock = make_watcher(30.0)
    watcher.on_fetch("g", [])  # the first result applies at once: it is the baseline
    p1 = play(1, "kickoff_return")
    watcher.on_fetch("g", [p1])
    assert watcher.next("g") is None, "not yet: it arrived just now"
    clock.advance(29.9)
    assert watcher.next("g") is None
    clock.advance(0.2)
    shown = watcher.next("g")
    assert shown.play is p1 and shown.shown_at == clock.t


def test_the_delay_keeps_order_across_polls_even_if_it_is_lowered():
    delay = [30.0]
    clock = Clock()
    watcher = PlayWatcher(clock, lambda: delay[0], clock.utc)
    watcher.on_fetch("g", [])
    a, b = play(1), play(2, "pass_complete")
    watcher.on_fetch("g", [a])
    clock.advance(5)
    delay[0] = 0.0  # the owner lowers the delay between two polls
    watcher.on_fetch("g", [a, b])
    watcher.tick()
    assert watcher.queue("g").depth == 0, "b must not overtake a, which is still waiting out 30s"
    clock.advance(30)
    assert [s.play.id for s in _drain_watcher(watcher, "g")] == [a.id, b.id]


def _drain_watcher(watcher, game):
    out = []
    while (shown := watcher.next(game)) is not None:
        out.append(shown)
    return out


def test_no_delay_applies_everything_at_once():
    watcher, _ = make_watcher(0.0)
    watcher.on_fetch("g", [])
    watcher.on_fetch("g", [play(1)])
    assert watcher.next("g").play.id == "play0001"


def test_each_game_has_its_own_queue_and_baseline():
    watcher, _ = make_watcher(0.0)
    watcher.on_fetch(1, [play(1), play(2)])  # game 1 is already under way
    watcher.on_fetch(2, [])  # game 2 has not started
    watcher.on_fetch(1, [play(1), play(2), play(3)])
    watcher.on_fetch(2, [play(1)])
    assert watcher.next(1).play.id == "play0003"
    assert watcher.next(2).play.id == "play0001"
    watcher.forget(lambda g: g == 2)
    assert watcher.queue(1).baselined is False, "a forgotten game starts over"


# -- --watch-nfl --------------------------------------------------------------------------


def test_replaying_a_fixture_shows_every_new_play_once_in_order():
    plays = [w.replace(play(n, "rush"), wallclock=None) for n in range(1, 9)]
    feed = w.FixtureFeed(plays, chunk=2)
    monotonic, sleep, utc_now = w.simulated()
    lines = []
    shown = w.watch(feed, "g", exhausted=lambda: feed.exhausted, out=lines.append,
                    monotonic=monotonic, sleep=sleep, utc_now=utc_now)  # fmt: skip
    assert shown == len(lines)
    ids = [line for line in lines]
    assert shown >= 3 and all("depth=" in line and "speed=" in line for line in ids)
    assert all("lag=n/a" in line for line in lines), "a replay has no live clock"


def test_a_replay_with_big_chunks_shows_the_catch_up():
    plays = [w.replace(play(n, "rush"), wallclock=None) for n in range(1, 13)]
    feed = w.FixtureFeed(plays, chunk=6)
    monotonic, sleep, utc_now = w.simulated()
    lines = []
    w.watch(feed, "g", exhausted=lambda: feed.exhausted, out=lines.append,
            monotonic=monotonic, sleep=sleep, utc_now=utc_now)  # fmt: skip
    assert any("speed=2.0" in line and "skipped=" in line for line in lines)
    assert lines[-1].endswith(plays[-1].text[:60]), "the newest play is always shown last"


def test_the_live_loop_stops_on_ctrl_c_and_keeps_what_it_showed():
    monotonic, sleep, utc_now = w.simulated()
    calls = []

    def fetch():
        calls.append(1)
        if len(calls) == 1:
            return []
        if len(calls) == 2:
            return [play(1)]
        raise KeyboardInterrupt

    lines = []
    shown = w.watch(fetch, "g", out=lines.append, monotonic=monotonic, sleep=sleep, utc_now=utc_now)
    assert shown == 1 and len(lines) == 1


def test_a_failed_poll_is_skipped_not_fatal():
    monotonic, sleep, utc_now = w.simulated()
    results = iter([[], None, [play(1)]])
    lines = []
    w.watch(lambda: next(results), "g", out=lines.append, monotonic=monotonic, sleep=sleep,
            utc_now=utc_now, max_polls=3)  # fmt: skip
    assert len(lines) == 1


def test_the_cli_replays_a_fixture_file(capsys, caplog):
    path = FIXTURES / "summary_drives.json"
    assert cli.main(["--watch-nfl", "401873038", "--fixture", str(path), "--chunk", "5"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out and all(line.startswith("+") and "depth=" in line for line in out)
    assert any("skipped=" in line for line in out)


def test_the_cli_uses_the_configured_broadcast_delay(tmp_path, capsys):
    """The first poll is the baseline; the second (at +10s) is held for the 30s delay."""
    cfg = tmp_path / "scoreboard.toml"
    cfg.write_text("[scoreboard]\nbroadcast_delay_seconds = 30\n")
    path = FIXTURES / "summary_drives.json"
    assert (
        cli.main(["--watch-nfl", "1", "--fixture", str(path), "--chunk", "3", "-c", str(cfg)]) == 0
    )
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("+  40."), first
    assert cli.main(["--watch-nfl", "1", "--fixture", str(path), "--chunk", "3"]) == 0
    assert capsys.readouterr().out.splitlines()[0].startswith("+  10."), "no delay: shown at once"


def test_a_replay_does_not_stop_while_results_are_still_held_by_the_delay():
    plays = [w.replace(play(n, "rush"), wallclock=None) for n in range(1, 7)]
    feed = w.FixtureFeed(plays, chunk=3)
    monotonic, sleep, utc_now = w.simulated()
    lines = []
    w.watch(feed, "g", delay_seconds=60.0, exhausted=lambda: feed.exhausted, out=lines.append,
            monotonic=monotonic, sleep=sleep, utc_now=utc_now)  # fmt: skip
    assert len(lines) >= 1, "plays still waiting out the delay must be shown, not abandoned"
