"""ScoreboardApp.refresh_brightness: wiring a LightSensor to the matrix (#44).

A fake sensor stands in for LightSensor so these never touch I2C; a fake
matrix records what brightness ends up applied.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhl_scoreboard.app import ScoreboardApp
from nhl_scoreboard.brightness import lux_to_brightness
from nhl_scoreboard.config import Settings
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.models import Game
from test_app import FakeClient, FakeGraphics, FakeMatrix, FakeOptions


class FakeLightSensor:
    def __init__(self, lux: float | None) -> None:
        self.lux = lux
        self.calls = 0

    def read_lux(self) -> float | None:
        self.calls += 1
        return self.lux


class NoBrightnessMatrix(FakeMatrix):
    """A backend whose canvas has no settable brightness at all."""

    @property
    def brightness(self):
        raise AttributeError("no such attribute")

    @brightness.setter
    def brightness(self, _value):
        raise AttributeError("brightness is not settable on this backend")


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


@pytest.fixture
def games() -> list[Game]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())
    return [Game.from_api(raw) for raw in payload["games"]]


def build_app(fake_backend, games, sensor, **panel_kwargs) -> ScoreboardApp:
    settings = Settings()
    settings.panel.auto_brightness = True
    for key, value in panel_kwargs.items():
        setattr(settings.panel, key, value)
    return ScoreboardApp(
        settings, client=FakeClient(games), backend=fake_backend, light_sensor=sensor
    )


def test_auto_brightness_off_by_default_no_sensor_probed(fake_backend, games):
    app = ScoreboardApp(Settings(), client=FakeClient(games), backend=fake_backend)
    assert app.light_sensor is None
    app.refresh_brightness()  # no-op, must not raise
    assert not hasattr(app.matrix, "brightness"), "never touched the matrix at all"


def test_dark_room_dims_toward_min_brightness(fake_backend, games):
    sensor = FakeLightSensor(lux=0)
    app = build_app(fake_backend, games, sensor, min_brightness=10, max_brightness=100)
    app.refresh_brightness()
    assert sensor.calls == 1
    assert app.matrix.brightness == 10


def test_bright_room_moves_toward_max_brightness(fake_backend, games):
    sensor = FakeLightSensor(lux=5000)
    app = build_app(fake_backend, games, sensor, min_brightness=10, max_brightness=100)
    app.refresh_brightness()
    assert app.matrix.brightness == 100


def test_sensor_returning_none_leaves_brightness_untouched(fake_backend, games):
    sensor = FakeLightSensor(lux=None)
    app = build_app(fake_backend, games, sensor)
    app.refresh_brightness()
    assert app._applied_brightness == app.settings.panel.brightness
    assert not hasattr(app.matrix, "brightness"), "never touched the matrix at all"


def test_unchanged_target_does_not_rewrite_matrix_brightness(fake_backend, games):
    """Constant light shouldn't keep poking the matrix every poll."""
    sensor = FakeLightSensor(lux=0)
    app = build_app(fake_backend, games, sensor, min_brightness=10, max_brightness=100)
    app.refresh_brightness()
    app.matrix.brightness = "sentinel"
    app.refresh_brightness()
    assert app.matrix.brightness == "sentinel"


def test_a_big_jump_is_smoothed_not_applied_in_one_step(fake_backend, games):
    sensor = FakeLightSensor(lux=0)
    app = build_app(fake_backend, games, sensor, min_brightness=10, max_brightness=100)
    app.refresh_brightness()
    assert app.matrix.brightness == 10

    sensor.lux = 300  # room lights just came on
    target = lux_to_brightness(sensor.lux, 10, 100)
    app.refresh_brightness()
    first_jump = app.matrix.brightness
    assert 10 < first_jump < target, "should ease toward the new reading, not jump straight to it"

    for _ in range(30):
        app.refresh_brightness()
    assert app.matrix.brightness == target, "should converge given enough samples"


def test_backend_without_settable_brightness_does_not_raise(games):
    backend = Backend("fake", NoBrightnessMatrix, FakeOptions, FakeGraphics)
    sensor = FakeLightSensor(lux=5000)
    app = build_app(backend, games, sensor, min_brightness=10, max_brightness=100)
    app.refresh_brightness()  # must not raise despite the matrix rejecting the setattr
