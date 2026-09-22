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
    #: Static brightness, and the fallback used whenever auto_brightness is
    #: off or the ambient sensor (#44) isn't answering.
    brightness: int = 60
    limit_refresh_rate_hz: int = 0
    disable_hardware_pulsing: bool = False
    #: rpi-rgb-led-matrix's --led-pixel-mapper equivalent, e.g. "U-mapper"
    #: to fold two panels chained end-to-end into a stacked 64x64 display,
    #: or "Rotate:180" / "Mirror:H" for a panel mounted flipped. Chain
    #: several with ";", e.g. "U-mapper;Rotate:90". Empty means none.
    pixel_mapper: str = ""

    #: Dim/brighten the panel from a BH1750 ambient light sensor on the I2C
    #: bus instead of a fixed `brightness`. Off by default: not every board
    #: has the sensor wired up, and `LightSensor` degrades to `brightness`
    #: on its own if this is on but nothing answers, so there's no harm in
    #: leaving it on for a board without the sensor -- it's just extra I2C
    #: probing for nothing.
    auto_brightness: bool = False
    min_brightness: int = 10
    max_brightness: int = 100
    #: How often the sensor is sampled and brightness re-applied. Smoothed
    #: on top of this (see ScoreboardApp.refresh_brightness) so this can be
    #: fairly frequent without the panel visibly flickering.
    brightness_poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        self.min_brightness = max(1, min(100, self.min_brightness))
        self.max_brightness = max(1, min(100, self.max_brightness))
        if self.min_brightness > self.max_brightness:
            log.warning(
                "panel.min_brightness (%d) > max_brightness (%d); swapping",
                self.min_brightness,
                self.max_brightness,
            )
            self.min_brightness, self.max_brightness = self.max_brightness, self.min_brightness

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

    #: Pinned to the front of the rotation and eligible for the special-teams
    #: indicator. Nashville unless the boot-partition config says otherwise.
    favourite_team: str = "NSH"
    timezone: str = "America/Chicago"
    rotate_seconds: float = 8.0
    poll_seconds: float = 60.0
    live_poll_seconds: float = 15.0
    show_clock_when_idle: bool = True
    prefer_favourite: bool = True
    show_logos: bool = True
    logo_variant: str = "dark"
    #: How long a goal celebration screen stays up before returning to the
    #: normal game scene.
    goal_flash_seconds: float = 6.0
    #: "favourite": follow the favourite's game -- countdown, live, final,
    #: then a preview of the next one. "all": rotate every game today.
    rotation: str = "favourite"
    #: Inside this many hours of puck drop the preview becomes a countdown.
    countdown_hours: float = 2.0
    #: How long a finished favourite game stays up before the next preview.
    final_hold_minutes: float = 30.0
    #: Show the favourite's conference playoff picture, interleaved with the
    #: preview/countdown screen, once their season has actually started.
    show_standings: bool = True

    def __post_init__(self) -> None:
        self.favourite_team = self.favourite_team.strip().upper()
        self.logo_variant = self.logo_variant.strip().lower() or "dark"
        self.rotation = self.rotation.strip().lower() or "favourite"
        if self.rotation not in ("favourite", "all"):
            log.warning("Unknown rotation %r; using 'all'", self.rotation)
            self.rotation = "all"
        if self.rotation == "favourite" and not self.favourite_team:
            log.warning("rotation = 'favourite' needs a favourite_team; using 'all'")
            self.rotation = "all"


@dataclass(slots=True)
class AudioConfig:
    """Goal horn playback. See ``audio.GoalHornPlayer``."""

    enabled: bool = True
    #: ALSA device name, e.g. "plughw:1,0". Empty uses aplay's default.
    device: str = ""
    #: Override the search directory for horn WAVs. Empty uses the built-in
    #: search path (NHL_SCOREBOARD_HORN_DIR env var, then the shipped assets).
    horn_dir: str = ""


@dataclass(slots=True)
class StatusServerConfig:
    """Read-only web status page for headless debugging (#48).

    Off by default so it isn't one more thing that has to be reasoned about
    for every board. No auth: it binds the local network only, for a device
    already trusted there -- do not port-forward it to the internet.
    """

    enabled: bool = False
    port: int = 8080


@dataclass(slots=True)
class Settings:
    panel: PanelConfig = field(default_factory=PanelConfig)
    scoreboard: ScoreboardConfig = field(default_factory=ScoreboardConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    status: StatusServerConfig = field(default_factory=StatusServerConfig)
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
            audio=_build(AudioConfig, raw.get("audio", {})),
            status=_build(StatusServerConfig, raw.get("status", {})),
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
