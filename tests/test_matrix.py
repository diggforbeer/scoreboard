"""Backend selection and option translation.

No real hardware or emulator needed: a bare object with the attributes
RGBMatrixOptions would have stands in, so these run anywhere.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.config import PanelConfig
from nhl_scoreboard.display.matrix import Backend, build_options, load_backend


class FakeOptions:
    """Accepts any attribute -- mirrors the real RGBMatrixOptions surface."""


def fake_backend() -> Backend:
    return Backend(name="fake", RGBMatrix=object, RGBMatrixOptions=FakeOptions, graphics=object)


def test_build_options_translates_every_panel_field():
    panel = PanelConfig(
        rows=32,
        cols=64,
        chain_length=2,
        parallel=1,
        hardware_mapping="regular",
        rgb_sequence="RGB",
        gpio_slowdown=4,
        pwm_bits=11,
        pwm_lsb_nanoseconds=130,
        brightness=60,
        limit_refresh_rate_hz=0,
        disable_hardware_pulsing=False,
        pixel_mapper="",
    )
    options = build_options(fake_backend(), panel)
    assert options.rows == 32
    assert options.cols == 64
    assert options.chain_length == 2
    assert options.parallel == 1
    assert options.hardware_mapping == "regular"
    assert options.led_rgb_sequence == "RGB"
    assert options.gpio_slowdown == 4
    assert options.pwm_bits == 11
    assert options.pwm_lsb_nanoseconds == 130
    assert options.brightness == 60
    assert options.disable_hardware_pulsing is False
    assert options.pixel_mapper_config == ""
    assert options.drop_privileges is False


def test_pixel_mapper_passed_through_as_pixel_mapper_config():
    """The binding's field is 'pixel_mapper_config'; ours is the shorter 'pixel_mapper'."""
    panel = PanelConfig(pixel_mapper="U-mapper")
    options = build_options(fake_backend(), panel)
    assert options.pixel_mapper_config == "U-mapper"


def test_rgb_sequence_passed_through_as_led_rgb_sequence():
    """The binding's field is 'led_rgb_sequence'; ours is the shorter 'rgb_sequence'."""
    panel = PanelConfig(rgb_sequence="RBG")
    options = build_options(fake_backend(), panel)
    assert options.led_rgb_sequence == "RBG"


def test_chained_pixel_mappers_pass_through_unmodified():
    """rpi-rgb-led-matrix chains mappers with ';'; we don't parse or validate it."""
    panel = PanelConfig(pixel_mapper="U-mapper;Rotate:90")
    options = build_options(fake_backend(), panel)
    assert options.pixel_mapper_config == "U-mapper;Rotate:90"


def test_default_pixel_mapper_is_empty_string_not_none():
    options = build_options(fake_backend(), PanelConfig())
    assert options.pixel_mapper_config == ""


def test_unsupported_option_on_a_backend_is_swallowed_not_fatal():
    """The emulator implements a subset of options; a missing one must not raise."""

    class LimitedOptions:
        def __setattr__(self, name, value):
            if name not in ("rows", "cols"):
                raise AttributeError(name)
            object.__setattr__(self, name, value)

    limited = Backend(
        name="limited", RGBMatrix=object, RGBMatrixOptions=LimitedOptions, graphics=object
    )
    options = build_options(limited, PanelConfig())
    assert options.rows == 32
    assert options.cols == 64


def test_load_backend_raises_with_both_names_when_none_available():
    with pytest.raises(ImportError) as exc_info:
        load_backend("definitely-not-a-real-module")
    assert "definitely-not-a-real-module" in str(exc_info.value)


def test_load_backend_prefers_explicit_choice():
    """RGBMatrixEmulator is a real optional dependency here; use it as the probe."""
    pytest.importorskip("RGBMatrixEmulator")
    backend = load_backend("RGBMatrixEmulator")
    assert backend.name == "RGBMatrixEmulator"
    assert backend.is_hardware is False
