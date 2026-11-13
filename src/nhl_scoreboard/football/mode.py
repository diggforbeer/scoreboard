"""The NFL half of the sport switch (#346): scene selection over the feed worker (#351, #352).

The app builds a fresh ``NflMode`` each time the sport changes to ``nfl`` and drops it on the
way back, so nothing a previous visit held can leak into the next one. Fetching happens on
the mode's :class:`~.worker.FeedWorker` thread, never on the render loop; the scene methods
only read its latest snapshot.

The scenes are the thin base every designed ``fb_*`` screen builds on (``FB_SCENE_KINDS``):
the status screens and a plain text scoreboard. None of the designed screens (the field,
the run, the pass ...) exist yet.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from .api import MIN_POLL_SECONDS
from .models import FbGame
from .worker import STALE_AFTER_SECONDS, FeedSnapshot, FeedWorker

if TYPE_CHECKING:
    from ..app import Scene
    from ..config import FootballConfig, ScoreboardConfig

#: Every scene kind NFL mode produces. Documented in ``football_screen.md`` ("Base scenes");
#: a test keeps that list, this tuple and the renderer in step.
FB_SCENE_KINDS = ("fb_connecting", "fb_no_data", "fb_no_games", "fb_scores")

#: Seconds each game stays up when more than one is on the rotation, if no settings are given.
DEFAULT_ROTATE_SECONDS = 8.0


class NflMode:
    def __init__(
        self,
        scoreboard: Callable[[], ScoreboardConfig] | None = None,
        client_factory: Callable[[], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        football: Callable[[], FootballConfig] | None = None,
    ) -> None:
        """``scoreboard`` and ``football`` return the live ``[scoreboard]`` and ``[football]``
        settings (read at each poll and each frame, so an admin-page change applies without a
        restart); ``client_factory`` makes the feed client (a fake in tests)."""
        if client_factory is None:
            from .api import NflClient

            client_factory = NflClient
        self._scoreboard = scoreboard
        self._football = football
        self._monotonic = monotonic
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

    # -- what to show ----------------------------------------------------

    def scene(self) -> Scene:
        from ..app import Scene

        now = self._monotonic()
        snap = self.snapshot
        if not snap.has_data:
            # Never had an answer: connecting, until it has been failing for as long as the
            # NHL side waits before it admits there is no data.
            waited = None if snap.started_at is None else now - snap.started_at
            if snap.failures and waited is not None and waited > STALE_AFTER_SECONDS:
                return Scene("fb_no_data")
            return Scene("fb_connecting")
        if snap.is_stale(now):
            return Scene("fb_no_data")
        games = snap.games or ()
        if not games:
            return Scene("fb_no_games")
        game = self.pick_game(games, now)
        return Scene("fb_scores", fb_game=game)

    def pick_game(self, games: Sequence[FbGame], now: float) -> FbGame:
        """Which game to show: the favourite's while it is live, else the followed teams' in turn.

        ``games`` comes best-first from the client (live, then upcoming, then finished).

        1. The favourite's own game, while it is live, holds the screen alone.
        2. Otherwise the games the followed teams are in take turns, ``rotate_seconds`` each,
           the favourite's first. If any of them is live, only the live ones do.
        3. With nobody followed, or none of them playing, every game takes a turn.

        Turns are timed by the (injectable) monotonic clock, not a counter, so a refresh
        that changes the slate never makes the board skip or repeat a game.
        """
        cfg = self._football() if self._football else None
        followed = cfg.followed_teams if cfg else []
        favourite = cfg.favourite_team if cfg else ""
        favourite_game = next((g for g in games if favourite and g.involves(favourite)), None)
        if favourite_game is not None and favourite_game.is_live:
            return favourite_game
        pool = [g for g in games if any(g.involves(t) for t in followed)]
        live = [g for g in pool if g.is_live]
        pool = live or pool or list(games)
        if favourite_game is not None and favourite_game in pool:
            pool.remove(favourite_game)
            pool.insert(0, favourite_game)
        seconds = self._scoreboard().rotate_seconds if self._scoreboard else DEFAULT_ROTATE_SECONDS
        turn = int(now // max(seconds, 1.0)) % len(pool)
        return pool[turn]
