"""April Fools' Day on a Predators board (#248): demoted to the Admirals.

An Easter egg for the owners' own boards, not a holiday overlay: it changes
what the screens *say*, so it is fenced in tightly --

* only when the favourite is NSH (every other board: nothing);
* only on April 1 (local time), all day;
* only on screens that aren't a game: never ``game``, ``goal``,
  ``goal_detail`` or ``three_stars``. April 1 is late in the season, often
  mid playoff race, and a renamed team on a real live game reads as a bug.

Deliberately not a Holiday Cheer checkbox and not gated on ``[holiday]``
(owner's call): a Preds board just gets it.

On those screens NSH becomes MIL, the Milwaukee Admirals -- the Preds' AHL
affiliate, logo in ``assets/logos/overrides`` -- and the standings drop
them to the bottom of the conference with a winless record. If they really
are last, they go to the top with a perfect one instead: either way the
screen never shows their true position, so nobody wonders if it's real.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from .nhl.models import Game, StandingsRow

PRANK_TEAM = "NSH"
PRANK_AS = "MIL"
#: Scenes that are safe to prank -- everything that isn't a game in progress
#: or a moment from one.
PRANK_SCENES = frozenset(
    {"countdown", "preview", "matchup", "standings", "leaders", "clock", "no_games"}
)


def active(favourite: str, local_now: datetime) -> bool:
    return favourite == PRANK_TEAM and (local_now.month, local_now.day) == (4, 1)


def rename(abbrev: str) -> str:
    return PRANK_AS if abbrev == PRANK_TEAM else abbrev


def swap_game(game: Game) -> Game:
    """The same game with NSH's side relabelled -- scores, time, opponent untouched."""
    away = dataclasses.replace(game.away, abbrev=rename(game.away.abbrev))
    home = dataclasses.replace(game.home, abbrev=rename(game.home.abbrev))
    return dataclasses.replace(game, away=away, home=home)


def prank_conference(ranked: list[StandingsRow]) -> list[StandingsRow]:
    """``ranked`` (one conference, best first) with NSH moved and relabelled.

    Normally to the bottom, winless with 0 points. If they're genuinely last
    already, to the top with a perfect record instead -- the joke still
    reads, and the screen still doesn't show the real position. Everyone
    else keeps their order and is renumbered around them.
    """
    index = next((i for i, r in enumerate(ranked) if r.abbrev == PRANK_TEAM), None)
    if index is None:
        return ranked
    real = ranked[index]
    others = ranked[:index] + ranked[index + 1 :]
    if index == len(ranked) - 1:
        fake = dataclasses.replace(
            real,
            abbrev=PRANK_AS,
            wins=real.games_played,
            losses=0,
            ot_losses=0,
            points=2 * real.games_played,
        )
        order = [fake, *others]
    else:
        fake = dataclasses.replace(
            real,
            abbrev=PRANK_AS,
            wins=0,
            losses=real.games_played,
            ot_losses=0,
            points=0,
        )
        order = [*others, fake]
    return [dataclasses.replace(r, conference_sequence=i) for i, r in enumerate(order, start=1)]
