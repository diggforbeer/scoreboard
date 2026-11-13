"""``fb_reversal`` (#396): a celebrated play the feed has since changed.

Amber, not green or red: this is a correction, neither good nor bad news yet. It preempts whatever
is on screen (the director skips the detail screen) for ``fb_reversal_seconds`` (5s), silent, and
the board then returns to ``fb_field`` with the score band already corrected. The detector
(``football/reversals.py``, #357) decides *that* it happened and finds the reason; this draws it::

    [logo]   TOUCHDOWN            the title from what was reversed, split over two lines
             OVERTURNED           (``TOUCHDOWN OVERTURNED``, ``FIELD GOAL NEGATED``,
             OFFENSIVE PASS ...   ``SCORE OVERTURNED``, ``TURNOVER OVERTURNED``)
             SCORE BACK TO NYG 0 WSH 0 · 1ST&10      the restored score, then the new down

The **reason** is the feed's own words, trimmed by the detector; a reason too long for the row
**scrolls** (held, then a character at a time, a pure function of the seconds since the stage
began). With no usable text the detector supplies ``PLAY CHANGED ON REVIEW``. The logo is the team
whose play was reversed. A single 64px panel has no logo or flag, and its last row **alternates**
between the reason and the score. A pure function of the seconds since the stage began.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..football.director import REVERSAL
from ..football.reversals import Reversal
from ..football.teams import is_team
from .fonts import text_width
from .football_plays import AMBER_CARD, DIM, WHITE, event_screen, r_fit
from .football_punt import draw_flag

if TYPE_CHECKING:
    from ..app import Scene
    from .renderer import Renderer

#: Seconds the reason is held before it starts to scroll, and per character after that.
HOLD, PER_CHAR = 1.0, 0.12
#: At 64px the last row shows the reason for this share of the stage, then the score.
NARROW_REASON_SHARE = 0.55
TEXT_LEFT, TEXT_RIGHT = 22, 106
LOGO_X, LOGO_SIZE = 10, 14


def split_title(title: str) -> tuple[str, str]:
    """``TOUCHDOWN OVERTURNED`` -> (``TOUCHDOWN``, ``OVERTURNED``); ``FIELD GOAL NEGATED`` ->
    (``FIELD GOAL``, ``NEGATED``): the last word goes on the second line."""
    head, _, tail = title.rpartition(" ")
    return (head, tail) if head else (title, "")


def reason_window(text: str, elapsed: float, chars: int) -> str:
    """The part of ``text`` a row of ``chars`` characters shows ``elapsed`` seconds in: all of it
    when it fits, else held for ``HOLD`` seconds and then moved on a character at a time until
    its end is showing."""
    if len(text) <= chars:
        return text
    steps = len(text) - chars
    start = 0 if elapsed <= HOLD else min(steps, 1 + int((elapsed - HOLD) / PER_CHAR))
    return text[start : start + chars]


def score_text(scene: Scene) -> str:
    """``SCORE BACK TO NYG 0  WSH 0``: the restored score, the home team first, as on the field."""
    event, game = scene.fb_event, scene.fb_game
    home, away = f"{game.home.abbrev} {event.home_score}", f"{game.away.abbrev} {event.away_score}"
    return f"SCORE BACK TO {home}  {away}"


def down_text(scene: Scene) -> str:
    """The new down and distance if the feed gives it, tight enough to share the score's row."""
    return (
        scene.fb_event.down_distance.upper().replace(" & ", "&")
        if scene.fb_event.down_distance
        else ""
    )


def last_row(score: str, down: str, width: int, font: Any) -> str:
    """The restored score, with the new down after it when there is room: ``SCORE BACK TO`` is
    shortened to ``BACK TO`` before the down is given up."""
    if not down:
        return score
    for text in (f"{score}  {down}", f"{score.removeprefix('SCORE ')}  {down}"):
        if text_width(font, text) <= width:
            return text
    return score


def _logo(r: Renderer, canvas: Any, team: str) -> None:
    logo = r.nfl_logos.get(team, 16) if r.nfl_logos is not None and is_team(team) else None
    if logo is not None:
        ox, oy = LOGO_X + 1 - logo.width // 2, 16 - logo.height // 2
        for dx, dy, (red, green, blue) in logo.pixels:
            canvas.SetPixel(ox + dx, oy + dy, red, green, blue)
        return
    r.text_center(canvas, r.fonts.small, LOGO_X + 1, 19, AMBER_CARD, r_fit(team, 20, r.fonts.small))


@event_screen(Reversal, REVERSAL)
def draw_reversal(r: Renderer, canvas: Any, scene: Scene) -> None:
    event = scene.fb_event
    canvas.Clear()
    share = 1.0 if scene.fb_seconds <= 0 else max(0.0, scene.fb_elapsed / scene.fb_seconds)
    wide = r.width >= 128
    first, second = split_title(event.title)
    reason = event.reason.upper()
    score = score_text(scene)
    down = down_text(scene)
    left, right = (TEXT_LEFT, TEXT_RIGHT) if wide else (1, r.width - 1)
    cx, width = (left + right) // 2, right - left

    if wide:
        _logo(r, canvas, event.original.team)
        draw_flag(canvas, r.width - 12, 21)
        r.text_center(canvas, r.fonts.small, cx, 8, AMBER_CARD, r_fit(first, width, r.fonts.small))
        r.text_center(
            canvas, r.fonts.small, cx, 16, AMBER_CARD, r_fit(second, width, r.fonts.small)
        )
        chars = width // text_width(r.fonts.tiny, "W")
        window = reason_window(reason, scene.fb_elapsed, chars)
        r.text_center(canvas, r.fonts.tiny, cx, 23, WHITE, window)
        # The last row sits under the logo, so it may use the panel's full width.
        full = r.width - 4
        last = last_row(score, down, full, r.fonts.tiny)
        r.text_center(canvas, r.fonts.tiny, r.width // 2, 31, DIM, r_fit(last, full, r.fonts.tiny))
        return
    r.text_center(canvas, r.fonts.tiny, cx, 7, AMBER_CARD, r_fit(first, width, r.fonts.tiny))
    r.text_center(canvas, r.fonts.tiny, cx, 14, AMBER_CARD, r_fit(second, width, r.fonts.tiny))
    if share < NARROW_REASON_SHARE:
        chars = width // text_width(r.fonts.tiny, "W")
        r.text_center(
            canvas, r.fonts.tiny, cx, 24, WHITE, reason_window(reason, scene.fb_elapsed, chars)
        )
    else:
        r.text_center(
            canvas,
            r.fonts.tiny,
            cx,
            24,
            DIM,
            r_fit(f"BACK TO {score.split('TO ')[-1]}", width, r.fonts.tiny),
        )
