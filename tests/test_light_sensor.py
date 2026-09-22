"""LightSensor: BH1750 lux decoding, and that a missing/misbehaving sensor
degrades to None rather than raising.

A fake I2C bus stands in for smbus2/smbus so these never touch real
hardware or need the library installed.
"""

from __future__ import annotations

from nhl_scoreboard.light_sensor import DEFAULT_ADDRESS, LightSensor


class FakeBus:
    def __init__(self, response: list[int] | None = None, raises: Exception | None = None) -> None:
        self.response = response or [0x01, 0x90]  # 400 / 1.2 = ~333 lux
        self.raises = raises
        self.writes: list[tuple[int, int]] = []
        self.reads: list[tuple[int, int, int]] = []

    def write_byte(self, address: int, value: int) -> None:
        if self.raises:
            raise self.raises
        self.writes.append((address, value))

    def read_i2c_block_data(self, address: int, register: int, length: int) -> list[int]:
        if self.raises:
            raise self.raises
        self.reads.append((address, register, length))
        return self.response


def test_read_lux_decodes_the_two_byte_reading():
    bus = FakeBus(response=[0x01, 0x90])  # 400 raw -> 400 / 1.2 lux
    sensor = LightSensor(bus)
    assert sensor.read_lux() == 400 / 1.2
    assert bus.writes == [(DEFAULT_ADDRESS, 0x10)]
    assert bus.reads == [(DEFAULT_ADDRESS, 0x10, 2)]


def test_no_bus_reads_as_none_without_touching_anything():
    sensor = LightSensor(None)
    assert sensor.read_lux() is None


def test_bus_error_reads_as_none_not_raised():
    bus = FakeBus(raises=OSError("Remote I/O error"))
    sensor = LightSensor(bus)
    assert sensor.read_lux() is None


def test_a_sensor_that_recovers_is_read_again_not_latched_off():
    bus = FakeBus(response=[0x01, 0x90], raises=OSError("Remote I/O error"))
    sensor = LightSensor(bus)
    assert sensor.read_lux() is None
    bus.raises = None
    assert sensor.read_lux() == 400 / 1.2


def test_custom_address_is_used():
    bus = FakeBus()
    sensor = LightSensor(bus, address=0x5C)
    sensor.read_lux()
    assert bus.writes == [(0x5C, 0x10)]


def test_open_with_no_i2c_library_falls_back_to_none_bus(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name in ("smbus2", "smbus"):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    sensor = LightSensor.open()
    assert sensor.bus is None
    assert sensor.read_lux() is None


def test_open_with_no_such_i2c_bus_falls_back_to_none_bus(monkeypatch):
    import smbus2

    def raise_oserror(_bus_number):
        raise OSError("No such device or address")

    monkeypatch.setattr(smbus2, "SMBus", raise_oserror)
    sensor = LightSensor.open(bus_number=99)
    assert sensor.bus is None
