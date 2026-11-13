"""``nhl-scoreboard --watch-nfl``: see the play queue run (#355).

Prints each play as it would be animated, with the queue depth, how far behind the live
game it ran and whether the queue was catching up. Driven by the live feed, or by a
saved ``summary`` file replayed a few plays per poll, which is the way to *see* a burst
and the catch-up rules without waiting for a game. The loop takes its clock, sleep and
output as arguments so it can be tested without waiting.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .api import plays_from_summary
from .models import Play
from .queue import PlayWatcher, Shown

#: What the watcher pretends an animation lasts. The real durations belong to the screens.
ASSUMED_ANIMATION_SECONDS = 3.0
POLL_SECONDS = 10.0


class FixtureFeed:
    """Replays a saved game: each poll returns a few more plays than the last."""

    def __init__(self, plays: list[Play], chunk: int = 3) -> None:
        self.plays = plays
        self.chunk = max(1, chunk)
        self.shown = 0

    @classmethod
    def from_file(cls, path: str | Path, chunk: int = 3) -> FixtureFeed:
        """A saved file has no live clock, so its ``wallclock`` times are dropped: lag then
        reads ``n/a`` instead of a meaningless difference from the replay's fake time."""
        plays = plays_from_summary(json.loads(Path(path).read_text()))
        return cls([replace(p, wallclock=None) for p in plays], chunk)

    @property
    def exhausted(self) -> bool:
        return self.shown >= len(self.plays)

    def __call__(self) -> list[Play]:
        self.shown = min(len(self.plays), self.shown + self.chunk)
        return self.plays[: self.shown]


def describe(shown: Shown, elapsed: float) -> str:
    p = shown.play
    lag = "n/a" if shown.lag_seconds is None else f"{shown.lag_seconds:.0f}s"
    skipped = f" skipped={len(shown.skipped)}" if shown.skipped else ""
    return (
        f"+{elapsed:6.1f}s  Q{p.period} {p.clock:>5}  {p.kind.value:<26} "
        f"depth={shown.depth} speed={shown.speed:.1f} lag={lag}{skipped}  {p.text[:60]}"
    )


def watch(
    fetch: Callable[[], list[Play] | None],
    game_id: int | str = "game",
    *,
    poll_seconds: float = POLL_SECONDS,
    animation_seconds: float = ASSUMED_ANIMATION_SECONDS,
    delay_seconds: float = 0.0,
    exhausted: Callable[[], bool] | None = None,
    out: Callable[[str], None] = print,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    utc_now: Callable[[], datetime] | None = None,
    tick_seconds: float = 0.25,
    max_polls: int | None = None,
) -> int:
    """Poll ``fetch`` every ``poll_seconds`` and print each play as it is shown.

    Stops when ``exhausted()`` is true and nothing is left to show, after ``max_polls``
    polls, or on Ctrl-C. Returns the number of plays shown.
    """
    started = monotonic()
    watcher = PlayWatcher(monotonic, lambda: delay_seconds, utc_now or (lambda: datetime.now(UTC)))
    next_poll = started
    animation_ends = started
    polls = 0
    shown_count = 0
    try:
        while True:
            now = monotonic()
            if now >= next_poll and not (exhausted and exhausted() and polls):
                plays = fetch()
                polls += 1
                if plays is not None:
                    watcher.on_fetch(game_id, plays)
                next_poll = now + poll_seconds
            watcher.tick()
            queue = watcher.queue(game_id)
            if now >= animation_ends:
                shown = watcher.next(game_id)
                if shown is not None:
                    shown_count += 1
                    out(describe(shown, now - started))
                    animation_ends = now + animation_seconds / shown.speed
            finished_polling = (exhausted is not None and exhausted()) or (
                max_polls is not None and polls >= max_polls
            )
            idle = queue.depth == 0 and watcher.waiting == 0 and now >= animation_ends
            if finished_polling and idle:
                queue.finish()
                return shown_count
            sleep(tick_seconds)
    except KeyboardInterrupt:
        return shown_count


def simulated(start: datetime | None = None):
    """A fake clock for replaying a fixture instantly: (monotonic, sleep, utc_now)."""
    state = {"t": 0.0}
    base = start or datetime(2026, 11, 8, 14, 0, tzinfo=UTC)

    def monotonic() -> float:
        return state["t"]

    def sleep(seconds: float) -> None:
        state["t"] += seconds

    def utc_now() -> datetime:
        return base + timedelta(seconds=state["t"])

    return monotonic, sleep, utc_now
