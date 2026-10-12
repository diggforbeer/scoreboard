"""A copy of each frame for the admin page's live view (#268).

The real ``rgbmatrix`` binding can't read pixels back, and its text and
lines are drawn in C++, so a frame can't be recovered after the fact or
caught at ``SetPixel`` alone. Instead, while someone is watching:

- ``MirrorCanvas`` wraps the panel's canvas. ``SetPixel``/``Clear`` pass
  straight through and also land in a ``width*height*3`` framebuffer.
- ``MirrorGraphics`` wraps the backend's ``graphics`` module. ``DrawText``
  and ``DrawLine`` still draw on the real canvas through the real module,
  then, for a ``MirrorCanvas``, draw the same glyphs or line into the
  framebuffer -- from the same vendored BDF files, placed the way the C++
  ``Font::DrawGlyph`` places them.

With nobody watching, the app never wraps its canvas, so the panel is
drawn exactly as before: the only cost is one ``isinstance`` per text or
line call. ``Mirror`` is shared between the render thread (which
publishes) and the admin server's thread (which reads and toggles), so
both sides only ever swap whole values: ``active`` is a plain bool, and a
published frame is an immutable ``Frame``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Frame:
    """One finished frame: ``pixels`` is RGB, row-major, 3 bytes a pixel."""

    seq: int
    width: int
    height: int
    pixels: bytes
    #: The panel brightness (percent) the frame was shown at. ``pixels`` are
    #: what was drawn, at full brightness; this is for the page to note.
    brightness: int


class Mirror:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        #: Set from the admin server's thread while it has a live-view
        #: subscriber; read once per frame by the render thread.
        self.active = False
        self.buffer = bytearray(width * height * 3)
        self._frame: Frame | None = None
        self._seq = 0

    def clear(self) -> None:
        self.buffer[:] = bytes(len(self.buffer))

    def set_pixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            i = (y * self.width + x) * 3
            self.buffer[i : i + 3] = bytes((r & 0xFF, g & 0xFF, b & 0xFF))

    def publish(self, brightness: int) -> None:
        self._seq += 1
        self._frame = Frame(self._seq, self.width, self.height, bytes(self.buffer), brightness)

    def latest(self) -> Frame | None:
        return self._frame

    def discard(self) -> None:
        """Forget the last frame, so a viewer who opens the live view later
        never gets one from before it was switched off."""
        self._frame = None


class MirrorCanvas:
    """The panel's canvas, recording everything drawn on it into a ``Mirror``."""

    def __init__(self, inner: Any, mirror: Mirror) -> None:
        self.inner = inner
        self.mirror = mirror
        mirror.clear()

    def Clear(self) -> None:  # noqa: N802 - mirrors the binding's API
        self.inner.Clear()
        self.mirror.clear()

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:  # noqa: N802
        self.inner.SetPixel(x, y, r, g, b)
        self.mirror.set_pixel(int(x), int(y), int(r), int(g), int(b))

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def unwrap(canvas: Any) -> Any:
    return canvas.inner if isinstance(canvas, MirrorCanvas) else canvas


@dataclass(frozen=True, slots=True)
class _Glyph:
    width: int
    height: int
    y_offset: int
    advance: int
    #: Lit pixels as (x, y) from the glyph's top-left.
    lit: tuple[tuple[int, int], ...]


def parse_bdf(path: Path) -> dict[int, _Glyph]:
    """Codepoint -> glyph, read the way rpi-rgb-led-matrix's bdf-font.cc
    reads a BDF: ``ENCODING``, ``DWIDTH`` for the advance, ``BBX`` for the
    size and y offset (its x offset is ignored there too), then one hex row
    per line, most significant bit leftmost."""
    glyphs: dict[int, _Glyph] = {}
    codepoint = advance = width = height = y_offset = 0
    rows: list[str] | None = None
    for line in path.read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if rows is not None:
            if key == "ENDCHAR":
                lit = []
                for y, hex_row in enumerate(rows[:height]):
                    bits = int(hex_row, 16)
                    total = len(hex_row) * 4
                    lit.extend((x, y) for x in range(width) if bits >> (total - 1 - x) & 1)
                glyphs[codepoint] = _Glyph(width, height, y_offset, advance, tuple(lit))
                rows = None
            else:
                rows.append(parts[0])
        elif key == "ENCODING":
            codepoint = int(parts[1])
        elif key == "DWIDTH":
            advance = int(parts[1])
        elif key == "BBX":
            width, height, y_offset = int(parts[1]), int(parts[2]), int(parts[4])
        elif key == "BITMAP":
            rows = []
    return glyphs


#: rpi-rgb-led-matrix draws this for a codepoint the font lacks.
REPLACEMENT = 0xFFFD


class MirrorFont:
    """The backend's font, plus its glyphs parsed for the mirror (lazily:
    a board nobody watches never parses a BDF a second time)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.path: Path | None = None
        self._glyphs: dict[int, _Glyph] | None = None

    def LoadFont(self, path: str) -> None:  # noqa: N802
        self.inner.LoadFont(path)
        self.path = Path(path)

    def CharacterWidth(self, codepoint: int) -> int:  # noqa: N802
        return self.inner.CharacterWidth(codepoint)

    def glyph(self, codepoint: int) -> _Glyph | None:
        if self._glyphs is None:
            self._glyphs = parse_bdf(self.path) if self.path is not None else {}
        return self._glyphs.get(codepoint) or self._glyphs.get(REPLACEMENT)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class MirrorGraphics:
    """Stands in for the backend's ``graphics`` module (see module docstring)."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def Font(self) -> MirrorFont:  # noqa: N802
        return MirrorFont(self.inner.Font())

    def DrawText(self, canvas: Any, font: Any, x: int, y: int, color: Any, text: str) -> int:  # noqa: N802
        real_font = font.inner if isinstance(font, MirrorFont) else font
        result = self.inner.DrawText(unwrap(canvas), real_font, x, y, color, text)
        if isinstance(canvas, MirrorCanvas) and isinstance(font, MirrorFont):
            rgb = _rgb(color)
            pen = int(x)
            for ch in text:
                glyph = font.glyph(ord(ch))
                if glyph is None:
                    continue
                top = int(y) - glyph.height - glyph.y_offset
                for gx, gy in glyph.lit:
                    canvas.mirror.set_pixel(pen + gx, top + gy, *rgb)
                pen += glyph.advance
        return result

    def DrawLine(self, canvas: Any, x0: int, y0: int, x1: int, y1: int, color: Any) -> None:  # noqa: N802
        self.inner.DrawLine(unwrap(canvas), x0, y0, x1, y1, color)
        if isinstance(canvas, MirrorCanvas):
            rgb = _rgb(color)
            for px, py in _line(int(x0), int(y0), int(x1), int(y1)):
                canvas.mirror.set_pixel(px, py, *rgb)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _rgb(color: Any) -> tuple[int, int, int]:
    if isinstance(color, tuple):  # tests' stand-in graphics module
        return color
    return int(color.red), int(color.green), int(color.blue)


def _line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Bresenham, every point from one end to the other inclusive."""
    points = []
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            return points
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy
