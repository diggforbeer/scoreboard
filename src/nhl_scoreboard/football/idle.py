"""What the idle screens need beyond today's slate (#421): the schedule, the standings, the week.

``screens_not_during_games.md`` proposes screens for when no game is on; the data they read lives
here, parsed from the shapes recorded in ``football_api.md`` ("Between games") and cached with the
cadences the design gives: **a team's schedule daily, the standings hourly, the week's games every
few minutes while idle**. Nothing here draws, decides which screen shows, or touches the network
by itself: the feed worker's thread calls :class:`IdleCache`, publishes an immutable
:class:`IdleSnapshot`, and the render loop only reads it.

Rules, from the design:

* A failed fetch **keeps the last good data** and never blanks a screen; a failed fetch is retried
  after ``RETRY_SECONDS``, not every frame.
* Data older than twice its window is **stale**, and the snapshot's accessors then return ``None``
  rather than pass it off as fresh.
* **Nothing is fetched while a game is live** (the live poll is busy and the idle screens are not
  showing); the last data is kept, and the scoreboard's own week, byes and calendar still update
  (they arrive on the poll the worker makes anyway).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Generic, TypeVar

from .models import FbGame, _dict, _int, _list, _parse_time, _str
from .teams import team_by_id

log = logging.getLogger(__name__)

#: How long each kind of data is good for before it is fetched again.
SCHEDULE_TTL = 24 * 3600.0
STANDINGS_TTL = 3600.0
WEEK_TTL = 300.0
#: After a failed fetch, do not try again for this long.
RETRY_SECONDS = 60.0
#: Data older than ``STALE_FACTOR`` windows is stale: reported as missing, not shown as fresh.
STALE_FACTOR = 2.0

T = TypeVar("T")


def _abbrev(team_id: int | None, fallback: str = "") -> str:
    """The NFL abbreviation for an ESPN team id, else the feed's own abbreviation."""
    if team_id is not None:
        try:
            return team_by_id(team_id).abbrev
        except KeyError:
            pass
    return fallback.strip().upper()


# -- the scoreboard's own extras: the week, the byes and the calendar ------------------------


@dataclass(frozen=True, slots=True)
class CalendarEntry:
    """One week of the season calendar (``leagues[0].calendar`` on every scoreboard response)."""

    season_type: int  #: 1 preseason, 2 regular season, 3 postseason
    season_label: str  #: ``Regular Season``, ``Postseason``
    week: int | None  #: the week's value; ``None`` for an entry-less type such as ``Off Season``
    label: str  #: ``Week 12``, ``Divisional Round``
    short_label: str  #: ``Week 12``, ``Div Rd`` (the feed's ``alternateLabel``)
    start: datetime | None
    end: datetime | None


@dataclass(frozen=True, slots=True)
class Scoreboard:
    """A scoreboard response: its games and what the response says about the week."""

    games: tuple[FbGame, ...]
    season_type: int | None = None
    season_year: int | None = None
    week: int | None = None
    #: Abbreviations of the teams on a bye this week (``week.teamsOnBye``): the whole bye signal.
    teams_on_bye: tuple[str, ...] = ()
    calendar: tuple[CalendarEntry, ...] = ()

    def on_bye(self, abbrev: str) -> bool:
        return abbrev.strip().upper() in self.teams_on_bye


def calendar_from_payload(payload: Any) -> tuple[CalendarEntry, ...]:
    """Every week of every season type in the payload's calendar; ``()`` when it has none."""
    out: list[CalendarEntry] = []
    leagues = _list(_dict(payload).get("leagues"))
    for season in _list(_dict(next(iter(leagues), None)).get("calendar")):
        season = _dict(season)
        kind = _int(season.get("value"), None)
        label = _str(season.get("label"))
        entries = _list(season.get("entries"))
        if not entries and kind is not None:  # ``Off Season`` has no weeks: the type is the entry
            out.append(
                CalendarEntry(
                    kind,
                    label,
                    None,
                    label,
                    label,
                    _parse_time(season.get("startDate")),
                    _parse_time(season.get("endDate")),
                )
            )
        for entry in entries:
            entry = _dict(entry)
            if kind is None:
                continue
            out.append(
                CalendarEntry(
                    season_type=kind,
                    season_label=label,
                    week=_int(entry.get("value"), None),
                    label=_str(entry.get("label")),
                    short_label=_str(entry.get("alternateLabel") or entry.get("label")),
                    start=_parse_time(entry.get("startDate")),
                    end=_parse_time(entry.get("endDate")),
                )
            )
    return tuple(out)


def scoreboard_from_payload(payload: Any, games: list[FbGame]) -> Scoreboard:
    """The week, byes and calendar of a scoreboard payload, around its already-parsed games."""
    body = _dict(payload)
    season = _dict(body.get("season"))
    week = _dict(body.get("week"))
    byes = tuple(
        _abbrev(_int(_dict(t).get("id"), None), _str(_dict(t).get("abbreviation")))
        for t in _list(week.get("teamsOnBye"))
    )
    return Scoreboard(
        games=tuple(games),
        season_type=_int(season.get("type"), None),
        season_year=_int(season.get("year"), None),
        week=_int(week.get("number"), None),
        teams_on_bye=tuple(b for b in byes if b),
        calendar=calendar_from_payload(body),
    )


# -- a team's schedule -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ScheduleGame:
    """One game of a team's regular-season schedule."""

    event_id: int | None
    week: int | None
    season_type: int | None
    start_utc: datetime | None
    home: str
    away: str
    #: ``None`` until played.
    home_score: int | None
    away_score: int | None
    status_name: str
    completed: bool

    def opponent(self, team: str) -> str:
        key = team.strip().upper()
        return self.away if self.home == key else self.home

    def is_home(self, team: str) -> bool:
        return self.home == team.strip().upper()


@dataclass(frozen=True, slots=True)
class TeamSchedule:
    team_id: int
    season_year: int | None
    #: The bye week (``byeWeek``); ``None`` when the feed gives none.
    bye_week: int | None
    games: tuple[ScheduleGame, ...]

    def upcoming(self, now: datetime) -> tuple[ScheduleGame, ...]:
        """Games not yet over, soonest first: scheduled ones, and any whose kickoff is ahead."""
        later = [
            g for g in self.games if not g.completed and (g.start_utc is None or g.start_utc >= now)
        ]
        return tuple(sorted(later, key=lambda g: (g.start_utc is None, g.start_utc or now)))

    def next_game(self, now: datetime) -> ScheduleGame | None:
        coming = self.upcoming(now)
        return coming[0] if coming else None


def schedule_from_payload(team_id: int, payload: Any) -> TeamSchedule | None:
    """A team's schedule from ``/teams/{id}/schedule``; ``None`` if it has no events at all
    (a season that is not published yet). Unusable events are skipped, never raised."""
    body = _dict(payload)
    games: list[ScheduleGame] = []
    for raw in _list(body.get("events")):
        try:
            games.append(_schedule_game(raw))
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            log.warning("Skipping unusable schedule event: %s", exc)
    if not games:
        return None
    games.sort(key=lambda g: (g.start_utc is None, g.start_utc.timestamp() if g.start_utc else 0.0))
    return TeamSchedule(
        team_id=team_id,
        season_year=_int(_dict(body.get("season")).get("year"), None),
        bye_week=_int(body.get("byeWeek"), None),
        games=tuple(games),
    )


def _schedule_game(raw: Any) -> ScheduleGame:
    event = _dict(raw)
    comp = _dict(next(iter(_list(event.get("competitions"))), None))
    sides: dict[str, tuple[str, int | None]] = {}
    for c in _list(comp.get("competitors")):
        c = _dict(c)
        team = _dict(c.get("team"))
        abbrev = _abbrev(_int(team.get("id"), None), _str(team.get("abbreviation")))
        score = _dict(c.get("score"))
        sides[_str(c.get("homeAway"))] = (abbrev, _int(score.get("value"), None) if score else None)
    if "home" not in sides or "away" not in sides:
        raise ValueError("event has no home and away team")
    stype = _dict(_dict(comp.get("status")).get("type"))
    return ScheduleGame(
        event_id=_int(event.get("id"), None),
        week=_int(_dict(event.get("week")).get("number"), None),
        season_type=_int(_dict(event.get("seasonType")).get("type"), None),
        start_utc=_parse_time(comp.get("date") or event.get("date")),
        home=sides["home"][0],
        away=sides["away"][0],
        home_score=sides["home"][1],
        away_score=sides["away"][1],
        status_name=_str(stype.get("name")),
        completed=bool(stype.get("completed")),
    )


# -- the standings ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StandingsRow:
    team: str
    team_id: int | None
    #: ``7-1`` or ``5-3-1``.
    overall: str
    wins: int
    losses: int
    ties: int
    #: ``.875``.
    win_pct: str
    #: 1 is the top seed; ``None`` for a team with no seed yet.
    seed: int | None
    #: ``W4`` / ``L1``.
    streak: str
    points_for: int
    points_against: int
    division_record: str = ""


@dataclass(frozen=True, slots=True)
class Division:
    name: str  #: ``NFC East``
    rows: tuple[StandingsRow, ...]  #: in standings order


@dataclass(frozen=True, slots=True)
class Conference:
    name: str  #: ``National Football Conference``
    abbreviation: str  #: ``NFC``
    divisions: tuple[Division, ...]

    def seeds(self) -> tuple[StandingsRow, ...]:
        """The seeded teams, seed 1 first."""
        rows = [r for d in self.divisions for r in d.rows if r.seed is not None]
        return tuple(sorted(rows, key=lambda r: r.seed or 0))

    def unseeded(self) -> tuple[StandingsRow, ...]:
        """The teams with no seed, best record first: the first team out is the first of these."""
        rows = [r for d in self.divisions for r in d.rows if r.seed is None]
        return tuple(sorted(rows, key=lambda r: r.win_pct, reverse=True))


@dataclass(frozen=True, slots=True)
class Standings:
    conferences: tuple[Conference, ...]

    def conference_of(self, team: str) -> Conference | None:
        key = team.strip().upper()
        return next(
            (c for c in self.conferences for d in c.divisions for r in d.rows if r.team == key),
            None,
        )

    def division_of(self, team: str) -> Division | None:
        key = team.strip().upper()
        return next(
            (d for c in self.conferences for d in c.divisions for r in d.rows if r.team == key),
            None,
        )


def standings_from_payload(payload: Any) -> Standings | None:
    """The standings from ``/apis/v2/sports/football/nfl/standings?level=3``: each conference's
    divisions with their teams. ``None`` when there are no conferences."""
    conferences: list[Conference] = []
    for conf in _list(_dict(payload).get("children")):
        conf = _dict(conf)
        divisions = []
        for div in _list(conf.get("children")):
            div = _dict(div)
            rows = tuple(
                r
                for r in (
                    _standings_row(e) for e in _list(_dict(div.get("standings")).get("entries"))
                )
                if r
            )
            if rows:
                divisions.append(Division(_str(div.get("name")), rows))
        if divisions:
            conferences.append(
                Conference(_str(conf.get("name")), _str(conf.get("abbreviation")), tuple(divisions))
            )
    return Standings(tuple(conferences)) if conferences else None


def _standings_row(raw: Any) -> StandingsRow | None:
    entry = _dict(raw)
    team = _dict(entry.get("team"))
    team_id = _int(team.get("id"), None)
    abbrev = _abbrev(team_id, _str(team.get("abbreviation")))
    if not abbrev:
        return None
    stats = {
        _str(_dict(s).get("name")): _str(_dict(s).get("displayValue"))
        for s in _list(entry.get("stats"))
    }

    def number(name: str) -> int:
        try:
            return int(stats.get(name, "0") or 0)
        except ValueError:
            return 0

    seed = _int(stats.get("playoffSeed"), None)
    return StandingsRow(
        team=abbrev,
        team_id=team_id,
        overall=stats.get("overall", ""),
        wins=number("wins"),
        losses=number("losses"),
        ties=number("ties"),
        win_pct=stats.get("winPercent", ""),
        seed=seed if seed and seed > 0 else None,
        streak=stats.get("streak", ""),
        points_for=number("pointsFor"),
        points_against=number("pointsAgainst"),
        division_record=stats.get("divisionRecord", ""),
    )


# -- the cache and what is published ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cached(Generic[T]):
    value: T
    #: Monotonic time it was fetched.
    fetched_at: float

    def age(self, now: float) -> float:
        return now - self.fetched_at


@dataclass(frozen=True, slots=True)
class IdleSnapshot:
    """Everything the idle screens read, immutable: the render loop never waits on any of it.

    The accessors return ``None`` for anything missing or **stale** (older than twice its window),
    so a screen asks and skips itself rather than showing old data as current.
    """

    #: The latest scoreboard's week, byes and calendar (updated on every poll, even live).
    scoreboard: Scoreboard | None = None
    schedules: Mapping[int, Cached[TeamSchedule]] = field(default_factory=dict)
    standings_cached: Cached[Standings] | None = None
    week_cached: Cached[Scoreboard] | None = None

    def schedule(self, team_id: int, now: float) -> TeamSchedule | None:
        return _fresh(self.schedules.get(team_id), SCHEDULE_TTL, now)

    def standings(self, now: float) -> Standings | None:
        return _fresh(self.standings_cached, STANDINGS_TTL, now)

    def week(self, now: float) -> Scoreboard | None:
        return _fresh(self.week_cached, WEEK_TTL, now)


def _fresh(item: Cached[T] | None, ttl: float, now: float) -> T | None:
    if item is None or item.age(now) > ttl * STALE_FACTOR:
        return None
    return item.value


class IdleCache:
    """Fetches the idle data on the feed worker's thread, at most once per window.

    ``fetch`` callables return the parsed value or ``None`` for no data; an exception is treated
    the same. Either way the last good value is kept and the key is not retried for
    ``RETRY_SECONDS``. Not thread-safe: the worker owns it.
    """

    def __init__(self, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._items: dict[object, Cached[Any]] = {}
        self._retry_after: dict[object, float] = {}

    def refresh(self, key: object, ttl: float, fetch: Callable[[], Any]) -> Cached[Any] | None:
        """The cached item for ``key``, fetching first if it is older than ``ttl`` (and the last
        failure is not too recent). ``None`` if there is nothing, fresh or old."""
        now = self._monotonic()
        item = self._items.get(key)
        if item is not None and item.age(now) < ttl:
            return item
        if now < self._retry_after.get(key, 0.0):
            return item
        try:
            value = fetch()
        except Exception as exc:  # the worker's thread must survive whatever the client does
            log.warning("idle fetch %r raised %s", key, exc)
            value = None
        if value is None:
            self._retry_after[key] = now + RETRY_SECONDS
            return item
        self._retry_after.pop(key, None)
        self._items[key] = Cached(value, now)
        return self._items[key]

    def forget(self, keep: Callable[[object], bool]) -> None:
        for key in [k for k in self._items if not keep(k)]:
            del self._items[key]

    def clear(self) -> None:
        self._items.clear()
        self._retry_after.clear()


def with_scoreboard(snapshot: IdleSnapshot, scoreboard: Scoreboard | None) -> IdleSnapshot:
    """The snapshot with the latest scoreboard extras (week, byes, calendar) swapped in."""
    return snapshot if scoreboard is None else replace(snapshot, scoreboard=scoreboard)
