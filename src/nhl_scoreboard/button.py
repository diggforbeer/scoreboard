"""Physical push-button control via GPIO (#50).

A momentary push-button, one leg to the chosen GPIO pin, the other to
GND -- gpiozero's default pull_up=True means the pin reads HIGH normally
and LOW when pressed, no external resistor needed.

Short press: mute the goal horn for a while. Long press (held past
hold_seconds): force the next rotation. Degrades to doing nothing if
gpiozero isn't installed or the pin can't be claimed, same convention as
light_sensor.py and audio.py -- hardware that isn't there is never a
crash, just a no-op.

Thread safety: gpiozero fires ``when_pressed``/``when_released`` from its
pin-monitoring thread and ``when_held`` from a separate hold-timer thread,
never from ``ScoreboardApp.run()``'s loop. The callbacks here therefore
only ever set plain ``bool`` flags (a single attribute store, atomic under
the GIL); ``run()`` reads-and-clears them via ``consume_short_press()``/
``consume_long_press()`` on its own thread and does every actual state
change there -- the same "background thread never touches live app state"
rule status_server.py follows for its request thread.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _claim_errors() -> tuple[type[BaseException], ...]:
    """What gpiozero (or the backend under it) raises when a pin can't be had.

    ``GPIOZeroError`` covers gpiozero's own failures -- ``BadPinFactory``
    when no backend loads at all (not a Pi, no /dev/gpiomem), and
    ``GPIOPinInUse`` when this process already holds the pin. Below that,
    backends raise their own types when the OS refuses the pin: the native
    factory an ``OSError`` (/dev/gpiomem permissions), RPi.GPIO a
    ``RuntimeError``, lgpio its own ``lgpio.error`` (e.g. "GPIO busy" when
    another process claimed the line). Anything else is a real bug and is
    left to propagate.
    """
    from gpiozero.exc import GPIOZeroError

    errors: list[type[BaseException]] = [GPIOZeroError, OSError, RuntimeError]
    try:
        import lgpio
    except ImportError:
        pass
    else:
        errors.append(lgpio.error)
    return tuple(errors)


class Button:
    """Wraps a ``gpiozero.Button`` and turns its events into consumable flags.

    Only ever constructed around a real, working device -- ``open()``
    returns ``None`` instead when there's no button to be had, so
    ``ScoreboardApp.button`` is either this or ``None``, nothing between.
    """

    def __init__(self, device: Any) -> None:
        self._device = device
        #: Whether when_held already fired for the current press, so the
        #: release that ends a long press isn't also counted as a short one.
        #: Only touched from gpiozero's own threads, never from run()'s.
        self._held_this_press = False
        self._short_press = False
        self._long_press = False
        device.when_pressed = self._on_pressed
        device.when_held = self._on_held
        device.when_released = self._on_released

    @classmethod
    def open(cls, pin: int, hold_seconds: float) -> Button | None:
        try:
            from gpiozero import Button as GPIOButton
        except ImportError:
            log.info("gpiozero not installed; physical button disabled")
            return None
        try:
            device = GPIOButton(pin, hold_time=hold_seconds)
        except _claim_errors() as exc:
            log.info("GPIO %d unavailable: %s; physical button disabled", pin, exc)
            return None
        log.info("Physical button on GPIO %d (hold %.1fs for next rotation)", pin, hold_seconds)
        return cls(device)

    # -- gpiozero callbacks: background threads, flags only -----------------

    def _on_pressed(self) -> None:
        self._held_this_press = False

    def _on_held(self) -> None:
        self._held_this_press = True
        self._long_press = True

    def _on_released(self) -> None:
        if not self._held_this_press:
            self._short_press = True

    # -- run()'s thread ----------------------------------------------------

    def consume_short_press(self) -> bool:
        """True once per short press since the last call.

        No lock: the worst interleaving (a second press landing between the
        read and the clear) folds two presses inside one 0.5s frame into
        one, which for "mute" is the same outcome anyway.
        """
        if self._short_press:
            self._short_press = False
            return True
        return False

    def consume_long_press(self) -> bool:
        """True once per long press since the last call."""
        if self._long_press:
            self._long_press = False
            return True
        return False

    def close(self) -> None:
        """Release the GPIO pin, so a config reload can reclaim it (or another pin)."""
        self._device.close()
