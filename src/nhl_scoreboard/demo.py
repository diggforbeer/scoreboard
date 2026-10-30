"""Synthetic scenes for ``--demo`` (#47): every visual state, no NHL API needed.

Games are built from raw API-shaped dicts through ``Game.from_api()`` -- the
same construction the tests use -- so a demo frame goes through exactly the
parsing and rendering a real one would, just with made-up numbers.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from .app import Scene, ScoreboardApp
from .nhl.models import (
    AssistDetail,
    Game,
    GoalEvent,
    GoalieLine,
    MeetingResult,
    SeasonSeriesRecord,
    Shootout,
    ShootoutAttempt,
    Situation,
    SkaterLine,
    StandingsRow,
    Star,
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
_ADDRESS_QR = ScoreboardApp._qr_matrix("http://192.168.1.42:8080", "demo address")

_AP_QR = ScoreboardApp._qr_matrix("WIFI:T:WPA;S:NHL-Scoreboard;P:scoreboard;;", "demo AP setup")

_LEADERS = TeamLeaders(
    goals=SkaterLine(1, "F. Forsberg", 14, 9, 23),
    points=SkaterLine(2, "R. O'Reilly", 9, 17, 26),
    goalies=(
        GoalieLine(3, "J. Saros", 22, 13, 7, 2, 0.915),
        GoalieLine(4, "J. Wright", 9, 4, 3, 1, 0.902),
    ),
)


#: Long enough for the hold at each end plus an unhurried scroll.
DEMO_SCROLL_SECONDS = 17.0
DEMO_DIVISION_SECONDS = 8.0


class DemoStep(NamedTuple):
    """One frame of the demo: what to draw, and whether to draw it with logos."""

    scene: Scene
    use_logos: bool = True
    #: A holiday (#237) to force on for this step, whatever the date or
    #: config, with a fly-by starting the moment the step does.
    holiday: str | None = None
    #: Pop the newest shootout attempt in as the step starts (#259).
    animate_shootout: bool = False
    #: Scroll the scene's table over this many seconds (``conference_leaders``).
    scroll_seconds: float = 0.0
    #: A unique, file-safe name (``game_live``, ``game_live_text``), which
    #: ``scripts/render-screens.py`` uses to name the step's image.
    name: str = ""


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

    goal_event = GoalEvent(
        team_abbrev=home,
        scorer_name="F. Forsberg",
        scorer_goals_to_date=15,
        scorer_player_id=1,
        assists=(AssistDetail("R. O'Reilly", 18, 90), AssistDetail("R. Josi", 12, 59)),
        strength="pp",
        scorer_sweater_number=9,
        scorer_points=24,
    )
    stars = (
        Star(1, 1, home, "F. Forsberg", 9, "R", 2, 1, 3),
        Star(2, 2, away, "N. MacKinnon", 29, "C", 1, 1, 2),
        Star(3, 3, home, "R. O'Reilly", 90, "C", 0, 2, 2),
    )

    steps = [
        ("connecting", Scene("connecting"), {}),
        ("preview", Scene("preview", upcoming), {}),
        ("matchup", Scene("matchup", upcoming, season_series=SeasonSeriesRecord(2, 1)), {}),
        (
            "matchup_text",
            Scene("matchup", upcoming, season_series=SeasonSeriesRecord(2, 1)),
            {"use_logos": False},
        ),
        ("matchup_meetings", Scene("matchup_meetings", upcoming, meetings=_meetings(now)), {}),
        (
            "matchup_meetings_text",
            Scene("matchup_meetings", upcoming, meetings=_meetings(now)),
            {"use_logos": False},
        ),
        ("countdown", Scene("countdown", soon), {}),
        ("game_pregame", Scene("game", soon), {}),
        ("game_live", Scene("game", live), {}),
        ("game_live_text", Scene("game", live), {"use_logos": False}),
        ("game_power_play", Scene("game", power_play), {}),
        ("game_empty_net", Scene("game", empty_net), {}),
        ("game_intermission", Scene("game", intermission), {}),
        ("game_overtime", Scene("game", overtime), {}),
        ("goal", Scene("goal", goal, goal_team=home), {}),
        ("goal_text", Scene("goal", goal, goal_team=home), {"use_logos": False}),
        ("goal_detail", Scene("goal_detail", goal, goal_event=goal_event), {}),
        (
            "goal_detail_text",
            Scene("goal_detail", goal, goal_event=goal_event),
            {"use_logos": False},
        ),
        ("game_final", Scene("game", final), {}),
        ("game_final_text", Scene("game", final), {"use_logos": False}),
        ("three_stars", Scene("three_stars", final, stars=stars), {}),
        ("three_stars_text", Scene("three_stars", final, stars=stars), {"use_logos": False}),
        ("game_final_shootout", Scene("game", shootout), {}),
        ("shootout_live", Scene("game", so_live), {"animate_shootout": True}),
        ("shootout_must_score", Scene("game", so_must_score), {"animate_shootout": True}),
        ("shootout_sudden_death", Scene("game", so_sudden), {"animate_shootout": True}),
        ("shootout_final", Scene("game", so_final), {"animate_shootout": True}),
        ("scores", Scene("scores", games=(live, intermission, final, shootout)), {}),
        ("standings", Scene("standings", standings=_standings(favourite)), {}),
        (
            "standings_text",
            Scene("standings", standings=_standings(favourite)),
            {"use_logos": False},
        ),
        (
            "conference_leaders",
            Scene(
                "conference_leaders",
                standings=tuple(_conference_table(favourite)),
                playoff_cut=8,
            ),
            {"scroll_seconds": DEMO_SCROLL_SECONDS},
        ),
        (
            "division",
            Scene("division", standings=tuple(_conference_table(favourite)[:8]), playoff_cut=3),
            {"scroll_seconds": DEMO_DIVISION_SECONDS},
        ),
        (
            "wildcard",
            Scene("wildcard", standings=tuple(_conference_table(favourite)[8:]), playoff_cut=2),
            {"scroll_seconds": DEMO_DIVISION_SECONDS},
        ),
        ("leaders", Scene("leaders", leaders=_LEADERS), {}),
        ("leaders_text", Scene("leaders", leaders=_LEADERS), {"use_logos": False}),
        (
            "address",
            Scene("address", address_ip="192.168.1.42", address_port=8080, address_qr=_ADDRESS_QR),
            {},
        ),
        ("clock", Scene("clock"), {}),
    ]
    for holiday in (
        "halloween",
        "thanksgiving",
        "christmas",
        "new_year",
        "groundhog",
        "valentines",
        "st_patricks",
        "easter",
    ):
        steps.append((f"game_{holiday}", Scene("game", live), {"holiday": holiday}))
        steps.append((f"clock_{holiday}", Scene("clock"), {"holiday": holiday}))
    # July is the off-season: the clock is what these holidays decorate.
    steps += [
        ("clock_canada_day", Scene("clock"), {"holiday": "canada_day"}),
        ("clock_july_4th", Scene("clock"), {"holiday": "july_4th"}),
        ("christmas_tree", Scene("christmas_tree"), {}),
        ("no_games", Scene("no_games"), {}),
        ("no_data", Scene("no_data"), {}),
        (
            "ap_setup",
            Scene(
                "ap_setup",
                ap_ssid="NHL-Scoreboard",
                ap_password="scoreboard",
                ap_qr_matrix=_AP_QR,
            ),
            {},
        ),
        (
            "wifi_join_attempting",
            Scene("wifi_join", wifi_join_status="attempting", wifi_join_ssid="HomeNetwork"),
            {},
        ),
        (
            "wifi_join_connected",
            Scene("wifi_join", wifi_join_status="connected", wifi_join_ssid="HomeNetwork"),
            {},
        ),
        ("wifi_join_failed", Scene("wifi_join", wifi_join_status="failed"), {}),
    ]
    return [DemoStep(scene, name=name, **options) for name, scene, options in steps]


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
    ranked = _conference_table(favourite)
    window = standings_window(ranked, favourite) if favourite else ranked[:5]
    return tuple(window)


def _conference_table(favourite: str) -> list[StandingsRow]:
    """All sixteen rows of the synthetic West, ranked."""
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
    return conference_standings(rows, "W")
