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
