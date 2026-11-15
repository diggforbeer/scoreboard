"""Team stats for the break in play (the stats screen shown over an official timeout).

Read from the **same** site ``summary`` payload the plays come from (``boxscore.teams[]``, each
with ``statistics[]`` of ``{name, label, displayValue}``), so showing them costs no request. The
screen is a split table, away on the left and home on the right, a handful of rows a page.

Everything here is pure: :func:`stats_from_summary` parses, :class:`GameStats` answers "what does
each side say for this row, and who is ahead".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: A row where the bigger number is better, the smaller is better, or there is no winner.
HIGHER, LOWER, NONE = "higher", "lower", "none"
#: Compared as a fraction (``4-5`` converted 4 of 5 -> 0.8), not as the first number.
RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class StatRow:
    """One line of the table: the feed's key, the label drawn, and who is ahead."""

    key: str
    label: str
    better: str = HIGHER


#: The table, a page at a time (5 rows fit the 32px panel). Yardage first, as in the app the owner
#: showed; the rest are what a broadcast puts up at a break.
PAGES: tuple[tuple[StatRow, ...], ...] = (
    (
        StatRow("totalYards", "TOTAL YDS"),
        StatRow("netPassingYards", "PASSING"),
        StatRow("rushingYards", "RUSHING"),
        StatRow("yardsPerPlay", "YDS/PLAY"),
        StatRow("firstDowns", "1ST DOWNS"),
    ),
    (
        StatRow("thirdDownEff", "3RD DOWN", RATIO),
        StatRow("turnovers", "TURNOVERS", LOWER),
        StatRow("totalPenaltiesYards", "PENALTIES", LOWER),
        StatRow("totalOffensivePlays", "TOTAL PLAYS"),
        StatRow("possessionTime", "POSSESSION"),
    ),
)

# A minus only counts at the start of a number ("-2" yards), not as the dash in "4-5".
_NUMBER = re.compile(r"(?<!\d)-?\d+(?:\.\d+)?")
_COUNTS = re.compile(r"\d+")


@dataclass(frozen=True, slots=True)
class GameStats:
    """Both sides' feed values by key, as the feed displays them (``"197"``, ``"4-5"``)."""

    away: dict[str, str]
    home: dict[str, str]

    def value(self, side: str, key: str) -> str:
        """The text for a side (``"away"`` / ``"home"``); ``"-"`` when the feed has none."""
        return display((self.away if side == "away" else self.home).get(key, ""))

    def leader(self, row: StatRow) -> str | None:
        """``"away"``, ``"home"``, or ``None`` (a tie, no winner, or an unreadable value)."""
        if row.better == NONE:
            return None
        a = _score(self.away.get(row.key, ""), row.better)
        h = _score(self.home.get(row.key, ""), row.better)
        if a is None or h is None or a == h:
            return None
        ahead = a > h
        if row.better == LOWER:
            ahead = not ahead
        return "away" if ahead else "home"

    @property
    def pages(self) -> int:
        return len(PAGES)

    def usable(self) -> bool:
        """True when the feed gave enough to be worth a screen (not a game with no snaps yet)."""
        first = PAGES[0][0].key
        return bool(self.away.get(first)) and bool(self.home.get(first))


def display(raw: str) -> str:
    """The value as drawn: ``" 6:51"`` -> ``"6:51"``, ``"4-5"`` -> ``"4/5"``, ``""`` -> ``"-"``."""
    text = raw.strip()
    if not text:
        return "-"
    if re.fullmatch(r"\d+-\d+", text):
        return text.replace("-", "/")
    return text


def _score(raw: str, better: str) -> float | None:
    """A comparable number for a value, or ``None`` if it has none."""
    text = raw.strip()
    if not text:
        return None
    if ":" in text:  # a possession clock, minutes:seconds
        minutes, _, seconds = text.partition(":")
        try:
            return int(minutes) * 60 + int(seconds)
        except ValueError:
            return None
    if better == RATIO:  # "4-5": made and attempted
        counts = _COUNTS.findall(text)
        if not counts:
            return None
        attempts = float(counts[1]) if len(counts) > 1 else 0.0
        return float(counts[0]) / attempts if attempts else 0.0
    nums = _NUMBER.findall(text)
    return float(nums[0]) if nums else None


def stats_from_summary(payload: dict[str, Any]) -> GameStats | None:
    """The team stats in a site ``summary`` payload, or ``None`` when it has none.

    Sides are matched by ``homeAway``, never by order. A key the feed lists twice (it does for
    ``interceptions``) keeps its first value. Anything malformed is skipped, never raised.
    """
    box = payload.get("boxscore")
    teams = box.get("teams") if isinstance(box, dict) else None
    if not isinstance(teams, list):
        return None
    sides: dict[str, dict[str, str]] = {}
    for team in teams:
        if not isinstance(team, dict) or team.get("homeAway") not in ("home", "away"):
            continue
        values: dict[str, str] = {}
        for item in team.get("statistics") or []:
            if not isinstance(item, dict):
                continue
            name, shown = item.get("name"), item.get("displayValue")
            if isinstance(name, str) and isinstance(shown, str):
                values.setdefault(name, shown)
        sides[team["homeAway"]] = values
    if "home" not in sides or "away" not in sides:
        return None
    stats = GameStats(away=sides["away"], home=sides["home"])
    return stats if stats.usable() else None
