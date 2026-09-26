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


#: abbrev -> (r, g, b), a second accent colour distinct from TEAM_COLORS.
#:
#: Scoped to the idle clock scene (#123): kept separate from TEAM_COLORS so
#: nothing that already depends on team_color()'s single-colour contract
#: (game score text, standings rows, and the tests asserting on them) has to
#: change. Real secondaries that are black, near-black, or otherwise too dim
#: to read on an LED matrix are substituted the same way TEAM_COLORS already
#: does for navy/burgundy primaries -- usually with the team's actual gold,
#: red, or blue accent instead of a literal black-to-white swap.
TEAM_SECONDARY_COLORS: dict[str, tuple[int, int, int]] = {
    "ANA": (190, 160, 100),  # gold
    "BOS": (255, 255, 255),  # black -> white
    "BUF": (0, 90, 180),  # navy, lifted (primary already uses BUF's gold)
    "CAR": (185, 190, 195),  # "storm surge" grey
    "CBJ": (206, 17, 38),  # red
    "CGY": (250, 190, 40),  # gold
    "CHI": (240, 180, 60),  # old gold
    "COL": (35, 140, 210),  # blue
    "DAL": (190, 190, 190),  # silver
    "DET": (255, 255, 255),  # white
    "EDM": (30, 100, 200),  # navy, lifted
    "FLA": (200, 165, 90),  # gold
    "LAK": (60, 110, 190),  # forum blue
    "MIN": (220, 175, 60),  # gold
    "MTL": (30, 70, 180),  # blue
    "NJD": (255, 255, 255),  # black -> white
    "NSH": (30, 100, 190),  # navy, lifted (primary already uses NSH's gold)
    "NYI": (255, 140, 0),  # orange
    "NYR": (220, 20, 50),  # red
    "OTT": (200, 160, 60),  # gold
    "PHI": (255, 255, 255),  # black -> white
    "PIT": (255, 255, 255),  # black -> white
    "SEA": (233, 20, 40),  # "boot red"
    "SJS": (234, 120, 20),  # burnt orange
    "STL": (250, 180, 20),  # gold
    "TBL": (255, 255, 255),  # white
    "TOR": (255, 255, 255),  # white
    "UTA": (255, 255, 255),  # white
    "VAN": (20, 80, 170),  # navy, lifted
    "VGK": (200, 20, 44),  # red
    "WPG": (200, 20, 40),  # red
    "WSH": (20, 90, 190),  # navy, lifted
}


def team_secondary_color(abbrev: str) -> tuple[int, int, int]:
    return TEAM_SECONDARY_COLORS.get(abbrev.strip().upper(), DEFAULT_COLOR)
