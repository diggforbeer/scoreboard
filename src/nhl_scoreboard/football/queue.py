"""Turn polled plays into an ordered queue of plays to animate (#355).

The play client returns **every play so far** on each poll, a whole drive can arrive
in one poll, and the board may be a minute behind the broadcast. This module decides
which plays get animated, in what order and how fast. It draws nothing and knows no
durations: the caller shows a play, and asks for the next one when it is done.

The rules (``football_screen.md``, "Every other play: pace, queueing and catch-up"):

* **Plays are de-duplicated by id and ordered by ``sequenceNumber``**, whatever order a
  poll lists them in or how often one is repeated.
* **The first poll is a baseline.** A board that starts mid-game animates nothing that
  happened before it started (the same rule as NHL goal detection), but ``latest`` still
  says where the ball is. A game the board is already watching when it begins, whose
  first poll is empty, animates from the opening kickoff.
* **Catch-up.** If more plays are waiting than ``backlog`` (2), the ones that carry no
  ball movement are dropped first (timeouts, official timeouts, the two-minute warning,
  end of a quarter), oldest first; if that is not enough the oldest plays are skipped so
  only ``backlog`` remain, and the one shown is shown at ``speedup`` (2x). Halftime, the
  end of regulation and the end of the game are never dropped (they carry state), and
  neither is the newest ball-moving play: it is always shown, and ``latest`` always has the
  real position.
* **Time is when a play is *shown*, not its ``wallclock``**, so the broadcast delay shifts
  everything together. The delay itself is not here: poll results go through the existing
  :class:`~..delay.DelayQueue` (:class:`PlayWatcher`), as the NHL side does, so no
  animation has delay logic of its own.
* **Every play logs how far behind it ran** (queue depth, seconds from its ``wallclock`` to
  being shown, speed, how many plays were skipped) and how long it was animated, at INFO,
  so a real game's lag can be read from the journal. That is the evidence the deferred
  "animation pace" question needs.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..delay import DelayQueue
from .models import Play, PlayKind

log = logging.getLogger(__name__)

#: How many plays may wait before the queue starts catching up.
BACKLOG = 2
#: How much faster a play is shown while catching up.
SPEEDUP = 2.0

#: Plays with no ball movement: dropped first when the queue is behind.
STOPPAGES = frozenset(
    {
        PlayKind.TIMEOUT,
        PlayKind.OFFICIAL_TIMEOUT,
        PlayKind.TWO_MINUTE_WARNING,
        PlayKind.END_PERIOD,
    }
)


#: Plays that are never dropped, even when the queue is far behind: halftime, the end of
#: regulation and the end of the game carry state the board needs (a card, the final).
KEEPERS = frozenset({PlayKind.END_HALF, PlayKind.END_REGULATION, PlayKind.END_GAME})


@dataclass(frozen=True, slots=True)
class Shown:
    """A play to animate now."""

    play: Play
    #: Monotonic time it was handed out. The animation clock starts here.
    shown_at: float
    #: 1.0 normally, ``SPEEDUP`` while catching up.
    speed: float
    #: Plays that were waiting when this one was chosen (before any were dropped).
    depth: int
    #: Plays dropped to catch up, oldest first (stoppages first, then the oldest plays).
    skipped: tuple[Play, ...]
    #: Seconds from the play's ``wallclock`` to ``shown_at``; ``None`` if it had none.
    lag_seconds: float | None


@dataclass
class PlayQueue:
    """One game's queue. Not thread-safe: the render loop owns it."""

    monotonic: Callable[[], float] = time.monotonic
    utc_now: Callable[[], datetime] = lambda: datetime.now(UTC)
    backlog: int = BACKLOG
    speedup: float = SPEEDUP
    label: str = ""

    baselined: bool = field(default=False, init=False)
    #: The newest play already played when the first poll arrived (``None`` if the game had
    #: not started). Its score is the score the board starts from, so nothing downstream
    #: celebrates it (#356).
    baseline: Play | None = field(default=None, init=False)
    #: The newest play offered (shown or not): where the ball really is.
    latest: Play | None = field(default=None, init=False)
    current: Shown | None = field(default=None, init=False)
    _seen: set[str] = field(default_factory=set, init=False, repr=False)
    _pending: list[Play] = field(default_factory=list, init=False, repr=False)
    _last_shown_key: tuple | None = field(default=None, init=False, repr=False)

    @property
    def depth(self) -> int:
        """Plays waiting to be shown."""
        return len(self._pending)

    # -- input -----------------------------------------------------------

    def offer(self, plays: Iterable[Play]) -> list[Play]:
        """Take a poll's plays. Returns the ones newly queued to animate (after the baseline)."""
        batch = sorted(plays, key=Play.sort_key)
        if not self.baselined:
            # Whatever is there now has already happened.
            self.baselined = True
            self._seen.update(p.id for p in batch)
            self.latest = batch[-1] if batch else None
            self.baseline = self.latest
            if batch:
                log.info(
                    "%sbaseline: %d plays already played, not animated", self._tag(), len(batch)
                )
            return []
        added: list[Play] = []
        for play in batch:
            if play.id in self._seen:
                continue
            self._seen.add(play.id)
            if self.latest is None or play.sort_key() > self.latest.sort_key():
                self.latest = play
            if self._last_shown_key is not None and play.sort_key() < self._last_shown_key:
                # Arrived after the board moved past it: the field has moved on.
                log.info("%sdropping a late play %s (seq %d)", self._tag(), play.id, play.sequence)
                continue
            self._pending.append(play)
            added.append(play)
        self._pending.sort(key=Play.sort_key)
        return added

    # -- output ----------------------------------------------------------

    def next(self) -> Shown | None:
        """Finish the play being shown, and hand out the next one (``None`` if none waits)."""
        self.finish()
        depth = len(self._pending)
        if depth == 0:
            return None
        skipped: list[Play] = []
        speed = 1.0
        if depth > self.backlog:
            speed = self.speedup
            skipped = self._catch_up()
        play = self._pending.pop(0)
        self._last_shown_key = play.sort_key()
        now = self.monotonic()
        lag = None
        if play.wallclock is not None:
            lag = (self.utc_now() - play.wallclock).total_seconds()
        shown = Shown(play, now, speed, depth, tuple(skipped), lag)
        self.current = shown
        log.info(
            "%splay shown: id=%s seq=%d kind=%s depth=%d lag=%s speed=%.1f skipped=%d",
            self._tag(),
            play.id,
            play.sequence,
            play.kind.value,
            depth,
            "n/a" if lag is None else f"{lag:.1f}s",
            speed,
            len(skipped),
        )
        return shown

    def finish(self) -> None:
        """The play being shown is over: log how long it was animated."""
        shown, self.current = self.current, None
        if shown is not None:
            log.info(
                "%splay animated: id=%s kind=%s took=%.2fs speed=%.1f",
                self._tag(),
                shown.play.id,
                shown.play.kind.value,
                self.monotonic() - shown.shown_at,
                shown.speed,
            )

    def _catch_up(self) -> list[Play]:
        """Drop plays until only ``backlog`` wait: stoppages first, then the oldest plays.

        Never drops the ``KEEPERS`` (halftime, end of game) or the newest ball-moving play,
        so the queue can end up holding more than ``backlog`` when they are what is left.
        """
        skipped: list[Play] = []
        for play in [p for p in self._pending if p.kind in STOPPAGES]:
            if len(self._pending) <= self.backlog:
                break
            self._pending.remove(play)
            skipped.append(play)
        while len(self._pending) > self.backlog:
            droppable = [p for p in self._pending if p.kind not in KEEPERS]
            if len(droppable) <= 1:
                break  # only the newest ball play and the keepers are left
            self._pending.remove(droppable[0])
            skipped.append(droppable[0])
        skipped.sort(key=Play.sort_key)
        return skipped

    def _tag(self) -> str:
        return f"[{self.label}] " if self.label else ""


class PlayWatcher:
    """A queue per game, fed through the broadcast delay.

    Poll results go in through :meth:`on_fetch`, which hands them to the shared
    :class:`~..delay.DelayQueue`: the first result for a game applies at once (that is the
    baseline), later ones wait ``delay_seconds()``, in order. Call :meth:`tick` every frame
    to apply what is due, then :meth:`next` when an animation ends.
    """

    def __init__(
        self,
        monotonic: Callable[[], float] = time.monotonic,
        delay_seconds: Callable[[], float] = lambda: 0.0,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        backlog: int = BACKLOG,
        speedup: float = SPEEDUP,
        on_applied: Callable[[int | str, Sequence[Play]], None] | None = None,
    ) -> None:
        #: Called with each poll's plays when the broadcast delay lets them in, so a reversal
        #: detector sees a rewritten play on the same clock as the celebration of it (#357).
        self._on_applied = on_applied
        self._monotonic = monotonic
        self._delay_seconds = delay_seconds
        self._utc_now = utc_now
        self._backlog = backlog
        self._speedup = speedup
        self._delay = DelayQueue(monotonic)
        self._queues: dict[int | str, PlayQueue] = {}

    def queue(self, game_id: int | str) -> PlayQueue:
        if game_id not in self._queues:
            self._queues[game_id] = PlayQueue(
                self._monotonic,
                self._utc_now,
                self._backlog,
                self._speedup,
                label=str(game_id),
            )
        return self._queues[game_id]

    def on_fetch(self, game_id: int | str, plays: Sequence[Play]) -> None:
        """A poll's plays arrived. They are applied after the broadcast delay."""
        queue = self.queue(game_id)

        def apply() -> None:
            queue.offer(plays)
            if self._on_applied is not None:
                self._on_applied(game_id, plays)

        self._delay.submit(game_id, self._delay_seconds(), apply)

    @property
    def waiting(self) -> int:
        """Poll results still waiting out the broadcast delay."""
        return len(self._delay)

    def tick(self) -> None:
        """Apply any poll results whose delay has run out."""
        self._delay.drain()

    def next(self, game_id: int | str) -> Shown | None:
        self.tick()
        return self.queue(game_id).next()

    def forget(self, keep: Callable[[int | str], bool]) -> None:
        """Drop games ``keep`` rejects (a game left the slate)."""
        for game_id in [g for g in self._queues if not keep(g)]:
            del self._queues[game_id]
        self._delay.forget(keep)
