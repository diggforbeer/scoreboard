"""The 32 NFL teams (#347): names, ESPN ids and LED-tuned colours.

Kept apart from ``display/teams.py`` on purpose. NFL and NHL abbreviations
overlap (``BUF``, ``CAR``, ``DAL``, ``DET``, ``MIN`` and others) and mean
different teams, so the two tables must never be merged or looked up across.
Nothing in here imports the NHL table.

Ids, cities and nicknames are ESPN's own (``site.api.espn.com/apis/site/v2/
sports/football/nfl/teams``), pinned by a test. Colours are tuned for an LED
matrix the way the NHL ones are: several real primaries are navy, dark green,
brown or black and vanish on the panel, so those are substituted with the team's
brighter accent or a lifted shade of the same hue.
"""

from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class NflTeam:
    abbrev: str  #: ESPN's abbreviation: ``NYG``, ``WSH``
    espn_id: int
    city: str
    nickname: str
    #: What a full-panel screen shows under the headline, upper case and short
    #: enough for the panel; the two New York and two Los Angeles teams carry
    #: their nickname so they can be told apart.
    name: str
    color: RGB  #: the team's LED-tuned primary
    secondary: RGB  #: a second accent, also LED-tuned


def _t(abbrev, espn_id, city, nickname, name, color, secondary) -> NflTeam:
    return NflTeam(abbrev, espn_id, city, nickname, name, color, secondary)


#: In ESPN's alphabetical order by abbreviation.
_TEAMS: tuple[NflTeam, ...] = (
    _t("ARI", 22, "Arizona", "Cardinals", "ARIZONA", (226, 36, 66), (255, 255, 255)),
    _t(
        "ATL", 1, "Atlanta", "Falcons", "ATLANTA", (230, 30, 60), (190, 190, 190)
    ),  # black -> silver
    _t(
        "BAL", 33, "Baltimore", "Ravens", "BALTIMORE", (130, 60, 220), (200, 160, 30)
    ),  # purple, lifted
    _t("BUF", 2, "Buffalo", "Bills", "BUFFALO", (0, 100, 235), (230, 40, 40)),  # navy -> blue
    _t("CAR", 29, "Carolina", "Panthers", "CAROLINA", (0, 133, 202), (185, 190, 195)),
    _t("CHI", 3, "Chicago", "Bears", "CHICAGO", (230, 65, 0), (60, 110, 220)),  # navy -> orange
    _t("CIN", 4, "Cincinnati", "Bengals", "CINCINNATI", (251, 79, 20), (255, 255, 255)),
    _t(
        "CLE", 5, "Cleveland", "Browns", "CLEVELAND", (255, 70, 0), (255, 255, 255)
    ),  # brown -> orange
    _t("DAL", 6, "Dallas", "Cowboys", "DALLAS", (40, 110, 210), (176, 183, 188)),  # navy, lifted
    _t("DEN", 7, "Denver", "Broncos", "DENVER", (252, 76, 2), (40, 100, 200)),  # navy -> orange
    _t("DET", 8, "Detroit", "Lions", "DETROIT", (0, 118, 182), (187, 187, 187)),
    _t(
        "GB", 9, "Green Bay", "Packers", "GREEN BAY", (40, 160, 85), (255, 182, 18)
    ),  # green, lifted
    _t("HOU", 34, "Houston", "Texans", "HOUSTON", (240, 20, 50), (40, 100, 200)),  # navy -> red
    _t("IND", 11, "Indianapolis", "Colts", "INDIANAPOLIS", (0, 100, 200), (255, 255, 255)),
    _t("JAX", 30, "Jacksonville", "Jaguars", "JACKSONVILLE", (0, 116, 135), (215, 162, 42)),
    _t("KC", 12, "Kansas City", "Chiefs", "KANSAS CITY", (227, 24, 55), (255, 182, 18)),
    _t(
        "LV", 13, "Las Vegas", "Raiders", "LAS VEGAS", (165, 172, 175), (255, 255, 255)
    ),  # black -> silver
    _t("LAC", 24, "Los Angeles", "Chargers", "LA CHARGERS", (0, 128, 198), (255, 194, 14)),
    _t("LAR", 14, "Los Angeles", "Rams", "LA RAMS", (20, 95, 215), (255, 209, 0)),  # navy, lifted
    _t("MIA", 15, "Miami", "Dolphins", "MIAMI", (0, 142, 151), (252, 76, 2)),
    _t(
        "MIN", 16, "Minnesota", "Vikings", "MINNESOTA", (130, 70, 200), (255, 198, 47)
    ),  # purple, lifted
    _t(
        "NE", 17, "New England", "Patriots", "NEW ENGLAND", (225, 30, 60), (50, 100, 200)
    ),  # navy -> red
    _t("NO", 18, "New Orleans", "Saints", "NEW ORLEANS", (211, 188, 141), (255, 255, 255)),
    _t("NYG", 19, "New York", "Giants", "NY GIANTS", (40, 110, 255), (201, 36, 63)),  # navy, lifted
    _t("NYJ", 20, "New York", "Jets", "NY JETS", (30, 150, 90), (255, 255, 255)),  # green, lifted
    _t("PHI", 21, "Philadelphia", "Eagles", "PHILADELPHIA", (0, 130, 120), (190, 195, 200)),
    _t(
        "PIT", 23, "Pittsburgh", "Steelers", "PITTSBURGH", (255, 182, 18), (255, 255, 255)
    ),  # black -> gold
    _t("SF", 25, "San Francisco", "49ers", "SAN FRAN", (220, 20, 30), (200, 170, 90)),
    _t(
        "SEA", 26, "Seattle", "Seahawks", "SEATTLE", (105, 190, 40), (40, 100, 200)
    ),  # navy -> green
    _t("TB", 27, "Tampa Bay", "Buccaneers", "TAMPA BAY", (215, 35, 60), (160, 155, 145)),
    _t("TEN", 10, "Tennessee", "Titans", "TENNESSEE", (68, 149, 210), (225, 30, 60)),
    _t(
        "WSH", 28, "Washington", "Commanders", "WASHINGTON", (255, 184, 28), (255, 255, 255)
    ),  # burgundy -> gold
)

TEAMS: dict[str, NflTeam] = {t.abbrev: t for t in _TEAMS}
_BY_ID: dict[int, NflTeam] = {t.espn_id: t for t in _TEAMS}

#: The abbreviations the favourite and followed pickers accept (#348).
ABBREVIATIONS: tuple[str, ...] = tuple(sorted(TEAMS))


class UnknownTeamError(KeyError):
    """An abbreviation or id that is not one of the 32 NFL teams."""

    def __str__(self) -> str:  # KeyError would repr() the message
        return str(self.args[0])


def is_team(abbrev: str) -> bool:
    return str(abbrev).strip().upper() in TEAMS


def team(abbrev: str) -> NflTeam:
    """The team for an abbreviation (case and spaces ignored); raises if unknown."""
    key = str(abbrev).strip().upper()
    try:
        return TEAMS[key]
    except KeyError:
        raise UnknownTeamError(f"{abbrev!r} is not an NFL team abbreviation") from None


def team_by_id(espn_id: int | str) -> NflTeam:
    """The team for an ESPN team id, given as an int or the string the feed uses."""
    try:
        return _BY_ID[int(espn_id)]
    except (KeyError, TypeError, ValueError):
        raise UnknownTeamError(f"{espn_id!r} is not an ESPN NFL team id") from None


def team_color(abbrev: str) -> RGB:
    return team(abbrev).color


def team_secondary_color(abbrev: str) -> RGB:
    return team(abbrev).secondary


def team_name(abbrev: str) -> str:
    return team(abbrev).name
