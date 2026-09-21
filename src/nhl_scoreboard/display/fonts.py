"""Locating the bundled BDF fonts.

Both the real ``rgbmatrix`` bindings and ``RGBMatrixEmulator`` load fonts from
BDF files, so the same files work on hardware and on a development laptop.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

#: Searched in order; first hit wins.
FONT_DIRS = (
    Path(os.environ.get("NHL_SCOREBOARD_FONT_DIR", "")),
    Path("/usr/share/nhl-scoreboard/fonts"),
    Path(__file__).resolve().parents[3] / "fonts",
    Path("/opt/rgbmatrix/fonts"),
    Path("/usr/local/share/rpi-rgb-led-matrix/fonts"),
)


def font_path(name: str) -> Path:
    """Absolute path to a bundled BDF font, e.g. ``font_path("5x7.bdf")``."""
    for directory in FONT_DIRS:
        if not directory or str(directory) == ".":
            continue
        candidate = directory / name
        if candidate.is_file():
            return candidate
    searched = ", ".join(str(d) for d in FONT_DIRS if d and str(d) != ".")
    raise FileNotFoundError(f"BDF font {name!r} not found. Searched: {searched}")


class FontSet:
    """The three type sizes the 128x32 layout uses, loaded once."""

    def __init__(self, graphics: object) -> None:
        self.tiny = _load(graphics, "4x6.bdf")
        self.small = _load(graphics, "5x7.bdf")
        self.medium = _load(graphics, "6x10.bdf")
        self.large = _load(graphics, "7x13B.bdf")


def _load(graphics: object, name: str):
    font = graphics.Font()  # type: ignore[attr-defined]
    path = font_path(name)
    font.LoadFont(str(path))
    log.debug("Loaded font %s", path)
    return font


def text_width(font: object, text: str) -> int:
    """Pixel width of ``text`` in ``font`` without drawing it."""
    return sum(font.CharacterWidth(ord(ch)) for ch in text)  # type: ignore[attr-defined]
