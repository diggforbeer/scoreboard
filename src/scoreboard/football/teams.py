"""The 32 football teams (#347): names, ESPN ids and LED-tuned colours.

Kept apart from ``display/teams.py`` on purpose. Football and hockey abbreviations
overlap (``BUF``, ``CAR``, ``DAL``, ``DET``, ``MIN`` and others) and mean
different teams, so the two tables must never be merged or looked up across.
Nothing in here imports the hockey table.

Ids, cities and nicknames are ESPN's own (``site.api.espn.com/apis/site/v2/
sports/football/nfl/teams``), pinned by a test. Colours are tuned for an LED
matrix the way the hockey ones are: several real primaries are navy, dark green,
brown or black and vanish on the panel, so those are substituted with the team's
brighter accent or a lifted shade of the same hue.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

RGB = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class FootballTeam:
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


def _t(abbrev, espn_id, city, nickname, name, color, secondary) -> FootballTeam:
    return FootballTeam(abbrev, espn_id, city, nickname, name, color, secondary)


#: In ESPN's alphabetical order by abbreviation.
_TEAMS: tuple[FootballTeam, ...] = (
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


@dataclass(frozen=True, slots=True)
class Directory:
    """One league's teams: looked up by abbreviation or by ESPN id.

    The NFL's 32 and the FBS's ~138 share abbreviations (``CIN``, ``HOU``, ``MIA``) and ESPN ids
    (Auburn and the Bills are both 2), so a lookup is only meaningful *inside* a league. The
    module-level functions below (``team``, ``team_by_id``, ``team_color``, ``is_team``...) answer
    from the **active** directory: the NFL's unless a ``use_directory`` block says otherwise, so
    the ~20 files that call them need not know there are two leagues.
    """

    league: str
    by_abbrev: Mapping[str, FootballTeam]
    by_id: Mapping[int, FootballTeam]

    @staticmethod
    def of(league: str, teams: Iterable[FootballTeam]) -> Directory:
        listed = tuple(teams)
        return Directory(
            league,
            {t.abbrev: t for t in listed},
            {t.espn_id: t for t in listed},
        )

    def __len__(self) -> int:
        return len(self.by_abbrev)


NFL_DIRECTORY = Directory.of("nfl", _TEAMS)
#: A league with no teams yet (the college table is fetched). Every lookup misses, so a game is
#: drawn with the plain "unknown team" look rather than with another league's colours.
EMPTY_DIRECTORY = Directory("none", {}, {})

TEAMS: dict[str, FootballTeam] = dict(NFL_DIRECTORY.by_abbrev)
_BY_ID: dict[int, FootballTeam] = dict(NFL_DIRECTORY.by_id)

#: The abbreviations the favourite and followed pickers accept (#348).
ABBREVIATIONS: tuple[str, ...] = tuple(sorted(TEAMS))

_ACTIVE: ContextVar[Directory] = ContextVar("football_directory", default=NFL_DIRECTORY)


@contextmanager
def use_directory(directory: Directory) -> Iterator[None]:
    """Resolve every lookup in this module against ``directory`` inside the block (``holiday.
    use_sport`` is the same idea for colours). Context-local, so a worker thread sees the NFL's
    unless it enters its own block: the client does that for its own parsing."""
    token = _ACTIVE.set(directory)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active_directory() -> Directory:
    return _ACTIVE.get()


class UnknownTeamError(KeyError):
    """An abbreviation or id that is not one of the active league's teams."""

    def __str__(self) -> str:  # KeyError would repr() the message
        return str(self.args[0])


def is_team(abbrev: str) -> bool:
    """Whether ``abbrev`` is a team of the active league (the NFL's unless told otherwise)."""
    return str(abbrev).strip().upper() in _ACTIVE.get().by_abbrev


def is_nfl_team(abbrev: str) -> bool:
    """Whether ``abbrev`` is one of the 32 NFL clubs, whatever league is active (the config's
    validation of a ``football`` entry must never depend on what is being drawn)."""
    return str(abbrev).strip().upper() in NFL_DIRECTORY.by_abbrev


#: The night games a ranked list can follow as if they were teams: ``TNF``, ``SNF`` and ``MNF`` are
#: every game kicking off on a Thursday, Sunday or Monday evening Eastern time. They are not in
#: ``TEAMS`` (which is pinned to the 32 clubs); the abbreviations are what ``[[teams]]`` stores.
NIGHT_SLOTS: dict[str, str] = {
    "TNF": "Thursday Night Football",
    "SNF": "Sunday Night Football",
    "MNF": "Monday Night Football",
}
_SLOT_DAY = {"TNF": 3, "SNF": 6, "MNF": 0}  # Python weekday: Monday 0 ... Sunday 6
#: The league schedules its night games in Eastern time; "evening" is 7pm on.
_SLOT_ZONE = "America/New_York"
_EVENING_HOUR = 19


def is_slot(abbrev: str) -> bool:
    return str(abbrev).strip().upper() in NIGHT_SLOTS


def in_night_slot(slot: str, start_utc: datetime | None) -> bool:
    """Whether a game kicking off at ``start_utc`` is in the ``SNF`` / ``MNF`` slot."""
    key = str(slot).strip().upper()
    if key not in _SLOT_DAY or start_utc is None:
        return False
    local = start_utc.astimezone(ZoneInfo(_SLOT_ZONE))
    return local.weekday() == _SLOT_DAY[key] and local.hour >= _EVENING_HOUR


def team(abbrev: str) -> FootballTeam:
    """The team for an abbreviation (case and spaces ignored); raises if unknown."""
    key = str(abbrev).strip().upper()
    try:
        return _ACTIVE.get().by_abbrev[key]
    except KeyError:
        raise UnknownTeamError(f"{abbrev!r} is not a football team abbreviation") from None


def team_by_id(espn_id: int | str) -> FootballTeam:
    """The team for an ESPN team id, given as an int or the string the feed uses."""
    try:
        return _ACTIVE.get().by_id[int(espn_id)]
    except (KeyError, TypeError, ValueError):
        raise UnknownTeamError(f"{espn_id!r} is not an ESPN football team id") from None


def team_color(abbrev: str) -> RGB:
    return team(abbrev).color


def team_secondary_color(abbrev: str) -> RGB:
    return team(abbrev).secondary


def team_name(abbrev: str) -> str:
    return team(abbrev).name
