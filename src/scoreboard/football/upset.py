"""The upset alert: a ranked team is losing to a lower-ranked or unranked one (#557).

The owner's rules (2026-11-20):

* **From halftime on.** Nothing fires in the first half: a deficit at the half is a story, one in
  the first quarter is not.
* **A ranked team trailing a lower-ranked or unranked one.** Unranked counts as below every rank, so
  #5 trailing #20 is an upset and so is #5 trailing a team nobody ranks. A ranked team trailing a
  *higher*-ranked one is not.
* **And at the final.** A ranked team that lost to a lower-ranked or unranked one gets an upset
  final, whether or not the alert fired during the game.
* **Only for the ranked list's teams** (#588, the owner's standing rule that nothing but the teams
  they follow takes the board): the team being upset must be the favourite or a followed team. An
  upset between teams nobody follows never alerts, however big. ``teams`` is that list of
  abbreviations; ``None`` (the pure-function default, used by the tests) means any game.

Ranks are the chosen poll's (``FootballMode.ranked``), so the alert and the badges always agree.
Pure functions plus a small watcher; whether the board may show it (the setting, a 128px panel)
is the mode's decision.

Like the red zone alert it is a **transition, not a state**: it is made when a game enters the
upset, and a game already in one when the board first sees it is only noted, so a restart does not
announce what was already happening. Each game alerts once while live and once at the final.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

from .models import FbGame, FbTeam

log = logging.getLogger(__name__)

#: How an unranked team compares: below the 25th.
UNRANKED_KEY = 26
#: Seconds a queued alert may wait before it is dropped as old news.
STALE_AFTER = 45.0


@dataclass(frozen=True, slots=True)
class Upset:
    """A ranked team losing (or lost) to a lower-ranked or unranked one."""

    #: The ranked team that is behind, or lost.
    favourite: FbTeam
    #: The team beating it.
    underdog: FbTeam
    #: The game is over: an upset *final*, not an alert.
    final: bool
    #: How many points the favourite is down by (or lost by).
    margin: int


def upset_of(game: FbGame, min_gap: int = 1, teams: Collection[str] | None = None) -> Upset | None:
    """The upset ``game`` is in, or ``None``.

    ``min_gap`` is how many places lower the leader must be ranked (1: any lower-ranked team, and
    every unranked one). Needs ranks on the game's teams. ``teams`` limits it to games with one of
    those abbreviations (the ranked list's) on either side, the team being upset or the one
    pulling the upset (#599); ``None`` is any game.
    """
    if game.is_final:
        final = True
    elif game.is_live and (game.is_halftime or game.period >= 3):
        final = False
    else:
        return None  # not started, or still in the first half
    if game.away.score == game.home.score:
        return None
    trailing, leading = (
        (game.away, game.home) if game.away.score < game.home.score else (game.home, game.away)
    )
    if trailing.rank is None:
        return None  # only a ranked team can be upset
    if teams is not None and not {trailing.abbrev.upper(), leading.abbrev.upper()} & {
        t.upper() for t in teams
    }:
        return None  # neither team is one the owner follows
    if (leading.rank or UNRANKED_KEY) - trailing.rank < max(1, min_gap):
        return None
    return Upset(trailing, leading, final, leading.score - trailing.score)


@dataclass(frozen=True, slots=True)
class UpsetAlert:
    game_id: int
    final: bool
    queued_at: float


class UpsetWatcher:
    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        #: game id -> what the last look found: ``None`` (no upset), ``"live"`` or ``"final"``
        self._state: dict[int, str | None] = {}
        #: (game id, final?) pairs already alerted: each fires once
        self._fired: set[tuple[int, bool]] = set()
        self._pending: deque[UpsetAlert] = deque()
        self._active: tuple[UpsetAlert, float] | None = None
        #: The list of teams the last look used: a different list is a new baseline (#588).
        self._teams: frozenset[str] | None = None

    def observe(
        self, games: Sequence[FbGame], min_gap: int = 1, teams: Collection[str] | None = None
    ) -> None:
        """Look at the (ranked) slate as the feed last gave it. Cheap: call it every frame.

        When ``teams`` is not the list of the last look (a team was added or removed), every game
        is looked at afresh as a first sight, so a newly followed team that is already being upset
        does not fire: the alert is for what happens after, like every other detector."""
        now = self._monotonic()
        listed = None if teams is None else frozenset(t.upper() for t in teams)
        if listed != self._teams:
            self._teams = listed
            self._state.clear()
        seen = set()
        for game in games:
            seen.add(game.id)
            upset = upset_of(game, min_gap, listed)
            state = None if upset is None else ("final" if upset.final else "live")
            known = game.id in self._state
            previous = self._state.get(game.id)
            self._state[game.id] = state
            if state is None or not known or state == previous:
                # No upset; or first sight (noted only); or one that was already going on at the
                # last look. Only a game *entering* an upset (or reaching its final) alerts: it
                # used to alert on the second look at a game that was already in one.
                continue
            key = (game.id, state == "final")
            if key in self._fired:
                continue
            self._fired.add(key)
            self._pending.append(UpsetAlert(game.id, state == "final", now))
            log.info(
                "[%s] upset %s: %s #%s is behind %s",
                game.id,
                state,
                upset.favourite.abbrev,
                upset.favourite.rank,
                upset.underdog.abbrev,
            )
        for gone in [g for g in self._state if g not in seen]:
            del self._state[gone]
            self._fired = {k for k in self._fired if k[0] != gone}

    def current(
        self,
        games: Sequence[FbGame],
        seconds: float,
        min_gap: int = 1,
        teams: Collection[str] | None = None,
    ) -> tuple[FbGame, Upset, float] | None:
        """The alert on screen as ``(game, upset, seconds in)``, starting the next queued one when
        the last has had its ``seconds``; ``None`` when there is nothing to show."""
        now = self._monotonic()
        if self._active is not None and now - self._active[1] >= seconds:
            self._active = None
        by_id = {g.id: g for g in games}
        while self._active is None and self._pending:
            alert = self._pending.popleft()
            if now - alert.queued_at > STALE_AFTER or alert.game_id not in by_id:
                continue
            self._active = (alert, now)
        if self._active is None:
            return None
        alert, started = self._active
        game = by_id.get(alert.game_id)
        upset = upset_of(game, min_gap, teams) if game is not None else None
        if game is None or upset is None:
            # The lead changed back while it waited: nothing to announce any more.
            self._active = None
            return None
        return game, upset, now - started

    @property
    def waiting(self) -> int:
        return len(self._pending)

    def clear(self) -> None:
        self._teams = None
        self._state.clear()
        self._fired.clear()
        self._pending.clear()
        self._active = None
