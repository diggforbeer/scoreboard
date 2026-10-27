"""Apply fetched results N seconds after they arrived (#301).

The NHL API runs 30-60s ahead of the TV broadcast. Rather than delaying
each feature (horn, goal screen, scorer, shootout...), every fetch result
is applied through this queue, so the board shows the world as it was
``delay`` seconds ago and everything downstream shifts together.
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Callable, Hashable


class DelayQueue:
    """Run callbacks once their delay has elapsed, in fetch order per key.

    The first result for a key is applied at once, not delayed: after a
    restart (or when a game first appears) the board shows data straight
    away and the delay catches up behind it, rather than sitting blank for
    the first ``delay`` seconds. Later results for the same key never run
    before an earlier one, even if the delay is lowered in between.
    """

    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        self._heap: list[tuple[float, int, Callable[[], None]]] = []
        self._sequence = itertools.count()
        self._last_due: dict[Hashable, float] = {}

    def __len__(self) -> int:
        return len(self._heap)

    def submit(self, key: Hashable, delay: float, apply: Callable[[], None]) -> None:
        now = self._monotonic()
        last = self._last_due.get(key)
        due = now if last is None else max(now + max(delay, 0.0), last)
        self._last_due[key] = due
        heapq.heappush(self._heap, (due, next(self._sequence), apply))
        self.drain()

    def drain(self) -> None:
        """Run everything that is now due."""
        now = self._monotonic()
        while self._heap and self._heap[0][0] <= now:
            _, _, apply = heapq.heappop(self._heap)
            apply()

    def forget(self, keep: Callable[[Hashable], bool]) -> None:
        """Drop bookkeeping for keys ``keep`` rejects (a game left the slate).

        Queued callbacks for those keys still run; they are harmless, and
        removing them from the heap would cost more than it saves.
        """
        for key in list(self._last_due):
            if not keep(key):
                del self._last_due[key]
