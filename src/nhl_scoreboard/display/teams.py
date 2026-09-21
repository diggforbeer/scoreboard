"""Per-team accent colours, tuned for an LED matrix.

Several NHL identities are near-black navy or burgundy, which disappear on an
LED matrix. Those are substituted with the team's brighter secondary colour so
every abbreviation stays legible at low brightness.
"""

from __future__ import annotations

#: abbrev -> (r, g, b)
TEAM_COLORS: dict[str, tuple[int, int, int]] = {
    "ANA": (252, 76, 2),
    "BOS": (255, 184, 28),
    "BUF": (252, 181, 20),  # navy -> gold
    "CAR": (226, 24, 54),
    "CBJ": (0, 106, 214),  # navy -> brighter blue
    "CGY": (210, 0, 28),
    "CHI": (207, 10, 44),
    "COL": (198, 39, 77),  # burgundy -> lifted
    "DAL": (0, 168, 89),
    "DET": (206, 17, 38),
    "EDM": (255, 76, 0),
    "FLA": (200, 16, 46),
    "LAK": (200, 200, 200),  # black/silver -> silver
    "MIN": (0, 176, 104),  # deep green -> lifted
    "MTL": (191, 30, 45),
    "NJD": (206, 17, 38),
    "NSH": (255, 184, 28),
    "NYI": (0, 110, 200),
    "NYR": (0, 82, 224),
    "OTT": (218, 26, 50),
    "PHI": (247, 73, 2),
    "PIT": (252, 181, 20),
    "SEA": (153, 217, 217),
    "SJS": (0, 160, 172),  # teal -> lifted
    "STL": (0, 104, 255),
    "TBL": (0, 92, 224),  # navy -> brighter blue
    "TOR": (0, 114, 206),  # navy -> brighter blue
    "UTA": (108, 172, 228),
    "VAN": (0, 168, 78),
    "VGK": (200, 168, 96),
    "WPG": (0, 118, 196),  # navy -> brighter blue
    "WSH": (200, 16, 46),
}

DEFAULT_COLOR = (220, 220, 220)


def team_color(abbrev: str) -> tuple[int, int, int]:
    return TEAM_COLORS.get(abbrev.strip().upper(), DEFAULT_COLOR)
