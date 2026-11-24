"""The football half of the sport switch (#346): scene selection over the feed worker (#351, #352).

The app builds a fresh ``FootballMode`` each time the sport becomes ``football`` and drops it on the
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
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import wraps
from typing import TYPE_CHECKING, Any

from ..important_dates import pick as pick_date
from .api import LEAGUE_COLLEGE, LEAGUE_NFL, MIN_POLL_SECONDS
from .director import Director, Timings, timings_from
from .idle import (
    POLLS_TTL,
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
from .redzone import RedZoneWatcher
from .scroll import is_moving, scroll_px, scroll_seconds
from .stats import GameStats
from .teams import (
    EMPTY_DIRECTORY,
    NFL_DIRECTORY,
    Directory,
    is_team,
    team,
    team_by_id,
    use_directory,
)
from .upset import UpsetWatcher
from .worker import STALE_AFTER_SECONDS, FeedSnapshot, FeedWorker

if TYPE_CHECKING:
    from ..app import Scene
    from ..config import FootballConfig, ScoreboardConfig

#: Every scene kind football mode draws.
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


def _in_scope(method: Callable[..., Any]) -> Callable[..., Any]:
    """Run a render-thread (or admin-thread) method of the mode in its league's team directory."""

    @wraps(method)
    def scoped(self: FootballMode, *args: Any, **kwargs: Any) -> Any:
        with self.scope():
            return method(self, *args, **kwargs)

    return scoped


class FootballMode:
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
        on_sound: Callable[[Any], None] | None = None,
        dates: Callable[[], Sequence[Any]] = lambda: (),
        league: str = LEAGUE_NFL,
    ) -> None:
        """``league`` is ``nfl`` or ``college-football``: the mode's team lookups (by id and by
        abbreviation) resolve in that league's directory (``teams.use_directory``), since the two
        share both. ``scoreboard`` and ``football`` return the live ``[scoreboard]`` and
        ``[football]`` settings (read at each poll and each frame, so an admin-page change
        applies without a restart); ``client_factory`` makes the feed client (a fake in tests).
        The settings carry the idle rotation's rows as ``idle_rotation`` (football's share of the
        one mixed ``[[rotation]]`` list, epic #470)."""
        if client_factory is None:
            from .api import FootballClient

            def client_factory() -> Any:
                return FootballClient(league=league, keep_table=league != "nfl")

        self.league = league
        #: The league's teams: fixed for the NFL; for college, the FBS table the feed's client
        #: fetched (set from its thread, read by the render loop: one reference swap).
        self._directory: Directory | None = None
        #: When each game's halftime was first seen (monotonic), for the halftime cycle (#549).
        self._half_since: dict[int, float] = {}
        self._scoreboard = scoreboard
        self._on_sound = on_sound
        #: The owner's important dates inside their window (#524), nearest first: what the shared
        #: ``dates`` rotation screen shows between games, as hockey's does.
        self._dates = dates
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
        #: The chosen slot's length in seconds, for a table that scrolls over it (#551).
        self._slot_length = 0.0
        #: When this mode's idle rotation began (monotonic seconds): the app sets it so a rotation
        #: starts at the top of the turn the sports alternate in (epic #470), 0 otherwise.
        self.idle_origin = 0.0
        self._final_since: dict[int, float] = {}
        #: The idle screens' data cache (#421): the feed worker's thread owns it.
        self._idle_cache = IdleCache(monotonic)
        #: Scopes the admin page asked to clear, applied on the worker's thread (it owns the cache).
        self._clear_requests: set[str] = set()
        self.worker = FeedWorker(
            client_factory,
            self._interval,
            monotonic,
            collect=self._collect,
            idle=self._collect_idle,
            scope=self._scope_for_client,
        )
        #: Which play, celebration or reversal is on screen (#377). Render loop only.
        if timings is None and football is not None:
            timings = lambda: timings_from(football())  # noqa: E731 - the owner's [football] lengths
        #: Each watched game's team stats (shown over an official timeout). The feed worker's
        #: thread swaps in a new dict; the render loop only reads the reference.
        self._stats: Mapping[int, GameStats] = {}
        self._director_args = (football or _no_football, monotonic, delay_seconds, utc_now, timings)
        self.director = self._make_director()
        self._core_sync = CoreSync()
        #: Teams driving inside the 20, for the alert over the idle screens (``redzone``).
        self.redzone = RedZoneWatcher(monotonic)
        #: A ranked college team losing to a lower-ranked one (#557); college only.
        self.upsets = UpsetWatcher(monotonic)
        #: Team rosters for jersey numbers (#354), fetched hourly on first use. Held here, so
        #: it lives as long as the mode and survives the board switching sport back and forth. The
        #: feed worker's thread owns it: it must not be used from the render loop.
        self.rosters = RosterCache(self._fetch_roster, monotonic)
        self._roster_client: Any = None

    @property
    def directory(self) -> Directory | None:
        """The league's teams: the NFL's from the start, the FBS's once its client loaded them."""
        return NFL_DIRECTORY if self.league != LEAGUE_COLLEGE else self._directory

    def scope(self) -> AbstractContextManager[None]:
        """The league's team directory as a context: wrap anything that resolves teams (drawing a
        scene, reading the snapshot) in it. The NFL's is the default, so it is a no-op there. Until
        the college table has loaded nothing resolves (everything is drawn as an unknown team)."""
        if self.league != LEAGUE_COLLEGE:
            return nullcontext()
        return use_directory(self._directory or EMPTY_DIRECTORY)

    def _scope_for_client(self, client: Any) -> AbstractContextManager[None]:
        """The scope for the feed worker's thread, and where the render loop learns the table."""
        if self.league != LEAGUE_COLLEGE:
            return nullcontext()
        directory = getattr(client, "directory", None)
        if directory is not None:
            self._directory = directory
        return use_directory(directory or EMPTY_DIRECTORY)

    def _chosen_poll(self) -> Any:
        """The poll that decides "ranked" (``[football] college_poll``), or ``None``: not college,
        no polls fetched yet, or none fresh (out of season nobody is ranked)."""
        from ..config import COLLEGE_POLL_DEFAULT

        if self.league != LEAGUE_COLLEGE:
            return None
        polls = self.snapshot.idle.polls()
        if polls is None:
            return None
        cfg = self._football() if self._football else None
        return polls.chosen(getattr(cfg, "college_poll", COLLEGE_POLL_DEFAULT), self._utc_now())

    def rank_of(self, team_id: int | str | None) -> int | None:
        """A team's number in the chosen poll, or ``None`` (unranked, or no poll to say)."""
        poll = self._chosen_poll()
        return None if poll is None or team_id is None else poll.rank_of(team_id)

    def ranked(self, games: Sequence[FbGame]) -> list[FbGame]:
        """``games`` with each team's ``rank`` filled in from the chosen poll. Ranks are not in
        the game feed (its ``curatedRank`` follows an unknown poll), so they are applied here, at
        read time: a new poll shows on the next frame without refetching a game."""
        poll = self._chosen_poll()
        if poll is None:
            return list(games)
        out: list[FbGame] = []
        for game in games:
            away, home = poll.rank_of(game.away.espn_id), poll.rank_of(game.home.espn_id)
            if away is None and home is None:
                out.append(game)
                continue
            out.append(
                replace(
                    game,
                    away=replace(game.away, rank=away),
                    home=replace(game.home, rank=home),
                )
            )
        return out

    def _make_director(self) -> Director:
        return Director(
            *self._director_args,
            stats=self._stats_for,
            on_sound=self._on_sound,
            scores_only=self.league == LEAGUE_COLLEGE,
            stats_at_timeouts=self.league == LEAGUE_COLLEGE,
        )

    def request_clear(self, scope: str) -> None:
        """Ask for the idle data (and rosters) to be forgotten: ``football`` or ``football:<item>``
        (``schedule``, ``standings``, ``week``, ``rosters``). The worker owns that cache, so this
        only leaves a note; the next poll does it, and fetches afresh."""
        self._clear_requests.add(":".join(scope.split(":")[:2]))  # a team's item clears its kind

    @_in_scope
    def cache_items(self) -> list[dict[str, Any]]:
        """What football has cached, for the admin page's Cache tab (read-only; any thread)."""
        from ..cache_view import item

        now = self._monotonic()
        idle = self.snapshot.idle
        out: list[dict[str, Any]] = []
        for team_id, cached in sorted(dict(idle.schedules).items()):
            club = team_by_id(team_id)
            name = club.abbrev if club else str(team_id)
            games = getattr(cached.value, "games", ())
            out.append(
                item(
                    f"football:schedule:{name}",
                    "football",
                    f"{name} schedule",
                    cached.age(now),
                    f"{len(games)} games",
                    cached.value,
                )
            )
        if idle.standings_cached is not None:
            out.append(
                item(
                    "football:standings",
                    "football",
                    "Standings",
                    idle.standings_cached.age(now),
                    "both conferences",
                    idle.standings_cached.value,
                )
            )
        if idle.week_cached is not None:
            week = idle.week_cached.value
            out.append(
                item(
                    "football:week",
                    "football",
                    "The week's games",
                    idle.week_cached.age(now),
                    f"week {getattr(week, 'week', '?')}, {len(getattr(week, 'games', ()))} games",
                    week,
                )
            )
        if idle.scoreboard is not None:
            sb = idle.scoreboard
            byes = ", ".join(getattr(sb, "teams_on_bye", ()) or ()) or "none"
            out.append(
                item(
                    "football:scoreboard",
                    "football",
                    "Scoreboard extras (week, byes)",
                    None,
                    f"week {sb.week}, byes: {byes}",
                    sb,
                    clear=False,
                )
            )
        for team_id, (fetched_at, players) in sorted(self.rosters.snapshot().items()):
            club = team_by_id(team_id)
            name = club.abbrev if club else str(team_id)
            out.append(
                item(
                    f"football:rosters:{name}",
                    "football",
                    f"{name} roster",
                    now - fetched_at,
                    f"{len(players)} players",
                    players,
                )
            )
        return out

    def reset_screens(self) -> None:
        """Start the screens afresh, keeping the feed running (epic #470).

        When football becomes the sport on screen after another sport had it, the plays that
        happened meanwhile must not be animated or celebrated late: the director and the red zone
        watcher start empty and baseline on the next poll, as a sport switch always has. What the
        board knows about the games themselves (which were seen live, when each final appeared) is
        kept, and so are the worker, rosters and idle data.
        """
        self.director = self._make_director()
        self.redzone.clear()
        self.upsets.clear()
        self._slot_fraction = 0.0
        self._slot_length = 0.0

    @_in_scope
    def track(self) -> None:
        """Note which games were seen live and when each final first appeared, from the latest
        snapshot. ``scene`` does this as it draws; the app calls it too while another sport has
        the screen, so a final can still be held when football takes the board back."""
        now = self._monotonic()
        for game in self.snapshot.games or ():
            if game.is_live:
                self._seen_live.add(game.id)
            elif game.is_final and game.id in self._seen_live:
                self._final_since.setdefault(game.id, now)
        if self.league == LEAGUE_COLLEGE:
            # The upset alert watches the whole slate, whichever sport is on screen.
            cfg = self._football() if self._football else None
            if getattr(cfg, "upset_alert", True):
                self.upsets.observe(
                    self.ranked(self.snapshot.games or ()),
                    getattr(cfg, "upset_min_gap", 1),
                    self._upset_teams(cfg),
                )

    @staticmethod
    def _upset_teams(cfg: Any) -> tuple[str, ...]:
        """The teams an upset alert may be about (#588, #599): the ranked list's own, the favourite
        and the followed teams, as the team being upset or the one pulling the upset. With none
        listed nothing alerts."""
        return tuple(getattr(cfg, "followed_teams", ()) or ())

    @_in_scope
    def final_ages(self) -> dict[int, float]:
        """Seconds since each final was first seen ending (only games seen live)."""
        now = self._monotonic()
        return {game_id: now - since for game_id, since in self._final_since.items()}

    def _stats_for(self, game_id: int) -> GameStats | None:
        """A game's team stats, for the stats screen; 128px panels only (it is a split table)."""
        return self._stats.get(game_id) if self._wide() else None

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

    @_in_scope
    def watched(self, games: Sequence[FbGame]) -> list[FbGame]:
        """The games whose plays are fetched: live (or about to start) ones the favourite or a
        followed team is in. Never every game on the slate.

        Only a board that follows **no** football team falls back to the first live game, so it
        always has something to animate. With teams followed, none of them playing means nothing
        is watched: an unfollowed game must not take over the idle rotation (a Monday-night game
        between two other teams did, replayed from the coin toss)."""
        cfg = self._football() if self._football else None
        followed = ([cfg.favourite_team] if cfg and cfg.favourite_team else []) + (
            list(cfg.followed_teams) if cfg else []
        )
        playing = [g for g in games if g.is_live or self._imminent(g)]
        mine = [g for g in playing if any(g.involves(t) for t in followed)]
        if mine or followed:
            return mine
        return playing[:1]

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
            self._keep_stats(client, game.id)
            players[game.id] = self.rosters.players_for([game.home.espn_id, game.away.espn_id])
        keep = {g.id for g in games}
        self._core_sync.forget(lambda game_id: game_id in keep)
        return plays, players

    def _keep_stats(self, client: Any, game_id: int) -> None:
        """Take the team stats the plays request just carried; a failure keeps the last good."""
        getter = getattr(client, "team_stats", None)
        stats = getter(game_id) if callable(getter) else None
        if stats is not None:
            self._stats = {**self._stats, game_id: stats}

    def _collect_idle(
        self, client: Any, games: list[FbGame], scoreboard: Scoreboard | None, prev: IdleSnapshot
    ) -> IdleSnapshot:
        """The idle screens' data (#421): the favourite's and followed teams' schedules (daily),
        the standings (hourly) and the week's games (every few minutes), each fetched only when it
        is due. The scoreboard's own week, byes and calendar come in on the poll already made.

        **Nothing is fetched while a followed team's game is live** (the idle screens are not
        showing and the live poll is the busy one); the last data is kept. A live game between
        two other teams does not count: the idle screens are up through it, so their data has to
        load (a board restarted during Monday-night football otherwise never got a schedule or
        the standings until the game ended). A failed fetch keeps the last good value
        (``IdleCache``), and a client without these methods (a test fake) is simply skipped.
        """
        if self._clear_requests:
            prev = self._apply_clears(prev)
        snap = with_scoreboard(prev, scoreboard)
        cfg = self._football() if self._football else None
        mine = ([cfg.favourite_team] if cfg and cfg.favourite_team else []) + (
            list(cfg.followed_teams) if cfg else []
        )
        mine = [t for t in dict.fromkeys(mine) if is_team(t)]
        live_followed = any(g.is_live and any(g.involves(t) for t in mine) for g in games)
        # The ranks are fetched at the usual pace, and once even with a followed game live (the
        # board may have started mid-game and every badge needs them).
        if (
            self.league == LEAGUE_COLLEGE
            and hasattr(client, "college_rankings")
            and (snap.polls_cached is None or not live_followed)
        ):
            polls = self._idle_cache.refresh(("polls",), POLLS_TTL, client.college_rankings)
            snap = replace(snap, polls_cached=polls or snap.polls_cached)
        if live_followed:
            return snap
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
        college_table = snap.college_standings_cached
        if (
            self.league == LEAGUE_COLLEGE
            and mine
            and hasattr(client, "college_standings")
            and any(entry.screen == "cfb_conference" for entry in self._entries())
        ):
            # ~2.5 MB, so only for a board that lists the conference table, and hourly.
            college_table = (
                cache.refresh(("college_standings",), STANDINGS_TTL, client.college_standings)
                or college_table
            )
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
            polls_cached=snap.polls_cached,
            college_standings_cached=college_table,
        )

    def _apply_clears(self, prev: IdleSnapshot) -> IdleSnapshot:
        """Forget what the admin page asked to clear (on the worker's thread, which owns it)."""
        from ..cache_view import matches

        requests, self._clear_requests = set(self._clear_requests), set()

        def wanted(key: str) -> bool:
            return any(matches(scope, key) for scope in requests)

        if wanted("football:schedule"):
            self._idle_cache.forget(lambda k: not (isinstance(k, tuple) and k[0] == "schedule"))
            prev = replace(prev, schedules={})
        if wanted("football:standings"):
            self._idle_cache.forget(lambda k: k != ("standings",))
            prev = replace(prev, standings_cached=None)
        if wanted("football:week"):
            self._idle_cache.forget(lambda k: not (isinstance(k, tuple) and k[0] == "week"))
            prev = replace(prev, week_cached=None)
        if wanted("football:rosters"):
            self.rosters.clear()
        return prev

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
        self.redzone.clear()
        self.upsets.clear()
        self._stats = {}

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

    @_in_scope
    def scene(self) -> Scene:
        from ..app import Scene

        now = self._monotonic()
        snap = self.snapshot
        if not snap.has_data:
            # Never had an answer: connecting, until it has been failing for as long as the
            # Hockey side waits before it admits there is no data.
            waited = None if snap.started_at is None else now - snap.started_at
            if snap.failures and waited is not None and waited > STALE_AFTER_SECONDS:
                return Scene("fb_no_data")
            return Scene("fb_connecting")
        if snap.is_stale(now):
            return Scene("fb_no_data")
        games = self.ranked(snap.games or ())
        # A red zone alert is a takeover too: for college, only the ranked list's games raise one.
        alerting = self.listed(games) if self.league == LEAGUE_COLLEGE else games
        self.redzone.observe(alerting)
        idle_kind = self._idle_kind(games, snap, now)
        if idle_kind is not None:
            scene = self._idle_scene(idle_kind, games, snap, now)
            if idle_kind in ("fb_countdown", "fb_final"):
                # The favourite's countdown or final outranks a followed team's live game, but a
                # followed team's score or turnover still breaks in over it.
                mine = self._favourite_game(games)
                self.director.ingest(snap)
                current = self.director.current(mine.id if mine else None, hold=mine is not None)
                if current is not None:
                    return self._play_scene(
                        current, Scene(resting_kind(current.stage.game), fb_game=current.stage.game)
                    )
            # A followed team's score banner (above) comes first; then a red zone alert, if one
            # is due; then the idle screen itself.
            return self._redzone_scene(alerting) or scene
        if not games:
            return Scene("fb_no_games")
        game = self.pick_game(games, now)
        if game is None:
            return Scene("fb_no_games")  # college, and none of the ranked list's teams plays
        # The field between plays while a ball is in play, the halftime card at the half, and
        # the text scoreboard before the game and once it is final.
        resting = resting_kind(game)
        base = Scene(resting, fb_game=game)
        self.director.ingest(snap)
        # The favourite's live game holds the screen: a followed team's plays are not animated
        # over it, only its scores and turnovers come through (``Director.current``). At the half
        # there is nothing to hold, so the other games' plays are shown in full.
        hold = self._is_favourite(game) and game.is_live and not game.is_halftime
        current = self.director.current(game.id, hold=hold)
        if current is None:
            return self._halftime_cycle(game, base, now) or base
        return self._play_scene(current, base)

    def _halftime_cycle(self, game: FbGame, base: Scene, now: float) -> Scene | None:
        """College halftime (#549): the card, then the team stats' pages, round again for as long
        as the half lasts; a pure function of how long the half has run. ``None`` (the plain
        card) for anything else, or until the stats have arrived. A score screen never gets
        here: ``current`` is only None when nothing is being played out."""
        from ..app import Scene
        from .director import STATS

        if not game.is_halftime:
            self._half_since.pop(game.id, None)
            return None
        since = self._half_since.setdefault(game.id, now)
        stats = self._stats_for(game.id) if self.league == LEAGUE_COLLEGE else None
        if stats is None:
            return None
        page = self.director.stats_page_seconds()
        cycle = HALFTIME_CARD_SECONDS + stats.pages * page
        t = (now - since) % cycle
        if t < HALFTIME_CARD_SECONDS:
            return None
        return Scene(
            "fb_event",
            fb_game=game,
            fb_stats=stats,
            fb_stage=STATS,
            fb_elapsed=t - HALFTIME_CARD_SECONDS,
            fb_seconds=page,
            animating=True,
        )

    def _favourite_game(self, games: Sequence[FbGame]) -> FbGame | None:
        favourite = self._football().favourite_team if self._football else ""
        return next((g for g in games if favourite and g.involves(favourite)), None)

    def _is_favourite(self, game: FbGame) -> bool:
        favourite = self._football().favourite_team if self._football else ""
        return bool(favourite) and game.involves(favourite)

    def _redzone_scene(self, games: Sequence[FbGame]) -> Scene | None:
        """The red zone alert, if one is due while an idle screen is up (see ``redzone``).

        Only on a 128px panel (the idle screens are), and only when the owner has not turned it
        off. The alert is one short card; the idle screen comes back when it has had its seconds.
        """
        from ..app import Scene

        cfg = self._football() if self._football else _no_football()
        if not cfg.show_redzone or not self._wide():
            return None
        seconds = timings_from(cfg).redzone
        shown = self.redzone.current(games, seconds)
        if shown is None:
            return None
        game, elapsed = shown
        return Scene(
            "fb_redzone", fb_game=game, fb_elapsed=elapsed, fb_seconds=seconds, animating=True
        )

    @_in_scope
    def upset_scene(self) -> Scene | None:
        """The upset alert to show now, or ``None``. Any sport may be on screen: like a goal, it
        is news about a team the owner follows, wherever the board is. College only, 128px only,
        silent, only if the owner has not turned it off, and only when the team being upset is
        in the ranked list (#588)."""
        from ..app import Scene

        if self.league != LEAGUE_COLLEGE or not self._wide():
            return None
        cfg = self._football() if self._football else None
        if not getattr(cfg, "upset_alert", True):
            return None
        seconds = float(getattr(cfg, "upset_seconds", 8.0))
        shown = self.upsets.current(
            self.ranked(self.snapshot.games or ()),
            seconds,
            getattr(cfg, "upset_min_gap", 1),
            self._upset_teams(cfg),
        )
        if shown is None:
            return None
        game, upset, elapsed = shown
        return Scene(
            "fb_upset",
            fb_game=game,
            fb_upset=upset,
            fb_elapsed=elapsed,
            fb_seconds=seconds,
            animating=True,
        )

    # -- the idle selection (#422) -----------------------------------------------

    def _idle_kind(self, games: Sequence[FbGame], snap: FeedSnapshot, now: float) -> str | None:
        """The idle screen to show, or None to fall through to the game scenes.

        In order: the favourite's own live game always wins; its kickoff window shows
        ``fb_countdown`` and its final, within the hold, ``fb_final``, even while a followed
        team's game is live; then a live game of a followed team (or of anyone when nobody is
        followed); then, with a favourite set, the idle rotation; an empty slate shows the
        rotation's clock (or ``fb_no_games``). 128px panels only: on 64px this returns None except
        for the empty slate's clock.
        """
        from .idle_screens import IDLE_SCREENS

        self._slot_fraction = 0.0
        self._slot_length = 0.0
        cfg = self._football() if self._football else _no_football()
        followed = cfg.followed_teams
        for game in games:
            if game.is_live:
                self._seen_live.add(game.id)
            elif game.is_final and game.id in self._seen_live:
                self._final_since.setdefault(game.id, now)
        playing = [g for g in games if g.is_live]
        favourite = cfg.favourite_team
        mine = next((g for g in games if favourite and g.involves(favourite)), None)
        if mine is not None and mine.is_live:
            return None  # the favourite's own game always wins
        # A followed team's live game takes the screen, but only after the favourite's countdown
        # and final below: those keep their place. With nobody followed the NFL shows any live
        # game, but a college game that involves no team in the ranked list never takes the board
        # (#587: the owner's rule).
        others_live = any(any(g.involves(t) for t in followed) for g in playing) or (
            bool(playing) and not followed and self.league != LEAGUE_COLLEGE
        )
        wide = self._wide()
        if not wide:
            return None if others_live else ("clock" if not games and self._has_clock() else None)
        ctx = self._idle_context(games, snap, now, cfg)
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
        if others_live:
            return None
        if favourite:
            slots = self._rotation(cfg, ctx, favourite)
            if slots:
                screen, self._slot_fraction, self._slot_length = _slot_span(
                    slots, now - self.idle_origin
                )
                return screen
        if not games:
            return "clock" if self._has_clock() else None
        return None

    def has_idle_rows(self) -> bool:
        """Whether the idle rotation has a row that can be drawn right now (the render loop's, for
        the app's sport alternation): a registered screen with something to show, or the
        owner's important dates. A mode with none has nothing for its turn, and the board
        skips it rather than sit on the plain scoreboards."""
        cfg = self._football() if self._football else _no_football()
        snap = self.snapshot
        if not snap.has_data or not cfg.favourite_team or not self._wide():
            return False
        with self.scope():
            games = self.ranked(snap.games or ())
            ctx = self._idle_context(games, snap, self._monotonic(), cfg)
            return bool(self._rotation(cfg, ctx, cfg.favourite_team))

    def _in_countdown(self, game: FbGame, cfg: FootballConfig) -> bool:
        if not game.is_pregame or game.start_utc is None:
            return False
        until = game.start_utc - self._utc_now()
        return timedelta(0) <= until <= timedelta(minutes=cfg.countdown_minutes)

    def _entries(self) -> Sequence[Any]:
        """The idle rotation's rows for football: the settings view's (the app puts football's
        share of the one ``[[rotation]]`` list there), else the built-in default."""
        cfg = self._football() if self._football else _no_football()
        return cfg.idle_rotation

    def _has_clock(self) -> bool:
        return any(entry.screen == "clock" for entry in self._entries())

    def _rotation(self, cfg: FootballConfig, ctx: Any, favourite: str) -> list[tuple[str, float]]:
        """The rotation's slots that can show right now, as (screen, seconds).

        A screen drops out unless it is registered and its ``should_show`` is true; the clock only
        counts when another screen resolved (a lone clock is the empty-slate case, not a rotation);
        ``fb_bye`` joins when the favourite is on a bye.
        """
        from .idle_screens import IDLE_SCREENS

        slots: list[tuple[str, float]] = []
        clock: list[tuple[str, float]] = []
        for entry in self._entries():
            if entry.screen == "clock":
                clock.append((entry.screen, entry.seconds))
            elif entry.screen == "dates":
                if self._dates():
                    slots.append((entry.screen, entry.seconds))
            elif entry.screen in IDLE_SCREENS:
                view = IDLE_SCREENS[entry.screen](ctx)
                if not view:
                    continue
                pages = int(getattr(view, "pages", 1) or 1)
                # A paged screen with its own page length ignores the row's seconds.
                seconds = (
                    cfg.page_seconds * pages if cfg.page_seconds and pages > 1 else entry.seconds
                )
                # A table taller than the panel scrolls, and the row's seconds is a minimum: the
                # slot lasts as long as a readable scroll needs (hockey's rule, ``scroll.py``).
                scrolled = int(getattr(view, "scroll_rows", 0) or 0)
                if scrolled:
                    seconds = scroll_seconds(scrolled, seconds)
                slots.append((entry.screen, seconds))
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

        if kind == "dates":
            views = list(self._dates())
            if views:
                shown = pick_date(views, self._slot_fraction, 1.0)
                return Scene("dates", date_views=(shown,))
        cfg = self._football() if self._football else _no_football()
        favourite = cfg.favourite_team
        mine = next((g for g in games if favourite and g.involves(favourite)), None)
        build = IDLE_SCREENS.get(kind)
        view = build(self._idle_context(games, snap, now, cfg)) if build is not None else None
        pages = max(int(getattr(view, "pages", 1) or 1), 1)
        page = min(int(self._slot_fraction * pages), pages - 1)
        rows = int(getattr(view, "scroll_rows", 0) or 0)
        offset = self._slot_fraction * self._slot_length
        return Scene(
            kind,
            fb_game=mine if kind in ("fb_countdown", "fb_final") else None,
            fb_idle=view,
            fb_page=page,
            scroll_px=scroll_px(rows, offset, self._slot_length) if rows else 0,
            scrolling=bool(rows) and is_moving(rows, offset, self._slot_length),
        )

    def _play_scene(self, current: Any, base: Scene) -> Scene:
        """The scene for the stage on screen (#377), over the game's latest score."""
        from ..app import Scene
        from .director import PLAY, PLAYTEXT, STATS

        stage = current.stage
        kind = {PLAY: "fb_play", PLAYTEXT: "fb_playtext"}.get(stage.stage, "fb_event")
        games = {g.id: g for g in self.snapshot.games or ()}
        return Scene(
            kind,
            fb_game=games.get(stage.game.id, stage.game),
            fb_play=stage.play,
            fb_people=stage.people,
            fb_event=stage.event,
            fb_stats=self._stats_for(stage.game.id) if stage.stage == STATS else None,
            fb_stage=stage.stage,
            fb_elapsed=current.elapsed,
            fb_seconds=stage.seconds,
            animating=True,
        )

    @_in_scope
    def pick_game(self, games: Sequence[FbGame], now: float) -> FbGame | None:
        """Which game to show: the favourite's while it is live, else the followed teams' in turn.

        ``games`` comes best-first from the client (live, then upcoming, then finished).

        1. The favourite's own game, while it is live, holds the screen alone.
        2. Otherwise the games the followed teams are in take turns, ``rotate_seconds`` each,
           the favourite's first. If any of them is live, only the live ones do.
        3. NFL: with nobody followed, or none of them playing, every game takes a turn. College
           (#587): never; a game that involves no team in the ranked list is not shown, and
           ``None`` comes back when none of the listed teams has a game.

        Turns are timed by the (injectable) monotonic clock, not a counter, so a refresh
        that changes the slate never makes the board skip or repeat a game.
        """
        cfg = self._football() if self._football else None
        followed = cfg.followed_teams if cfg else []
        favourite = cfg.favourite_team if cfg else ""
        if self.league == LEAGUE_COLLEGE:
            # Only the ranked list's teams take the board (#587): a game that involves none of
            # them is never shown, whatever the slate holds.
            games = self.listed(games)
            if not games:
                return None
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

    def listed(self, games: Sequence[FbGame]) -> list[FbGame]:
        """The games that involve the favourite or a followed team: the ranked list's own."""
        cfg = self._football() if self._football else None
        followed = cfg.followed_teams if cfg else []
        return [g for g in games if any(g.involves(t) for t in followed)]


#: How long the halftime card holds before the team stats' pages take their turns (#549).
HALFTIME_CARD_SECONDS = 15.0


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
    screen, fraction, _ = _slot_span(slots, now)
    return screen, fraction


def _slot_span(slots: Sequence[tuple[str, float]], now: float) -> tuple[str, float, float]:
    """``_slot_at`` and the slot's length in seconds, for a screen that scrolls over it."""
    total = sum(seconds for _, seconds in slots)
    at = now % total
    for screen, seconds in slots:
        if at < seconds:
            return screen, at / seconds, seconds
        at -= seconds
    return slots[-1][0], 0.0, slots[-1][1]


def _no_football() -> FootballConfig:
    """Football's settings when nothing was passed in: the defaults, with nobody followed."""
    from ..config import FootballConfig
    from ..priority import TeamView

    return TeamView(FootballConfig(), "", [], "")  # type: ignore[return-value]


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
