"""College as a sport of the ranked [[teams]] list (#545).

The config, the priority layer and the admin save accept college teams; the app keeps them inert
(never switches to a sport it does not run) until a college feed exists (epic #534).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from scoreboard import admin_server
from scoreboard.config import (
    FOOTBALL_SPORTS,
    RUNNING_SPORTS,
    TEAM_SPORTS,
    TEAMS_MAX,
    Settings,
    TeamEntry,
    _parse_teams,
    team_exists,
)
from scoreboard.priority import Kind, Priority, Windows

NOW = datetime(2026, 11, 21, 17, 0, tzinfo=UTC)
WINDOWS = {
    "hockey": Windows(timedelta(hours=2), timedelta(minutes=30)),
    "football": Windows(timedelta(minutes=60), timedelta(minutes=60)),
    "college": Windows(timedelta(minutes=60), timedelta(minutes=60)),
}


def row(sport, team):
    return {"sport": sport, "team": team}


@dataclass
class G:
    id: int
    away: str
    home: str
    state: str = "live"
    start_utc: datetime | None = None

    is_live = property(lambda self: self.state == "live")
    is_final = property(lambda self: self.state == "final")
    is_pregame = property(lambda self: self.state == "pre")

    def involves(self, abbrev):
        return abbrev in (self.away, self.home)


# -- config ---------------------------------------------------------------------------------------


def test_college_is_a_sport_the_app_runs_with_a_football_style_engine():
    assert "college" in TEAM_SPORTS and "college" in RUNNING_SPORTS
    assert set(RUNNING_SPORTS) <= set(TEAM_SPORTS)
    assert FOOTBALL_SPORTS == ("football", "college")


@pytest.mark.parametrize("abbrev", ["UGA", "UTSA", "SJSU", "M-OH", "TA&M", "BGSU", "OSU", "BYU"])
def test_real_fbs_abbreviations_are_accepted(abbrev):
    assert team_exists("college", abbrev)


@pytest.mark.parametrize("abbrev", ["", "A", "TOOLONGX", "ga", "UG A", "U/GA", "TNF", "SNF", "MNF"])
def test_what_could_not_be_an_abbreviation_is_refused(abbrev):
    assert not team_exists("college", abbrev)


def test_the_nfl_and_college_share_abbreviations_so_the_sport_is_the_key():
    teams = _parse_teams([row("football", "CIN"), row("college", "CIN"), row("college", "HOU")])
    assert teams == [
        TeamEntry("football", "CIN"),
        TeamEntry("college", "CIN"),
        TeamEntry("college", "HOU"),
    ]
    settings = Settings.from_dict({"teams": [row("football", "CIN"), row("college", "CIN")]})
    assert settings.rank_of("college", "CIN") == 2 and settings.rank_of("football", "CIN") == 1
    assert settings.teams_for("college") == ["CIN"]


def test_three_sports_mix_in_file_order_and_share_the_twelve_slot_cap():
    mixed = [row("hockey", "NSH"), row("football", "TEN"), row("college", "UGA")]
    assert [t.sport for t in _parse_teams(mixed)] == ["hockey", "football", "college"]
    many = [row("college", f"T{i:02d}") for i in range(TEAMS_MAX + 3)]
    assert len(_parse_teams(many)) == TEAMS_MAX


def test_case_is_forgiven_and_a_repeat_keeps_its_higher_place(caplog):
    with caplog.at_level(logging.WARNING):
        teams = _parse_teams(
            [row("college", " uga "), row("college", "BAMA"), row("college", "UGA")]
        )
    assert teams == [TeamEntry("college", "UGA"), TeamEntry("college", "BAMA")]
    assert "already ranked higher" in caplog.text


def test_a_college_entry_survives_a_save_and_reload(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[scoreboard]\nrotate_seconds = 9\n")
    settings = Settings.from_toml(path)
    settings.save({"teams": [row("college", "UGA"), row("hockey", "NSH"), row("college", "M-OH")]})
    assert Settings.from_toml(path).teams == [
        TeamEntry("college", "UGA"),
        TeamEntry("hockey", "NSH"),
        TeamEntry("college", "M-OH"),
    ]


# -- the admin save -------------------------------------------------------------------------------


def test_the_admin_save_accepts_college_rows():
    out = admin_server._coerce_teams({"teams": [row("college", "uga"), row("hockey", "NSH")]})
    assert out == [row("college", "UGA"), row("hockey", "NSH")]


def test_the_admin_save_refuses_a_malformed_college_abbreviation_and_names_the_row():
    with pytest.raises(ValueError) as err:
        admin_server._coerce_teams({"teams": [row("hockey", "NSH"), row("college", "NOT A TEAM")]})
    assert "row 2" in json.loads(str(err.value)) and "college team" in str(err.value)


def test_the_admin_save_refuses_the_same_college_team_twice_but_not_across_sports():
    with pytest.raises(ValueError, match="already in the list"):
        admin_server._coerce_teams({"teams": [row("college", "UGA"), row("college", "UGA")]})
    assert admin_server._coerce_teams({"teams": [row("football", "CIN"), row("college", "CIN")]})


# -- the priority layer ---------------------------------------------------------------------------


def board(*rows):
    return Priority([TeamEntry(s, t) for s, t in rows])


def test_a_live_college_game_owns_the_board_by_rank_across_sports():
    games = {"hockey": [G(1, "NSH", "TOR")], "football": [], "college": [G(7, "UGA", "AUB")]}
    college_first = board(("college", "UGA"), ("hockey", "NSH"))
    moment = college_first.owner(games, NOW, WINDOWS)
    assert (moment.sport, moment.team, moment.kind) == ("college", "UGA", Kind.LIVE)
    hockey_first = board(("hockey", "NSH"), ("college", "UGA"))
    assert hockey_first.owner(games, NOW, WINDOWS).sport == "hockey"


def test_the_nfl_cin_and_the_college_cin_do_not_see_each_others_games():
    # Cincinnati's two teams have the same abbreviation: each only matches its own sport's slate.
    games = {"football": [G(1, "CIN", "BAL")], "college": [G(2, "UC", "ISU")]}
    assert board(("college", "CIN")).owner(games, NOW, WINDOWS) is None
    assert board(("football", "CIN")).owner(games, NOW, WINDOWS).sport == "football"


def test_a_college_countdown_and_held_final_follow_its_own_windows():
    soon = G(3, "UGA", "AUB", "pre", NOW + timedelta(minutes=30))
    assert board(("college", "UGA")).owner({"college": [soon]}, NOW, WINDOWS).kind is Kind.COUNTDOWN
    done = G(4, "UGA", "AUB", "final")
    held = board(("college", "UGA")).owner(
        {"college": [done]}, NOW, WINDOWS, {("college", 4): timedelta(minutes=10)}
    )
    assert held.kind is Kind.FINAL


def test_sports_lists_college_in_rank_order_and_the_lead_team_is_per_sport():
    priority = board(("college", "UGA"), ("hockey", "NSH"), ("college", "BAMA"))
    assert priority.sports() == ["college", "hockey"]


def test_colour_team_can_skip_a_team_whose_colours_cannot_be_drawn_yet():
    priority = board(("college", "UGA"), ("hockey", "NSH"))
    assert priority.colour_team().sport == "college"
    assert priority.colour_team(lambda e: e.sport != "college").team == "NSH"
    assert board(("college", "UGA")).colour_team(lambda e: e.sport != "college") is None


def test_with_no_hockey_or_football_team_ranked_a_live_game_of_either_still_takes_the_board():
    # A list holding only college teams is not "empty": nothing else should be pulled in by it.
    only_college = Priority([TeamEntry("college", "UGA")])
    assert not only_college.empty
    assert only_college.empty_list_sport({"hockey": [G(1, "NSH", "TOR")]}) is None
