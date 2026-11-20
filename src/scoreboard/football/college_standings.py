"""College conference tables (#553): the standings payload as one table per conference.

``/apis/v2/sports/football/college-football/standings?group=80`` has a child per conference with
``standings.entries[]``. Three things in it are not what they look like (``football_api.md``):

* each entry's ``stats`` is a flat list in which the **same stat name repeats once per split**
  (overall, Home, Away, vs. Division, vs. Conf.), so a stat is found by its ``type`` (``total`` is
  the overall record, ``vsconf`` the conference record, ``playoffseed`` the conference seed), never
  by ``name``;
* the **Sun Belt is nested**: its node has two divisions and no ``standings`` of its own, and the
  seeds run across both, so its teams are merged into one table;
* the entries are **not in seed order** (a team with a lower seed can be listed later), so the
  table is sorted by ``playoffseed``.

The FBS Independents (Notre Dame and UConn) play no conference schedule: their conference record is
``0-0`` and is left out (``conf`` is empty).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

#: How ESPN's conference names are shortened to fit beside a record (4 letters of room).
CONFERENCE_SHORT = {
    "big ten": "B1G",
    "big 12": "B12",
    "pac-12": "PAC",
    "fbs indep.": "IND",
    "american": "AAC",
    "sun belt": "SBC",
    "mountain west": "MWC",
    "conference usa": "CUSA",
    "mid-american": "MAC",
}


def short_conference(name: str) -> str:
    """``Big Ten`` as ``B1G``: the known names by table, any other upper-cased and cut to 4."""
    key = name.strip().lower()
    return CONFERENCE_SHORT.get(key, key.upper()[:4])


@dataclass(frozen=True, slots=True)
class ConferenceRow:
    team_id: int
    abbrev: str
    #: The overall record, ``8-2`` (or ``5-3-1``).
    overall: str
    #: The conference record, ``5-1``; empty for a team with no conference schedule.
    conf: str
    #: The conference seed (1 is the top); ``None`` when the feed gave none.
    seed: int | None
    #: ``W4`` / ``L1``; empty when the feed gave none.
    streak: str

    @property
    def played(self) -> bool:
        """Whether the team has played a game this season."""
        return self.overall not in ("", "0-0", "0-0-0")


@dataclass(frozen=True, slots=True)
class ConferenceTable:
    #: ``Southeastern Conference``.
    name: str
    #: ``SEC``.
    short: str
    #: In standings order: best seed first.
    rows: tuple[ConferenceRow, ...]

    @property
    def played(self) -> bool:
        return any(r.played for r in self.rows)


@dataclass(frozen=True, slots=True)
class CollegeStandings:
    conferences: tuple[ConferenceTable, ...]

    def conference_of(self, abbrev: str) -> ConferenceTable | None:
        key = abbrev.strip().upper()
        return next((c for c in self.conferences if any(r.abbrev == key for r in c.rows)), None)


def _stat(stats: list[Any], kind: str) -> dict[str, Any] | None:
    """The stat of ``type`` ``kind``: its first (and, by type, only) match."""
    return next((s for s in stats if isinstance(s, dict) and s.get("type") == kind), None)


def _text(stat: dict[str, Any] | None, *keys: str) -> str:
    for key in keys:
        value = (stat or {}).get(key)
        if isinstance(value, str) and value.strip() and value.strip() != "-":
            return value.strip()
    return ""


def _row(entry: Any) -> ConferenceRow | None:
    try:
        team = entry["team"]
        team_id, abbrev = int(team["id"]), str(team["abbreviation"]).strip().upper()
    except (KeyError, TypeError, ValueError):
        return None
    if not abbrev:
        return None
    stats = entry.get("stats")
    stats = stats if isinstance(stats, list) else []
    overall = _text(_stat(stats, "total"), "summary", "displayValue")
    conf = _text(_stat(stats, "vsconf"), "summary", "displayValue")
    if conf in ("0-0", "0-0-0"):
        conf = ""  # no conference game played (an Independent, or the first week)
    try:
        seed: int | None = int(_text(_stat(stats, "playoffseed"), "displayValue"))
    except ValueError:
        seed = None
    if seed is not None and seed < 1:
        seed = None
    return ConferenceRow(
        team_id, abbrev, overall, conf, seed, _text(_stat(stats, "streak"), "displayValue")
    )


def _entries(node: Any) -> list[Any]:
    """Every standings entry at or below ``node`` (the Sun Belt's are one level down)."""
    found: list[Any] = []
    if not isinstance(node, dict):
        return found
    standings = node.get("standings")
    listed = standings.get("entries") if isinstance(standings, dict) else None
    if isinstance(listed, list):
        found.extend(listed)
    for child in node.get("children") or []:
        found.extend(_entries(child))
    return found


def _order(row: ConferenceRow) -> tuple[int, str]:
    """Seed order; a team without a seed goes last, in a stable order."""
    return (row.seed if row.seed is not None else 10**6, row.abbrev)


def college_standings_from_payload(payload: Any) -> CollegeStandings | None:
    """Every conference's table from a ``group=80`` standings payload, or ``None`` when it holds
    none (the wrong shape, or no entries). An entry that cannot be read is skipped."""
    children = payload.get("children") if isinstance(payload, dict) else None
    tables: list[ConferenceTable] = []
    for node in children if isinstance(children, list) else []:
        if not isinstance(node, dict):
            continue
        rows = [r for r in (_row(e) for e in _entries(node)) if r is not None]
        if not rows:
            continue
        name = str(node.get("name") or "").strip()
        short = short_conference(str(node.get("shortName") or name))
        tables.append(ConferenceTable(name, short, tuple(sorted(rows, key=_order))))
    return CollegeStandings(tuple(tables)) if tables else None
