from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scoreboard.hockey.models import Game

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
    assert so.status_label(TZ) == "FINAL/SO"


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

from scoreboard.hockey.models import Situation  # noqa: E402


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

from scoreboard.hockey.models import (  # noqa: E402
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

from scoreboard.hockey.models import (  # noqa: E402
    AssistDetail,
    GoalEvent,
    goal_events_from_landing,
    player_details_from_api,
)


def _goal_raw(
    team="NSH", scorer="F. Forsberg", goals=12, assists=(), strength="ev", player_id=8479999
):
    return {
        "teamAbbrev": team,
        "name": {"default": scorer},
        "goalsToDate": goals,
        "playerId": player_id,
        "assists": [
            {"name": {"default": n}, "assistsToDate": a, "sweaterNumber": num}
            for n, a, num in assists
        ],
        "strength": strength,
    }


def test_goal_event_parses_scorer_and_assists():
    """sweaterNumber on an assist is confirmed free straight from this
    payload (#124) -- unlike the scorer's own jersey number/points, which
    need a second call this dataclass alone never makes (see
    scorer_sweater_number/scorer_points's own default of None here)."""
    event = GoalEvent.from_api(
        _goal_raw(
            assists=[("J. Smith", 5, 22), ("B. Johnson", 9, 53)], strength="pp", player_id=8481540
        )
    )
    assert event.team_abbrev == "NSH"
    assert event.scorer_name == "F. Forsberg"
    assert event.scorer_goals_to_date == 12
    assert event.scorer_player_id == 8481540
    assert event.scorer_sweater_number is None
    assert event.scorer_points is None
    assert event.assists == (
        AssistDetail(name="J. Smith", assists_to_date=5, sweater_number=22),
        AssistDetail(name="B. Johnson", assists_to_date=9, sweater_number=53),
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


def test_player_details_combines_roster_and_club_stats():
    roster = {
        "forwards": [{"id": 1, "sweaterNumber": 9}],
        "defensemen": [{"id": 2, "sweaterNumber": 55}],
    }
    club_stats = {"skaters": [{"playerId": 1, "points": 40}, {"playerId": 2, "points": 20}]}
    details = player_details_from_api(roster, club_stats)
    assert details[1].sweater_number == 9
    assert details[1].points == 40
    assert details[2].sweater_number == 55
    assert details[2].points == 20


def test_player_details_omits_a_player_missing_from_either_side():
    roster = {"forwards": [{"id": 1, "sweaterNumber": 9}, {"id": 2, "sweaterNumber": 55}]}
    club_stats = {"skaters": [{"playerId": 1, "points": 40}]}
    assert set(player_details_from_api(roster, club_stats)) == {1}


def test_player_details_skips_a_malformed_entry_without_losing_the_rest():
    roster = {
        "forwards": [{"id": "not-a-number", "sweaterNumber": 9}, {"id": 2, "sweaterNumber": 55}]
    }
    club_stats = {"skaters": [{"playerId": 1, "points": 40}, {"playerId": 2, "points": 20}]}
    assert set(player_details_from_api(roster, club_stats)) == {2}


# -- three stars (#156) -------------------------------------------------------

from scoreboard.hockey.models import Star, three_stars_from_landing  # noqa: E402


def _star_raw(star=1, team="CAR", name="F. Unger Sorum", goals=1, assists=0, points=1):
    """Shaped like a real final game's landing ``threeStars`` entry."""
    return {
        "star": star,
        "playerId": 8484392,
        "teamAbbrev": team,
        "name": {"default": name},
        "sweaterNo": 36,
        "position": "R",
        "goals": goals,
        "assists": assists,
        "points": points,
    }


def test_star_parses_a_real_shaped_entry():
    star = Star.from_api(_star_raw())
    assert star == Star(
        star=1,
        player_id=8484392,
        team_abbrev="CAR",
        name="F. Unger Sorum",
        sweater_no=36,
        position="R",
        goals=1,
        assists=0,
        points=1,
    )


def test_star_goalie_entry_without_skater_stats_reads_as_zero():
    raw = _star_raw(star=3)
    for key in ("goals", "assists", "points"):
        del raw[key]
    raw["position"] = "G"
    star = Star.from_api(raw)
    assert (star.goals, star.assists, star.points, star.position) == (0, 0, 0, "G")


def test_three_stars_from_landing_orders_by_rank():
    raw = {"threeStars": [_star_raw(star=3), _star_raw(star=1), _star_raw(star=2)]}
    assert [s.star for s in three_stars_from_landing(raw)] == [1, 2, 3]


def test_three_stars_from_landing_absent_is_empty():
    assert three_stars_from_landing(None) == ()
    assert three_stars_from_landing({}) == ()
    assert three_stars_from_landing({"threeStars": None}) == ()
    assert three_stars_from_landing({"threeStars": []}) == ()


def test_three_stars_from_landing_skips_a_malformed_entry_without_losing_the_rest():
    raw = {"threeStars": [{"name": {"default": "NO RANK"}}, _star_raw(star=2, name="OK")]}
    assert [s.name for s in three_stars_from_landing(raw)] == ["OK"]


import random  # noqa: E402

from scoreboard.hockey.models import (  # noqa: E402
    ClubStats,
    GoalieLine,
    SkaterLine,
    team_leaders,
)


def _goalie(pid: int, gp: int) -> GoalieLine:
    return GoalieLine(pid, f"G. {pid}", gp, 1, 2, 3, 0.9)


def test_team_leaders_picks_max_goals_points_and_top_two_goalies_by_games():
    stats = ClubStats(
        skaters=(
            SkaterLine(1, "A. A", 10, 1, 11),
            SkaterLine(2, "B. B", 4, 20, 24),
            SkaterLine(3, "C. C", 2, 2, 4),
        ),
        goalies=(_goalie(1, 5), _goalie(2, 50), _goalie(3, 30)),
    )
    leaders = team_leaders(stats, random.Random(0))
    assert leaders.goals.player_id == 1
    assert leaders.points.player_id == 2
    assert [g.player_id for g in leaders.goalies] == [2, 3]


def test_team_leaders_ties_are_random_but_always_a_tied_player():
    stats = ClubStats(tuple(SkaterLine(i, f"P. {i}", 0, 0, 0) for i in range(20)), ())
    picks = {team_leaders(stats, random.Random(seed)).goals.player_id for seed in range(30)}
    assert len(picks) > 1
    assert picks <= set(range(20))


def test_team_leaders_tie_only_among_the_actual_leaders():
    stats = ClubStats(
        (
            SkaterLine(1, "A. A", 5, 0, 5),
            SkaterLine(2, "B. B", 5, 0, 5),
            SkaterLine(3, "C. C", 1, 0, 1),
        ),
        (),
    )
    for seed in range(20):
        assert team_leaders(stats, random.Random(seed)).goals.player_id in {1, 2}


def test_team_leaders_none_when_nothing_to_show():
    assert team_leaders(ClubStats((), ())) is None


def test_team_leaders_goalies_only_still_shows():
    leaders = team_leaders(ClubStats((), (_goalie(1, 3),)))
    assert leaders.goals is None and leaders.points is None
    assert len(leaders.goalies) == 1


def test_goalie_save_pct_label():
    assert GoalieLine(1, "G", 1, 0, 0, 0, 0.915).save_pct_label() == ".915"
    assert GoalieLine(1, "G", 1, 0, 0, 0, 1.0).save_pct_label() == "1.000"
    assert GoalieLine(1, "G", 0, 0, 0, 0, 0.0).save_pct_label() == ".000"


# -- season series meetings (#168) -----------------------------------------

from datetime import date  # noqa: E402

from scoreboard.hockey.models import MeetingResult, SeriesMeeting  # noqa: E402

MEETING = SeriesMeeting(1, date(2026, 1, 10), "MIN", "NSH", 2, 3, "OT")


def test_meeting_result_from_each_side():
    assert MEETING.result_for("NSH") == MeetingResult(date(2026, 1, 10), True, 3, 2, "OT")
    assert MEETING.result_for(" min ") == MeetingResult(date(2026, 1, 10), False, 2, 3, "OT")
    assert MEETING.result_for("NSH").score_label() == "3-2"


def test_meeting_result_none_for_a_team_not_in_it():
    assert MEETING.result_for("DAL") is None


def test_regulation_meeting_has_no_suffix():
    regulation = SeriesMeeting(1, date(2026, 1, 10), "MIN", "NSH", 4, 1, "REG")
    assert regulation.result_for("NSH").decided_in == ""
    assert not regulation.result_for("NSH").won


def test_unseen_period_type_passes_through_as_the_suffix():
    """SO is presumed, not seen live (#168): whatever the API says is shown as-is."""
    shootout = SeriesMeeting.from_api(
        {
            "id": 1,
            "gameDate": "2026-01-10",
            "gameType": 2,
            "gameState": "FINAL",
            "awayTeam": {"abbrev": "min", "score": 3},
            "homeTeam": {"abbrev": "nsh", "score": 2},
            "gameOutcome": {"lastPeriodType": "SO"},
        }
    )
    assert shootout.result_for("NSH").decided_in == "SO"
    assert shootout.result_for("MIN").won


def test_missing_game_outcome_reads_as_regulation():
    meeting = SeriesMeeting.from_api(
        {
            "id": 1,
            "gameDate": "2026-01-10",
            "gameType": 2,
            "gameState": "OFF",
            "awayTeam": {"abbrev": "MIN", "score": 3},
            "homeTeam": {"abbrev": "NSH", "score": 2},
        }
    )
    assert meeting.last_period_type == "REG"


def _end_of_period(period, away, home):
    return Game.from_api(
        {
            "id": 1,
            "gameState": "LIVE",
            "period": period,
            "periodDescriptor": {"number": period, "periodType": "REG", "maxRegulationPeriods": 3},
            "clock": {"timeRemaining": "00:00", "running": False, "inIntermission": True},
            "awayTeam": {"abbrev": "NSH", "score": away},
            "homeTeam": {"abbrev": "CAR", "score": home},
        }
    )


def test_no_third_intermission_when_the_game_is_decided():
    assert not _end_of_period(3, 3, 2).in_intermission
    assert _end_of_period(3, 2, 2).in_intermission  # tied: OT follows
    assert _end_of_period(2, 3, 2).in_intermission  # earlier periods unaffected


def _seq_row(abbrev: str, division_sequence: int, wildcard_sequence: int = 0, conf: str = "W"):
    return StandingsRow(
        abbrev=abbrev,
        conference=conf,
        division="C",
        division_sequence=division_sequence,
        wildcard_sequence=wildcard_sequence,
        conference_sequence=1,
        clinch_indicator="",
        points=0,
        games_played=1,
        wins=0,
        losses=0,
        ot_losses=0,
    )


def test_wildcard_standings_ranks_teams_outside_the_division_top_three():
    from scoreboard.hockey.models import wildcard_standings

    rows = [
        _seq_row("A", 1),
        _seq_row("C", 4, 2),
        _seq_row("B", 4, 1),
        _seq_row("D", 5, 3),
        _seq_row("E", 4, 1, conf="E"),
    ]
    assert [r.abbrev for r in wildcard_standings(rows, "w")] == ["B", "C", "D"]


def test_playoff_cut_is_the_count_of_leading_teams_in():
    from scoreboard.hockey.models import playoff_cut

    rows = [_seq_row("A", 1), _seq_row("B", 2), _seq_row("C", 3), _seq_row("D", 4)]
    assert playoff_cut(rows) == 3


@pytest.mark.parametrize(
    "sequences",
    [
        [1, 2, 3],  # everyone in: nothing to draw
        [4, 5, 6],  # everyone out
        [1, 4, 2],  # in-rows aren't a clean prefix: a line would mislead
    ],
)
def test_playoff_cut_is_none_without_a_clean_line(sequences):
    from scoreboard.hockey.models import playoff_cut

    rows = [_seq_row(f"T{i}", s) for i, s in enumerate(sequences)]
    assert playoff_cut(rows) is None


# -- the intermission stats ------------------------------------------------------------------------

from scoreboard.hockey.models import game_stats_from_right_rail  # noqa: E402

RIGHT_RAIL = {
    "teamGameStats": [
        {"category": "sog", "awayValue": 19, "homeValue": 25},
        {"category": "faceoffWinningPctg", "awayValue": 0.589286, "homeValue": 0.410714},
        {"category": "faceoffWins", "awayValue": "33/56", "homeValue": "23/56"},
        {"category": "powerPlay", "awayValue": "0/2", "homeValue": "1/2"},
        {"category": "pim", "awayValue": 6, "homeValue": 4},
        {"category": "hits", "awayValue": 28, "homeValue": 23},
        {"category": "blockedShots", "awayValue": 11, "homeValue": 10},
        {"category": "giveaways", "awayValue": 8, "homeValue": 17},
        {"category": "takeaways", "awayValue": 4, "homeValue": 1},
    ],
    "shotsByPeriod": [
        {"periodDescriptor": {"number": 1, "periodType": "REG"}, "away": 6, "home": 8},
        {"periodDescriptor": {"number": 2, "periodType": "REG"}, "away": 5, "home": 9},
        {"periodDescriptor": {"number": 3, "periodType": "REG"}, "away": 8, "home": 8},
    ],
}


def test_game_stats_read_the_right_rail_in_display_order_with_who_leads():
    stats = game_stats_from_right_rail(RIGHT_RAIL)
    rows = {line.label: line for line in stats.lines}
    assert [line.label for line in stats.lines] == [
        "SHOTS", "FACEOFF", "PP", "HITS", "PIM", "BLOCKS", "GIVE", "TAKE",
    ]  # fmt: skip
    assert (rows["SHOTS"].away, rows["SHOTS"].home, rows["SHOTS"].leader) == ("19", "25", "home")
    assert (rows["FACEOFF"].away, rows["FACEOFF"].home) == ("59%", "41%")
    assert rows["FACEOFF"].leader == "away"
    assert rows["PP"].leader == "home", "a power play compares its goals"
    assert rows["PIM"].leader == "home", "fewer penalty minutes is the better side"
    assert rows["GIVE"].leader == "away", "and fewer giveaways"
    assert rows["TAKE"].leader == "away"


def test_game_stats_pages_are_five_rows_with_the_last_two_periods_of_shots_at_the_end():
    stats = game_stats_from_right_rail(RIGHT_RAIL)
    pages = stats.pages
    assert [len(p) for p in pages] == [5, 5]
    assert [line.label for line in pages[1]] == ["BLOCKS", "GIVE", "TAKE", "SOG P2", "SOG P3"]
    assert [line.leader for line in pages[1][3:]] == ["home", None]


def test_a_tie_and_a_missing_number_have_no_leader():
    stats = game_stats_from_right_rail(
        {
            "teamGameStats": [
                {"category": "hits", "awayValue": 9, "homeValue": 9},
                {"category": "sog", "awayValue": None, "homeValue": 4},
            ]
        }
    )
    assert [(line.label, line.leader) for line in stats.lines] == [("SHOTS", None), ("HITS", None)]
    assert stats.lines[0].away == "-"


def test_game_stats_skip_a_malformed_entry_and_are_none_without_any_stats():
    stats = game_stats_from_right_rail(
        {
            "teamGameStats": [
                {"category": "hits"},
                {"category": "sog", "awayValue": 1, "homeValue": 2},
            ]
        }
    )
    assert [line.label for line in stats.lines] == ["SHOTS"]
    assert game_stats_from_right_rail({"teamGameStats": []}) is None
    assert game_stats_from_right_rail({}) is None
    assert game_stats_from_right_rail(None) is None
    assert (
        game_stats_from_right_rail({"teamGameStats": [{"category": "bogus", "awayValue": 1}]})
        is None
    )


# -- the shot map ------------------------------------------------------------------------------

from scoreboard.hockey.models import shot_map_from_play_by_play  # noqa: E402


def _pbp(*plays, home_id=6, away_id=26):
    return {"awayTeam": {"id": away_id}, "homeTeam": {"id": home_id}, "plays": list(plays)}


def _shot(owner, x, y, kind="shot-on-goal", defending="left", period_type="REG"):
    play = {
        "typeDescKey": kind,
        "periodDescriptor": {"number": 1, "periodType": period_type},
        "details": {"xCoord": x, "yCoord": y, "eventOwnerTeamId": owner},
    }
    if defending is not None:
        play["homeTeamDefendingSide"] = defending
    return play


def test_the_home_team_attacks_the_right_net_and_the_away_team_the_left():
    # Period one: home (6) defends the left end, so it shoots at x > 0 and away at x < 0.
    shots = shot_map_from_play_by_play(_pbp(_shot(6, 80, 22), _shot(26, -70, -10)))
    assert [(s.side, s.x, s.y) for s in shots.shots] == [("home", 80, 22), ("away", -70, -10)]


def test_the_ends_swap_in_the_next_period_so_the_shots_are_turned_back():
    # Period two: home defends the right end, so it now shoots at x < 0 and away at x > 0.
    shots = shot_map_from_play_by_play(
        _pbp(_shot(6, -80, -22, defending="right"), _shot(26, 70, 10, defending="right"))
    )
    assert [(s.side, s.x, s.y) for s in shots.shots] == [("home", 80, 22), ("away", -70, -10)]


def test_a_play_with_no_defending_side_is_read_from_where_it_is():
    shots = shot_map_from_play_by_play(_pbp(_shot(6, -80, -22, defending=None)))
    assert [(s.side, s.x, s.y) for s in shots.shots] == [("home", 80, 22)]


def test_goals_are_marked_and_only_shots_on_goal_and_goals_count():
    shots = shot_map_from_play_by_play(
        _pbp(
            _shot(6, 80, 1, "goal"),
            _shot(6, 70, 2),
            _shot(6, 75, 3, "missed-shot"),
            _shot(26, -75, 3, "blocked-shot"),
            _shot(26, -60, 3, "hit"),
        )
    )
    assert [(s.x, s.goal) for s in shots.shots] == [(80, True), (70, False)]


def test_shootout_attempts_and_impossible_coordinates_are_left_out():
    shots = shot_map_from_play_by_play(
        _pbp(
            _shot(6, 80, 1, period_type="SO"),
            _shot(6, 150, 0),
            _shot(6, 80, 60),
            _shot(6, 71, 5),
        )
    )
    assert [(s.x, s.y) for s in shots.shots] == [(71, 5)]


def test_one_bad_play_does_not_lose_the_rest_and_no_shots_is_none():
    shots = shot_map_from_play_by_play(
        _pbp({"typeDescKey": "shot-on-goal", "details": {}}, _shot(6, 80, 1), _shot(99, 80, 1))
    )
    assert len(shots.shots) == 1, "an unknown team is skipped too"
    assert shot_map_from_play_by_play(_pbp()) is None
    assert shot_map_from_play_by_play({"plays": []}) is None
    assert shot_map_from_play_by_play(None) is None


def test_shots_of_a_side_are_picked_out():
    shots = shot_map_from_play_by_play(_pbp(_shot(6, 80, 1), _shot(26, -80, 1), _shot(26, -70, 2)))
    assert len(shots.of("away")) == 2 and len(shots.of("home")) == 1


def _so_game(state: str, away: int, home: int) -> Game:
    return Game.from_api(
        {
            "id": 9,
            "gameState": state,
            "awayTeam": {"abbrev": "UTA", "score": away},
            "homeTeam": {"abbrev": "NSH", "score": home},
            "periodDescriptor": {"number": 5, "periodType": "SO", "maxRegulationPeriods": 3},
            "clock": {"timeRemaining": "00:00", "running": False, "inIntermission": False},
        }
    )


def test_shootout_with_a_winner_is_final_even_if_feed_stays_crit() -> None:
    game = _so_game("CRIT", 6, 5)
    assert game.is_final
    assert not game.is_live
    assert not game.shows_shootout


def test_shootout_still_level_stays_live() -> None:
    game = _so_game("CRIT", 5, 5)
    assert game.is_live
    assert game.shows_shootout
