"""The college football idle screens' drawers (#579, screens #551-#556).

The idle screens a college board rotates through have their own scene kinds, ``cfb_*``, apart from
the NFL's ``fb_*`` (they show different data: polls, conferences, bowls). This is the registry the
app's draw dispatch reads: a screen's story adds ``@college_screen("cfb_ap")`` over its drawer and
registers its builder in ``football/idle_screens.py`` with ``@idle_screen("cfb_ap")``. Nothing is
drawn here yet; with none registered a college board has no idle rows and sits out the alternation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: scene kind -> ``draw(renderer, canvas, scene, now)``.
COLLEGE_DRAWERS: dict[str, Callable[[Any, Any, Any, Any], None]] = {}


def college_screen(
    kind: str,
) -> Callable[[Callable[[Any, Any, Any, Any], None]], Callable[[Any, Any, Any, Any], None]]:
    """Register ``draw`` as the drawer of the scene kind ``kind``."""

    def register(
        draw: Callable[[Any, Any, Any, Any], None],
    ) -> Callable[[Any, Any, Any, Any], None]:
        COLLEGE_DRAWERS[kind] = draw
        return draw

    return register
