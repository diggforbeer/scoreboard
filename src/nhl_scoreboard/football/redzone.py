"""The red zone alert: a team has driven inside the opponent's 20 (#redzone).

Followed teams have their own screens, and the favourite's game takes the whole panel. This is
for the board when it is showing an *idle* screen (the countdown, the final, the standings, the
week, the schedule, the clock): a live game somewhere moves into scoring range, which is the
moment worth leaving the idle screen for. It is the league-wide "RedZone" idea, in one short card.

It reads the scoreboard feed's ``situation`` (``isRedZone`` and who has the ball), so it costs no
extra requests, and it only *describes* the alert: whether the board may show it (the setting, a
128px panel, an idle screen up) is the mode's decision.

Rules:

* **A transition, not a state.** An alert is made when a game goes from out of the red zone to
  in it (or to the other team's red zone). A game that is already there when the board first
  sees it is only noted: nothing fires for what the board started with.
* **One per visit, spaced out.** A game that flickers in and out at the edge of the zone alerts
  once per ``COOLDOWN`` seconds. Several games entering together queue up and are shown one after
  another; one that has waited more than ``STALE_AFTER`` seconds is dropped, since by then it is
  old news.
* Only live games with a ball in play count: not the half, not a final.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .models import FbGame

log = logging.getLogger(__name__)

#: Seconds before the same game may alert again.
COOLDOWN = 120.0
#: Seconds a queued alert may wait before it is dropped.
STALE_AFTER = 30.0


@dataclass(frozen=True, slots=True)
class RedZoneAlert:
    game_id: int
    #: ESPN team id of the team with the ball.
    team_id: int
    queued_at: float


def attacking_team(game: FbGame) -> int | None:
    """The ESPN team id of the team in the red zone, or ``None`` if the game is not in one."""
    if not game.is_live or game.is_halftime or game.situation is None:
        return None
    situation = game.situation
    if not situation.is_red_zone or situation.possession_team_id is None:
        return None
    if situation.possession_team_id not in (game.away.espn_id, game.home.espn_id):
        return None
    return situation.possession_team_id


class RedZoneWatcher:
    def __init__(self, monotonic: Callable[[], float]) -> None:
        self._monotonic = monotonic
        #: game id -> the team id that was in the zone at the last look (``None``: nobody)
        self._zone: dict[int, int | None] = {}
        self._last_alert: dict[int, float] = {}
        self._pending: deque[RedZoneAlert] = deque()
        self._active: tuple[RedZoneAlert, float] | None = None

    def observe(self, games: Sequence[FbGame]) -> None:
        """Look at the slate as the feed last gave it. Cheap: call it as often as you like."""
        now = self._monotonic()
        seen = set()
        for game in games:
            seen.add(game.id)
            team = attacking_team(game)
            known = game.id in self._zone
            before = self._zone.get(game.id)
            self._zone[game.id] = team
            if team is None or not known or team == before:
                continue  # not in the zone, first sight (noted only), or still in the same one
            if now - self._last_alert.get(game.id, -COOLDOWN) < COOLDOWN:
                continue
            self._last_alert[game.id] = now
            self._pending.append(RedZoneAlert(game.id, team, now))
            log.info("[%s] red zone: team %s has driven inside the 20", game.id, team)
        for gone in [g for g in self._zone if g not in seen]:
            del self._zone[gone]
            self._last_alert.pop(gone, None)

    def current(self, games: Sequence[FbGame], seconds: float) -> tuple[FbGame, float] | None:
        """The alert on screen as ``(game, seconds in)``, starting the next queued one when the
        last has had its ``seconds``; ``None`` when there is nothing to show."""
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
        if game is None:
            self._active = None
            return None
        return game, now - started

    @property
    def waiting(self) -> int:
        return len(self._pending)

    def clear(self) -> None:
        self._zone.clear()
        self._last_alert.clear()
        self._pending.clear()
        self._active = None
