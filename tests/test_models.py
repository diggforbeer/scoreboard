from __future__ import annotations

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
