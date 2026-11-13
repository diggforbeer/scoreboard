"""The NFL team table (#347)."""

from __future__ import annotations

import pytest

from nhl_scoreboard.display import teams as nhl_teams
from nhl_scoreboard.football import teams

#: ESPN's ids for the 32 teams, as returned by .../football/nfl/teams on
#: 2026-11-13. Pinned here so a typo in the table fails a test.
ESPN_IDS = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3, "CIN": 4, "CLE": 5,
    "DAL": 6, "DEN": 7, "DET": 8, "GB": 9, "HOU": 34, "IND": 11, "JAX": 30, "KC": 12,
    "LV": 13, "LAC": 24, "LAR": 14, "MIA": 15, "MIN": 16, "NE": 17, "NO": 18, "NYG": 19,
    "NYJ": 20, "PHI": 21, "PIT": 23, "SF": 25, "SEA": 26, "TB": 27, "TEN": 10, "WSH": 28,
}  # fmt: skip

#: A colour darker than this is hard to read on the panel. The dimmest NHL
#: colour in display/teams.py sits around 96; 60 leaves room without letting a
#: navy or black through.
MIN_LUMINANCE = 60


def luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_there_are_exactly_32_teams_with_unique_abbreviations_and_ids():
    assert len(teams.TEAMS) == 32
    assert len({t.espn_id for t in teams.TEAMS.values()}) == 32
    assert len({t.abbrev for t in teams.TEAMS.values()}) == 32


def test_every_id_matches_espns():
    assert {a: t.espn_id for a, t in teams.TEAMS.items()} == ESPN_IDS


@pytest.mark.parametrize("abbrev", sorted(ESPN_IDS))
def test_colours_are_bright_enough_for_the_panel(abbrev):
    t = teams.TEAMS[abbrev]
    assert luminance(t.color) >= MIN_LUMINANCE, f"{abbrev} primary is too dark"
    assert luminance(t.secondary) >= MIN_LUMINANCE, f"{abbrev} secondary is too dark"
    for channel in (*t.color, *t.secondary):
        assert 0 <= channel <= 255


@pytest.mark.parametrize("abbrev", sorted(ESPN_IDS))
def test_screen_names_are_upper_case_and_short(abbrev):
    name = teams.TEAMS[abbrev].name
    assert name == name.upper()
    assert 0 < len(name) <= 12, "must fit a 64px panel's headline"


def test_the_two_new_york_and_two_los_angeles_teams_can_be_told_apart():
    names = {teams.team(a).name for a in ("NYG", "NYJ", "LAC", "LAR")}
    assert len(names) == 4


def test_lookup_by_abbreviation_ignores_case_and_spaces():
    assert teams.team("nyg") is teams.TEAMS["NYG"]
    assert teams.team(" WSH ").nickname == "Commanders"
    assert teams.team_name("GB") == "GREEN BAY"
    assert teams.team_color("NYG") == teams.TEAMS["NYG"].color
    assert teams.team_secondary_color("NYG") == teams.TEAMS["NYG"].secondary


def test_lookup_by_id_takes_an_int_or_the_feeds_string():
    assert teams.team_by_id(19).abbrev == "NYG"
    assert teams.team_by_id("28").abbrev == "WSH"


def test_an_unknown_team_fails_clearly():
    with pytest.raises(teams.UnknownTeamError, match="'XYZ'"):
        teams.team("XYZ")
    with pytest.raises(teams.UnknownTeamError, match="'99'"):
        teams.team_by_id("99")
    with pytest.raises(teams.UnknownTeamError):
        teams.team_by_id(None)
    assert not teams.is_team("NSH")  # an NHL team is not an NFL team
    assert teams.is_team("kc")


def test_abbreviations_are_the_sorted_set_of_valid_teams():
    assert tuple(sorted(ESPN_IDS)) == teams.ABBREVIATIONS


def test_the_nfl_and_nhl_tables_are_separate():
    assert teams.TEAMS is not nhl_teams.TEAM_COLORS
    # Abbreviations that exist in both leagues resolve to different teams.
    shared = set(teams.TEAMS) & set(nhl_teams.TEAM_COLORS)
    assert {"BUF", "CAR", "DAL", "DET", "MIN"} <= shared
    assert teams.team("BUF").color != nhl_teams.team_color("BUF")
    assert teams.team("DAL").color != nhl_teams.team_color("DAL")
    # And NHL-only abbreviations are not NFL teams.
    assert "NSH" not in teams.TEAMS and "NSH" in nhl_teams.TEAM_COLORS
