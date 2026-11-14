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
from .idle import (
    SCHEDULE_TTL,
    STANDINGS_TTL,
    WEEK_TTL,
    IdleCache,
    IdleSnapshot,
    Scoreboard,
    with_scoreboard,
)
from .models import FbGame, Play
from .people import CoreSync, RosterCache, RosterPlayer, merge_core
from .teams import is_team, team
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
    "fb_halftime",
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
        wide: Callable[[], bool] = lambda: True,
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
        #: Whether the panel is 128px wide: the idle screens are drawn for that width only.
        self._wide = wide
        #: Final games' first sighting while live, per game id, so the hold after the whistle is
        #: timed from the end of the game we watched (a board that joins late gets no hold).
        self._seen_live: set[int] = set()
        #: How far through its slot the chosen rotation screen is (0 to 1): a screen of several
        #: pages shares its seconds between them, so the page is read off this. Render loop only.
        self._slot_fraction = 0.0
        self._final_since: dict[int, float] = {}
        #: The idle screens' data cache (#421): the feed worker's thread owns it.
        self._idle_cache = IdleCache(monotonic)
        self.worker = FeedWorker(
            client_factory,
            self._interval,
            monotonic,
            collect=self._collect,
            idle=self._collect_idle,
        )
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

    def _collect_idle(
        self, client: Any, games: list[FbGame], scoreboard: Scoreboard | None, prev: IdleSnapshot
    ) -> IdleSnapshot:
        """The idle screens' data (#421): the favourite's and followed teams' schedules (daily),
        the standings (hourly) and the week's games (every few minutes), each fetched only when it
        is due. The scoreboard's own week, byes and calendar come in on the poll already made.

        **Nothing is fetched while any game is live** (the idle screens are not showing and the
        live poll is the busy one); the last data is kept. A failed fetch keeps the last good
        value (``IdleCache``), and a client without these methods (a test fake) is simply skipped.
        """
        snap = with_scoreboard(prev, scoreboard)
        if any(g.is_live for g in games):
            return snap
        cfg = self._football() if self._football else None
        mine = ([cfg.favourite_team] if cfg and cfg.favourite_team else []) + (
            list(cfg.followed_teams) if cfg else []
        )
        mine = [t for t in dict.fromkeys(mine) if is_team(t)]
        cache = self._idle_cache
        schedules = dict(snap.schedules)
        if hasattr(client, "schedule"):
            for abbrev in mine:
                team_id = team(abbrev).espn_id
                item = cache.refresh(
                    ("schedule", team_id), SCHEDULE_TTL, lambda tid=team_id: client.schedule(tid)
                )
                if item is not None:
                    schedules[team_id] = item
        standings = snap.standings_cached
        if mine and hasattr(client, "standings"):
            standings = cache.refresh(("standings",), STANDINGS_TTL, client.standings) or standings
        week_item = snap.week_cached
        if scoreboard is not None and scoreboard.week is not None and hasattr(client, "week"):
            number, kind = scoreboard.week, scoreboard.season_type or 2
            week_item = (
                cache.refresh(("week", number, kind), WEEK_TTL, lambda: client.week(number, kind))
                or week_item
            )
        return IdleSnapshot(
            scoreboard=snap.scoreboard,
            schedules=schedules,
            standings_cached=standings,
            week_cached=week_item,
        )

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
        self._idle_cache.clear()

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
        idle_kind = self._idle_kind(games, snap, now)
        if idle_kind is not None:
            return self._idle_scene(idle_kind, games, snap, now)
        if not games:
            return Scene("fb_no_games")
        game = self.pick_game(games, now)
        # The field between plays while a ball is in play, the halftime card at the half, and
        # the text scoreboard before the game and once it is final.
        resting = resting_kind(game)
        base = Scene(resting, fb_game=game)
        self.director.ingest(snap)
        current = self.director.current(game.id)
        if current is None:
            return base
        return self._play_scene(current, base)

    # -- the idle selection (#422) -----------------------------------------------

    def _idle_kind(self, games: Sequence[FbGame], snap: FeedSnapshot, now: float) -> str | None:
        """The idle screen to show, or None to fall through to the game scenes.

        In order: a live game (followed, or any when nobody is followed) always wins; the
        favourite's game inside the kickoff window shows ``fb_countdown``; its final, within the
        hold, ``fb_final``; then, with a favourite set, the idle rotation; an empty slate shows the
        rotation's clock (or ``fb_no_games``). 128px panels only: on 64px this returns None except
        for the empty slate's clock.
        """
        from .idle_screens import IDLE_SCREENS

        self._slot_fraction = 0.0
        cfg = self._football() if self._football else _no_football()
        followed = cfg.followed_teams
        for game in games:
            if game.is_live:
                self._seen_live.add(game.id)
            elif game.is_final and game.id in self._seen_live:
                self._final_since.setdefault(game.id, now)
        playing = [g for g in games if g.is_live]
        if any(any(g.involves(t) for t in followed) for g in playing) or (playing and not followed):
            return None
        wide = self._wide()
        if not wide:
            return "clock" if not games and _has_clock(cfg) else None
        favourite = cfg.favourite_team
        ctx = self._idle_context(games, snap, now, cfg)
        mine = next((g for g in games if favourite and g.involves(favourite)), None)
        if (
            mine is not None
            and cfg.show_countdown
            and "fb_countdown" in IDLE_SCREENS
            and self._in_countdown(mine, cfg)
        ):
            return "fb_countdown"
        if (
            mine is not None
            and cfg.show_final
            and "fb_final" in IDLE_SCREENS
            and mine.is_final
            and now - self._final_since.get(mine.id, -1e18) < cfg.final_hold_minutes * 60
        ):
            return "fb_final"
        if favourite:
            slots = self._rotation(cfg, ctx, favourite)
            if slots:
                screen, self._slot_fraction = _slot_at(slots, now)
                return screen
        if not games:
            return "clock" if _has_clock(cfg) else None
        return None

    def _in_countdown(self, game: FbGame, cfg: FootballConfig) -> bool:
        if not game.is_pregame or game.start_utc is None:
            return False
        until = game.start_utc - self._utc_now()
        return timedelta(0) <= until <= timedelta(minutes=cfg.countdown_minutes)

    def _rotation(self, cfg: FootballConfig, ctx: Any, favourite: str) -> list[tuple[str, float]]:
        """The rotation's slots that can show right now, as (screen, seconds).

        A screen drops out unless it is registered and its ``should_show`` is true; the clock only
        counts when another screen resolved (a lone clock is the empty-slate case, not a rotation);
        ``fb_bye`` joins when the favourite is on a bye.
        """
        from .idle_screens import IDLE_SCREENS

        slots: list[tuple[str, float]] = []
        clock: list[tuple[str, float]] = []
        for entry in cfg.idle_rotation:
            if entry.screen == "clock":
                clock.append((entry.screen, entry.seconds))
            elif entry.screen in IDLE_SCREENS and IDLE_SCREENS[entry.screen](ctx):
                slots.append((entry.screen, entry.seconds))
        scoreboard = ctx.idle.scoreboard
        if (
            cfg.show_bye
            and scoreboard is not None
            and scoreboard.on_bye(favourite)
            and "fb_bye" in IDLE_SCREENS
            and IDLE_SCREENS["fb_bye"](ctx)
        ):
            slots.append(("fb_bye", 8.0))
        return slots + clock if slots else []

    def _idle_context(
        self, games: Sequence[FbGame], snap: FeedSnapshot, now: float, cfg: FootballConfig
    ) -> Any:
        from .idle_screens import IdleContext

        return IdleContext(now, self._utc_now(), games, snap.idle, cfg)

    def _idle_scene(
        self, kind: str, games: Sequence[FbGame], snap: FeedSnapshot, now: float
    ) -> Scene:
        """The scene for the chosen idle screen: its builder's view, and the favourite's game."""
        from ..app import Scene
        from .idle_screens import IDLE_SCREENS

        cfg = self._football() if self._football else _no_football()
        favourite = cfg.favourite_team
        mine = next((g for g in games if favourite and g.involves(favourite)), None)
        build = IDLE_SCREENS.get(kind)
        view = build(self._idle_context(games, snap, now, cfg)) if build is not None else None
        pages = max(int(getattr(view, "pages", 1) or 1), 1)
        page = min(int(self._slot_fraction * pages), pages - 1)
        return Scene(
            kind,
            fb_game=mine if kind in ("fb_countdown", "fb_final") else None,
            fb_idle=view,
            fb_page=page,
        )

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


def resting_kind(game: FbGame) -> str:
    """The scene a game rests on when nothing is being played out: the field while a ball is in
    play, the halftime card at the half, and the text scoreboard before the game and once final."""
    if game.is_halftime:
        return "fb_halftime"
    return "fb_field" if game.is_live else "fb_scores"


def _slot_at(slots: Sequence[tuple[str, float]], now: float) -> tuple[str, float]:
    """The slot on screen at monotonic time ``now`` and how far through it (0 to 1): a pure
    function of the clock, so a refresh that changes the slots never makes the board lose its
    place by more than one turn."""
    total = sum(seconds for _, seconds in slots)
    at = now % total
    for screen, seconds in slots:
        if at < seconds:
            return screen, at / seconds
        at -= seconds
    return slots[-1][0], 0.0


def _has_clock(cfg: FootballConfig) -> bool:
    return any(entry.screen == "clock" for entry in cfg.idle_rotation)


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
