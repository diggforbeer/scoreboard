"""Team logos, pre-rasterised to panel size by scripts/fetch-logos.py.

Logos are decoded once into a flat list of opaque pixels so drawing is a
plain SetPixel loop -- the same path on hardware, in the emulator and on
the recording canvas the tests use. Alpha is composited against black,
which is what a transparent edge looks like on an unlit LED anyway.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]

#: Below this alpha a pixel is treated as unlit rather than drawn dark.
ALPHA_FLOOR = 48
#: Composited pixels darker than this are dropped too; they read as noise.
LUMA_FLOOR = 12


@dataclass(frozen=True, slots=True)
class Logo:
    abbrev: str
    width: int
    height: int
    #: (dx, dy, (r, g, b)) for every pixel worth lighting.
    pixels: tuple[tuple[int, int, RGB], ...]


#: The sports with logos. NFL and NHL abbreviations overlap (``BUF``, ``CAR``, ``DAL``, ``DET``,
#: ``MIN`` ...) and mean different teams, so each sport has its own directories and its own
#: library: ``BUF`` is never looked up across them.
SPORTS = ("nhl", "nfl")


def default_directories(size: int, variant: str, sport: str = "nhl") -> list[Path]:
    """Where to look, most specific first.

    NHL art keeps its original layout (``assets/logos/32/dark``). NFL art lives beside it
    under ``nfl/`` (``assets/logos/nfl/12/dark``), with the same ``overrides`` slot, and its
    own environment variable.
    """
    if sport not in SPORTS:
        raise ValueError(f"unknown sport {sport!r}; expected one of {SPORTS}")
    dirs: list[Path] = []
    env = os.environ.get(
        "NHL_SCOREBOARD_LOGO_DIR" if sport == "nhl" else "NHL_SCOREBOARD_NFL_LOGO_DIR"
    )
    if env:
        dirs.append(Path(env))
    repo_root = Path(__file__).resolve().parents[3]
    if sport == "nfl":
        system = Path("/usr/share/nhl-scoreboard/logos/nfl")
        assets = repo_root / "assets" / "logos" / "nfl"
        return [
            *dirs,
            system / "overrides" / str(size) / variant,
            assets / "overrides" / str(size) / variant,
            system / str(size) / variant,
            assets / str(size) / variant,
        ]
    # Hand-picked overrides for teams whose official crest doesn't
    # downscale legibly at panel size (#12) -- checked before the
    # auto-fetched directory below, so one of these wins without needing
    # to touch fetch-logos.py's own output.
    dirs.append(Path("/usr/share/nhl-scoreboard/logos/overrides") / str(size) / variant)
    dirs.append(repo_root / "assets" / "logos" / "overrides" / str(size) / variant)
    dirs.append(Path("/usr/share/nhl-scoreboard/logos") / str(size) / variant)
    dirs.append(repo_root / "assets" / "logos" / str(size) / variant)
    return dirs


class LogoLibrary:
    """Finds and caches logos; a missing logo is ``None``, never an error."""

    def __init__(self, directories: Sequence[Path], size: int = 32) -> None:
        self.directories = [Path(d) for d in directories]
        self.size = size
        self._cache: dict[str, Logo | None] = {}
        self._warned_no_pillow = False

    @classmethod
    def default(cls, size: int = 32, variant: str = "dark", sport: str = "nhl") -> LogoLibrary:
        return cls(default_directories(size, variant, sport), size=size)

    def path_for(self, abbrev: str) -> Path | None:
        name = f"{abbrev.strip().upper()}.png"
        for directory in self.directories:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return None

    def get(self, abbrev: str) -> Logo | None:
        key = abbrev.strip().upper()
        if key not in self._cache:
            self._cache[key] = self._load(key)
        return self._cache[key]

    def has(self, abbrev: str) -> bool:
        return self.get(abbrev) is not None

    def _load(self, abbrev: str) -> Logo | None:
        path = self.path_for(abbrev)
        if path is None:
            log.debug("No logo for %s in %s", abbrev, self.directories)
            return None
        try:
            from PIL import Image
        except ImportError:
            if not self._warned_no_pillow:
                log.warning("Pillow not installed; logos disabled")
                self._warned_no_pillow = True
            return None
        try:
            with Image.open(path) as im:
                logo = decode(abbrev, im.convert("RGBA"), self.size)
        except OSError as exc:
            log.warning("Could not read logo %s: %s", path, exc)
            return None
        log.debug("Loaded logo %s (%d px lit)", path, len(logo.pixels))
        return logo


def decode(abbrev: str, image, size: int) -> Logo:
    """Flatten an RGBA image into lit pixels, composited over black."""
    if image.size != (size, size):
        # Lazy, like _load's: Pillow is optional. Callers only get here with an
        # image Pillow already decoded, so no ImportError guard is needed.
        # LANCZOS matches fetch-logos.py; the default filter mushes fine
        # linework at 32px, which is the whole point of the override slot.
        from PIL import Image

        image = image.resize((size, size), resample=Image.LANCZOS)
    pixels: list[tuple[int, int, RGB]] = []
    data = image.load()
    for y in range(size):
        for x in range(size):
            r, g, b, a = data[x, y]
            if a < ALPHA_FLOOR:
                continue
            rgb = (r * a // 255, g * a // 255, b * a // 255)
            if max(rgb) < LUMA_FLOOR:
                continue
            pixels.append((x, y, rgb))
    return Logo(abbrev=abbrev, width=size, height=size, pixels=tuple(pixels))


class LogoSet:
    """One sport's logos at several sizes: a library per size, made on first use (#349).

    Football draws a team at more than one size (a small one in each end zone, a larger one on
    the coin toss and score screens), and ``LogoLibrary`` is square and fixed-size, so a screen
    asks for ``get("KC", 12)``. A size that was never fetched is simply ``None`` and the screen
    falls back to the team's abbreviation, as NHL does.
    """

    def __init__(self, sport: str, variant: str = "dark", libraries: dict | None = None) -> None:
        self.sport = sport
        self.variant = variant
        self._libraries: dict[int, LogoLibrary] = dict(libraries or {})

    def for_size(self, size: int) -> LogoLibrary:
        if size not in self._libraries:
            self._libraries[size] = LogoLibrary.default(size, self.variant, self.sport)
        return self._libraries[size]

    def get(self, abbrev: str, size: int) -> Logo | None:
        return self.for_size(size).get(abbrev)
