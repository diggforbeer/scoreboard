"""The end of a quarter, of the half and of the game (#388): a card wiped across the field.

The field stays (the ball where the play left it) and a black card **wipes out from the middle**
with the headline in the large font: ``END Q1`` (amber), ``END Q2`` at the half, ``FINAL`` at the
end of the game (white). It is a pure function of the seconds since the stage began (3s)::

    0.00-0.35  the card wipes open across the field
    0.35-1.00  the headline holds

What comes **after** is the resting scene, not this stage: at the half the board holds the
``fb_halftime`` card until play resumes, and at the end of the game it holds the final
scoreboard (``fb_scores``, which a finished game rests on). The quarter number comes from the
text (``END QUARTER 2``), because the feed's own period number is not reliable on these plays.
End of regulation (``END QUARTER 4``) is drawn like any other quarter.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from ..football.geometry import FieldLayout, clamp_yard_line, possession_side
from ..football.models import PlayKind
from . import football_field as ff
from .fonts import text_width
from .football_plays import AMBER_CARD, DIM, WHITE, play_screen, quarter_clock, r_fit
from .football_run import eased

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

WIPE_END = 0.35
#: The card's size on a 128px panel; a narrower panel gets the same card inset by 4px.
CARD_WIDTH, CARD_TOP, CARD_BOTTOM = 88, 9, 29
_QUARTER = re.compile(r"END QUARTER (\d)", re.I)


def headline(scene: Scene) -> tuple[str, tuple[int, int, int]]:
    """``END Q1``, ``END Q2``, ``END OT`` or ``FINAL``, and its colour."""
    play = scene.fb_play
    if play.kind == PlayKind.END_GAME:
        return "FINAL", WHITE
    match = _QUARTER.search(play.text)
    quarter = int(match.group(1)) if match else (play.period or 1)
    return ("END OT" if quarter > 4 else f"END Q{quarter}"), AMBER_CARD


def draw_period_card(r: Renderer, canvas: Any, scene: Scene) -> None:
    game, play = scene.fb_game, scene.fb_play
    canvas.Clear()
    layout = FieldLayout.for_panel(r.width)
    pos = play.end or play.start
    side = possession_side(game, pos.team_id) if pos else None
    ff.draw_field(r, canvas, layout, game.home.abbrev, game.away.abbrev, side, logos=r.nfl_logos)
    if pos is not None and pos.yard_line is not None:
        ff.draw_ball(canvas, layout, clamp_yard_line(float(pos.yard_line)))

    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    full = min(CARD_WIDTH, r.width - 8)
    width = round(full * eased(share / WIPE_END))
    cx = r.width // 2
    if width > 0:
        for y in range(CARD_TOP, CARD_BOTTOM + 1):
            r.hline(canvas, cx - width // 2, cx - width // 2 + width - 1, y, (0, 0, 0))
    text, color = headline(scene)
    font = r.fonts.large if text_width(r.fonts.large, text) <= full - 4 else r.fonts.medium
    if width >= text_width(font, text) + 4:
        r.text_center(canvas, font, cx, 22, color, r_fit(text, full - 4, font))
    r.text(canvas, r.fonts.tiny, 1, 6, DIM, r_fit(quarter_clock(play), r.width // 2, r.fonts.tiny))


for _kind in (PlayKind.END_PERIOD, PlayKind.END_HALF, PlayKind.END_REGULATION, PlayKind.END_GAME):
    play_screen(_kind)(draw_period_card)
