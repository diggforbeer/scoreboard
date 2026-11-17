"""The Easter egg tour (#509): ``scoreboard --eggs [name]``, a hidden way to see them.

The tree screen's quote, squirrel and fire, and the blowout flash, are all rare by design, and
the tree ones only exist in December, so waiting for one on a real board is not a plan. The flag
plays each in turn on the real panel, in a loop (Ctrl-C to stop), or just the one named.

Like the eggs themselves this is kept out of ``--help``, the README, ``screens.md`` and demo
mode (owner's call); ``tests/test_eggs.py`` pins that. April Fools is date-gated relabelling of
every screen, not a scene, so it is not part of the tour.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import blowout
from .app import Scene
from .demo import demo_steps
from .display.holiday import TREE_EGGS

#: The tour's items, in order.
NAMES = ("quote", "squirrel", "fire", "blowout")
#: A calm moment of the plain screen before and after each, so the start and end are seen.
PAUSE_SECONDS = 2.0
#: Where the tree screen's date is held, so its countdown shows whatever the real date is.
TOUR_DAY = (12, 13)


def seconds(name: str) -> float:
    """How long ``name`` plays."""
    if name == "blowout":
        return blowout.SECONDS
    return {kind: s for kind, _odds, s in TREE_EGGS}[name]


def final_game():
    """A finished game to hang the blowout flash on (its score is not drawn)."""
    steps = demo_steps("NSH", datetime(2026, 10, 14, tzinfo=UTC))
    return next(
        s.scene.game
        for s in steps
        if s.scene.kind == "game" and s.scene.game and s.scene.game.is_final
    )


def scene_for(name: str) -> Scene:
    return Scene("blowout", final_game()) if name == "blowout" else Scene("christmas_tree")
