"""Runtime configuration.

The deployed image reads its settings from a TOML file on the FAT boot
partition (``/boot/firmware/scoreboard.toml``) so that it can be edited from
any machine after the card has been flashed -- no SSH, no keyboard.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_CONFIG_PATHS = (
    Path("/boot/firmware/scoreboard.toml"),
    Path("/boot/scoreboard.toml"),
    Path("/etc/nhl-scoreboard/scoreboard.toml"),
)


@dataclass(slots=True)
class PanelConfig:
    """Geometry and electrical settings for the HUB75 chain.

    Defaults describe two 64x32 panels daisy-chained into one 128x32
    display through a HUB75 adapter wired to the driver's "regular" pinout.
    Pixel pitch does not affect the driver; it is recorded so physical
    dimensions can be derived rather than remembered.
    """

    rows: int = 32
    cols: int = 64
    chain_length: int = 2
    parallel: int = 1
    pitch_mm: float = 2.5
    hardware_mapping: str = "regular"
    gpio_slowdown: int = 4
    pwm_bits: int = 11
    pwm_lsb_nanoseconds: int = 130
    brightness: int = 60
    limit_refresh_rate_hz: int = 0
    disable_hardware_pulsing: bool = False

    @property
    def width(self) -> int:
        return self.cols * self.chain_length

    @property
    def height(self) -> int:
        return self.rows * self.parallel

    @property
    def physical_mm(self) -> tuple[float, float]:
        """(width, height) of the assembled display in millimetres."""
        return (self.width * self.pitch_mm, self.height * self.pitch_mm)


@dataclass(slots=True)
class ScoreboardConfig:
    """Behaviour of the scoreboard itself."""

    favourite_team: str = ""
    timezone: str = "America/Toronto"
    rotate_seconds: float = 8.0
    poll_seconds: float = 60.0
    live_poll_seconds: float = 15.0
    show_clock_when_idle: bool = True
    prefer_favourite: bool = True

    def __post_init__(self) -> None:
        self.favourite_team = self.favourite_team.strip().upper()


@dataclass(slots=True)
class Settings:
    panel: PanelConfig = field(default_factory=PanelConfig)
    scoreboard: ScoreboardConfig = field(default_factory=ScoreboardConfig)
    source_path: Path | None = None

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> Settings:
        """Load settings from ``path``, the first default location, or defaults."""
        candidates = [Path(path)] if path else list(DEFAULT_CONFIG_PATHS)
        for candidate in candidates:
            if candidate.is_file():
                return cls.from_toml(candidate)
        log.info("No config file found in %s; using built-in defaults", candidates)
        return cls()

    @classmethod
    def from_toml(cls, path: Path) -> Settings:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
        settings = cls.from_dict(raw)
        settings.source_path = path
        log.info("Loaded configuration from %s", path)
        return settings

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Settings:
        return cls(
            panel=_build(PanelConfig, raw.get("panel", {})),
            scoreboard=_build(ScoreboardConfig, raw.get("scoreboard", {})),
        )


def _build(cls: type, raw: dict[str, Any]) -> Any:
    """Construct a dataclass from ``raw``, ignoring unknown keys.

    Unknown keys are warned about rather than fatal: a user hand-editing the
    file on the boot partition should never end up with a board that refuses
    to start because of one typo.
    """
    known = {f.name for f in fields(cls)}
    kwargs = {}
    for key, value in raw.items():
        if key in known:
            kwargs[key] = value
        else:
            log.warning("Ignoring unknown config key %r in [%s]", key, cls.__name__)
    return cls(**kwargs)
