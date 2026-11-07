"""The favourite's goal screen: an arena goal light and animated GOAL text.

Modelled on the Predators' goal pennant, where a caged lamp flashes above the
word GOAL. The whole thing is a pure function of ``age`` (seconds since the
goal), so tests, the demo and the live view can draw any frame on demand and
the clock alone drives the animation.

Timeline (``BUILD_SECONDS`` long, then it loops its pulse and shimmer until the
scene's ``goal_flash_seconds`` runs out):

* 0.0-1.3s  white flash, one big lamp in the middle strobing, beams sweeping
  the whole panel.
* 1.3-2.1s  the beams fade; the lamp slides left and shrinks.
* 1.6s on   GOAL's letters drop in one at a time (the font scaled 2x).
* 2.0s on   a lamp at each edge, pulsing in alternation.
* 2.6s on   the team name fades in along the bottom, secondary to the lamps.
* 3.0s on   a white shimmer sweeps across the letters every ``SHIMMER_PERIOD``.

Everything is drawn through ``SetPixel`` into an in-memory buffer first (the
beams and glow are additive) and clipped to the panel here, so nothing is ever
recorded off-panel.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from .ascii import AsciiCanvas
from .teams import team_color, team_name

if TYPE_CHECKING:
    from .renderer import Renderer

RGB = tuple[int, int, int]

#: By this age everything has landed; what's left (pulse, shimmer) loops.
BUILD_SECONDS = 3.0
FLASH_SECONDS = 0.12
BEAM_SECONDS = 1.7
BIG_LAMP_SECONDS = 2.1
SLIDE_START = 1.3
SLIDE_SECONDS = 0.7
LETTERS_START = 1.6
LETTER_STAGGER = 0.14
LETTER_DROP_SECONDS = 0.28
SIDE_LAMPS_START = 2.0
NAME_START = 2.6
NAME_FADE_SECONDS = 0.4
SHIMMER_START = 3.0
SHIMMER_PERIOD = 1.5
SHIMMER_SWEEP_SECONDS = 0.55

#: Pixels each font pixel becomes in GOAL.
TEXT_SCALE = 2
#: Panel width from which the two edge lamps fit either side of the letters.
SIDE_LAMPS_MIN_WIDTH = 128
SIDE_LAMP_INSET = 16
GOAL_TOP = 3
NAME_BASELINE_FROM_BOTTOM = 1

WHITE: RGB = (255, 255, 255)


def draw(r: Renderer, canvas: Any, scorer: str, age: float) -> None:
    """Draw the goal light for the scoring team ``scorer`` at ``age`` seconds."""
    canvas.Clear()
    width, height = r.width, r.height
    colour = team_color(scorer)
    buf = _Buffer(width, height)
    cx = width // 2
    wide = width >= SIDE_LAMPS_MIN_WIDTH

    if age < BEAM_SECONDS + 0.4:
        fade = max(0.0, min(1.0, (BEAM_SECONDS - age) / 0.4))
        _beams(buf, cx, height // 2, colour, age * 5.5, 0.85 * fade)
    if age < FLASH_SECONDS:
        buf.wash(WHITE, 0.35 * (1 - age / FLASH_SECONDS))

    if age < BIG_LAMP_SECONDS:
        slide = _ease((age - SLIDE_START) / SLIDE_SECONDS)
        if age < SLIDE_START:
            glow = 0.5 + 0.5 * math.sin(age * 22)
        else:
            glow = max(0.0, 1 - (age - SLIDE_START) / (BIG_LAMP_SECONDS - SLIDE_START))
        if wide or age < SLIDE_START:
            lamp_x = cx - round((cx - SIDE_LAMP_INSET) * slide) if wide else cx
            _lamp(buf, lamp_x, 2, 17, 28 - round(8 * slide), colour, max(0.2, glow))

    if age >= LETTERS_START:
        pulse = 0.5 + 0.5 * math.sin((age - SLIDE_START - 0.2) * 9)
        if wide and age >= SIDE_LAMPS_START:
            _lamp(buf, SIDE_LAMP_INSET, 4, 13, 20, colour, pulse)
            _lamp(buf, width - 1 - SIDE_LAMP_INSET, 4, 13, 20, colour, 1 - pulse)
        _letters(r, buf, colour, age)
        if age >= NAME_START:
            _name(r, buf, scorer, colour, age)

    buf.flush(canvas)


# -- text --------------------------------------------------------------------


def _glyph(r: Renderer, ch: str) -> tuple[frozenset[tuple[int, int]], int]:
    """A letter's lit pixels (origin at its top-left) and its advance, cached."""
    cache = r.goal_glyphs
    if ch not in cache:
        probe = AsciiCanvas(40, 32)
        advance = r.text(probe, r.fonts.large, 0, 20, WHITE, ch)
        x0 = min(x for x, _ in probe.pixels)
        y0 = min(y for _, y in probe.pixels)
        cache[ch] = (frozenset((x - x0, y - y0) for x, y in probe.pixels), advance)
    return cache[ch]


def _letters(r: Renderer, buf: _Buffer, colour: RGB, age: float) -> None:
    glyphs = [_glyph(r, ch) for ch in "GOAL"]
    cell = max(advance for _, advance in glyphs) * TEXT_SCALE
    left = r.width // 2 - (cell * len(glyphs)) // 2
    for i, (pixels, advance) in enumerate(glyphs):
        start = LETTERS_START + LETTER_STAGGER * i
        if age < start:
            continue
        drop = _ease((age - start) / LETTER_DROP_SECONDS)
        top = GOAL_TOP - round(26 * (1 - drop))
        landing = max(0.0, 1 - (age - start) / 0.25)
        glyph_left = left + i * cell + (cell - advance * TEXT_SCALE) // 2
        for px, py in pixels:
            sweep = _shimmer(age, glyph_left + px * TEXT_SCALE)
            lift = min(1.0, landing * 0.9 + sweep * 0.75)
            lit = _towards_white(colour, lift)
            for dx in range(TEXT_SCALE):
                for dy in range(TEXT_SCALE):
                    buf.set(glyph_left + px * TEXT_SCALE + dx, top + py * TEXT_SCALE + dy, lit)


def _shimmer(age: float, x: int) -> float:
    """How far a white band, sweeping left to right, has lit column ``x``."""
    if age < SHIMMER_START:
        return 0.0
    phase = (age - SHIMMER_START) % SHIMMER_PERIOD
    if phase >= SHIMMER_SWEEP_SECONDS:
        return 0.0
    front = -10 + phase / SHIMMER_SWEEP_SECONDS * 80
    return max(0.0, 1 - abs(x - 28 - front) / 9)


def _name(r: Renderer, buf: _Buffer, scorer: str, colour: RGB, age: float) -> None:
    name = team_name(scorer)
    if r.text(AsciiCanvas(1, 1), r.fonts.small, 0, 0, WHITE, name) > r.width:
        name = scorer
    fade = _ease((age - NAME_START) / NAME_FADE_SECONDS)
    probe = AsciiCanvas(r.width, r.height)
    baseline = r.height - NAME_BASELINE_FROM_BOTTOM
    shade = _scaled(colour, 0.35 + 0.65 * fade)
    r.text_center(probe, r.fonts.small, r.width // 2, baseline, shade, name)
    for (x, y), rgb in probe.pixels.items():
        buf.set(x, y, rgb)


# -- lamp and beams ----------------------------------------------------------


def _lamp(buf: _Buffer, cx: int, top: int, w: int, h: int, colour: RGB, glow: float) -> None:
    """A caged beacon: cap, glass dome with cage bars, and a bulb lit by ``glow``."""
    half = w / 2
    body0, body1 = top + 3, top + h - 1
    middle = top + h // 2
    reach = int(w * 1.3)
    for dy in range(-reach, reach + 1):  # glow first, so the lamp draws over it
        for dx in range(-reach, reach + 1):
            d = math.hypot(dx, dy)
            if d < reach:
                buf.add(cx + dx, middle + dy, colour, 0.35 * glow * (1 - d / reach) ** 2)
    for y in range(top, top + 3):
        for x in range(int(cx - half * 0.55), int(cx + half * 0.55) + 1):
            buf.set(x, y, _scaled(colour, 0.35))
    cage = _scaled(colour, 0.55)
    for y in range(body0, body1 + 1):
        t = (y - body0) / max(1, body1 - body0)
        reach_x = half * (1 if t < 0.55 else math.sqrt(max(0.0, 1 - ((t - 0.55) / 0.45) ** 2)))
        for x in range(int(cx - reach_x), int(cx + reach_x) + 1):
            dx = abs(x - cx)
            frame = dx >= reach_x - 1 or (y - body0) % 5 == 2 or dx < 1
            if (dx / (half * 0.62)) ** 2 + ((t - 0.45) / 0.42) ** 2 <= 1:
                lit = _scaled(colour, 0.25 + 0.75 * glow)
                if (dx / (half * 0.3)) ** 2 + ((t - 0.45) / 0.25) ** 2 <= 1:
                    lit = _towards_white(lit, glow * 0.8)
                buf.set(x, y, _scaled(colour, 0.5 + 0.3 * glow) if frame else lit)
            elif frame:
                buf.set(x, y, cage)


def _beams(buf: _Buffer, cx: int, cy: int, colour: RGB, angle: float, strength: float) -> None:
    """Two opposite beams, rotating about ``(cx, cy)`` and fading with distance."""
    if strength <= 0:
        return
    for y in range(buf.height):
        for x in range(buf.width):
            dx, dy = x - cx, (y - cy) * 1.6  # rows are taller than the panel's pitch looks
            d = math.hypot(dx, dy)
            if d < 3:
                continue
            a = math.atan2(dy, dx)
            for offset in (0.0, math.pi):
                off = abs((a - angle - offset + math.pi) % (2 * math.pi) - math.pi)
                if off < 0.22:
                    buf.add(x, y, colour, strength * (1 - off / 0.22) * max(0.25, 1 - d / 110))


# -- helpers -----------------------------------------------------------------


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def _scaled(colour: RGB, k: float) -> RGB:
    return (
        min(255, max(0, int(colour[0] * k))),
        min(255, max(0, int(colour[1] * k))),
        min(255, max(0, int(colour[2] * k))),
    )


def _towards_white(colour: RGB, k: float) -> RGB:
    return (
        int(colour[0] + (255 - colour[0]) * k),
        int(colour[1] + (255 - colour[1]) * k),
        int(colour[2] + (255 - colour[2]) * k),
    )


class _Buffer:
    """A panel-sized frame under construction: additive light, clipped to the panel."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels: dict[tuple[int, int], RGB] = {}

    def set(self, x: int, y: int, rgb: RGB) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[(x, y)] = rgb

    def add(self, x: int, y: int, rgb: RGB, k: float) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            r, g, b = self.pixels.get((x, y), (0, 0, 0))
            self.pixels[(x, y)] = (
                min(255, r + int(rgb[0] * k)),
                min(255, g + int(rgb[1] * k)),
                min(255, b + int(rgb[2] * k)),
            )

    def wash(self, rgb: RGB, k: float) -> None:
        for y in range(self.height):
            for x in range(self.width):
                self.add(x, y, rgb, k)

    def flush(self, canvas: Any) -> None:
        for (x, y), (r, g, b) in self.pixels.items():
            if r or g or b:
                canvas.SetPixel(x, y, r, g, b)
