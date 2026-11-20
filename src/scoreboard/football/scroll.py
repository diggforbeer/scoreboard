"""The scroll rule of a table taller than the panel, for the college idle screens (#551).

It is hockey's conference-table rule (``Renderer.standings_scroll_px`` and friends): rest at the
top, scroll evenly, rest at the bottom, never faster than ``MAX_PX_PER_SECOND``, so the slot's
seconds is a minimum that stretches when a readable scroll needs longer. Written here as pure
functions of the row count and the clock so the football mode (which times its own slots) can use
it without the renderer; a test holds the constants and results to the renderer's, so the two
cannot drift apart.
"""

from __future__ import annotations

PANEL_HEIGHT = 32
ROW_HEIGHT = 6
HOLD_SECONDS = 2.0
MAX_PX_PER_SECOND = 5.0


def scroll_range(rows: int) -> int:
    """Pixels the table overflows the panel by (0 when it all fits)."""
    return max(0, rows * ROW_HEIGHT + 1 - PANEL_HEIGHT)


def scroll_seconds(rows: int, minimum: float) -> float:
    """The slot length a table needs: ``minimum``, or longer if scrolling it at no more than
    ``MAX_PX_PER_SECOND`` takes more than that."""
    overflow = scroll_range(rows)
    if overflow <= 0:
        return minimum
    return max(minimum, 2 * HOLD_SECONDS + overflow / MAX_PX_PER_SECOND)


def scroll_px(rows: int, offset: float, seconds: float) -> int:
    """How far the table has scrolled ``offset`` seconds into a ``seconds`` slot."""
    overflow = scroll_range(rows)
    hold = min(HOLD_SECONDS, seconds / 4)
    travel = seconds - 2 * hold
    if overflow <= 0 or travel <= 0:
        return 0
    progress = min(1.0, max(0.0, (offset - hold) / travel))
    return round(progress * overflow)


def is_moving(rows: int, offset: float, seconds: float) -> bool:
    """Whether the table is between its two rests (the board runs its fast loop then)."""
    hold = min(HOLD_SECONDS, seconds / 4)
    return scroll_range(rows) > 0 and hold <= offset < seconds - hold
