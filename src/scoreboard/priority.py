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
* **Idle screens alternate between sports** (``idle_sport``): when nothing ranked is on, each
  sport that has a ranked team and something to show takes a turn, in the order of their lead
  teams' ranks. It is a pure function of the clock, so it never flickers: a sport holds its whole
  turn.
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
class Moment:
    """One ranked team with a game that matters now."""

    sport: str
    team: str
    rank: int
    kind: Kind
    game: Any
    #: How long ago a final ended (only for ``Kind.FINAL``), else zero.
    age: timedelta = timedelta(0)


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
        return next((e.team for e in self.teams if e.sport == sport), None)

    def sports(self) -> list[str]:
        """The sports that have a ranked team, ordered by their lead team's rank."""
        out: list[str] = []
        for entry in self.teams:
            if entry.sport not in out:
                out.append(entry.sport)
        return out

    def colour_team(self) -> TeamEntry | None:
        """The team the clock and holiday colours follow: the overall rank 1."""
        return self.teams[0] if self.teams else None

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
                if not game.involves(entry.team):
                    continue
                if game.is_live:
                    out.append(Moment(entry.sport, entry.team, rank, Kind.LIVE, game))
                elif game.is_pregame and window is not None and game.start_utc is not None:
                    until = game.start_utc - now
                    if timedelta(0) <= until <= window.countdown:
                        out.append(Moment(entry.sport, entry.team, rank, Kind.COUNTDOWN, game))
                elif game.is_final and window is not None:
                    age = final_ages.get((entry.sport, game.id))
                    if age is not None and age < window.final_hold:
                        out.append(Moment(entry.sport, entry.team, rank, Kind.FINAL, game, age))
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

    def idle_sport(
        self, clock: float, turns: Mapping[str, float | None]
    ) -> tuple[str, float] | None:
        """Which sport's idle screens are up at ``clock`` seconds, and how far through its turn
        (0 to 1), or ``None`` if no sport has anything to show.

        ``turns`` gives each sport's turn length (its whole idle rotation, in seconds), or ``None``
        for a sport with nothing to show (an offseason, no data). Only sports with a ranked team
        take turns, in the order of their lead teams' ranks. A pure function of ``clock``: a sport
        holds its whole turn, so the board cannot flicker between sports.
        """
        slots = [(s, turns[s]) for s in self.sports() if turns.get(s)]
        total = sum(length for _, length in slots if length)
        if not slots or total <= 0:
            return None
        at = clock % total
        for sport, length in slots:
            assert length is not None
            if at < length:
                return sport, at / length
            at -= length
        sport, _ = slots[-1]
        return sport, 1.0

    def empty_list_sport(self, games: Mapping[str, Sequence[GameLike]]) -> str | None:
        """With no team ranked: the sport whose live game takes the board (hockey before
        football), else ``None`` (the clock)."""
        if self.teams:
            return None
        return next((s for s in TEAM_SPORTS if any(g.is_live for g in games.get(s, ()))), None)


def _order(moment: Moment) -> tuple[int, timedelta, int]:
    """Live and countdown go by rank; a held final by recency first, then rank."""
    if moment.kind is Kind.FINAL:
        return (int(moment.kind), moment.age, moment.rank)
    return (int(moment.kind), timedelta(0), moment.rank)
