"""The possession marker (mock-up): a small football sprite, and a drive arrow for the field.

``SetPixel`` sprites like the holiday and date art, so hardware, emulator, tests and the Live view
draw the same pixels. ``B`` is leather, ``W`` the laces, ``.`` is left untouched.
"""

from __future__ import annotations

from typing import Any

RGB = tuple[int, int, int]

LEATHER: RGB = (150, 82, 30)
LEATHER_LIT: RGB = (214, 130, 54)
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
FIELD = (  # 7x4, on the line of scrimmage
    "..BBB..",
    ".BBWBB.",
    "BBWWWBB",
    ".BBBBB.",
)
_PALETTE = {"B": LEATHER_LIT, "W": LACES}
#: Pointing right; a team driving left draws it mirrored.
CHEVRON = (
    "X.",
    ".X",
    "X.",
)


def sprite_width(sprite: tuple[str, ...]) -> int:
    return len(sprite[0])


def draw_sprite(canvas: Any, x: int, y: int, sprite: tuple[str, ...]) -> None:
    """``sprite`` with its top-left corner at (``x``, ``y``)."""
    for dy, row in enumerate(sprite):
        for dx, ch in enumerate(row):
            if ch in _PALETTE:
                canvas.SetPixel(x + dx, y + dy, *_PALETTE[ch])


def draw_drive_ball(
    canvas: Any, bx: int, by: int, direction: int, color: RGB, *, trail: int = 2
) -> None:
    """The ball centred on column ``bx`` / row ``by`` with ``trail`` chevrons behind it in
    ``color``, pointing the way the offence drives (``direction`` +1 right, -1 left)."""
    sprite = FIELD
    w, h = sprite_width(sprite), len(sprite)
    draw_sprite(canvas, bx - w // 2, by - h // 2 + 1, sprite)
    start = bx - direction * (w // 2 + 3)  # first chevron column, just behind the ball
    for i in range(trail):
        cx = start - direction * 3 * i
        for dy, row in enumerate(CHEVRON):
            for dx, ch in enumerate(row):
                if ch != "X":
                    continue
                # The glyph points right; for leftward drives mirror it about its own column.
                px = cx + (dx if direction > 0 else 1 - dx) - (1 if direction < 0 else 0)
                canvas.SetPixel(px, by - 1 + dy, *color)
