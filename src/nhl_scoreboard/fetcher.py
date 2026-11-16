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
from collections import deque
from collections.abc import Callable, Hashable
from typing import Any

from .nhl.api import NHLApiError

log = logging.getLogger(__name__)

#: ``done(result, error)``: exactly one of the two is not ``None``.
Done = Callable[[Any, "Exception | None"], None]

#: How long ``close()`` waits for the worker. A request in flight is not
#: interrupted (the client's own timeout ends it); the thread is a daemon.
CLOSE_JOIN_SECONDS = 2.0


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

    def close(self) -> None:
        """Nothing to stop."""


class ThreadedFetcher:
    """Runs fetches one at a time on a background thread; results apply in ``drain``."""

    threaded = True

    def __init__(self) -> None:
        self._work: queue.Queue[tuple[Hashable, Callable[[], Any], Done] | None] = queue.Queue()
        #: Finished results, appended by the worker, consumed by ``drain``.
        self._results: deque[tuple[Hashable, Done, Any, Exception | None]] = deque()
        #: Keys queued or running. Touched only by the thread that submits and
        #: drains (the render loop), so it needs no lock.
        self._pending: set[Hashable] = set()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    # -- render thread ----------------------------------------------------

    def submit(self, key: Hashable, work: Callable[[], Any], done: Done) -> bool:
        """Queue ``work``; ``False`` if ``key`` is already queued or running."""
        if key in self._pending:
            return False
        self._start()
        self._pending.add(key)
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
            self._pending.discard(key)
            done(result, error)

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
            try:
                result = work()
            except NHLApiError as exc:
                error = exc
            except Exception as exc:  # the thread must survive whatever a parse does
                log.warning("NHL fetch %r raised %s: %s", key, type(exc).__name__, exc)
                error = exc
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
