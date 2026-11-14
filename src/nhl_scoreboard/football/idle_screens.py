"""The registry of NFL idle screens (#422).

Each idle screen story (#423-#429) adds one entry here with ``@idle_screen("fb_...")``: a
``should_show(ctx)`` predicate saying whether the screen has anything to show right now. The
selection in ``NflMode.scene`` only ever picks registered screens whose predicate is true, so a
screen without data (a feed that failed, a team with no next game) drops out of the rotation
instead of showing an empty card. Until the screens exist the registry is empty and the board
behaves as before.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from .idle_views import (
    ByeView,
    FinalView,
    PreviewView,
    StandingsView,
    build_bye,
    build_final,
    build_preview,
    build_standings,
)

if TYPE_CHECKING:
    from ..config import FootballConfig
    from .idle import IdleSnapshot
    from .models import FbGame


@dataclass(frozen=True, slots=True)
class IdleContext:
    """What a screen's ``should_show`` reads: the clock, the slate, the cached idle data, config."""

    now: float  # monotonic seconds
    utc: datetime
    games: Sequence[FbGame]
    idle: IdleSnapshot
    config: FootballConfig


#: screen name -> ``should_show``. ``clock`` is not here: it is drawn by the app itself.
IDLE_SCREENS: dict[str, Callable[[IdleContext], bool]] = {}


def idle_screen(
    name: str,
) -> Callable[[Callable[[IdleContext], bool]], Callable[[IdleContext], bool]]:
    """Register ``should_show`` as the idle screen ``name``."""

    def register(should_show: Callable[[IdleContext], bool]) -> Callable[[IdleContext], bool]:
        IDLE_SCREENS[name] = should_show
        return should_show

    return register


#: Every idle screen kind the board will have once #423-#429 are built; a test keeps this, the
#: registry and the renderer in step.
FB_IDLE_KINDS = (
    "fb_countdown",
    "fb_preview",
    "fb_bye",
    "fb_final",
    "fb_standings",
    "fb_week",
    "fb_schedule",
)


def _favourite_game(ctx: IdleContext) -> FbGame | None:
    favourite = ctx.config.favourite_team
    return next((g for g in ctx.games if favourite and g.involves(favourite)), None)


@idle_screen("fb_countdown")
def _countdown(ctx: IdleContext) -> FbGame | None:
    """The favourite's game, if it has not started and has a kickoff time to count to.
    (The window itself is ``NflMode._in_countdown``: this screen is not in the rotation.)"""
    game = _favourite_game(ctx)
    return game if game is not None and game.is_pregame and game.start_utc is not None else None


@idle_screen("fb_preview")
def _preview(ctx: IdleContext) -> PreviewView | None:
    return build_preview(ctx)


@idle_screen("fb_bye")
def _bye(ctx: IdleContext) -> ByeView | None:
    return build_bye(ctx)


@idle_screen("fb_final")
def _final(ctx: IdleContext) -> FinalView | None:
    return build_final(ctx)


@idle_screen("fb_standings")
def _standings(ctx: IdleContext) -> StandingsView | None:
    return build_standings(ctx)
