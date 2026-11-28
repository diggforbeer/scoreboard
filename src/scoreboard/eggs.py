"""The Easter egg tour (#509): ``scoreboard --eggs [name]``, a hidden way to see them.

The tree screen's quote, squirrel and fire, the Thanksgiving turkey's run (and the roast that
replaces him on the day itself), the blowout flash and April Fools' Admirals are all rare by
design: the tree ones only exist in December, the turkey in November, April Fools on one day, and
the blowout needs a five-goal loss. Waiting for one on a
real board is not a plan, so the flag plays each in turn on the real panel, in a loop (Ctrl-C to
stop), or just the one named.

Like the eggs themselves this is kept out of ``--help``, the README, ``screens.md`` and demo
mode (owner's call); ``tests/test_eggs.py`` pins that. The holiday fly-bys are documented
features, not hidden, and are already in ``--demo``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import NamedTuple

from . import blowout
from .demo import demo_steps
from .display.holiday import TREE_EGGS, TURKEY_RUN_SECONDS, nth_weekday
from .scene import Scene

#: The tour's items, in order.
NAMES = ("quote", "squirrel", "fire", "blowout", "april_fools", "turkey", "roast")
#: A calm moment of the plain screen before and after each, so the start and end are seen.
PAUSE_SECONDS = 2.0
#: Where the tree screen's date is held, so its countdown shows whatever the real date is.
TOUR_DAY = (12, 13)
#: The turkey's screen only exists in November: the tour holds the date here for it.
THANKSGIVING_DAY = (11, 19)


def roast_day() -> tuple[int, int]:
    """Thanksgiving Day proper, for the roast that replaces the turkey on it (#626): the 4th
    Thursday of this year's November, whatever the real date is."""
    day = nth_weekday(datetime.now(UTC).year, 11, 3, 4)
    return day.month, day.day


#: How long each April Fools screen is shown relabelled.
PRANK_SECONDS = 4.0


class Phase(NamedTuple):
    """One stretch of the tour: a scene, for a time, optionally with an egg playing."""

    scene: Scene
    seconds: float
    #: A tree egg (quote, squirrel, fire) to play from the phase's start.
    egg: str | None = None
    #: Draw as April Fools' Day on a Preds board (NSH shown as MIL).
    prank: bool = False
    #: (month, day) to hold the clock at for this phase; default ``TOUR_DAY``.
    day: tuple[int, int] | None = None


def _demo_scene(name: str) -> Scene:
    steps = demo_steps("NSH", datetime(2026, 10, 14, tzinfo=UTC))
    return next(s.scene for s in steps if s.name == name)


def seconds(name: str) -> float:
    """How long the egg itself plays (the calm moments around it not counted)."""
    return sum(
        p.seconds
        for p in plan(name)
        if p.egg or p.prank or p.scene.kind == "blowout" or name == "roast"
    )


def plan(name: str) -> list[Phase]:
    """The tour of ``name``: a calm moment, the egg, a calm moment."""
    tree = Scene("christmas_tree")
    if name in {kind for kind, _odds, _s in TREE_EGGS}:
        length = {kind: s for kind, _odds, s in TREE_EGGS}[name]
        return [
            Phase(tree, PAUSE_SECONDS),
            Phase(tree, length, egg=name),
            Phase(tree, PAUSE_SECONDS),
        ]
    if name == "turkey":
        screen = Scene("thanksgiving")
        return [
            Phase(screen, PAUSE_SECONDS, day=THANKSGIVING_DAY),
            Phase(screen, TURKEY_RUN_SECONDS, egg="turkey", day=THANKSGIVING_DAY),
            Phase(screen, PAUSE_SECONDS, day=THANKSGIVING_DAY),
        ]
    if name == "roast":
        screen = Scene("thanksgiving")
        return [Phase(screen, PAUSE_SECONDS * 3, day=roast_day())]
    if name == "blowout":
        final = next(
            s.scene.game
            for s in demo_steps("NSH", datetime(2026, 10, 14, tzinfo=UTC))
            if s.scene.kind == "game" and s.scene.game and s.scene.game.is_final
        )
        return [
            Phase(tree, PAUSE_SECONDS),
            Phase(Scene("blowout", final), blowout.SECONDS),
            Phase(tree, PAUSE_SECONDS),
        ]
    if name == "april_fools":
        game, table = _demo_scene("game_live"), _demo_scene("standings")
        return [
            Phase(game, PAUSE_SECONDS + 1),
            Phase(game, PRANK_SECONDS, prank=True),
            Phase(table, PRANK_SECONDS, prank=True),
            Phase(game, PAUSE_SECONDS),
        ]
    raise KeyError(name)
