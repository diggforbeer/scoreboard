"""Seasonal holiday decorations drawn over the normal scenes (#236, #237).

An overlay, not a scene: ``ScoreboardApp.draw_scene()`` draws whatever scene
is up, then hands the canvas here before swapping it, so no individual scene
needs to know holidays exist. Each holiday turns itself on only inside its
own date window; the owner only ticks which ones they want (``[holiday]``
``themes``), never dates.

Everything draws through ``SetPixel`` (CLAUDE.md's one-code-path rule), and
every animated position is a pure function of the monotonic time passed in,
so a test can freeze a fly-by mid-crossing and snapshot it like any scene.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class Holiday:
    name: str
    #: Human-readable, for the admin page's checkbox list (#238).
    label: str
    is_active: Callable[[date], bool]


def _between(start: tuple[int, int], end: tuple[int, int]) -> Callable[[date], bool]:
    """Inclusive (month, day) window inside a single calendar year."""

    def check(day: date) -> bool:
        return start <= (day.month, day.day) <= end

    return check


#: Registry order is also precedence if two enabled windows ever overlap --
#: none do yet; #241 (New Year's) is where that gets decided properly.
HOLIDAYS: dict[str, Holiday] = {
    "halloween": Holiday("halloween", "Halloween", _between((10, 1), (10, 31))),
}
HOLIDAY_NAMES = tuple(HOLIDAYS)


def active_holiday(themes: Sequence[str], day: date) -> Holiday | None:
    """The first enabled holiday whose window contains ``day``, if any."""
    for name, holiday in HOLIDAYS.items():
        if name in themes and holiday.is_active(day):
            return holiday
    return None


#: The scoring moments and the Wi-Fi setup screens stay clean: a ghost
#: crossing "GOAL" or a QR code someone is trying to scan helps nobody.
NO_OVERLAY_SCENES = frozenset({"goal", "goal_detail", "three_stars", "ap_setup", "wifi_join"})
#: Idle scenes with empty corners. Not countdown/preview: their 32px logos
#: fill both edges, same reason the game scene gets no pumpkins.
PUMPKIN_SCENES = frozenset({"clock", "no_games"})

GHOST_BODY = (235, 235, 255)
EYE = (0, 0, 0)
# The face has to stand out from the shell even at the flicker's dim end:
# a first try at (255, 100, 0) shell / (255, 150, 0) dim glow read as a
# plain orange ball in a rendered preview.
PUMPKIN = (200, 60, 0)
STEM = (0, 150, 0)
GLOW_BRIGHT = (255, 235, 60)
GLOW_DIM = (255, 190, 0)

# '#' body, 'o' eye. Two frames that differ only in the hem, so the ghost
# wiggles as it floats. Faces left, the way it travels.
_GHOST_TOP = (
    "...####...",
    ".########.",
    "##########",
    "#oo##oo###",
    "#oo##oo###",
    "##########",
    "##########",
    "##########",
    "##########",
    "##########",
)
GHOST_FRAMES = (
    (*_GHOST_TOP, "##########", "#.##.##.##"),
    (*_GHOST_TOP, "##########", "##.##.##.#"),
)
GHOST_WIDTH = len(_GHOST_TOP[0])
GHOST_HEIGHT = len(GHOST_FRAMES[0])

# 'O' pumpkin, 'G' stem, 'Y' the carved face (lit from inside).
PUMPKIN_SPRITE = (
    ".....G.....",
    "....GG.....",
    "..OOOOOOO..",
    ".OOOOOOOOO.",
    "OOYOOOOOYOO",
    "OYYYOOOYYYO",
    "OOOOOYOOOOO",
    "OYYYYYYYYYO",
    ".OOYOYOYOO.",
    "..OOOOOOO..",
)
PUMPKIN_WIDTH = len(PUMPKIN_SPRITE[0])
PUMPKIN_HEIGHT = len(PUMPKIN_SPRITE)

#: Pixels per second. ~7s to cross 128px: slow enough to read as floating.
FLYBY_SPEED = 20.0
#: Bob amplitude (px) and period (s).
BOB_PIXELS = 1.5
BOB_PERIOD = 1.6
#: How often the hem alternates.
WIGGLE_SECONDS = 0.25


def draw_sprite(
    canvas: Any,
    rows: Sequence[str],
    palette: dict[str, RGB],
    x: int,
    y: int,
    width: int,
    height: int,
) -> None:
    """Blit ``rows`` at (x, y), clipped to the panel ('.' is transparent).

    Clipped here rather than left to the driver: the fly-by enters and
    leaves off-panel, and the test canvas records off-panel writes as bugs.
    """
    for dy, row in enumerate(rows):
        py = y + dy
        if not 0 <= py < height:
            continue
        for dx, ch in enumerate(row):
            px = x + dx
            if ch == "." or not 0 <= px < width:
                continue
            canvas.SetPixel(px, py, *palette[ch])


class HolidayOverlay:
    """Draws the active holiday's decorations and times its fly-bys.

    The only state is when the next fly-by is due and when the current one
    started. A fly-by only *starts* while a scene that allows it is up; one
    already crossing is simply not drawn over an excluded scene (a goal
    mid-pass), and its clock keeps running underneath.
    """

    def __init__(self, rng: random.Random | None = None) -> None:
        self.rng = rng or random.Random()
        self._next_flyby_at: float | None = None
        self._flyby_started: float | None = None

    def reset(self) -> None:
        self._next_flyby_at = None
        self._flyby_started = None

    def start_flyby(self, now: float) -> None:
        """Begin a fly-by right now -- for demo mode, which can't wait minutes."""
        self._flyby_started = now
        self._next_flyby_at = None

    def draw(
        self,
        canvas: Any,
        *,
        scene_kind: str,
        holiday: Holiday | None,
        now: float,
        width: int,
        height: int,
        min_gap_seconds: float,
        max_gap_seconds: float,
    ) -> bool:
        """Decorate ``canvas``; returns True while something is moving.

        The caller uses that to run the frame loop fast only for the few
        seconds a fly-by is on screen, and at its normal 2fps otherwise.
        """
        if holiday is None:
            # Out of season or unticked: forget any schedule, so turning it
            # back on starts a fresh random gap instead of firing at once.
            self.reset()
            return False
        if scene_kind in NO_OVERLAY_SCENES:
            return False
        if scene_kind in PUMPKIN_SCENES:
            self._draw_pumpkins(canvas, now, width, height)
        return self._draw_ghost(canvas, now, width, height, min_gap_seconds, max_gap_seconds)

    def _draw_pumpkins(self, canvas: Any, now: float, width: int, height: int) -> None:
        # Candle flicker: mostly bright, briefly dim, the two pumpkins out
        # of step so it doesn't read as one blinking light.
        y = (height - PUMPKIN_HEIGHT) // 2
        for x, phase in ((4, 0), (width - PUMPKIN_WIDTH - 4, 1)):
            glow = GLOW_DIM if (int(now * 2) + phase) % 3 == 0 else GLOW_BRIGHT
            palette = {"O": PUMPKIN, "G": STEM, "Y": glow}
            draw_sprite(canvas, PUMPKIN_SPRITE, palette, x, y, width, height)

    def _draw_ghost(
        self,
        canvas: Any,
        now: float,
        width: int,
        height: int,
        min_gap: float,
        max_gap: float,
    ) -> bool:
        if self._flyby_started is None:
            if self._next_flyby_at is None:
                self._next_flyby_at = now + self.rng.uniform(min_gap, max_gap)
            if now < self._next_flyby_at:
                return False
            self.start_flyby(now)
        elapsed = now - self._flyby_started
        x = width - round(elapsed * FLYBY_SPEED)
        if x + GHOST_WIDTH <= 0:
            self._flyby_started = None
            self._next_flyby_at = now + self.rng.uniform(min_gap, max_gap)
            return False
        bob = round(BOB_PIXELS * math.sin(2 * math.pi * elapsed / BOB_PERIOD))
        y = (height - GHOST_HEIGHT) // 2 + bob
        frame = GHOST_FRAMES[int(elapsed / WIGGLE_SECONDS) % len(GHOST_FRAMES)]
        draw_sprite(canvas, frame, {"#": GHOST_BODY, "o": EYE}, x, y, width, height)
        return True
