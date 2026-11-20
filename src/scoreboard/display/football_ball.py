"""The possession marker: a small football drawn beside the team that has the ball.

``SetPixel`` sprites like the holiday and date art, so hardware, emulator, tests and the Live view
draw the same pixels. ``B`` is leather, ``W`` the laces, ``.`` is left untouched.
"""

from __future__ import annotations

from typing import Any

RGB = tuple[int, int, int]

LEATHER: RGB = (214, 130, 54)
LACES: RGB = (255, 255, 255)

SMALL = (  # 5x3, for the 4x6 band
    ".BBB.",
    "BWWWB",
    ".BBB.",
)
LARGE = (  # 9x5, for the big scores screen
    "..BBBBB..",
    ".BBBBBBB.",
    "BBBWWWBBB",
    ".BBBBBBB.",
    "..BBBBB..",
)
_PALETTE = {"B": LEATHER, "W": LACES}


def sprite_width(sprite: tuple[str, ...]) -> int:
    return len(sprite[0])


def draw_sprite(canvas: Any, x: int, y: int, sprite: tuple[str, ...]) -> None:
    """``sprite`` with its top-left corner at (``x``, ``y``)."""
    for dy, row in enumerate(sprite):
        for dx, ch in enumerate(row):
            if ch in _PALETTE:
                canvas.SetPixel(x + dx, y + dy, *_PALETTE[ch])
