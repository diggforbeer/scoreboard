"""The priority layer: which team the board is about, from the ranked list (epic #470, #472).

Pure: no panel, no network, no clock of its own. It answers the board's questions from the ranked
``[[teams]]`` list, the games each sport's feed has today, and the time. The screens ask this module
instead of reading a favourite setting.

The rules (decided in the epic):

* **Rank picks the current favourite** (the owner). The highest-ranked team with something on
  owns the board: a live game beats a countdown beats a final still being held. Among live games
  and among countdowns the better rank wins, whichever sport it is in; among held finals the
  most recent one does.
* **The lead team of a sport** is its highest-ranked team: it gets the horn and the idle screens
  (``lead``), whether or not it is playing.
* **One idle rotation, mixed** (``idle_segments`` / ``segment_at``): the one ``[[rotation]]`` list
  holds screens of either sport. Consecutive rows of the same sport form a *segment* (the clock
  takes the sport of the rows around it) and the board alternates between segments, the sport
  of the segment having the board. Rows of a sport with nothing to show are skipped. It is a pure
  function of the clock, so it never flickers: a segment holds its whole length.
* **An empty list** keeps the old "nobody followed" behaviour per sport (``empty_list_sport``):
  a live game of either sport takes the board, hockey before football.
* **Colours** (the clock, the holidays) follow the overall rank 1 (``colour_team``), so they do not
  change as games start and end.

A team is always a (sport, abbreviation) pair: ``BUF`` is Buffalo in both leagues.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any, Protocol

from .config import TEAM_SPORTS, TeamEntry
from .football.teams import NIGHT_SLOTS


class GameLike(Protocol):
    """What this module needs of a game: both sports' game models already have it."""

    id: int
    start_utc: datetime | None

    @property
    def is_live(self) -> bool: ...
    @property
    def is_final(self) -> bool: ...
    @property
    def is_pregame(self) -> bool: ...
    def involves(self, abbrev: str) -> bool: ...


class Kind(IntEnum):
    """What a ranked team has on. A lower number outranks a higher one."""

    LIVE = 0
    COUNTDOWN = 1
    FINAL = 2


@dataclass(frozen=True, slots=True)
class Windows:
    """One sport's settings that decide when a game counts: how long before the start its
    countdown shows, and how long a final is held."""

    countdown: timedelta
    final_hold: timedelta


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of consecutive idle-rotation rows that one sport shows."""

    sport: str
    #: The rows (``RotationEntry``-like: ``screen`` and ``seconds``), in order.
    entries: tuple[Any, ...]

    @property
    def seconds(self) -> float:
        return sum(e.seconds for e in self.entries)


def idle_segments(entries: Sequence[Any], available: Sequence[str]) -> list[Segment]:
    """Group the one idle rotation into per-sport segments.

    ``entries`` is the rotation in order; ``available`` the sports that have something to show
    (rows of any other sport are skipped). The clock belongs to no sport: it joins the run before
    it, or the one after it when it comes first, or the first available sport when it is alone.
    """
    from .config import screen_sport

    kept: list[tuple[Any, str | None]] = []
    for entry in entries:
        sport = screen_sport(entry.screen)
        if sport == "shared":
            kept.append((entry, None))
        elif sport in available:
            kept.append((entry, sport))
    firsts = [s for _, s in kept if s is not None]
    if not firsts:
        if not kept or not available:
            return []
        firsts = [available[0]]
    current = firsts[0]
    out: list[Segment] = []
    for entry, sport in kept:
        current = sport or current
        if out and out[-1].sport == current:
            out[-1] = Segment(current, (*out[-1].entries, entry))
        else:
            out.append(Segment(current, (entry,)))
    return out


def segment_at(segments: Sequence[Segment], clock: float) -> tuple[int, float] | None:
    """Which segment is up at ``clock`` seconds and how far through it (0 to 1), or ``None``
    if there are none. A pure function of ``clock``."""
    total = sum(s.seconds for s in segments)
    if not segments or total <= 0:
        return None
    at = clock % total
    for index, segment in enumerate(segments):
        if at < segment.seconds:
            return index, at / segment.seconds
        at -= segment.seconds
    return len(segments) - 1, 1.0


@dataclass(frozen=True, slots=True)
class Moment:
    """One ranked team with a game that matters now."""

    sport: str
    team: str
    rank: int
    kind: Kind
    game: Any
    #: How long ago a final ended (only for ``Kind.FINAL``), else zero.
    age: timedelta = timedelta(0)


class TeamView:
    """A sport's settings as its screens should see them under a ranked list.

    The screens read ``favourite_team`` and ``followed_teams`` from their sport's settings object.
    Under a ranked list those are not settings but the priority layer's answers, so this wraps the
    real settings and supplies them: the **favourite** is the current owner (when it is this
    sport's) or else the sport's lead team, the followed teams are the sport's other ranked teams,
    and ``horn_team`` is the sport's lead team, the only one whose scores carry the horn. Every
    other attribute is the real settings object's own.
    """

    def __init__(
        self,
        base: Any,
        favourite: str,
        also_follow: Sequence[str],
        horn_team: str,
        idle_rotation: Sequence[Any] | None = None,
    ) -> None:
        from .config import DEFAULT_FOOTBALL_ROTATION, RotationEntry

        self._base = base
        #: The idle rotation's rows this sport shows (football reads it; the app puts football's
        #: share of the one mixed ``[[rotation]]`` list here), else football's built-in default.
        self.idle_rotation: list[Any] = (
            list(idle_rotation)
            if idle_rotation is not None
            else [RotationEntry(s, sec) for s, sec in DEFAULT_FOOTBALL_ROTATION]
        )
        self.favourite_team = favourite
        self.also_follow = list(also_follow)
        self.horn_team = horn_team

    @property
    def followed_teams(self) -> list[str]:
        """The favourite (if any) first, then the others: as the settings objects spell it."""
        return [self.favourite_team, *self.also_follow] if self.favourite_team else self.also_follow

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


class Priority:
    def __init__(self, teams: Sequence[TeamEntry]) -> None:
        self.teams: tuple[TeamEntry, ...] = tuple(teams)

    # -- the list ------------------------------------------------------------------------

    @property
    def empty(self) -> bool:
        return not self.teams

    def rank(self, sport: str, team: str) -> int | None:
        """A team's place in the whole list (1 is the top), or ``None`` if it is not ranked."""
        for rank, entry in enumerate(self.teams, start=1):
            if entry.sport == sport and entry.team == team:
                return rank
        return None

    def lead(self, sport: str) -> str | None:
        """The highest-ranked team of ``sport``: the one with the horn and the idle screens."""
        return next((e.team for e in self.teams if e.sport == sport and not _is_slot(e)), None)

    def teams_for(self, sport: str) -> list[str]:
        """The ranked teams of ``sport``, best first (the night-game slots are not teams)."""
        return [e.team for e in self.teams if e.sport == sport and not _is_slot(e)]

    def view(
        self,
        sport: str,
        base: Any,
        owner: Moment | None,
        idle_rotation: Sequence[Any] | None = None,
    ) -> TeamView:
        """``sport``'s settings (``base``) with the favourite, followed teams and horn team the
        ranked list gives: the favourite is the owner when it is this sport's, else the lead
        team."""
        teams = self.teams_for(sport)
        favourite = owner.team if owner is not None and owner.sport == sport else ""
        favourite = favourite or (teams[0] if teams else "")
        return TeamView(
            base,
            favourite,
            [t for t in teams if t != favourite],
            teams[0] if teams else "",
            idle_rotation,
        )

    def sports(self) -> list[str]:
        """The sports that have a ranked team, ordered by their lead team's rank."""
        out: list[str] = []
        for entry in self.teams:
            if entry.sport not in out:
                out.append(entry.sport)
        return out

    def colour_team(self, sports: Sequence[str] | None = None) -> TeamEntry | None:
        """The team the clock and holiday colours follow: the overall rank 1 (a night-game slot
        has no colours, so the first real team). ``sports`` limits it to the sports whose colours
        can be drawn (the app passes the ones it runs)."""
        return next(
            (e for e in self.teams if not _is_slot(e) and (sports is None or e.sport in sports)),
            None,
        )

    def _perspective(self, entry: TeamEntry, game: GameLike) -> str:
        """The team a moment is about: the ranked team itself, or for a night-game slot a ranked
        team playing in that game, else the home team (the screens need one side to favour)."""
        if not _is_slot(entry):
            return entry.team
        for other in self.teams:
            if other.sport == entry.sport and not _is_slot(other) and game.involves(other.team):
                return other.team
        home = getattr(game, "home", "")
        return str(getattr(home, "abbrev", home))

    # -- what is on ------------------------------------------------------------------------

    def moments(
        self,
        games: Mapping[str, Sequence[GameLike]],
        now: datetime,
        windows: Mapping[str, Windows],
        final_ages: Mapping[tuple[str, int], timedelta] | None = None,
    ) -> list[Moment]:
        """Every ranked team's game that matters now, best first.

        ``games`` is each sport's slate. ``final_ages`` maps ``(sport, game id)`` to how long ago
        a final was first seen ending: only a game in it can be held, so a board that starts after
        the whistle holds nothing, as before.
        """
        final_ages = final_ages or {}
        out: list[Moment] = []
        for rank, entry in enumerate(self.teams, start=1):
            window = windows.get(entry.sport)
            for game in games.get(entry.sport, ()):
                if _is_slot(entry):
                    if not getattr(game, "in_slot", lambda _s: False)(entry.team):
                        continue
                elif not game.involves(entry.team):
                    continue
                team = self._perspective(entry, game)
                if game.is_live:
                    out.append(Moment(entry.sport, team, rank, Kind.LIVE, game))
                elif game.is_pregame and window is not None and game.start_utc is not None:
                    until = game.start_utc - now
                    if timedelta(0) <= until <= window.countdown:
                        out.append(Moment(entry.sport, team, rank, Kind.COUNTDOWN, game))
                elif game.is_final and window is not None:
                    age = final_ages.get((entry.sport, game.id))
                    if age is not None and age < window.final_hold:
                        out.append(Moment(entry.sport, team, rank, Kind.FINAL, game, age))
        out.sort(key=_order)
        return out

    def owner(
        self,
        games: Mapping[str, Sequence[GameLike]],
        now: datetime,
        windows: Mapping[str, Windows],
        final_ages: Mapping[tuple[str, int], timedelta] | None = None,
    ) -> Moment | None:
        """The current favourite: the best moment, or ``None`` when nothing ranked is on."""
        moments = self.moments(games, now, windows, final_ages)
        return moments[0] if moments else None

    # -- nothing on --------------------------------------------------------------------------

    def empty_list_sport(self, games: Mapping[str, Sequence[GameLike]]) -> str | None:
        """With no team ranked: the sport whose live game takes the board (hockey before
        football), else ``None`` (the clock)."""
        if self.teams:
            return None
        return next((s for s in TEAM_SPORTS if any(g.is_live for g in games.get(s, ()))), None)


def _is_slot(entry: TeamEntry) -> bool:
    """A night-game slot (``TNF`` / ``SNF`` / ``MNF``) rather than a team."""
    return entry.sport == "football" and entry.team in NIGHT_SLOTS


def _order(moment: Moment) -> tuple[int, timedelta, int]:
    """Live and countdown go by rank; a held final by recency first, then rank."""
    if moment.kind is Kind.FINAL:
        return (int(moment.kind), moment.age, moment.rank)
    return (int(moment.kind), timedelta(0), moment.rank)
