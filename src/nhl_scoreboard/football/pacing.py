"""How long each kind of play's animation lasts (#380): pure, no drawing.

The default is ``Timings.play`` (3s). A screen that scales with the play (a run's length with its
yardage) registers a function here; the director asks :func:`animation_seconds`. Kept apart from
the drawing so the football package never imports the display code. **Every pacer lives in this
module**: the director asks for a play's length before any display module has been imported, so a
pacer registered next to its drawing function would silently not apply to the first play.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import Play, PlayKind

Pacer = Callable[[Play], float]
PLAY_SECONDS: dict[PlayKind, Pacer] = {}

#: The design's bounds for a run or pass animation ("2-4s").
MIN_SECONDS, MAX_SECONDS = 2.0, 4.0


def pacer(*kinds: PlayKind) -> Callable[[Pacer], Pacer]:
    """Register a length function for one or more play kinds."""

    def register(fn: Pacer) -> Pacer:
        for kind in kinds:
            PLAY_SECONDS[kind] = fn
        return fn

    return register


def animation_seconds(play: Play, default: float) -> float:
    """Seconds the play's animation lasts at normal speed."""
    fn = PLAY_SECONDS.get(play.kind)
    return default if fn is None else fn(play)


def yards_gained(play: Play) -> int:
    """Signed yards the play gained, in the offence's direction (a loss is negative): the feed's
    own ``statYardage``."""
    return play.stat_yardage


@pacer(
    PlayKind.RUSH, PlayKind.RUSHING_TOUCHDOWN, PlayKind.PASS_COMPLETE, PlayKind.PASSING_TOUCHDOWN
)
def run_seconds(play: Play) -> float:
    """A run or a completed pass scales with its yardage: 2s when short, up to 4s when long."""
    return max(MIN_SECONDS, min(MAX_SECONDS, 2.0 + abs(yards_gained(play)) / 10))


#: A kickoff with a return is 5s; a touchback or an onside kick is 4s (``football_screen.md``).
KICKOFF_SECONDS, SHORT_KICKOFF_SECONDS = 5.0, 4.0


@pacer(PlayKind.KICKOFF)
def kickoff_seconds(play: Play) -> float:
    """5s for a return; 4s for a touchback or an onside kick."""
    short = play.info.touchback or play.info.onside
    return SHORT_KICKOFF_SECONDS if short else KICKOFF_SECONDS
