"""Backend selection for the LED matrix.

On the Pi this is Henner Zeller's ``rgbmatrix`` binding driving the HUB75
chain. On a development machine it falls back to ``RGBMatrixEmulator``, which
implements the same API against a browser window, and finally to a headless
no-op so tests can run anywhere.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..config import PanelConfig

log = logging.getLogger(__name__)

HARDWARE = "rgbmatrix"
EMULATOR = "RGBMatrixEmulator"


@dataclass(slots=True)
class Backend:
    """The three symbols every backend exposes, plus which one we got."""

    name: str
    RGBMatrix: Any
    RGBMatrixOptions: Any
    graphics: Any

    @property
    def is_hardware(self) -> bool:
        return self.name == HARDWARE


def load_backend(prefer: str | None = None) -> Backend:
    """Import the best available matrix backend.

    ``prefer`` forces a specific one (``"rgbmatrix"`` or ``"RGBMatrixEmulator"``)
    and raises if it is missing, which is what CI and the systemd unit want --
    silently emulating on real hardware would be worse than failing loudly.
    """
    order = [prefer] if prefer else [HARDWARE, EMULATOR]
    errors: list[str] = []
    for module_name in order:
        try:
            module = __import__(module_name, fromlist=["RGBMatrix", "RGBMatrixOptions", "graphics"])
        except ImportError as exc:
            errors.append(f"{module_name}: {exc}")
            continue
        log.info("Using LED matrix backend: %s", module_name)
        return Backend(
            name=module_name,
            RGBMatrix=module.RGBMatrix,
            RGBMatrixOptions=module.RGBMatrixOptions,
            graphics=module.graphics,
        )
    raise ImportError("No LED matrix backend available. Tried -> " + "; ".join(errors))


def build_options(backend: Backend, panel: PanelConfig) -> Any:
    """Translate our PanelConfig onto the backend's options object."""
    options = backend.RGBMatrixOptions()
    wanted = {
        "rows": panel.rows,
        "cols": panel.cols,
        "chain_length": panel.chain_length,
        "parallel": panel.parallel,
        "hardware_mapping": panel.hardware_mapping,
        "gpio_slowdown": panel.gpio_slowdown,
        "pwm_bits": panel.pwm_bits,
        "pwm_lsb_nanoseconds": panel.pwm_lsb_nanoseconds,
        "brightness": panel.brightness,
        "limit_refresh_rate_hz": panel.limit_refresh_rate_hz,
        "disable_hardware_pulsing": panel.disable_hardware_pulsing,
        "drop_privileges": False,
    }
    for key, value in wanted.items():
        try:
            setattr(options, key, value)
        except (AttributeError, TypeError):
            # The emulator implements a subset; hardware-only knobs are noise there.
            log.debug("Backend %s ignores option %s", backend.name, key)
    return options


def create_matrix(panel: PanelConfig, backend: Backend | None = None) -> tuple[Any, Backend]:
    backend = backend or load_backend()
    matrix = backend.RGBMatrix(options=build_options(backend, panel))
    log.info("Matrix ready: %dx%d via %s", panel.width, panel.height, backend.name)
    return matrix, backend
