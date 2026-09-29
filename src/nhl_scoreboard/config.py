"""Runtime configuration.

The deployed image reads its settings from a TOML file on the FAT boot
partition (``/boot/firmware/scoreboard.toml``) so that it can be edited from
any machine after the card has been flashed -- no SSH, no keyboard.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tomlkit

log = logging.getLogger(__name__)

#: Nashville's zone, used whenever a configured timezone can't be resolved
#: and there is no previous value worth keeping instead (boot, --dump).
DEFAULT_TIMEZONE = "America/Chicago"


def resolve_timezone(name: str, fallback: ZoneInfo | None = None) -> ZoneInfo:
    """``ZoneInfo`` for ``name``, degrading instead of raising on a bad value.

    A typo in ``scoreboard.toml``'s ``timezone`` (e.g. "America/Chicagoo")
    must not crash the board -- see CLAUDE.md's config-conventions section
    and #80. On an unknown zone, this logs a warning and returns
    ``fallback`` if one was given (the currently running zone, so a bad
    live-reload keeps the board on whatever already worked) or else
    ``DEFAULT_TIMEZONE`` (boot and ``--dump`` have no previous value to
    keep).
    """
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        result = fallback if fallback is not None else ZoneInfo(DEFAULT_TIMEZONE)
        log.warning("Unknown timezone %r; using %s", name, result.key)
        return result


class ConfigWriteError(Exception):
    """Raised when Settings.save() cannot read or write the config file.

    Deliberately not swallowed: a save that silently didn't happen (boot
    partition full or read-only) needs to surface to whoever is editing the
    config, not vanish (#51).
    """


DEFAULT_CONFIG_PATHS = (
    Path("/boot/firmware/scoreboard.toml"),
    Path("/boot/scoreboard.toml"),
    Path("/etc/nhl-scoreboard/scoreboard.toml"),
)

#: Floor for any configurable polling/rotation interval. A `0` or negative
#: value (a typo in a hand-edited boot TOML) would make the matching
#: `now >= next_*` check in app.py's run loop non-advancing -- e.g. hitting
#: the scores endpoint every FRAME_INTERVAL (0.5s) instead of the intended
#: poll_seconds, defeating the whole point of a poll interval (#64).
MIN_INTERVAL_SECONDS = 1.0


def _clamp_interval(section: str, name: str, value: float) -> float:
    if value < MIN_INTERVAL_SECONDS:
        log.warning(
            "%s.%s (%s) is below the floor of %s seconds; using %s",
            section,
            name,
            value,
            MIN_INTERVAL_SECONDS,
            MIN_INTERVAL_SECONDS,
        )
        return MIN_INTERVAL_SECONDS
    return value


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
    #: rpi-rgb-led-matrix's --led-rgb-sequence equivalent: the order the
    #: three colour wires are actually driven in, e.g. "RBG" for a panel
    #: whose green/blue wires are swapped from the driver's "RGB" default.
    #: Verified live (2026-09-25) on the project's own reference panel:
    #: with the default "RGB", yellow rendered pink and blue rendered
    #: green -- both symptoms of a G/B swap -- and "RBG" fixed it. Default
    #: stays at the library's own "RGB" here since this is a per-panel
    #: wiring property, not something safe to assume for every board;
    #: override in scoreboard.toml if your panel shows the same swap.
    rgb_sequence: str = "RGB"
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
        self.brightness = max(1, min(100, self.brightness))
        self.min_brightness = max(1, min(100, self.min_brightness))
        self.max_brightness = max(1, min(100, self.max_brightness))
        if self.min_brightness > self.max_brightness:
            log.warning(
                "panel.min_brightness (%d) > max_brightness (%d); swapping",
                self.min_brightness,
                self.max_brightness,
            )
            self.min_brightness, self.max_brightness = self.max_brightness, self.min_brightness
        self.brightness_poll_seconds = _clamp_interval(
            "panel", "brightness_poll_seconds", self.brightness_poll_seconds
        )

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
    timezone: str = DEFAULT_TIMEZONE
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
    #: How long the scorer/assist detail screen (#122 phase 2) stays up once
    #: it fires. Longer than goal_flash_seconds by default: there is
    #: meaningfully more to read (name, season totals, assist(s)) than the
    #: "GOAL" + score flash.
    goal_detail_seconds: float = 8.0
    #: Inside this many hours of puck drop the preview becomes a countdown.
    countdown_hours: float = 2.0
    #: How long a finished favourite game stays up before the next preview.
    final_hold_minutes: float = 30.0
    #: Show the favourite's conference playoff picture, interleaved with the
    #: preview/countdown screen, once their season has actually started.
    show_standings: bool = True
    #: Cycle the idle clock into the favourite rotation's countdown/preview
    #: (and standings, if shown) alternation whenever the favourite isn't
    #: live -- separate from show_clock_when_idle, which only covers "no
    #: games left to preview at all". Off by default: existing installs get
    #: the same rotation they always had unless they opt in.
    show_clock_between_games: bool = False

    def __post_init__(self) -> None:
        self.favourite_team = self.favourite_team.strip().upper()
        self.logo_variant = self.logo_variant.strip().lower() or "dark"
        self.poll_seconds = _clamp_interval("scoreboard", "poll_seconds", self.poll_seconds)
        self.live_poll_seconds = _clamp_interval(
            "scoreboard", "live_poll_seconds", self.live_poll_seconds
        )
        self.rotate_seconds = _clamp_interval("scoreboard", "rotate_seconds", self.rotate_seconds)


#: The only screens ``_rotate_idle_scenes`` (app.py) knows how to show.
#: "countdown_preview" auto-switches between countdown/preview based on
#: countdown_hours, same as always -- which one shows isn't a user choice,
#: so it isn't split into two separately configurable screens (#150).
#: "matchup" (#157) is opt-in only: never part of the derived default list.
VALID_ROTATION_SCREENS = ("countdown_preview", "standings", "clock", "matchup")


@dataclass(slots=True)
class RotationEntry:
    """One slot in the configurable idle rotation (#150), parsed from a ``[[rotation]]`` table.

    Only ever constructed by ``_parse_rotation`` with an already-validated
    ``screen``/``seconds`` pair -- invalid entries (unknown screen,
    non-positive seconds) are dropped there and never reach this type.
    """

    screen: str
    seconds: float


def _parse_rotation(raw: list[Any]) -> list[RotationEntry]:
    """Parse ``[[rotation]]`` (an array of tables), dropping invalid entries.

    Per #150's decision 3, an invalid entry is never displayed on the panel
    but is not fatal either -- logged as a warning and skipped, same
    typo-tolerant convention as every other config value in this module.
    """
    entries: list[RotationEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            log.warning("Ignoring [[rotation]] entry that isn't a table: %r", item)
            continue
        screen = str(item.get("screen", "")).strip().lower()
        if screen not in VALID_ROTATION_SCREENS:
            log.warning(
                "Ignoring [[rotation]] entry with unknown screen %r (must be one of %s)",
                item.get("screen"),
                ", ".join(VALID_ROTATION_SCREENS),
            )
            continue
        seconds = item.get("seconds")
        try:
            seconds_value = float(seconds)
        except (TypeError, ValueError):
            log.warning(
                "Ignoring [[rotation]] entry %r with non-numeric seconds %r", screen, seconds
            )
            continue
        if seconds_value <= 0:
            log.warning(
                "Ignoring [[rotation]] entry %r with non-positive seconds %r", screen, seconds_value
            )
            continue
        entries.append(RotationEntry(screen=screen, seconds=seconds_value))
    return entries


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

    On by default: the board is headless by design, so this is the main way
    to check on it without SSH-ing in, and it's the only way at all until a
    phone has a captive-portal setup flow to reach it (#116). No auth: it
    binds the local network only, for a device already trusted there -- do
    not port-forward it to the internet.
    """

    enabled: bool = True
    port: int = 8080


@dataclass(slots=True)
class WifiSetupConfig:
    """The WiFi setup page served while the board's own first-boot AP is up (#132).

    On by default: while ``nhl-scoreboard-setup-ap`` (#131) has the AP up,
    this is the only way for a phone connected to it to actually choose a
    network -- reachability alone (#141's QR code) doesn't collect
    credentials. Port 80, not ``status.port``'s 8080: captive-portal probes
    (Apple/Android/Windows) hit the well-known plain-HTTP port, and
    dnsmasq's wildcard DNS only gets them as far as this board's IP -- the
    port still has to be the one they actually ask for. nhl-scoreboard.service
    already runs as root, so binding it needs no extra capability.
    """

    enabled: bool = True
    port: int = 80


@dataclass(slots=True)
class UpdateConfig:
    """Daily check for a newer release (#32).

    On by default, but only ever *checks* -- applying is always the admin
    page's button. This is the one thing that has the board contact anything
    besides the NHL API on its own (GitHub Releases), hence the switch.
    """

    enabled: bool = True


@dataclass(slots=True)
class WifiConfig:
    """How long a WiFi join attempt waits before deciding it failed (#133).

    Shared by boot-time provisioning (scoreboard-provision) and the AP setup
    page's live join flow -- nhl_scoreboard.wifi's own module-level default
    (WIFI_CONNECT_TIMEOUT, 90s) is the fallback when this isn't set. 90s is
    the number that default already used; exposed here as a real setting
    rather than left as the env var (NHL_SCOREBOARD_WIFI_TIMEOUT) that
    default is overridden by today, which is meant for tests/low-level
    overrides, not something a real user would find.

    ``ssid``/``password``/``country`` are deliberately NOT modelled here --
    scoreboard-provision reads those directly out of the raw TOML dict
    itself (predates this Settings dataclass) and nothing else needs typed
    access to them.
    """

    connect_timeout_seconds: float = 90.0

    def __post_init__(self) -> None:
        self.connect_timeout_seconds = _clamp_interval(
            "wifi", "connect_timeout_seconds", self.connect_timeout_seconds
        )


@dataclass(slots=True)
class NightModeConfig:
    """Scheduled dimming that stays out of the way of a live game (#92).

    Off by default: a board nobody asked to dim shouldn't go dark at
    22:30 on its own.
    """

    enabled: bool = False
    #: 24-hour "HH:MM", local to ``scoreboard.timezone``. The window may
    #: wrap midnight (the usual case: 22:30 -> 07:00).
    start_time: str = "22:30"
    end_time: str = "07:00"
    #: 0-100. Unlike panel.brightness this may be 0, which blanks the
    #: canvas outright rather than drawing scenes nobody can see.
    dim_brightness: int = 0
    #: "tracked": only the favourite's game holds off dimming. "all": any
    #: live game today does. Same favourite-vs-all scoping as the power-play
    #: indicator and goal detection.
    suppress_scope: str = "tracked"
    #: How long after the relevant game goes final the board stays at
    #: normal brightness, so the final score is still readable. 0 is valid:
    #: dim the moment it ends.
    cooldown_minutes: float = 15.0
    #: Parsed start_time/end_time, so the app never re-parses the strings.
    start: time = field(init=False, repr=False)
    end: time = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.start_time, self.start = _parse_hhmm("start_time", self.start_time, "22:30")
        self.end_time, self.end = _parse_hhmm("end_time", self.end_time, "07:00")
        self.dim_brightness = max(0, min(100, self.dim_brightness))
        self.suppress_scope = str(self.suppress_scope).strip().lower()
        if self.suppress_scope not in ("tracked", "all"):
            log.warning(
                "Unknown night_mode.suppress_scope %r; using 'tracked'", self.suppress_scope
            )
            self.suppress_scope = "tracked"
        self.cooldown_minutes = max(0.0, float(self.cooldown_minutes))


def _parse_hhmm(name: str, value: str, default: str) -> tuple[str, time]:
    """Parse a 24-hour "HH:MM", warning and falling back to ``default`` if it isn't one."""
    try:
        return value, datetime.strptime(str(value), "%H:%M").time()
    except ValueError:
        log.warning("night_mode.%s %r is not 24-hour HH:MM; using %s", name, value, default)
        return default, datetime.strptime(default, "%H:%M").time()


@dataclass(slots=True)
class Settings:
    panel: PanelConfig = field(default_factory=PanelConfig)
    scoreboard: ScoreboardConfig = field(default_factory=ScoreboardConfig)
    #: The idle rotation (#150), explicit ``[[rotation]]`` entries in file
    #: order. Empty when absent from the file -- app.py derives the old
    #: implicit default list (countdown/preview, standings, clock) from
    #: ScoreboardConfig's own rotate_seconds/show_standings/
    #: show_clock_between_games in that case, so an upgraded board changes
    #: nothing until the owner opts in.
    rotation: list[RotationEntry] = field(default_factory=list)
    audio: AudioConfig = field(default_factory=AudioConfig)
    status: StatusServerConfig = field(default_factory=StatusServerConfig)
    wifi_setup: WifiSetupConfig = field(default_factory=WifiSetupConfig)
    wifi: WifiConfig = field(default_factory=WifiConfig)
    night_mode: NightModeConfig = field(default_factory=NightModeConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)
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
            rotation=_parse_rotation(raw.get("rotation", [])),
            audio=_build(AudioConfig, raw.get("audio", {})),
            status=_build(StatusServerConfig, raw.get("status", {})),
            wifi_setup=_build(WifiSetupConfig, raw.get("wifi_setup", {})),
            wifi=_wifi_config(raw.get("wifi", {})),
            night_mode=_build(NightModeConfig, raw.get("night_mode", {})),
            update=_build(UpdateConfig, raw.get("update", {})),
        )

    def save(self, updates: Mapping[str, Any]) -> None:
        """Write ``updates`` into the source file, in place, keeping everything else.

        ``updates`` is normally ``{section: {key: value}}``, e.g.
        ``{"scoreboard": {"favourite_team": "TOR"}, "panel": {"brightness": 80}}``
        -- only those keys are touched, parsed and re-emitted with
        ``tomlkit`` rather than ``tomllib`` + a plain writer, so every
        comment in the heavily-annotated boot-partition template survives
        untouched (#51).

        The one exception is the ``"rotation"`` key (#150): ``[[rotation]]``
        is an array of tables, not a flat section of scalars, so its value
        is the *whole new list* of ``{"screen": ..., "seconds": ...}``
        dicts to write, not a ``{key: value}`` patch -- there is no
        per-field update for an ordered, variable-length list, only
        "replace it". Built with ``tomlkit.aot()`` rather than assigning a
        plain list, which would round-trip as an inline array rather than
        a sequence of ``[[rotation]]`` tables.

        Updates this object's in-memory settings from the same file afterwards,
        via the normal load path, so the caller sees the merged result without
        a separate reload.
        """
        if self.source_path is None:
            raise ConfigWriteError("no source file loaded; nothing to save to")
        try:
            doc = tomlkit.parse(self.source_path.read_text())
        except OSError as exc:
            raise ConfigWriteError(f"could not read {self.source_path}: {exc}") from exc

        for section, values in updates.items():
            if section == "rotation":
                aot = tomlkit.aot()
                for entry in values:
                    table = tomlkit.table()
                    table["screen"] = entry["screen"]
                    table["seconds"] = entry["seconds"]
                    aot.append(table)
                doc["rotation"] = aot
                continue
            table = doc.get(section)
            if table is None:
                table = tomlkit.table()
                doc[section] = table
            for key, value in values.items():
                table[key] = value

        tmp_path = self.source_path.with_name(self.source_path.name + ".tmp")
        try:
            tmp_path.write_text(tomlkit.dumps(doc))
            tmp_path.replace(self.source_path)
        except OSError as exc:
            raise ConfigWriteError(f"could not write {self.source_path}: {exc}") from exc

        reloaded = Settings.from_toml(self.source_path)
        self.panel = reloaded.panel
        self.scoreboard = reloaded.scoreboard
        self.rotation = reloaded.rotation
        self.audio = reloaded.audio
        self.status = reloaded.status
        self.wifi_setup = reloaded.wifi_setup
        self.wifi = reloaded.wifi
        self.night_mode = reloaded.night_mode
        self.update = reloaded.update


def _build(cls: type, raw: dict[str, Any]) -> Any:
    """Construct a dataclass from ``raw``, ignoring unknown keys.

    Unknown keys are warned about rather than fatal: a user hand-editing the
    file on the boot partition should never end up with a board that refuses
    to start because of one typo.
    """
    # init=False fields are derived (e.g. NightModeConfig.start), not settable.
    known = {f.name for f in fields(cls) if f.init}
    kwargs = {}
    for key, value in raw.items():
        if key in known:
            kwargs[key] = value
        else:
            log.warning("Ignoring unknown config key %r in [%s]", key, cls.__name__)
    return cls(**kwargs)


def _wifi_config(raw: dict[str, Any]) -> WifiConfig:
    """WifiConfig only models ``connect_timeout_seconds``.

    ``ssid``/``password``/``country`` live in the same ``[wifi]`` TOML
    section but are read directly out of the raw dict by
    scoreboard-provision (predates this dataclass), not through here.
    Filtered before ``_build()`` sees them so those three don't trip its
    "unknown key" warning on every single load.
    """
    filtered = {k: v for k, v in raw.items() if k == "connect_timeout_seconds"}
    return _build(WifiConfig, filtered)
