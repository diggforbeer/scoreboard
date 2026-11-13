"""The NFL half of the sport switch (#346): a stub until later stories add data.

The app builds a fresh ``NflMode`` each time the sport changes to ``nfl`` and
drops it on the way back, so nothing a previous visit held can leak into the
next one. For now its only job is to show ``connecting`` until its first
``refresh()`` and a placeholder after that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..app import Scene


class NflMode:
    def __init__(self) -> None:
        #: Set by the first refresh; until then the board says connecting.
        self.ready = False
        self.refreshes = 0

    def refresh(self) -> None:
        """One poll. The stub has no feed: it only records that it ran."""
        self.refreshes += 1
        self.ready = True

    def scene(self) -> Scene:
        from ..app import Scene

        return Scene("fb_stub" if self.ready else "fb_connecting")
