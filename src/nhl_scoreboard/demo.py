"""Synthetic scenes for ``--demo`` (#47): every visual state, no NHL API needed.

Games are built from raw API-shaped dicts through ``Game.from_api()`` -- the
same construction the tests use -- so a demo frame goes through exactly the
parsing and rendering a real one would, just with made-up numbers.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from .app import Scene
from .nhl.models import Game, Situation, StandingsRow, conference_standings, standings_window

#: Stand-ins for the favourite's opponents; any of them is skipped if it
#: happens to be the favourite itself, so a matchup never plays itself.
_OPPONENTS = ("DAL", "COL", "WPG", "MIN", "STL", "CHI", "EDM", "VGK")
#: Used as the "home" side when no favourite is configured at all.
_NO_FAVOURITE_HOME = "TBL"
#: A plausible Western Conference table, best to worst, for the standings scene.
_CONFERENCE = (
    "WPG",
    "DAL",
    "VGK",
    "LAK",
    "COL",
    "NSH",
    "EDM",
    "MIN",
    "STL",
    "CGY",
    "VAN",
    "UTA",
    "ANA",
    "SEA",
    "CHI",
    "SJS",
)


class DemoStep(NamedTuple):
    """One frame of the demo: what to draw, and whether to draw it with logos."""

    scene: Scene
    use_logos: bool = True


def demo_steps(favourite_team: str, now: datetime) -> list[DemoStep]:
    """Every scene the board can show, in a sensible viewing order.

    ``now`` anchors the upcoming games so the preview and countdown read as
    a real "in two days" / "in 12 minutes" rather than a date long past.
    """
    favourite = favourite_team.strip().upper()
    home = favourite or _NO_FAVOURITE_HOME
    away, other_away, other_home = [t for t in _OPPONENTS if t != home][:3]

    upcoming = _game(1, away, home, "FUT", now + timedelta(days=2, hours=3))
    soon = _game(2, away, home, "PRE", now + timedelta(minutes=12, seconds=34))
    live = _game(3, away, home, "LIVE", now, away_score=1, home_score=2, period=2, clock="08:17")
    power_play = dataclasses.replace(live, situation=_situation(home_codes=("PP",), away=4))
    # The trailing side pulls its goalie late in the third.
    empty_net = dataclasses.replace(
        _game(4, away, home, "LIVE", now, away_score=2, home_score=3, period=3, clock="01:12"),
        situation=_situation(away_codes=("EN",), away=6),
    )
    intermission = _game(
        5, away, home, "LIVE", now, away_score=1, home_score=1, period=2, intermission=True
    )
    overtime = _game(
        6, away, home, "LIVE", now, away_score=3, home_score=3, period=4, clock="03:21", ot="OT"
    )
    goal = _game(7, away, home, "LIVE", now, away_score=1, home_score=3, period=2, clock="06:40")
    final = _game(8, away, home, "OFF", now, away_score=2, home_score=4, period=3)
    shootout = _game(
        9, other_away, other_home, "OFF", now, away_score=3, home_score=2, period=5, ot="SO"
    )

    return [
        DemoStep(Scene("connecting")),
        DemoStep(Scene("preview", upcoming)),
        DemoStep(Scene("countdown", soon)),
        DemoStep(Scene("game", soon)),
        DemoStep(Scene("game", live)),
        DemoStep(Scene("game", live), use_logos=False),
        DemoStep(Scene("game", power_play)),
        DemoStep(Scene("game", empty_net)),
        DemoStep(Scene("game", intermission)),
        DemoStep(Scene("game", overtime)),
        DemoStep(Scene("goal", goal)),
        DemoStep(Scene("goal", goal), use_logos=False),
        DemoStep(Scene("game", final)),
        DemoStep(Scene("game", final), use_logos=False),
        DemoStep(Scene("game", shootout)),
        DemoStep(Scene("standings", standings=_standings(favourite))),
        DemoStep(Scene("standings", standings=_standings(favourite)), use_logos=False),
        DemoStep(Scene("clock")),
        DemoStep(Scene("no_games")),
        DemoStep(Scene("no_data")),
    ]


def _game(
    gid: int,
    away: str,
    home: str,
    state: str,
    start: datetime,
    *,
    away_score: int = 0,
    home_score: int = 0,
    period: int = 0,
    clock: str = "20:00",
    intermission: bool = False,
    ot: str = "REG",
) -> Game:
    raw: dict[str, Any] = {
        "id": gid,
        "gameState": state,
        "startTimeUTC": start.isoformat(),
        "awayTeam": {"abbrev": away, "score": away_score, "sog": 9 * away_score + 7},
        "homeTeam": {"abbrev": home, "score": home_score, "sog": 9 * home_score + 5},
        "period": period,
        "periodDescriptor": {"number": period, "periodType": ot, "maxRegulationPeriods": 3},
        "clock": {
            "timeRemaining": clock,
            "running": state == "LIVE",
            "inIntermission": intermission,
        },
    }
    return Game.from_api(raw)


def _situation(
    *, away_codes: tuple[str, ...] = (), home_codes: tuple[str, ...] = (), away: int = 5
) -> Situation | None:
    return Situation.from_api(
        {
            "awayTeam": {"strength": away, "situationDescriptions": list(away_codes)},
            "homeTeam": {"strength": 5, "situationDescriptions": list(home_codes)},
            "timeRemaining": "1:23",
            "secondsRemaining": 83,
        }
    )


def _standings(favourite: str) -> tuple[StandingsRow, ...]:
    """The favourite's neighbourhood of a synthetic conference table.

    A favourite outside the canned table takes 6th place in it, so any
    configured team gets a window centred on itself; with no favourite at
    all, the top of the table stands in.
    """
    teams = list(_CONFERENCE)
    if favourite and favourite not in teams:
        teams[5] = favourite
    rows = [
        StandingsRow.from_api(
            {
                "teamAbbrev": {"default": abbrev},
                "conferenceAbbrev": "W",
                "divisionAbbrev": "C",
                "conferenceSequence": rank,
                "divisionSequence": rank,
                "points": 2 * (30 - rank) + 4,
                "gamesPlayed": 40,
                "wins": 30 - rank,
                "losses": 6 + rank,
                "otLosses": 4,
            }
        )
        for rank, abbrev in enumerate(teams, start=1)
    ]
    ranked = conference_standings(rows, "W")
    window = standings_window(ranked, favourite) if favourite else ranked[:5]
    return tuple(window)
