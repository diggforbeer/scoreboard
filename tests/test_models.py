from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard.nhl.models import Game

TZ = ZoneInfo("America/Chicago")


@pytest.fixture
def games(score_payload) -> list[Game]:
    return [Game.from_api(raw) for raw in score_payload["games"]]


def test_parses_every_game_in_fixture(games):
    assert len(games) == 8
    assert all(g.away.abbrev and g.home.abbrev for g in games)


def test_final_game_fields(games):
    final = next(g for g in games if g.away.abbrev == "NYI")
    assert final.is_final
    assert not final.is_live
    assert (final.away.score, final.home.score) == (1, 2)
    assert final.status_label(TZ) == "FINAL"


def test_shootout_final_is_labelled(games):
    so = next(g for g in games if g.away.abbrev == "WSH")
    assert so.period_type == "SO"
    assert so.status_label(TZ) == "F/SO"


def test_live_game_shows_period_and_clock(games):
    live = next(g for g in games if g.away.abbrev == "SEA")
    assert live.is_live
    assert live.status_label(TZ) == "1ST 05:05"


def test_intermission_beats_period_clock(games):
    intermission = next(g for g in games if g.away.abbrev == "CAR")
    assert intermission.in_intermission
    assert intermission.status_label(TZ) == "INT2"


def test_clock_at_zero_not_running_is_intermission_even_if_the_flag_lags(score_payload):
    """A real live game was observed stuck at 00:00/not-running with
    inIntermission still false, on both score/now and gamecenter/landing,
    for well over one poll cycle -- the flag itself lags the period ending.
    A period clock can only read 00:00 once play has stopped (periods start
    at 20:00/5:00, never count down to it mid-play), so this combination is
    inferred as intermission regardless of the flag."""
    raw = next(g for g in score_payload["games"] if g["awayTeam"]["abbrev"] == "SEA")
    raw = {**raw, "clock": {"timeRemaining": "00:00", "running": False, "inIntermission": False}}
    game = Game.from_api(raw)
    assert game.in_intermission
    assert game.status_label(TZ) == f"INT{game.period}"


def test_pregame_shows_local_start_time(games):
    future = next(g for g in games if g.state == "FUT")
    # 23:00 UTC is 18:00 in Chicago (CDT).
    assert future.status_label(TZ) == "6:00P"


def test_sort_puts_live_first_then_upcoming_then_finals(games):
    ordered = sorted(games, key=Game.sort_key)
    ranks = [0 if g.is_live else (1 if g.is_pregame else 2) for g in ordered]
    assert ranks == sorted(ranks)


def test_involves_is_case_insensitive_and_ignores_blank(games):
    game = next(g for g in games if g.away.abbrev == "NYI")
    assert game.involves("nyi")
    assert game.involves("NJD")
    assert not game.involves("TOR")
    assert not game.involves("")


@pytest.mark.parametrize(
    ("period", "period_type", "expected"),
    [
        (1, "REG", "1ST"),
        (2, "REG", "2ND"),
        (3, "REG", "3RD"),
        (4, "OT", "OT"),
        (5, "OT", "2OT"),
        (5, "SO", "SO"),
    ],
)
def test_period_labels(period, period_type, expected):
    game = Game.from_api(
        {
            "id": 1,
            "gameState": "LIVE",
            "startTimeUTC": "2026-09-20T23:00:00Z",
            "awayTeam": {"abbrev": "AAA"},
            "homeTeam": {"abbrev": "BBB"},
            "period": period,
            "periodDescriptor": {
                "number": period,
                "periodType": period_type,
                "maxRegulationPeriods": 3,
            },
        }
    )
    assert game.period_label() == expected


def test_missing_fields_do_not_raise():
    game = Game.from_api({"id": 7, "awayTeam": {}, "homeTeam": {}})
    assert game.away.abbrev == "???"
    assert game.away.score == 0
    assert game.state == "FUT"


def test_explicit_null_abbrev_falls_back_like_a_missing_one():
    game = Game.from_api({"id": 7, "awayTeam": {"abbrev": None}, "homeTeam": {}})
    assert game.away.abbrev == "???"


def test_explicit_null_game_state_falls_back_like_a_missing_one():
    game = Game.from_api({"id": 7, "gameState": None})
    assert game.state == "FUT"


def test_malformed_start_time_falls_back_instead_of_raising():
    game = Game.from_api({"id": 7, "startTimeUTC": "not-a-timestamp"})
    assert isinstance(game.start_utc, datetime)


# -- special teams -----------------------------------------------------------

from nhl_scoreboard.nhl.models import Situation  # noqa: E402


def situation(away_strength, home_strength, away=(), home=(), time="1:23"):
    return Situation.from_api(
        {
            "awayTeam": {"strength": away_strength, "situationDescriptions": list(away)},
            "homeTeam": {"strength": home_strength, "situationDescriptions": list(home)},
            "timeRemaining": time,
            "secondsRemaining": 83,
        }
    )


def test_situation_absent_at_even_strength():
    assert Situation.from_api(None) is None
    assert Situation.from_api({}) is None


def test_power_play_side_and_label():
    home_pp = situation(4, 5, home=["PP"])
    assert home_pp.indicator_side() == "home"
    assert home_pp.label() == "PP 1:23"

    away_pp = situation(5, 4, away=["PP"])
    assert away_pp.indicator_side() == "away"


def test_two_man_advantage_shows_strength():
    assert situation(3, 5, home=["PP"]).label() == "5v3 1:23"


def test_empty_net_without_power_play():
    en = situation(5, 6, home=["EN"])
    assert en.power_play_side() is None
    assert en.indicator_side() == "home"
    assert en.label() == "EN"


def test_four_on_four_is_not_an_indicator():
    assert situation(4, 4).indicator_side() is None
    assert situation(4, 4).label() == ""


def test_game_special_teams_flag(games):
    import dataclasses

    live = next(g for g in games if g.is_live)
    assert not live.special_teams
    assert dataclasses.replace(live, situation=situation(4, 5, home=["PP"])).special_teams
    assert not dataclasses.replace(live, situation=situation(4, 4)).special_teams


# -- estimated end ----------------------------------------------------------


def test_estimated_end_by_how_the_game_finished(games):
    from datetime import timedelta

    reg = next(g for g in games if g.away.abbrev == "NYI")  # FINAL in regulation
    so = next(g for g in games if g.away.abbrev == "WSH")  # F/SO
    assert reg.estimated_end() == reg.start_utc + timedelta(hours=2, minutes=30)
    assert so.estimated_end() == so.start_utc + timedelta(hours=2, minutes=45)

    ot = Game.from_api(
        {
            "id": 1,
            "gameState": "FINAL",
            "startTimeUTC": "2026-09-20T23:00:00Z",
            "awayTeam": {},
            "homeTeam": {},
            "period": 4,
            "periodDescriptor": {"number": 4, "periodType": "OT", "maxRegulationPeriods": 3},
        }
    )
    assert ot.estimated_end() == ot.start_utc + timedelta(hours=2, minutes=40)


# -- standings ----------------------------------------------------------

from nhl_scoreboard.nhl.models import (  # noqa: E402
    StandingsRow,
    conference_standings,
    standings_window,
)


@pytest.fixture
def standings_rows(standings_payload) -> list[StandingsRow]:
    return [StandingsRow.from_api(raw) for raw in standings_payload["standings"]]


def test_parses_every_row_in_fixture(standings_rows):
    assert len(standings_rows) == 9
    assert all(r.abbrev for r in standings_rows)


def test_standings_row_fields(standings_rows):
    nsh = next(r for r in standings_rows if r.abbrev == "NSH")
    assert nsh.conference == "W"
    assert nsh.division == "C"
    assert nsh.division_sequence == 4
    assert nsh.wildcard_sequence == 1
    assert nsh.conference_sequence == 5
    assert (nsh.wins, nsh.losses, nsh.ot_losses) == (9, 8, 2)
    assert nsh.points == 20
    assert nsh.games_played == 19
    assert nsh.record_label() == "9-8-2"


def test_missing_standings_fields_do_not_raise():
    row = StandingsRow.from_api({})
    assert row.abbrev == ""
    assert row.points == 0
    assert row.games_played == 0


@pytest.mark.parametrize(
    ("division_sequence", "wildcard_sequence", "expected"),
    [
        (1, 0, True),  # division leader
        (3, 0, True),  # 3rd in division: still in
        (4, 0, False),  # 4th in division, not a wildcard: out
        (4, 1, True),  # missed the division, holds a wildcard spot
        (4, 3, False),  # 3rd wildcard: out
    ],
)
def test_in_playoff_position(division_sequence, wildcard_sequence, expected):
    row = StandingsRow.from_api(
        {"divisionSequence": division_sequence, "wildcardSequence": wildcard_sequence}
    )
    assert row.in_playoff_position is expected


def test_conference_standings_filters_and_sorts(standings_rows):
    west = conference_standings(standings_rows, "w")  # case-insensitive
    assert [r.abbrev for r in west] == ["WPG", "DAL", "STL", "VGK", "NSH", "LAK", "CGY"]
    east = conference_standings(standings_rows, "E")
    assert [r.abbrev for r in east] == ["TOR", "CAR"]


def _row(abbrev: str, conference_sequence: int) -> StandingsRow:
    return StandingsRow(
        abbrev=abbrev,
        conference="W",
        division="C",
        division_sequence=1,
        wildcard_sequence=0,
        conference_sequence=conference_sequence,
        clinch_indicator="",
        points=0,
        games_played=1,
        wins=0,
        losses=0,
        ot_losses=0,
    )


def test_standings_window_centers_on_the_favourite():
    rows = [_row(f"T{i}", i) for i in range(8)]  # ranks 0..7
    window = standings_window(rows, "T4")
    assert [r.abbrev for r in window] == ["T2", "T3", "T4", "T5", "T6"]


def test_standings_window_clamps_at_the_top():
    rows = [_row(f"T{i}", i) for i in range(8)]
    window = standings_window(rows, "T0")
    assert [r.abbrev for r in window] == ["T0", "T1", "T2", "T3", "T4"]


def test_standings_window_clamps_at_the_bottom():
    rows = [_row(f"T{i}", i) for i in range(8)]
    window = standings_window(rows, "T7")
    assert [r.abbrev for r in window] == ["T3", "T4", "T5", "T6", "T7"]


def test_standings_window_shrinks_for_a_small_conference():
    rows = [_row(f"T{i}", i) for i in range(3)]
    window = standings_window(rows, "T1")
    assert [r.abbrev for r in window] == ["T0", "T1", "T2"]


def test_standings_window_missing_team_is_empty():
    rows = [_row(f"T{i}", i) for i in range(8)]
    assert standings_window(rows, "ZZZ") == []


# -- goal detail (#122) -------------------------------------------------------

from nhl_scoreboard.nhl.models import (  # noqa: E402
    AssistDetail,
    GoalEvent,
    goal_events_from_landing,
)


def _goal_raw(team="NSH", scorer="F. Forsberg", goals=12, assists=(), strength="ev"):
    return {
        "teamAbbrev": team,
        "name": {"default": scorer},
        "goalsToDate": goals,
        "assists": [{"name": {"default": n}, "assistsToDate": a} for n, a in assists],
        "strength": strength,
    }


def test_goal_event_parses_scorer_and_assists():
    event = GoalEvent.from_api(
        _goal_raw(assists=[("J. Smith", 5), ("B. Johnson", 9)], strength="pp")
    )
    assert event.team_abbrev == "NSH"
    assert event.scorer_name == "F. Forsberg"
    assert event.scorer_goals_to_date == 12
    assert event.assists == (
        AssistDetail(name="J. Smith", assists_to_date=5),
        AssistDetail(name="B. Johnson", assists_to_date=9),
    )
    assert event.strength == "pp"


def test_goal_event_defaults_to_even_strength_and_no_assists():
    event = GoalEvent.from_api(_goal_raw())
    assert event.strength == "ev"
    assert event.assists == ()


def test_goal_events_from_landing_flattens_every_period_in_order():
    raw = {
        "summary": {
            "scoring": [
                {"goals": [_goal_raw(scorer="A")]},
                {"goals": [_goal_raw(scorer="B"), _goal_raw(scorer="C")]},
            ]
        }
    }
    events = goal_events_from_landing(raw)
    assert [e.scorer_name for e in events] == ["A", "B", "C"]


def test_goal_events_from_landing_absent_is_empty():
    assert goal_events_from_landing(None) == ()
    assert goal_events_from_landing({}) == ()
    assert goal_events_from_landing({"summary": {}}) == ()


def test_goal_events_from_landing_skips_a_malformed_goal_without_losing_the_rest():
    raw = {
        "summary": {
            "scoring": [
                {"goals": [{"goalsToDate": "not-a-number"}, _goal_raw(scorer="OK")]},
            ]
        }
    }
    events = goal_events_from_landing(raw)
    assert [e.scorer_name for e in events] == ["OK"]
