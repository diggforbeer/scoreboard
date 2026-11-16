"""Lux -> LED brightness mapping for auto-dimming (#44).

Both human brightness perception and a cheap ambient sensor's usable range
are roughly logarithmic, not linear: the difference between 1 lux and 10 lux
(a dark room vs. a dim lamp) should move the panel about as much as 10 lux
to 100 lux (a dim lamp vs. normal room light). A linear map spends nearly
its whole range on the first few lux and then goes flat for the rest of a
typical room's brightness swing.
"""

from __future__ import annotations

import math

#: Lux at and beyond which the panel is already at max_brightness. This is
#: "a brightly lit room", not direct sunlight -- a living-room display never
#: needs to out-shine a window, and this board has no sensor housing rated
#: for outdoor use anyway.
REFERENCE_LUX = 1000.0


def lux_to_brightness(lux: float, min_brightness: int, max_brightness: int) -> int:
    """Map a lux reading onto ``[min_brightness, max_brightness]``."""
    lux = max(lux, 0.0)
    span = max_brightness - min_brightness
    fraction = math.log1p(lux) / math.log1p(REFERENCE_LUX)
    fraction = min(max(fraction, 0.0), 1.0)
    return round(min_brightness + span * fraction)
