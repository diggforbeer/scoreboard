"""A canvas that records pixels so a frame can be inspected as text.

The emulator's ``graphics`` module is pure Python and draws through
``SetPixel``, so anything the renderer produces can be captured here and
printed, diffed or asserted on -- no panel, no browser window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RGB = tuple[int, int, int]


@dataclass
class BBox:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0 + 1

    @property
    def height(self) -> int:
        return self.y1 - self.y0 + 1

    @property
    def center_x(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class AsciiCanvas:
    """Stands in for a matrix canvas, keeping every pixel that was lit."""

    width: int
    height: int
    pixels: dict[tuple[int, int], RGB] = field(default_factory=dict)
    #: SetPixel calls that fell outside the panel. The real driver clips
    #: these silently; recording them lets tests catch layout overflow.
    out_of_bounds: list[tuple[int, int]] = field(default_factory=list)

    # -- the subset of the binding's canvas API the renderer uses -------

    def Clear(self) -> None:  # noqa: N802 - mirrors the binding's API
        self.pixels.clear()
        self.out_of_bounds.clear()

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:  # noqa: N802
        x, y = int(x), int(y)
        if not (0 <= x < self.width and 0 <= y < self.height):
            self.out_of_bounds.append((x, y))
            return
        if r or g or b:
            self.pixels[(x, y)] = (r, g, b)
        else:
            self.pixels.pop((x, y), None)

    # -- inspection ------------------------------------------------------

    def render(self, on: str = "#", off: str = " ") -> str:
        """Every row, so vertical position is part of what a snapshot fixes."""
        border = "+" + "-" * self.width + "+"
        rows = [
            "|" + "".join(on if (x, y) in self.pixels else off for x in range(self.width)) + "|"
            for y in range(self.height)
        ]
        return "\n".join([border, *rows, border])

    def lit(self, x0: int = 0, y0: int = 0, x1: int | None = None, y1: int | None = None):
        """Pixels inside an inclusive region."""
        x1 = self.width - 1 if x1 is None else x1
        y1 = self.height - 1 if y1 is None else y1
        return {
            (x, y): rgb for (x, y), rgb in self.pixels.items() if x0 <= x <= x1 and y0 <= y <= y1
        }

    def bbox(self, x0: int = 0, y0: int = 0, x1: int | None = None, y1: int | None = None):
        region = self.lit(x0, y0, x1, y1)
        if not region:
            return None
        xs = [x for x, _ in region]
        ys = [y for _, y in region]
        return BBox(min(xs), min(ys), max(xs), max(ys))

    def colors(self, x0: int = 0, y0: int = 0, x1: int | None = None, y1: int | None = None):
        """Distinct colours used inside a region."""
        return set(self.lit(x0, y0, x1, y1).values())

    def row_is_solid(self, y: int) -> bool:
        return all((x, y) in self.pixels for x in range(self.width))
