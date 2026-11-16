"""When each part of the play-text layout is on screen (#379). Pure: no fonts, no canvas.

After a play's animation the board shows the field and the feed's own sentence. A long sentence
does not fit, so it **scrolls a line at a time**: it holds for ``HOLD`` seconds, then moves up one
line every ``STEP`` seconds and rests on the last lines. On a single 64px panel the field and the
text cannot share the screen, so the layout **alternates** between them: the field for
``FIELD_SECONDS``, then the text (scrolling the same way), then the field again, and so on.

Everything is a function of the seconds since the stage began, so the broadcast delay, the
catch-up speed and the live view all stay correct, and the renderer needs no state.
"""

from __future__ import annotations

import math

#: Seconds the first lines are held before the text starts to scroll, and per line after that.
HOLD = 2.0
STEP = 1.0
#: How long the last lines are held before the layout moves on (or, at 64px, back to the field).
REST = 1.5
#: On a 64px panel: how long the field is shown before the text.
FIELD_SECONDS = 2.0
#: Characters per line in the tiny font, for estimating how long a sentence takes to read.
CHARS_PER_LINE = 14
#: Lines the wide layout shows at once.
WIDE_LINES = 3
#: However long a sentence is, the layout moves on after this: the next play is ~40s away, but a
#: board that is behind must not sit on one play's text.
MAX_SECONDS = 15.0


def estimate_lines(text: str) -> int:
    """About how many lines ``text`` wraps to (the renderer measures exactly; this only sizes the
    stage). Long words wrap early, so it errs a little high."""
    return max(1, math.ceil(len(text) * 1.1 / CHARS_PER_LINE))


def playtext_seconds(text: str, base: float) -> float:
    """How long the play-text stage lasts: ``base`` (5s, the "at least" of the design), or longer
    when the sentence needs scrolling, including the field's turn on a 64px panel."""
    needed = FIELD_SECONDS + HOLD + max(0, estimate_lines(text) - WIDE_LINES) * STEP + REST
    return min(MAX_SECONDS, max(base, needed))


def first_line(elapsed: float, lines: int, visible: int) -> int:
    """The index of the first line shown ``elapsed`` seconds into the text: 0 while it is held,
    then one more every ``STEP``, stopping at the last full window."""
    last = max(0, lines - visible)
    if elapsed <= HOLD:
        return 0
    return min(last, 1 + int((elapsed - HOLD) / STEP))


def text_seconds(lines: int, visible: int) -> float:
    """How long the text is up in one go: held, scrolled to the end, and rested on."""
    return HOLD + max(0, lines - visible) * STEP + REST


def narrow_view(elapsed: float, lines: int, visible: int) -> tuple[str, float]:
    """For a 64px panel: ``("field", t)`` or ``("text", t)`` and the seconds into that view.

    One cycle is the field, then the text; it repeats until the stage ends.
    """
    text_for = text_seconds(lines, visible)
    cycle = FIELD_SECONDS + text_for
    t = elapsed % cycle
    if t < FIELD_SECONDS:
        return "field", t
    return "text", t - FIELD_SECONDS
