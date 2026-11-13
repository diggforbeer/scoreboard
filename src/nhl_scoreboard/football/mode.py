"""The NFL half of the sport switch (#346): scene selection over the feed worker (#351).

The app builds a fresh ``NflMode`` each time the sport changes to ``nfl`` and
drops it on the way back, so nothing a previous visit held can leak into the
next one. Fetching happens on the mode's :class:`~.worker.FeedWorker` thread, never
on the render loop; the scene methods only read its latest snapshot.

The scenes are still a stub: ``fb_connecting`` until the first successful fetch,
a placeholder after that. Real scenes come with the live-scoreboard story.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .api import MIN_POLL_SECONDS
from .worker import FeedSnapshot, FeedWorker

if TYPE_CHECKING:
    from ..app import Scene
    from ..config import ScoreboardConfig


class NflMode:
    def __init__(
        self,
        scoreboard: Callable[[], ScoreboardConfig] | None = None,
        client_factory: Callable[[], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """``scoreboard`` returns the live ``[scoreboard]`` settings (read at each poll,
        so an admin-page change applies without a restart); ``client_factory`` makes the
        feed client (a fake in tests)."""
        if client_factory is None:
            from .api import NflClient

            client_factory = NflClient
        self._scoreboard = scoreboard
        self.worker = FeedWorker(client_factory, self._interval, monotonic)

    def _interval(self, snap: FeedSnapshot) -> float:
        """Poll fast while a game is live, slowly otherwise, never faster than the feed caches."""
        cfg = self._scoreboard() if self._scoreboard else None
        live = any(g.is_live for g in snap.games or ())
        if cfg is None:
            base = 15.0 if live else 60.0
        else:
            base = cfg.live_poll_seconds if live else cfg.poll_seconds
        return max(base, MIN_POLL_SECONDS)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    @property
    def snapshot(self) -> FeedSnapshot:
        return self.worker.snapshot()

    @property
    def ready(self) -> bool:
        """True once the feed has answered at least once."""
        return self.snapshot.has_data

    def refresh(self) -> None:
        """The app's poll hook. Nothing to do: the worker fetches by itself, and the
        scene methods read its snapshot, so there is no fetch here to block on."""

    def scene(self) -> Scene:
        from ..app import Scene

        return Scene("fb_stub" if self.ready else "fb_connecting")
