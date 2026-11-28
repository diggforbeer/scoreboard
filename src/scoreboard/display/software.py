"""A pure-Python matrix backend: draws into memory, needs no hardware or window.

The board's drawing code only ever touches a small slice of the ``rgbmatrix``
API (``Clear``/``SetPixel`` on a canvas, ``Font``/``DrawText``/``DrawLine``/
``Color`` from ``graphics``, and ``CreateFrameCanvas``/``SwapOnVSync`` on the
matrix). This implements exactly that slice, so the same renderer can run
anywhere Python does -- an Android app, a test, a screenshot script -- and hand
back finished frames instead of driving a panel.

Text is placed the way the C++ ``Font::DrawGlyph`` places it (see
``mirror.parse_bdf``, which this reuses), so a frame matches the real panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .matrix import Backend
from .mirror import REPLACEMENT, _Glyph, _line, parse_bdf

SOFTWARE = "software"


@dataclass(frozen=True, slots=True)
class Color:
    red: int
    green: int
    blue: int


class Font:
    def __init__(self) -> None:
        self._glyphs: dict[int, _Glyph] = {}

    def LoadFont(self, path: str) -> None:  # noqa: N802 - mirrors the binding's API
        self._glyphs = parse_bdf(Path(path))

    def glyph(self, codepoint: int) -> _Glyph | None:
        return self._glyphs.get(codepoint) or self._glyphs.get(REPLACEMENT)

    def CharacterWidth(self, codepoint: int) -> int:  # noqa: N802
        glyph = self.glyph(codepoint)
        return glyph.advance if glyph is not None else 0


class Canvas:
    """``width*height*3`` RGB bytes, row-major, as ``mirror.Frame.pixels`` is."""

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height * 3)

    def Clear(self) -> None:  # noqa: N802
        self.pixels[:] = bytes(len(self.pixels))

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:  # noqa: N802
        x, y = int(x), int(y)
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.pixels[i : i + 3] = bytes((int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF))


class _Graphics:
    """Stands in for the backend's ``graphics`` module."""

    Color = Color
    Font = Font

    @staticmethod
    def DrawText(  # noqa: N802
        canvas: Canvas, font: Font, x: int, y: int, color: Color, text: str
    ) -> int:
        pen = int(x)
        for ch in text:
            glyph = font.glyph(ord(ch))
            if glyph is None:
                continue
            top = int(y) - glyph.height - glyph.y_offset
            for gx, gy in glyph.lit:
                canvas.SetPixel(pen + gx, top + gy, color.red, color.green, color.blue)
            pen += glyph.advance
        return pen - int(x)

    @staticmethod
    def DrawLine(  # noqa: N802
        canvas: Canvas, x0: int, y0: int, x1: int, y1: int, color: Color
    ) -> None:
        for px, py in _line(int(x0), int(y0), int(x1), int(y1)):
            canvas.SetPixel(px, py, color.red, color.green, color.blue)


class RGBMatrixOptions:
    """Accepts and ignores every hardware knob; only the geometry matters."""

    rows = 32
    cols = 64
    chain_length = 1
    parallel = 1
    brightness = 100


class RGBMatrix:
    def __init__(self, options: RGBMatrixOptions | None = None) -> None:
        options = options or RGBMatrixOptions()
        self.width = options.cols * options.chain_length
        self.height = options.rows * options.parallel
        self.brightness = options.brightness
        self._front = Canvas(self.width, self.height)
        #: Bumped on every ``SwapOnVSync``: a poller can tell a new frame from the last one.
        self.frames_shown = 0

    def CreateFrameCanvas(self) -> Canvas:  # noqa: N802
        return Canvas(self.width, self.height)

    def SwapOnVSync(self, canvas: Canvas) -> Canvas:  # noqa: N802
        """Show ``canvas`` and hand back the one drawn on next, as the binding does."""
        self._front, back = canvas, self._front
        self.frames_shown += 1
        return back

    def Clear(self) -> None:  # noqa: N802
        self._front.Clear()

    def latest_pixels(self) -> bytes:
        """The frame most recently shown, as RGB bytes at full brightness."""
        return bytes(self._front.pixels)


def backend() -> Backend:
    return Backend(
        name=SOFTWARE,
        RGBMatrix=RGBMatrix,
        RGBMatrixOptions=RGBMatrixOptions,
        graphics=_Graphics,
    )
