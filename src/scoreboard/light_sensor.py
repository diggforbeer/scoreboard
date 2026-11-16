"""Ambient light sensing via a BH1750 I2C lux sensor (#44).

Mirrors audio.GoalHornPlayer and display.logos.LogoLibrary: hardware that
isn't there degrades to ``None``, never an exception. ``ScoreboardApp``
keeps using the static ``scoreboard.toml`` brightness whenever this returns
``None`` -- whether that's because no sensor is wired up at all, or because
one that was working stops answering.
"""

from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)

#: BH1750's I2C address with the ADDR pin low (breakout default); pulling
#: ADDR high moves it to 0x5C, which is not covered here since every
#: breakout board we've seen ships ADDR-low.
DEFAULT_ADDRESS = 0x23
#: "Continuously H-Resolution Mode": 1 lux resolution, ~120ms per sample.
#: The sensor keeps re-measuring on its own once this is set, so re-sending
#: it before each read is just idempotent, not a fresh trigger.
_CONTINUOUS_HIGH_RES_MODE = 0x10


class I2CBus(Protocol):
    """The subset of smbus2.SMBus/smbus.SMBus this module calls."""

    def write_byte(self, address: int, value: int) -> None: ...
    def read_i2c_block_data(self, address: int, register: int, length: int) -> list[int]: ...


def _open_bus(bus_number: int) -> I2CBus | None:
    try:
        from smbus2 import SMBus
    except ImportError:
        try:
            from smbus import SMBus
        except ImportError:
            log.info("No I2C library (smbus2/smbus) installed; ambient light sensor disabled")
            return None
    try:
        return SMBus(bus_number)
    except OSError as exc:
        # No /dev/i2c-N (i2c_arm not enabled, or no such bus number) --
        # not an error, just a board without the sensor wired up.
        log.info("I2C bus %d unavailable: %s; ambient light sensor disabled", bus_number, exc)
        return None


class LightSensor:
    """Reads lux from a BH1750 breakout. ``read_lux()`` returns ``None`` if
    nothing answers -- at open time or on any later read, so a sensor that
    is unplugged after startup (or plugged in later) is handled the same
    way rather than latching a permanent failure.
    """

    def __init__(self, bus: I2CBus | None, address: int = DEFAULT_ADDRESS) -> None:
        self.bus = bus
        self.address = address

    @classmethod
    def open(cls, bus_number: int = 1, address: int = DEFAULT_ADDRESS) -> LightSensor:
        return cls(_open_bus(bus_number), address=address)

    def read_lux(self) -> float | None:
        if self.bus is None:
            return None
        try:
            self.bus.write_byte(self.address, _CONTINUOUS_HIGH_RES_MODE)
            data = self.bus.read_i2c_block_data(self.address, _CONTINUOUS_HIGH_RES_MODE, 2)
            # Decoded inside the try: a short read from flaky wiring raises
            # IndexError here, and must degrade to None like a bus error (#63).
            return ((data[0] << 8) | data[1]) / 1.2
        except (OSError, IndexError) as exc:
            log.debug("Light sensor read failed: %r", exc)
            return None
