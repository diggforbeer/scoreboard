"""Fetch the NFL scoreboard off the render thread (#351).

The NHL side fetches on the render loop, so a slow request freezes the panel for
as long as it takes (#267, ``CLAUDE.md``: "Every fetch blocks the render loop").
The football design animates every play at up to 20fps, so NFL mode never does
that: a :class:`FeedWorker` owns the client, polls on its own thread, and
publishes the **latest immutable snapshot**. The render loop only ever reads the
snapshot, which is a reference swap and never waits on the network.

Differences from the NHL side, deliberately: results are not queued through the
broadcast ``DelayQueue`` here (that is the play queue's job, later), and a
failure keeps the last good games so the panel does not blank on a blip.

Concurrency rules, because the cheap bugs here are the nasty ones:

* The snapshot is replaced, never mutated, under a lock.
* Each ``start()`` gets a new generation; a thread from a stopped generation can
  finish its request but can never publish it, so a late result cannot leak into
  a restarted worker or a switched-away mode.
* Each generation has its own client; ``stop()`` closes it, and a thread from an older
  generation never closes a newer one's.
* ``stop()`` waits a bounded time. A request in flight is not interrupted (the
  client's own timeout ends it); that thread is orphaned (a daemon), is no longer
  this worker's thread, and will not publish. So ``start()`` after ``stop()`` always
  starts cleanly, even with an old request still stuck.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .models import FbGame, Play
from .people import RosterPlayer

log = logging.getLogger(__name__)

#: A good fetch older than this is stale, matching ``app.STALE_AFTER_SECONDS`` on
#: the NHL side: the panel then says "no data" instead of an old score.
STALE_AFTER_SECONDS = 15 * 60

#: A fetch slower than this is logged at WARNING so a slow feed shows in the journal.
SLOW_FETCH_SECONDS = 3.0

#: The longest a failing feed is left between attempts.
MAX_BACKOFF_SECONDS = 120.0

#: Whatever the interval callable says, never spin faster than this.
MIN_DELAY_SECONDS = 0.01

#: How long ``stop()`` waits for the thread before leaving it (a daemon) to finish.
STOP_JOIN_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    """Everything the render loop knows about the feed. Immutable."""

    #: The games from the last **successful** fetch; ``None`` until there has been
    #: one. An empty tuple is a real answer (no games today).
    games: tuple[FbGame, ...] | None = None
    #: Monotonic time of the last successful fetch.
    fetched_at: float | None = None
    #: The last failure, ``""`` after a success.
    last_error: str = ""
    last_error_at: float | None = None
    #: Failed attempts in a row.
    failures: int = 0
    #: How long the last attempt took, in seconds.
    fetch_seconds: float = 0.0
    #: Attempts since start, successful or not.
    attempts: int = 0
    #: Monotonic time the worker was started, ``None`` if it never was. Lets the caller tell
    #: "still connecting" from "never connected in 15 minutes" (no data) before a first success.
    started_at: float | None = None
    #: Each watched game's plays so far, with the core feed's participants merged in (#377), as
    #: of the last successful fetch. A game whose play fetch failed keeps its previous plays.
    plays: Mapping[int, tuple[Play, ...]] = field(default_factory=dict)
    #: Both teams' rosters per game, for ``people.resolve_people``.
    players: Mapping[int, Mapping[int, RosterPlayer]] = field(default_factory=dict)

    @property
    def has_data(self) -> bool:
        return self.games is not None

    def age(self, now: float) -> float | None:
        """Seconds since the last successful fetch, or ``None`` if there has not been one."""
        return None if self.fetched_at is None else now - self.fetched_at

    def is_stale(self, now: float, window: float = STALE_AFTER_SECONDS) -> bool:
        """True when there *was* data but the last good fetch is older than ``window``.

        Before the first success this is False: that is "connecting", not "no
        data". The caller decides how long it is willing to wait for the first one.
        """
        age = self.age(now)
        return age is not None and age > window


class FeedWorker:
    def __init__(
        self,
        client_factory: Callable[[], Any],
        interval: Callable[[FeedSnapshot], float],
        monotonic: Callable[[], float] = time.monotonic,
        name: str = "nfl-feed",
        collect: Callable[[Any, list[FbGame], FeedSnapshot], tuple[dict, dict]] | None = None,
    ) -> None:
        #: After each good scoreboard fetch, ``collect(client, games, previous snapshot)`` returns
        #: ``(plays, players)`` for the snapshot (#377). It runs on this thread; if it raises, the
        #: scores are still published and the previous plays kept.
        self._collect = collect
        self._client_factory = client_factory
        self._interval = interval
        self._monotonic = monotonic
        self._name = name
        self._lock = threading.Lock()
        self._snapshot = FeedSnapshot()
        self._client: Any = None
        #: Which start() the client belongs to, so an old thread's cleanup can never close a
        #: newer generation's client.
        self._client_generation = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._generation = 0

    # -- what the render loop uses ---------------------------------------

    def snapshot(self) -> FeedSnapshot:
        """The latest snapshot. Never blocks on the network."""
        with self._lock:
            return self._snapshot

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Begin polling on a background thread. Idempotent."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._generation += 1
            self._stop = threading.Event()
            self._snapshot = FeedSnapshot(started_at=self._monotonic())
            generation, stop = self._generation, self._stop
            self._thread = threading.Thread(
                target=self._run, args=(generation, stop), name=self._name, daemon=True
            )
            thread = self._thread
        thread.start()

    def stop(self) -> None:
        """Stop polling and release the client. Idempotent, and bounded in time."""
        with self._lock:
            self._generation += 1  # anything still in flight may no longer publish
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(STOP_JOIN_SECONDS)
            if thread.is_alive():
                log.debug("%s thread is still finishing a request; it will not publish", self._name)
        self._close_client()
        with self._lock:
            if self._thread is thread:
                self._thread = None  # orphaned if still alive; it can no longer publish

    # -- the loop --------------------------------------------------------

    def _run(self, generation: int, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                delay = self.poll_once(generation)
                if stop.wait(max(delay, MIN_DELAY_SECONDS)):
                    break
        finally:
            self._close_client(only_generation=generation)

    def poll_once(self, generation: int | None = None) -> float:
        """One fetch, publish the result, and return the seconds to wait before the next.

        Public so tests can drive the worker without a thread or real waiting.
        """
        started = self._monotonic()
        games: list[FbGame] | None = None
        error = ""
        try:
            client = self._get_client(generation)
            games = client.scores()
            if games is None:
                error = getattr(client, "last_error", "") or "no data"
        except Exception as exc:  # the thread must survive whatever the client does
            error = f"{type(exc).__name__}: {exc}"
            log.warning("NFL fetch raised %s", error)
        finished = self._monotonic()
        took = max(0.0, finished - started)
        if took > SLOW_FETCH_SECONDS:
            log.warning("NFL fetch was slow: %.1fs", took)
        else:
            log.debug("NFL fetch took %.2fs", took)

        with self._lock:
            before = self._snapshot
        plays, players = before.plays, before.players
        if games is not None and self._collect is not None:
            try:
                plays, players = self._collect(client, games, before)
            except Exception:  # plays are a bonus: the scores must still reach the panel
                log.warning("collecting NFL plays failed", exc_info=True)

        with self._lock:
            if generation is not None and generation != self._generation:
                return 0.0  # stopped while this was in flight: publish nothing
            prev = self._snapshot
            if games is not None:
                snap = FeedSnapshot(
                    games=tuple(games),
                    fetched_at=finished,
                    fetch_seconds=took,
                    attempts=prev.attempts + 1,
                    started_at=prev.started_at,
                    plays=plays,
                    players=players,
                )
            else:
                snap = replace(
                    prev,
                    last_error=error,
                    last_error_at=finished,
                    failures=prev.failures + 1,
                    fetch_seconds=took,
                    attempts=prev.attempts + 1,
                )
            self._snapshot = snap
        return self._next_delay(snap)

    def _next_delay(self, snap: FeedSnapshot) -> float:
        """The normal interval after a success; exponential backoff, capped, after failures."""
        try:
            base = float(self._interval(snap))
        except Exception:
            log.exception("NFL poll interval callback failed; using 60s")
            base = 60.0
        base = max(base, MIN_DELAY_SECONDS)
        if snap.failures == 0:
            return base
        return min(base * 2 ** (snap.failures - 1), max(MAX_BACKOFF_SECONDS, base))

    # -- client ----------------------------------------------------------

    def _get_client(self, generation: int | None) -> Any:
        with self._lock:
            client = self._client
            current = self._generation if generation is None else generation
        if client is None:
            client = self._client_factory()
            with self._lock:
                self._client = client
                self._client_generation = current
        return client

    def _close_client(self, only_generation: int | None = None) -> None:
        with self._lock:
            if only_generation is not None and self._client_generation != only_generation:
                return
            client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                log.debug("closing the NFL client failed", exc_info=True)
