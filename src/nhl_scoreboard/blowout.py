"""A rare Easter egg for Predators boards (#326): the blowout loss.

When the favourite loses by a lot, a quick flash of a toilet and the word
BLOWOUT, then the held final as usual. Fenced in tightly, same family as
``april_fools.py`` (#248):

* only when the favourite is NSH (every other board: nothing);
* only a regulation loss by ``MARGIN`` or more goals -- last season (2025-26)
  that was twice in 82 games; by 4+ it was four times, by 3+ nineteen;
* only a game we watched end -- one already final at startup is a first
  sighting and records nothing, same as goal detection and three stars;
* decoration only: scores, goal detection, the horn and every fetch are
  untouched, and it follows the broadcast delay like everything else.

Deliberately kept out of README.md, ``screens.md``, demo mode and the
rendered snapshots (owner's call): the joke is finding it. ``test_blowout.py``
pins that, so a later pass over the screen guide can't quietly add it.
The scene kind is ``blowout`` and is not in ``Scene``'s docstring for the
same reason.
"""

from __future__ import annotations

from typing import Any

from .nhl.models import Game

FAVOURITE = "NSH"
#: Goals the favourite must lose by.
MARGIN = 5
#: How long the flash holds before the three stars / held final take over.
SECONDS = 6.0

_COLORS = {"W": (225, 228, 235), "G": (120, 126, 140), "B": (40, 120, 255), "Y": (255, 190, 0)}
_TOILET = (
    ".YY.............",
    ".WWWWWWWWWWWWW..",
    ".WWWWWWWWWWWWG..",
    ".WWWWWWWWWWWWG..",
    ".WWWWWWWWWWWWG..",
    ".WWWWWWWWWWWWG..",
    ".WGGGGGGGGGGGG..",
    "..WWWWWWWWWWG...",
    "WWWWWWWWWWWWWWWW",
    "WGGGGGGGGGGGGGGG",
    ".WBBBBBBBBBBBBW.",
    ".WBBBBBBBBBBBGW.",
    "..WBBBBBBBBBGW..",
    "..WWBBBBBBBWGW..",
    "...WWWWWWWWWG...",
    "....WWWWWWWG....",
    ".....WWWWWG.....",
    ".....WWWWWG.....",
    ".....WWWWWG.....",
    "....WWWWWWWG....",
    "...WWWWWWWWWG...",
    "..WWWWWWWWWWWG..",
    "..GGGGGGGGGGGG..",
)
WIDTH = len(_TOILET[0])
HEIGHT = len(_TOILET)


def is_blowout_loss(game: Game, favourite: str) -> bool:
    if favourite != FAVOURITE or not game.is_final or not game.involves(favourite):
        return False
    if game.period_type != "REG":
        return False
    mine, theirs = (
        (game.home, game.away) if game.home.abbrev == favourite else (game.away, game.home)
    )
    return theirs.score - mine.score >= MARGIN


def draw_toilet(canvas: Any, x0: int, y0: int, *, flip: bool = False) -> None:
    for y, row in enumerate(_TOILET):
        for x, ch in enumerate(row[::-1] if flip else row):
            color = _COLORS.get(ch)
            if color is not None:
                canvas.SetPixel(x0 + x, y0 + y, *color)
