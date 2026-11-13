"""The NFL half of the sport switch (#346): scene selection over the feed worker (#351, #352).

The app builds a fresh ``NflMode`` each time the sport changes to ``nfl`` and drops it on the
way back, so nothing a previous visit held can leak into the next one. Fetching happens on
the mode's :class:`~.worker.FeedWorker` thread, never on the render loop; the scene methods
only read its latest snapshot.

The scenes are the thin base every designed ``fb_*`` screen builds on (``FB_SCENE_KINDS``):
the status screens and a plain text scoreboard, and (#377) the three play scenes the
:class:`~.director.Director` hands out while a play, a celebration or a reversal is on screen.
The designed screens plug into the renderer's registries (``display/football_plays.py``).
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from .api import MIN_POLL_SECONDS
from .director import Director, Timings
from .models import FbGame, Play
from .people import CoreSync, RosterCache, RosterPlayer, merge_core
from .worker import STALE_AFTER_SECONDS, FeedSnapshot, FeedWorker

if TYPE_CHECKING:
    from ..app import Scene
    from ..config import FootballConfig, ScoreboardConfig

#: Every scene kind NFL mode draws.
#: Documented in ``football_screen.md`` ("Base scenes"); a test keeps that list, this tuple and
#: the renderer in step.
FB_SCENE_KINDS = (
    "fb_connecting",
    "fb_no_data",
    "fb_no_games",
    "fb_scores",
    "fb_field",
    "fb_play",
    "fb_playtext",
    "fb_event",
)

#: A game this close to kickoff has its plays fetched, so the opening kickoff (and the coin
#: toss read from it) animates instead of being swallowed by the baseline.
KICKOFF_WINDOW = timedelta(minutes=20)

#: Seconds each game stays up when more than one is on the rotation, if no settings are given.
DEFAULT_ROTATE_SECONDS = 8.0


class NflMode:
    def __init__(
        self,
        scoreboard: Callable[[], ScoreboardConfig] | None = None,
        client_factory: Callable[[], Any] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        football: Callable[[], FootballConfig] | None = None,
        delay_seconds: Callable[[], float] = lambda: 0.0,
        utc_now: Callable[[], datetime] = lambda: datetime.now(UTC),
        timings: Callable[[], Timings] | None = None,
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
        self._client_factory = client_factory
        self._utc_now = utc_now
        self.worker = FeedWorker(client_factory, self._interval, monotonic, collect=self._collect)
        #: Which play, celebration or reversal is on screen (#377). Render loop only.
        self.director = Director(
            football or _no_football, monotonic, delay_seconds, utc_now, timings
        )
        self._core_sync = CoreSync()
        #: Team rosters for jersey numbers (#354), fetched hourly on first use. Held here so a
        #: sport switch, which builds a fresh mode, starts with none. The feed worker's thread
        #: owns it: it must not be used from the render loop.
        self.rosters = RosterCache(self._fetch_roster, monotonic)
        self._roster_client: Any = None

    def _interval(self, snap: FeedSnapshot) -> float:
        """Poll fast while a game is live, slowly otherwise, never faster than the feed caches."""
        cfg = self._scoreboard() if self._scoreboard else None
        live = any(g.is_live or self._imminent(g) for g in snap.games or ())
        if cfg is None:
            base = 15.0 if live else 60.0
        else:
            base = cfg.live_poll_seconds if live else cfg.poll_seconds
        return max(base, MIN_POLL_SECONDS)

    def _imminent(self, game: FbGame) -> bool:
        """A game about to start: polled as fast as a live one so the kickoff is not missed."""
        if not game.is_pregame or game.start_utc is None:
            return False
        return timedelta(0) <= game.start_utc - self._utc_now() <= KICKOFF_WINDOW

    # -- the feed worker's plays (its thread) --------------------------------------

    def watched(self, games: Sequence[FbGame]) -> list[FbGame]:
        """The games whose plays are fetched: live (or about to start) ones the favourite or a
        followed team is in; with nobody followed in play, the first live game, so the board
        always has something to animate. Never every game on the slate."""
        cfg = self._football() if self._football else None
        followed = ([cfg.favourite_team] if cfg and cfg.favourite_team else []) + (
            list(cfg.followed_teams) if cfg else []
        )
        playing = [g for g in games if g.is_live or self._imminent(g)]
        mine = [g for g in playing if any(g.involves(t) for t in followed)]
        return mine or playing[:1]

    def _collect(
        self, client: Any, games: list[FbGame], prev: FeedSnapshot
    ) -> tuple[dict[int, tuple[Play, ...]], dict[int, dict[int, RosterPlayer]]]:
        """Each watched game's plays (site feed, with the core feed's participants merged in
        when it shows something new) and both teams' rosters. A failed fetch keeps what the
        last snapshot had for that game."""
        plays: dict[int, tuple[Play, ...]] = {}
        players: dict[int, dict[int, RosterPlayer]] = {}
        watched = self.watched(games)
        for game in watched:
            site = client.plays(game.id)
            if site is None:
                if game.id in prev.plays:
                    plays[game.id] = prev.plays[game.id]
                continue
            merged = list(site)
            if self._core_sync.should_fetch(game.id, site):
                core = client.core_plays(game.id)
                if core is not None:
                    self._core_sync.fetched(game.id, site)
                    merged = merge_core(site, core)
                elif game.id in prev.plays:
                    merged = _keep_participants(site, prev.plays[game.id])
            elif game.id in prev.plays:
                merged = _keep_participants(site, prev.plays[game.id])
            plays[game.id] = tuple(merged)
            players[game.id] = self.rosters.players_for([game.home.espn_id, game.away.espn_id])
        keep = {g.id for g in games}
        self._core_sync.forget(lambda game_id: game_id in keep)
        return plays, players

    def _fetch_roster(self, team_id: int) -> dict[int, RosterPlayer] | None:
        if self._roster_client is None:
            self._roster_client = self._client_factory()
        return self._roster_client.roster(team_id)

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()
        client, self._roster_client = self._roster_client, None
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        self.rosters.clear()

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
        # The field between plays while a ball is in play; the text scoreboard before the game,
        # at the half and once it is final (the half and final get their own cards later).
        resting = "fb_field" if game.is_live and not game.is_halftime else "fb_scores"
        base = Scene(resting, fb_game=game)
        self.director.ingest(snap)
        current = self.director.current(game.id)
        if current is None:
            return base
        return self._play_scene(current, base)

    def _play_scene(self, current: Any, base: Scene) -> Scene:
        """The scene for the stage on screen (#377), over the game's latest score."""
        from ..app import Scene
        from .director import PLAY, PLAYTEXT

        stage = current.stage
        kind = {PLAY: "fb_play", PLAYTEXT: "fb_playtext"}.get(stage.stage, "fb_event")
        games = {g.id: g for g in self.snapshot.games or ()}
        return Scene(
            kind,
            fb_game=games.get(stage.game.id, stage.game),
            fb_play=stage.play,
            fb_people=stage.people,
            fb_event=stage.event,
            fb_stage=stage.stage,
            fb_elapsed=current.elapsed,
            fb_seconds=stage.seconds,
            animating=True,
        )

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


def _no_football() -> FootballConfig:
    from ..config import FootballConfig

    return FootballConfig()


def _keep_participants(site: Sequence[Play], before: Sequence[Play]) -> list[Play]:
    """The site plays with the participants an earlier merge attached, so a poll that does not
    fetch the core feed does not lose the jersey numbers."""
    import dataclasses

    known = {p.id: p.participants for p in before if p.participants}
    return [
        dataclasses.replace(p, participants=known[p.id])
        if p.id in known and not p.participants
        else p
        for p in site
    ]
