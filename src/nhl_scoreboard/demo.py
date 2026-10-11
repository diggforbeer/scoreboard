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
from .nhl.models import (
    Game,
    GoalieLine,
    MeetingResult,
    SeasonSeriesRecord,
    Shootout,
    ShootoutAttempt,
    Situation,
    SkaterLine,
    StandingsRow,
    TeamLeaders,
    conference_standings,
    standings_window,
)


def _meetings(now: datetime) -> tuple[MeetingResult, ...]:
    """A 2-1 series so far, one win needing overtime, from the favourite's side."""
    day = now.date()
    return (
        MeetingResult(day - timedelta(days=60), True, 4, 1, ""),
        MeetingResult(day - timedelta(days=35), False, 2, 3, "OT"),
        MeetingResult(day - timedelta(days=12), True, 3, 2, "SO"),
    )


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


#: Made-up players, shown whichever team is the favourite.
_LEADERS = TeamLeaders(
    goals=SkaterLine(1, "F. Forsberg", 14, 9, 23),
    points=SkaterLine(2, "R. O'Reilly", 9, 17, 26),
    goalies=(
        GoalieLine(3, "J. Saros", 22, 13, 7, 2, 0.915),
        GoalieLine(4, "J. Wright", 9, 4, 3, 1, 0.902),
    ),
)


class DemoStep(NamedTuple):
    """One frame of the demo: what to draw, and whether to draw it with logos."""

    scene: Scene
    use_logos: bool = True
    #: A holiday (#237) to force on for this step, whatever the date or
    #: config, with a fly-by starting the moment the step does.
    holiday: str | None = None
    #: Pop the newest shootout attempt in as the step starts (#259).
    animate_shootout: bool = False


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

    # Rounds are (away, home): g = goal, x = miss, - = not taken yet.
    so_live = dataclasses.replace(
        _game(10, away, home, "LIVE", now, away_score=2, home_score=2, period=5, ot="SO"),
        shootout=_shootout(away, home, ["gx", "xg"]),
    )
    # Home is down 2-1 with one shot left, so a miss ends it.
    so_must_score = dataclasses.replace(
        _game(13, away, home, "LIVE", now, away_score=2, home_score=2, period=5, ot="SO"),
        shootout=_shootout(away, home, ["gx", "gg", "x-"]),
    )
    so_sudden = dataclasses.replace(
        _game(11, away, home, "LIVE", now, away_score=3, home_score=3, period=5, ot="SO"),
        shootout=_shootout(away, home, ["gx", "xg", "gg", "xx", "gg", "xx", "g-"]),
    )
    so_final = dataclasses.replace(
        _game(12, away, home, "OFF", now, away_score=3, home_score=4, period=5, ot="SO"),
        shootout=_shootout(away, home, ["xg", "gx", "xg"]),
    )

    return [
        DemoStep(Scene("connecting")),
        DemoStep(Scene("preview", upcoming)),
        DemoStep(Scene("matchup", upcoming, season_series=SeasonSeriesRecord(2, 1))),
        DemoStep(
            Scene("matchup", upcoming, season_series=SeasonSeriesRecord(2, 1)), use_logos=False
        ),
        DemoStep(Scene("matchup_meetings", upcoming, meetings=_meetings(now))),
        DemoStep(Scene("matchup_meetings", upcoming, meetings=_meetings(now)), use_logos=False),
        DemoStep(Scene("countdown", soon)),
        DemoStep(Scene("game", soon)),
        DemoStep(Scene("game", live)),
        DemoStep(Scene("game", live), use_logos=False),
        DemoStep(Scene("game", power_play)),
        DemoStep(Scene("game", empty_net)),
        DemoStep(Scene("game", intermission)),
        DemoStep(Scene("game", overtime)),
        DemoStep(Scene("goal", goal, goal_team=home)),
        DemoStep(Scene("goal", goal, goal_team=home), use_logos=False),
        DemoStep(Scene("game", final)),
        DemoStep(Scene("game", final), use_logos=False),
        DemoStep(Scene("game", shootout)),
        DemoStep(Scene("game", so_live), animate_shootout=True),
        DemoStep(Scene("game", so_must_score), animate_shootout=True),
        DemoStep(Scene("game", so_sudden), animate_shootout=True),
        DemoStep(Scene("game", so_final), animate_shootout=True),
        DemoStep(Scene("scores", games=(live, intermission, final, shootout))),
        DemoStep(Scene("standings", standings=_standings(favourite))),
        DemoStep(Scene("standings", standings=_standings(favourite)), use_logos=False),
        DemoStep(Scene("conference_leaders", standings=_standings("")[:5])),
        DemoStep(Scene("leaders", leaders=_LEADERS)),
        DemoStep(Scene("leaders", leaders=_LEADERS), use_logos=False),
        DemoStep(Scene("clock")),
        DemoStep(Scene("game", live), holiday="halloween"),
        DemoStep(Scene("clock"), holiday="halloween"),
        DemoStep(Scene("game", live), holiday="thanksgiving"),
        DemoStep(Scene("clock"), holiday="thanksgiving"),
        DemoStep(Scene("game", live), holiday="christmas"),
        DemoStep(Scene("clock"), holiday="christmas"),
        DemoStep(Scene("game", live), holiday="new_year"),
        DemoStep(Scene("clock"), holiday="new_year"),
        DemoStep(Scene("game", live), holiday="groundhog"),
        DemoStep(Scene("clock"), holiday="groundhog"),
        DemoStep(Scene("game", live), holiday="valentines"),
        DemoStep(Scene("clock"), holiday="valentines"),
        DemoStep(Scene("game", live), holiday="st_patricks"),
        DemoStep(Scene("clock"), holiday="st_patricks"),
        DemoStep(Scene("game", live), holiday="easter"),
        DemoStep(Scene("clock"), holiday="easter"),
        # July is the off-season: the clock is what these holidays decorate.
        DemoStep(Scene("clock"), holiday="canada_day"),
        DemoStep(Scene("clock"), holiday="july_4th"),
        DemoStep(Scene("christmas_tree")),
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


def _shootout(away: str, home: str, rounds: list[str]) -> Shootout:
    """A shootout from (away, home) rounds; the away team shoots first."""
    attempts: list[ShootoutAttempt] = []
    for pair in rounds:
        for abbrev, mark in zip((away, home), pair, strict=True):
            if mark != "-":
                attempts.append(ShootoutAttempt(len(attempts) + 1, abbrev, mark == "g"))
    goals = [sum(1 for a in attempts if a.scored and a.team_abbrev == t) for t in (away, home)]
    return Shootout(tuple(attempts), away_goals=goals[0], home_goals=goals[1])


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
