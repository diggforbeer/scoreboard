"""April Fools' Day on a Predators board (#248): demoted to the Admirals.

An Easter egg for the owners' own boards, not a holiday overlay: it changes
what the screens *say*, so it is fenced in tightly --

* only when the favourite is NSH (every other board: nothing);
* only on April 1 (local time), all day;
* every screen, live games included (owner's call: the joke is the whole
  day, not a sideshow) -- only labels change, never scores, times or who
  scored, and goal detection, the horn and every fetch still key off the
  real NSH.

Deliberately not a Holiday Cheer checkbox and not gated on ``[holiday]``
(owner's call): a Preds board just gets it.

NSH becomes MIL, the Milwaukee Admirals -- the Preds' AHL affiliate, logo
in ``assets/logos/overrides`` -- everywhere, standings included: relabelled
in their real spot with their real record, never moved or given made-up
numbers (owner's call). "Demoted for a day" is the whole joke.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from .nhl.models import Game, GoalEvent, StandingsRow, Star

PRANK_TEAM = "NSH"
PRANK_AS = "MIL"


def active(favourite: str, local_now: datetime) -> bool:
    return favourite == PRANK_TEAM and (local_now.month, local_now.day) == (4, 1)


def rename(abbrev: str) -> str:
    return PRANK_AS if abbrev == PRANK_TEAM else abbrev


def swap_game(game: Game) -> Game:
    """The same game with NSH's side relabelled -- scores, time, opponent untouched."""
    away = dataclasses.replace(game.away, abbrev=rename(game.away.abbrev))
    home = dataclasses.replace(game.home, abbrev=rename(game.home.abbrev))
    return dataclasses.replace(game, away=away, home=home)


def swap_goal(event: GoalEvent) -> GoalEvent:
    return dataclasses.replace(event, team_abbrev=rename(event.team_abbrev))


def swap_star(star: Star) -> Star:
    return dataclasses.replace(star, team_abbrev=rename(star.team_abbrev))


def swap_rows(rows: tuple[StandingsRow, ...]) -> tuple[StandingsRow, ...]:
    """Relabel only -- positions and records untouched."""
    return tuple(dataclasses.replace(r, abbrev=rename(r.abbrev)) for r in rows)
