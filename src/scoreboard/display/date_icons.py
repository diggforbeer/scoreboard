"""The pixel icons and the day-of sparkle for the ``dates`` screen (#524).

Five small sprites (``.`` is transparent) drawn through ``SetPixel`` like every other decoration.
On the day itself the icon bobs and confetti twinkles; both are a pure function of ``tick``
(half-seconds), so the screen runs at the normal 2fps loop and never holds the fast one.
"""

from __future__ import annotations

from typing import Any

from .holiday import draw_sprite

RGB = tuple[int, int, int]

#: Every icon is drawn centred in a box this size, so the text column starts at the same place.
ICON_BOX = (17, 18)

_SPRITES: dict[str, tuple[tuple[str, ...], dict[str, RGB]]] = {
    "cake": (
        (
            ".......Y.......",
            "......YOY......",
            "......YOY......",
            ".......B.......",
            ".......B.......",
            "..PPPPPPPPPPP..",
            "..PWPWPWPWPWP..",
            "..CCCCCCCCCCC..",
            "..CCCCCCCCCCC..",
            ".RRRRRRRRRRRRR.",
            ".RWRWRWRWRWRWR.",
            ".CCCCCCCCCCCCC.",
            ".CCCCCCCCCCCCC.",
            ".CCCCCCCCCCCCC.",
            "DDDDDDDDDDDDDDD",
        ),
        {
            "Y": (255, 210, 0),
            "O": (255, 120, 0),
            "B": (80, 160, 255),
            "P": (255, 105, 180),
            "W": (255, 240, 240),
            "C": (255, 215, 160),
            "R": (200, 40, 110),
            "D": (150, 90, 40),
        },
    ),
    "balloon": (
        (
            "...RRRRR...",
            "..RRWRRRR..",
            ".RRWRRRRRR.",
            ".RRWRRRRRR.",
            ".RRRRRRRRR.",
            ".RRRRRRRRR.",
            ".RRRRRRRRR.",
            "..RRRRRRR..",
            "...RRRRR...",
            "....RRR....",
            ".....K.....",
            ".....s.....",
            "....s......",
            ".....s.....",
            "......s....",
            ".....s.....",
            "....s......",
            ".....s.....",
        ),
        {"R": (230, 30, 50), "W": (255, 190, 190), "K": (150, 15, 30), "s": (170, 170, 170)},
    ),
    "heart": (
        (
            "..RRR...RRR..",
            ".RRRRR.RRRRR.",
            ".RRWRRRRRRRR.",
            "RRRRRRRRRRRRR",
            "RRRRRRRRRRRRR",
            ".RRRRRRRRRRR.",
            "..RRRRRRRRR..",
            "...RRRRRRR...",
            "....RRRRR....",
            ".....RRR.....",
            "......R......",
        ),
        {"R": (235, 30, 80), "W": (255, 190, 205)},
    ),
    "gift": (
        (
            "...YY...YY...",
            "..Y..Y.Y..Y..",
            "...YYYYYYY...",
            "GGGGGYYYGGGGG",
            "GGGGGYYYGGGGG",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
            ".ggggYYYgggg.",
        ),
        {"Y": (255, 210, 0), "G": (0, 185, 80), "g": (0, 130, 55)},
    ),
    "star": (
        (
            "......Y......",
            "......Y......",
            ".....YYY.....",
            ".....YYY.....",
            "YYYYYYYYYYYYY",
            ".YYYYYYYYYYY.",
            "..YYYYYYYYY..",
            "...YYYYYYY...",
            "...YYYYYYY...",
            "..YYYY.YYYY..",
            "..YYY...YYY..",
            ".YYY.....YYY.",
            ".YY.......YY.",
        ),
        {"Y": (255, 205, 0)},
    ),
}

#: The label's colour under each icon.
ICON_COLOURS: dict[str, RGB] = {
    "cake": (255, 105, 180),
    "balloon": (255, 70, 90),
    "heart": (255, 70, 110),
    "gift": (0, 210, 100),
    "star": (255, 205, 0),
}

#: The day-of confetti and the big greeting cycle through these.
CONFETTI: tuple[RGB, ...] = (
    (255, 60, 60),
    (255, 200, 0),
    (60, 220, 90),
    (70, 150, 255),
    (255, 90, 200),
    (255, 255, 255),
)


def icon_size(icon: str) -> tuple[int, int]:
    rows, _ = _SPRITES[icon]
    return len(rows[0]), len(rows)


def draw_icon(
    canvas: Any,
    icon: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    bob: int = 0,
) -> None:
    """The icon centred in the ``ICON_BOX`` whose top-left is (x, y), ``bob`` pixels higher."""
    rows, palette = _SPRITES[icon]
    w, h = len(rows[0]), len(rows)
    left = x + (ICON_BOX[0] - w) // 2
    top = y + (ICON_BOX[1] - h) // 2 - bob
    draw_sprite(canvas, rows, palette, left, top, width, height)


def _hash(a: int, b: int, c: int) -> int:
    """A small deterministic scramble (no state, so the same tick always draws the same)."""
    n = (a * 73856093) ^ (b * 19349663) ^ (c * 83492791)
    return (n ^ (n >> 13)) & 0x7FFFFFFF


def draw_confetti(
    canvas: Any,
    tick: int,
    regions: list[tuple[int, int, int, int]],
    width: int,
    height: int,
    per_region: int = 7,
) -> None:
    """Twinkling confetti: ``per_region`` pixels in each ``(x0, y0, x1, y1)`` box, moved every
    tick. Clipped to the panel here, since the test canvas records an off-panel write as a bug."""
    for index, (x0, y0, x1, y1) in enumerate(regions):
        span_x, span_y = x1 - x0, y1 - y0
        if span_x <= 0 or span_y <= 0:
            continue
        for n in range(per_region):
            h = _hash(index * 31 + n, tick, 7)
            px = x0 + h % span_x
            py = y0 + (h // span_x) % span_y
            if 0 <= px < width and 0 <= py < height:
                canvas.SetPixel(px, py, *CONFETTI[(h >> 8) % len(CONFETTI)])
