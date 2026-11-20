"""Client for ESPN's public football scoreboard (#350).

Free, keyless and undocumented, so it can change without notice (see
``football_api.md``). Modelled on ``hockey/api.py`` -- the same retry policy and
timeouts -- with one deliberate difference: a failure never raises. ``scores()``
returns ``None`` ("no data") when the feed could not be reached or made no
sense, and ``[]`` only when ESPN really said there are no games (a bye week, the
off-season). The caller can tell the two apart, which the staleness logic needs.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .college_rankings import Polls, polls_from_payload
from .college_teams import CollegeTable, directory_from_table, table_from_payloads
from .idle import (
    Scoreboard,
    Standings,
    TeamSchedule,
    schedule_from_payload,
    scoreboard_from_payload,
    standings_from_payload,
)
from .models import FbGame, Play
from .people import RosterPlayer, roster_from_payload
from .stats import GameStats, stats_from_summary
from .teams import NFL_DIRECTORY, Directory, use_directory

log = logging.getLogger(__name__)

#: ESPN's league slugs. The college feed has the NFL's shape, so one client serves both (#539).
LEAGUE_NFL = "nfl"
LEAGUE_COLLEGE = "college-football"
LEAGUES = (LEAGUE_NFL, LEAGUE_COLLEGE)


def league_base_url(league: str) -> str:
    """The site API for ``league``: scoreboard, summary, teams, roster."""
    return f"https://site.api.espn.com/apis/site/v2/sports/football/{league}"


def league_core_url(league: str) -> str:
    """The core API: per-play ``participants`` (who did it) and the ``Coin Toss`` play (#354)."""
    return f"https://sports.core.api.espn.com/v2/sports/football/leagues/{league}"


def league_standings_url(league: str) -> str:
    """The standings live on ``/apis/v2/``, not ``/apis/site/v2/`` (football_api.md)."""
    return f"https://site.api.espn.com/apis/v2/sports/football/{league}"


BASE_URL = league_base_url(LEAGUE_NFL)
CORE_URL = league_core_url(LEAGUE_NFL)
STANDINGS_URL = league_standings_url(LEAGUE_NFL)
#: ESPN group 80 is FBS. Without it the college scoreboard returns a curated 24 games; with it
#: every FBS game of the week (``football_api.md``, "College football"). ``limit`` is lifted
#: because the default page can cut a full Saturday short.
COLLEGE_SCOREBOARD_PARAMS = {"groups": "80", "limit": "300"}
#: Plays asked for per core page. A game has 150-200, so one page covers it; longer ones follow
#: ``pageCount``.
CORE_PAGE_LIMIT = 300
CORE_MAX_PAGES = 10
USER_AGENT = "scoreboard/0.1 (+https://github.com/diggforbeer/scoreboard)"

#: (connect, read) seconds, as the hockey client. Fetches may run on the render
#: thread until the worker story lands, so this is also how long a stalled
#: request can freeze the panel.
TIMEOUT = (5.0, 5.0)

#: The scoreboard answers ``cache-control: max-age=7`` to ``9`` (seen 2026-11-12/13),
#: so asking faster than this only returns the same bytes. The lowest interval
#: any caller should poll at.
MIN_POLL_SECONDS = 10.0


_R = TypeVar("_R")


def _in_league(method: Callable[..., _R | None]) -> Callable[..., _R | None]:
    """Run a parsing method with this client's league as the active team directory.

    The models look teams up by ESPN id and abbreviation, and those collide between the NFL and
    FBS, so a college client must parse inside its own directory whatever thread it runs on. A
    college client with no team table yet fetches it first, and answers ``None`` (no data) if it
    cannot: parsing without one would mark every team unknown, or worse, resolve it to the NFL's.
    """

    @wraps(method)
    def scoped(self: FootballClient, *args: Any, **kwargs: Any) -> _R | None:
        directory = self._league_directory()
        if directory is None:
            return None
        with use_directory(directory):
            return method(self, *args, **kwargs)

    return scoped


def _build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    # One retry for a timeout (a server that did not answer in 5s rarely does a
    # second later and the next poll is seconds away); quick 429/5xx keep three.
    retry = Retry(
        total=3,
        connect=1,
        read=1,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


class FootballClient:
    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | tuple[float, float] = TIMEOUT,
        session: requests.Session | None = None,
        core_url: str | None = None,
        league: str = LEAGUE_NFL,
        standings_url: str | None = None,
    ) -> None:
        if league not in LEAGUES:
            raise ValueError(f"unknown football league {league!r}; expected one of {LEAGUES}")
        self.league = league
        #: The teams this client parses against: the NFL's from the start, the FBS's once the
        #: table has been fetched (``college_teams``).
        self._directory: Directory | None = NFL_DIRECTORY if league == LEAGUE_NFL else None
        # An explicit URL wins (tests point these at a fake); otherwise the league decides.
        self.base_url = (base_url or league_base_url(league)).rstrip("/")
        self.core_url = (core_url or league_core_url(league)).rstrip("/")
        self.standings_url = (standings_url or league_standings_url(league)).rstrip("/")
        self.timeout = timeout
        self.session = session or _build_session()
        #: The last failure, or ``""`` after a success. For the admin page's status.
        self.last_error = ""
        #: Team stats by event id, kept from each ``plays()`` request (same payload).
        self._stats: dict[str, GameStats | None] = {}

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> FootballClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @_in_league
    def scoreboard(
        self, date: str | None = None, week: int | None = None, season_type: int | None = None
    ) -> Scoreboard | None:
        """A scoreboard response: its games (best-first) and its week, byes and calendar (#421).

        ``date`` is one day (``YYYYMMDD``; a range is a 400); ``week`` with ``season_type`` (1, 2
        or 3) asks for a whole week. ``None`` is no data, as for ``scores``; an empty slate gives
        a ``Scoreboard`` with no games.
        """
        params: dict[str, str] = (
            dict(COLLEGE_SCOREBOARD_PARAMS) if self.league == LEAGUE_COLLEGE else {}
        )
        if date:
            params["dates"] = date
        if week is not None:
            params["week"] = str(week)
            params["seasontype"] = str(season_type or 2)
        payload = self._get("/scoreboard", params or None)
        if payload is None:
            return None
        games = _parse_events(payload.get("events"))
        games.sort(key=FbGame.sort_key)
        return scoreboard_from_payload(payload, games)

    def scores(self, date: str | None = None) -> list[FbGame] | None:
        """Every game on ``date`` (``YYYYMMDD``; default today's slate), best-first.

        ``None`` means no data (network error, bad status, not JSON, not the
        shape expected); ``[]`` means ESPN answered and there are no games.
        """
        board = self.scoreboard(date)
        return None if board is None else list(board.games)

    def week(self, number: int, season_type: int = 2) -> Scoreboard | None:
        """The whole week's games in one request (``week=N&seasontype=T``) and its byes."""
        return self.scoreboard(week=number, season_type=season_type)

    @_in_league
    def schedule(self, team_id: int | str) -> TeamSchedule | None:
        """A team's regular-season schedule and bye week (~300 KB: fetch daily at most).

        ``None`` is no data, **or a season with no events** (next season's is unpublished).
        """
        payload = self._get(f"/teams/{team_id}/schedule")
        if payload is None:
            return None
        return schedule_from_payload(int(team_id), payload)

    def standings(self) -> Standings | None:
        """Each conference's divisions with every team's record, seed and streak (~160 KB)."""
        if self.league != LEAGUE_NFL:
            # The college table is a different shape (conferences, Sun Belt nested under its
            # divisions, repeated stat names); its parser is #553.
            raise NotImplementedError("college standings are not parsed yet (#553)")
        payload = self._get("/standings", {"level": "3"}, base=self.standings_url)
        if payload is None:
            return None
        return standings_from_payload(payload)

    def college_teams(self) -> CollegeTable | None:
        """Every FBS team with its conference and colours (#540): two requests, ~1.9 MB.

        The standings (``group=80``) say who is FBS and which conference; ``/teams`` has the
        colours. Fetch once and keep it (the caller caches); ``None`` if either request fails, so
        a half-built table with neutral colours is never kept for a day. NFL clients refuse.
        """
        if self.league != LEAGUE_COLLEGE:
            raise ValueError("college_teams() needs a college-football client")
        standings = self._get("/standings", {"group": "80"}, base=self.standings_url)
        if standings is None:
            return None
        teams = self._get("/teams", {"limit": "1000"})
        if teams is None:
            return None
        table = table_from_payloads(standings, teams)
        if table is not None:
            self._directory = directory_from_table(table)
        return table

    def _league_directory(self) -> Directory | None:
        """The directory to parse with, fetching the college table first if it is needed."""
        if self._directory is None and self.college_teams() is None:
            return None
        return self._directory

    def college_rankings(self) -> Polls | None:
        """The AP, Coaches and CFP polls in one request (~680 KB: fetch hourly at most) (#546).

        ``None`` is no data (a failure, or not the shape expected). NFL clients refuse.
        """
        if self.league != LEAGUE_COLLEGE:
            raise ValueError("college_rankings() needs a college-football client")
        payload = self._get("/rankings")
        return None if payload is None else polls_from_payload(payload)

    @_in_league
    def plays(self, event_id: int | str) -> list[Play] | None:
        """Every play of a game so far, in the order they happened (#353).

        Read from the site ``summary``: ``drives.previous[].plays`` plus
        ``drives.current.plays``. ``None`` is no data (as for ``scores``); ``[]`` is a
        game with no plays yet. The coin toss is not in this endpoint (see
        ``football_api.md``). Drives are only a grouping: plays are de-duplicated by id
        and sorted by ``sequenceNumber``, so the order ESPN lists drives in never matters.
        """
        payload = self._get("/summary", {"event": str(event_id)})
        if payload is None:
            return None
        # The same payload carries the team stats: keep them so showing them is no extra request.
        self._stats[str(event_id)] = stats_from_summary(payload)
        return plays_from_summary(payload)

    def team_stats(self, event_id: int | str) -> GameStats | None:
        """The team stats from the last :meth:`plays` call for this game, or ``None``."""
        return self._stats.get(str(event_id))

    @_in_league
    def core_plays(self, event_id: int | str) -> list[Play] | None:
        """A game's plays from the **core** feed, each with its ``participants`` (#354).

        The same plays as :meth:`plays` (ids match exactly) plus the ``Coin Toss`` the site feed
        omits. One request covers a whole game (37 KB on the wire); a longer one follows
        ``pageCount``. ``None`` is no data, ``[]`` is a game with no plays. See
        ``people.merge_core`` to join it with the site plays, and ``people.CoreSync`` for when
        it is worth fetching.
        """
        path = f"/events/{event_id}/competitions/{event_id}/plays"
        first = self._get(path, {"limit": str(CORE_PAGE_LIMIT)}, base=self.core_url)
        if first is None:
            return None
        pages = [first]
        total = _int_or(first.get("pageCount"), 1)
        for page in range(2, min(total, CORE_MAX_PAGES) + 1):
            more = self._get(
                path, {"limit": str(CORE_PAGE_LIMIT), "page": str(page)}, base=self.core_url
            )
            if more is None:
                return None
            pages.append(more)
        plays: dict[str, Play] = {}
        for payload in pages:
            for item in payload.get("items") or []:
                try:
                    play = Play.from_api(item)
                except (ValueError, TypeError, AttributeError, KeyError) as exc:
                    log.warning("Skipping unusable core play: %s", exc)
                    continue
                plays[play.id] = play
        return sorted(plays.values(), key=Play.sort_key)

    @_in_league
    def roster(self, team_id: int | str) -> dict[int, RosterPlayer] | None:
        """A team's roster by athlete id (jersey, name, position), or ``None`` on failure (#354)."""
        payload = self._get(f"/teams/{team_id}/roster")
        if payload is None:
            return None
        return roster_from_payload(payload)

    # -- plumbing --------------------------------------------------------

    def _get(
        self, path: str, params: dict[str, str] | None = None, base: str | None = None
    ) -> dict[str, Any] | None:
        url = f"{base or self.base_url}{path}"
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            return self._fail(f"GET {url} failed: {exc}")
        except ValueError as exc:
            return self._fail(f"GET {url} returned invalid JSON: {exc}")
        if not isinstance(payload, dict):
            return self._fail(f"GET {url} returned {type(payload).__name__}, expected an object")
        if self.last_error:
            log.info("ESPN scoreboard is reachable again")
        self.last_error = ""
        return payload

    def _fail(self, message: str) -> None:
        # Warn on the first failure of a run, then stay quiet until it recovers,
        # so a long outage is one line in the journal, not one per poll.
        if not self.last_error:
            log.warning("ESPN scoreboard unavailable: %s", message)
        else:
            log.debug("ESPN scoreboard still unavailable: %s", message)
        self.last_error = message
        return None


def plays_from_summary(payload: dict[str, Any]) -> list[Play]:
    """The plays in a site ``summary`` payload, de-duplicated by id and in play order.

    ``drives.previous[].plays`` plus ``drives.current.plays``; drives are only a grouping,
    so the order ESPN lists them in never matters. A play listed twice keeps the later copy
    (ESPN rewrites a play in place after a review). Unusable plays are skipped.
    """
    drives = payload.get("drives")
    drives = drives if isinstance(drives, dict) else {}
    previous = drives.get("previous")
    groups = list(previous) if isinstance(previous, list) else []
    if isinstance(drives.get("current"), dict):
        groups.append(drives["current"])
    plays: dict[str, Play] = {}
    for group in groups:
        for item in (group.get("plays") if isinstance(group, dict) else None) or []:
            try:
                play = Play.from_api(item)
            except (ValueError, TypeError, AttributeError, KeyError) as exc:
                log.warning("Skipping unusable play: %s", exc)
                continue
            plays[play.id] = play
    return sorted(plays.values(), key=Play.sort_key)


def _parse_events(raw: Any) -> list[FbGame]:
    games: list[FbGame] = []
    for item in raw if isinstance(raw, list) else []:
        try:
            games.append(FbGame.from_api(item))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            log.warning("Skipping unusable event: %s", exc)
    return games


def _int_or(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
