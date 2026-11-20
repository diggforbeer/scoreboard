"""The FBS team table (#540): ids, names, colours and conferences, built from ESPN's feed.

The NFL's 32 teams are a hand-written table (``teams.py``); ~138 college teams are too many to
pin by hand and they change with conference realignment, so this table is *built* from two
requests and cached by the caller (the teams payload alone is 1.8 MB):

* the **standings** (``apis/v2/.../college-football/standings?group=80``) says which teams are
  FBS and which conference each is in. ``/teams`` cannot: it lists all 763 teams of every
  division and ``groups=80`` does not filter it (``football_api.md``, "College football").
* ``/teams`` supplies the colours the standings leave out.

Teams are keyed by **ESPN id**. Abbreviations are only unique within FBS, and even there they
are ESPN's to change: ``OSU`` is Ohio State here but is also an Ohio State Newark, in the full
``/teams`` list.

Colours are LED-tuned by rule, not by hand (:func:`led_colors`): a primary that vanishes on a
panel (navy, black, dark green) is lifted, as ``teams.py`` and ``display/teams.py`` do one by one.
"""

from __future__ import annotations

import colorsys
import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

RGB = tuple[int, int, int]

#: ESPN names this node as the home of the teams with no conference. It sorts last.
INDEPENDENTS = "FBS Independents"

#: A primary below this perceived brightness (0-255) is hard to see on a lit panel.
MIN_LUMA = 70
#: What a lifted colour is brought up to (HSV value) and the least saturation it keeps.
LIFT_VALUE = 0.9
LIFT_SATURATION = 0.55
#: The most a lift will wash a hue out to make it read; below this it would no longer look like it.
MIN_LIFT_SATURATION = 0.35
#: Below this saturation a colour is grey: lifting it would only make a pale grey, so it falls
#: back to the alternate or to ``NEUTRAL``.
GREY_SATURATION = 0.18
NEUTRAL: RGB = (190, 190, 190)
WHITE: RGB = (255, 255, 255)
#: Used when ESPN lists a team with no colour at all.
UNKNOWN_COLOR: RGB = NEUTRAL


@dataclass(frozen=True, slots=True)
class CollegeTeam:
    espn_id: int
    abbrev: str  #: ESPN's abbreviation, unique within FBS: ``UGA``, ``MSU``
    location: str  #: ``Michigan State``
    nickname: str  #: ``Spartans``
    short_name: str  #: ESPN's short form for a tight space: ``Michigan St``
    #: What a full-panel screen shows, upper case: the short form, as the NFL table's ``name``.
    name: str
    conference: str  #: ``Big Ten Conference``
    conference_short: str  #: ``Big Ten``
    color: RGB  #: LED-tuned primary
    secondary: RGB  #: LED-tuned second accent


def _hex_rgb(value: Any) -> RGB | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return None


def _luma(rgb: RGB) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _saturation(rgb: RGB) -> float:
    return colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)[1]


def _lift(rgb: RGB) -> RGB:
    """The same hue, brightened until it reads on an LED.

    Value goes up first. A saturated blue is still dark at full value (pure blue is luma 29), so
    saturation then comes down a step at a time, towards a lighter shade of the hue, until it
    reads: navy becomes the light blue the hand-tuned hockey and NFL tables use.
    """
    h, s, v = colorsys.rgb_to_hsv(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255)
    s, v = max(s, LIFT_SATURATION), max(v, LIFT_VALUE)
    while True:
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        lifted = (round(r * 255), round(g * 255), round(b * 255))
        if _visible(lifted) or s <= MIN_LIFT_SATURATION:
            return lifted
        s = round(s - 0.05, 2)


def _visible(rgb: RGB) -> bool:
    return _luma(rgb) >= MIN_LUMA


def _tuned(rgb: RGB | None, fallback: RGB) -> RGB:
    """``rgb`` as shown: kept if it reads, lifted if a dark hue, else ``fallback``."""
    if rgb is None:
        return fallback
    if _visible(rgb):
        return rgb
    if _saturation(rgb) < GREY_SATURATION:
        return fallback  # black or charcoal: there is no hue to lift
    return _lift(rgb)


def _near(a: RGB, b: RGB) -> bool:
    return sum(abs(x - y) for x, y in zip(a, b, strict=True)) < 90


def led_colors(primary_hex: Any, alternate_hex: Any) -> tuple[RGB, RGB]:
    """``(primary, secondary)`` tuned for an LED matrix from ESPN's two hex colours.

    * A primary that reads on a panel is kept as it is.
    * A dark one with a hue (navy, maroon, forest green) is lifted to the same hue brightened.
    * A black or charcoal one uses the alternate if that reads, else a neutral grey.
    * The secondary is the alternate, tuned the same way, and white if it would be the same as
      the primary: two near-identical colours are no use as a pair.
    """
    primary = _hex_rgb(primary_hex)
    alternate = _hex_rgb(alternate_hex)
    if primary is not None and not _visible(primary) and _saturation(primary) < GREY_SATURATION:
        if alternate is not None and _visible(alternate):
            primary, alternate = alternate, primary
        else:
            primary = None
    main = _tuned(primary, UNKNOWN_COLOR)
    second = _tuned(alternate, WHITE)
    if _near(main, second):
        second = WHITE if _luma(main) < 200 else NEUTRAL
    return main, second


@dataclass(frozen=True, slots=True)
class CollegeTable:
    """Every FBS team, with lookups by id and by conference."""

    teams: tuple[CollegeTeam, ...]

    def by_id(self, espn_id: int | str) -> CollegeTeam | None:
        try:
            wanted = int(espn_id)
        except (TypeError, ValueError):
            return None
        for team in self.teams:
            if team.espn_id == wanted:
                return team
        return None

    def by_abbrev(self, abbrev: str) -> CollegeTeam | None:
        """A team by ESPN abbreviation (case-insensitive). FBS abbreviations are unique."""
        wanted = abbrev.strip().upper()
        for team in self.teams:
            if team.abbrev.upper() == wanted:
                return team
        return None

    def conferences(self) -> list[tuple[str, str, list[CollegeTeam]]]:
        """``(name, short name, teams)`` per conference, A-Z with the independents last.

        Teams inside a conference are A-Z by name. This is the shape the admin picker shows
        (#542, #543).
        """
        grouped: dict[str, list[CollegeTeam]] = {}
        shorts: dict[str, str] = {}
        for team in self.teams:
            grouped.setdefault(team.conference, []).append(team)
            shorts[team.conference] = team.conference_short
        order = sorted(grouped, key=lambda name: (name == INDEPENDENTS, name))
        return [(name, shorts[name], sorted(grouped[name], key=lambda t: t.name)) for name in order]

    def __len__(self) -> int:
        return len(self.teams)


def _standings_entries(
    node: Any, conference: str, short: str, out: list[tuple[dict[str, Any], str, str]]
) -> None:
    """Collect ``(team, conference, short)`` below a conference node.

    The Sun Belt is nested: its node has two *division* children (``Sun Belt - East`` and
    ``- West``) and no ``standings`` of its own, so a loop over the root's children alone
    silently loses it. Whatever the depth, a team belongs to the **top-level** conference.
    """
    if not isinstance(node, dict):
        return
    standings = node.get("standings")
    entries = standings.get("entries") if isinstance(standings, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        team = entry.get("team") if isinstance(entry, dict) else None
        if isinstance(team, dict):
            out.append((team, conference, short))
    for child in node.get("children") or []:
        _standings_entries(child, conference, short, out)


def _teams_by_id(payload: Any) -> dict[int, dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    try:
        listed = payload["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError, TypeError):
        return found
    for item in listed if isinstance(listed, list) else []:
        team = item.get("team") if isinstance(item, dict) else None
        try:
            found[int(team["id"])] = team
        except (KeyError, TypeError, ValueError):
            continue
    return found


def table_from_payloads(standings: Any, teams: Any) -> CollegeTable | None:
    """The FBS table from a standings payload and a ``/teams`` payload.

    ``None`` when the standings hold no team at all (nothing to build a table from). A team
    missing from ``/teams`` is kept, in neutral colours, rather than dropped: it is a real FBS
    team that only lacks a colour. An entry with no usable id or name is skipped and logged.
    """
    children = standings.get("children") if isinstance(standings, dict) else None
    found: list[tuple[dict[str, Any], str, str]] = []
    for conference in children if isinstance(children, list) else []:
        if not isinstance(conference, dict):
            continue
        name = str(conference.get("name") or "").strip()
        short = str(conference.get("shortName") or name).strip()
        if name:
            _standings_entries(conference, name, short, found)
    details = _teams_by_id(teams)
    built: dict[int, CollegeTeam] = {}
    for raw, conference, short in found:
        try:
            espn_id = int(raw["id"])
            abbrev = str(raw["abbreviation"]).strip()
            location = str(raw.get("location") or "").strip()
            nickname = str(raw.get("name") or "").strip()
            display = str(raw.get("displayName") or f"{location} {nickname}").strip()
        except (KeyError, TypeError, ValueError):
            log.warning("Skipping an FBS standings entry with no usable id or abbreviation")
            continue
        if not abbrev or not (location or display):
            log.warning("Skipping FBS team %s: no name", espn_id)
            continue
        short_name = str(raw.get("shortDisplayName") or location or display).strip()
        extra = details.get(espn_id)
        if extra is None:
            log.warning("FBS team %s (%s) is not in /teams: neutral colours", abbrev, espn_id)
        primary, secondary = led_colors(
            (extra or {}).get("color"), (extra or {}).get("alternateColor")
        )
        built[espn_id] = CollegeTeam(
            espn_id=espn_id,
            abbrev=abbrev,
            location=location or display,
            nickname=nickname,
            short_name=short_name,
            name=short_name.upper(),
            conference=conference,
            conference_short=short,
            color=primary,
            secondary=secondary,
        )
    if not built:
        return None
    return CollegeTable(tuple(sorted(built.values(), key=lambda t: (t.conference, t.name))))
