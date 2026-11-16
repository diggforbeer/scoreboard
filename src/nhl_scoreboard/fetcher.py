"""Run the NHL fetches off the render thread (#267).

Every NHL request used to run inline in ``ScoreboardApp.run()``, so a slow API
froze the whole panel (clock, animations, goal flash, button) for as long as
the request took. Here one worker thread makes every blocking call, and the
render thread only ever *applies* finished results, once per loop tick via
:meth:`drain`.

The split is what keeps the rest of ``app.py`` single-threaded: ``work`` runs on
the worker and must touch nothing but the client; ``done`` runs on whichever
thread calls ``drain`` (the render loop) and is where state changes. That is the
same rule ``button.py`` and ``admin_server.py`` follow.

* **One worker, FIFO.** A thread pool would need a lock around every cache and
  an answer to "which result is newer"; one sequential worker has neither
  problem, and the NHL client is only ever used from it.
* **A key is in flight at most once.** Submitting a key that is already queued or
  running is dropped, so a hung request cannot pile up a backlog of retries, and
  callers can re-submit on every tick without checking.
* **Inline mode** (the default, used by tests and ``--demo``) runs ``work`` and
  ``done`` straight away on the calling thread, so the flow tests that walk a game
  day with an injected clock stay deterministic and need no waiting.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any

from .nhl.api import NHLApiError

log = logging.getLogger(__name__)

#: ``done(result, error)``: exactly one of the two is not ``None``.
Done = Callable[[Any, "Exception | None"], None]

#: How long ``close()`` waits for the worker. A request in flight is not
#: interrupted (the client's own timeout ends it); the thread is a daemon.
CLOSE_JOIN_SECONDS = 2.0

#: A request slower than this is logged at WARNING, so a slow API shows in the
#: journal even though the panel no longer freezes to say so. Same bar as the
#: football feed worker.
SLOW_FETCH_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class FetchStats:
    """What the status page shows about the worker. Read-only, safe from any thread."""

    #: ``False`` for the inline fetcher: there is no worker to report on.
    threaded: bool = False
    #: Keys queued or running, and how long the oldest has been waiting.
    in_flight: int = 0
    oldest_age: float | None = None
    #: The most recent request to finish: what it was, how long it took, whether it worked.
    last_label: str = ""
    last_seconds: float | None = None
    last_ok: bool = True
    #: Totals since start.
    completed: int = 0
    failed: int = 0
    slow: int = 0


def label(key: Hashable) -> str:
    """``("situation", 3)`` -> ``situation 3``; a plain key is its own label."""
    if isinstance(key, tuple):
        return " ".join(str(part) for part in key)
    return str(key)


class InlineFetcher:
    """Runs each fetch on the calling thread. No threads, no waiting."""

    threaded = False

    def submit(self, key: Hashable, work: Callable[[], Any], done: Done) -> bool:
        try:
            result = work()
        except NHLApiError as exc:
            done(None, exc)
        else:
            done(result, None)
        return True

    def pending(self, key: Hashable) -> bool:
        return False

    def drain(self) -> None:
        """Nothing is ever queued."""

    def stats(self) -> FetchStats:
        return FetchStats()

    def close(self) -> None:
        """Nothing to stop."""


class ThreadedFetcher:
    """Runs fetches one at a time on a background thread; results apply in ``drain``."""

    threaded = True

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._work: queue.Queue[tuple[Hashable, Callable[[], Any], Done] | None] = queue.Queue()
        #: Finished results, appended by the worker, consumed by ``drain``.
        self._results: deque[tuple[Hashable, Done, Any, Exception | None]] = deque()
        #: Keys queued or running, with when each was submitted. Only the thread
        #: that submits and drains (the render loop) changes it, so it needs no
        #: lock; ``stats()`` copies the values from another thread.
        self._pending: dict[Hashable, float] = {}
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        #: Written only by the worker thread (a tuple is replaced whole, so a
        #: reader never sees half of one), read by ``stats()``.
        self._last: tuple[str, float, bool] | None = None
        self._completed = 0
        self._failed = 0
        self._slow = 0

    # -- render thread ----------------------------------------------------

    def submit(self, key: Hashable, work: Callable[[], Any], done: Done) -> bool:
        """Queue ``work``; ``False`` if ``key`` is already queued or running."""
        if key in self._pending:
            return False
        self._start()
        self._pending[key] = self._monotonic()
        self._work.put((key, work, done))
        return True

    def pending(self, key: Hashable) -> bool:
        return key in self._pending

    def drain(self) -> None:
        """Apply every finished result. Call once per loop tick on the render thread."""
        while True:
            try:
                key, done, result, error = self._results.popleft()
            except IndexError:
                return
            self._pending.pop(key, None)
            done(result, error)

    def stats(self) -> FetchStats:
        """The worker's health, for the status page. Reads only; callable from any thread."""
        submitted = list(self._pending.values())
        last = self._last
        return FetchStats(
            threaded=True,
            in_flight=len(submitted),
            oldest_age=self._monotonic() - min(submitted) if submitted else None,
            last_label=last[0] if last else "",
            last_seconds=last[1] if last else None,
            last_ok=last[2] if last else True,
            completed=self._completed,
            failed=self._failed,
            slow=self._slow,
        )

    def close(self) -> None:
        """Stop the worker. Idempotent, and bounded in time."""
        with self._lock:
            thread, self._thread = self._thread, None
        if thread is None:
            return
        self._work.put(None)
        thread.join(CLOSE_JOIN_SECONDS)
        if thread.is_alive():
            log.debug("NHL fetch worker is still finishing a request; it is a daemon")

    # -- worker thread ----------------------------------------------------

    def _start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="nhl-fetch", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            item = self._work.get()
            if item is None:
                self._work.task_done()
                return
            key, work, done = item
            result: Any = None
            error: Exception | None = None
            started = self._monotonic()
            try:
                result = work()
            except NHLApiError as exc:
                error = exc
            except Exception as exc:  # the thread must survive whatever a parse does
                log.warning("NHL fetch %s raised %s: %s", label(key), type(exc).__name__, exc)
                error = exc
            took = max(0.0, self._monotonic() - started)
            if took > SLOW_FETCH_SECONDS:
                self._slow += 1
                log.warning("NHL fetch %s was slow: %.1fs", label(key), took)
            else:
                log.debug("NHL fetch %s took %.2fs", label(key), took)
            self._completed += 1
            if error is not None:
                self._failed += 1
            self._last = (label(key), took, error is None)
            self._results.append((key, done, result, error))
            self._work.task_done()

    # -- tests ------------------------------------------------------------

    def wait_idle(self, timeout: float = 5.0) -> bool:
        """Block until every submitted fetch has finished running (not yet applied)."""
        tick = threading.Event()
        for _ in range(max(1, int(timeout / 0.005))):
            if self._work.unfinished_tasks == 0:
                return True
            tick.wait(0.005)
        return False
