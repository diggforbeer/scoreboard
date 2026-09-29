"""Button: short vs long press through the real gpiozero.Button, and that a
missing library or unclaimable pin degrades to None rather than raising.

Drives gpiozero's own MockFactory rather than a hand-rolled fake: the
press/hold/release event logic being relied on is gpiozero's, so it's what
runs here. Mock pins fire when_pressed/when_released synchronously on the
thread that drives them, while when_held still comes from gpiozero's real
hold-timer thread -- the same cross-thread shape as on hardware.
"""

from __future__ import annotations

import builtins
import time

from nhl_scoreboard.button import Button

PIN = 26
#: Short enough to keep the suite fast; the wrapper takes whatever it's
#: given -- the 0.5s floor is ButtonConfig's, not Button's.
HOLD = 0.1


def wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def long_press(button: Button, pin) -> None:
    pin.drive_low()
    # Wait for gpiozero's hold thread to have actually run our when_held
    # callback (not just flipped is_held, which it does first), rather than
    # sleeping a fixed amount a slow CI runner might not honour.
    assert wait_for(lambda: button._long_press)
    pin.drive_high()


def test_short_press_is_a_short_press_only(mock_pins):
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    pin = mock_pins.pin(PIN)

    pin.drive_low()
    pin.drive_high()

    assert button.consume_short_press() is True
    assert button.consume_long_press() is False


def test_long_press_is_a_long_press_only(mock_pins):
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    pin = mock_pins.pin(PIN)

    long_press(button, pin)

    assert button.consume_long_press() is True
    assert button.consume_short_press() is False, "the release ending a hold is not a tap"


def test_presses_are_consumed_once(mock_pins):
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    pin = mock_pins.pin(PIN)

    pin.drive_low()
    pin.drive_high()
    long_press(button, pin)

    assert button.consume_short_press() is True
    assert button.consume_short_press() is False
    assert button.consume_long_press() is True
    assert button.consume_long_press() is False


def test_a_tap_after_a_hold_still_counts(mock_pins):
    """The held-this-press tracking resets on every new press."""
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    pin = mock_pins.pin(PIN)

    long_press(button, pin)
    button.consume_long_press()
    pin.drive_low()
    pin.drive_high()

    assert button.consume_short_press() is True
    assert button.consume_long_press() is False


def test_nothing_pressed_consumes_nothing(mock_pins):
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    assert button.consume_short_press() is False
    assert button.consume_long_press() is False


def test_close_releases_the_pin_for_a_rebuild(mock_pins):
    button = Button.open(PIN, hold_seconds=HOLD)
    assert button is not None
    button.close()
    assert button._device.closed
    assert Button.open(PIN, hold_seconds=HOLD) is not None


def test_open_with_pin_already_in_use_is_none(mock_pins):
    first = Button.open(PIN, hold_seconds=HOLD)
    assert first is not None
    # gpiozero raises GPIOPinInUse for a pin this process already holds.
    assert Button.open(PIN, hold_seconds=HOLD) is None


def test_open_with_no_gpiozero_installed_is_none(monkeypatch):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "gpiozero" or name.startswith("gpiozero."):
            raise ImportError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    assert Button.open(PIN, hold_seconds=HOLD) is None
