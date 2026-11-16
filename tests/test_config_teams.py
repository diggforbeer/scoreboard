"""The ranked ``[[teams]]`` list (epic #470, story #471): parsing, validation and saving."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from scoreboard.config import TEAMS_MAX, Settings, TeamEntry, _parse_teams


def entry(sport, team):
    return {"sport": sport, "team": team}


def test_the_list_is_empty_by_default_and_when_absent():
    assert Settings().teams == []
    assert Settings.from_dict({}).teams == []
    assert Settings.from_dict({"teams": []}).teams == []


def test_hockey_and_football_teams_mix_in_file_order():
    teams = _parse_teams([entry("hockey", "NSH"), entry("football", "TEN"), entry("hockey", "TOR")])
    assert teams == [
        TeamEntry("hockey", "NSH"),
        TeamEntry("football", "TEN"),
        TeamEntry("hockey", "TOR"),
    ]


def test_the_same_abbreviation_in_two_sports_is_two_teams():
    """BUF is Buffalo in both leagues: the sport is part of the key."""
    teams = _parse_teams([entry("hockey", "BUF"), entry("football", "BUF")])
    assert teams == [TeamEntry("hockey", "BUF"), TeamEntry("football", "BUF")]


def test_case_and_spaces_are_forgiven():
    assert _parse_teams([{"sport": " Football ", "team": " nyg "}]) == [
        TeamEntry("football", "NYG")
    ]


@pytest.mark.parametrize(
    ("row", "why"),
    [
        (entry("basketball", "NSH"), "sport"),
        (entry("hockey", "TEN"), "hockey team"),  # TEN is football only
        (entry("football", "NSH"), "football team"),  # NSH is hockey only
        (entry("hockey", ""), "hockey team"),
        ({"team": "NSH"}, "sport"),
        ("NSH", "not a table"),
    ],
)
def test_a_bad_entry_is_dropped_with_a_warning_and_the_rest_kept(row, why, caplog):
    with caplog.at_level(logging.WARNING):
        teams = _parse_teams([entry("hockey", "NSH"), row, entry("football", "TEN")])
    assert teams == [TeamEntry("hockey", "NSH"), TeamEntry("football", "TEN")]
    assert why in caplog.text


def test_a_repeat_keeps_its_first_and_highest_place(caplog):
    with caplog.at_level(logging.WARNING):
        teams = _parse_teams(
            [entry("hockey", "NSH"), entry("football", "TEN"), entry("hockey", "NSH")]
        )
    assert teams == [TeamEntry("hockey", "NSH"), TeamEntry("football", "TEN")]
    assert "already ranked higher" in caplog.text


def test_only_the_first_twelve_are_kept(caplog):
    football = [
        "ARI",
        "ATL",
        "BAL",
        "BUF",
        "CAR",
        "CHI",
        "CIN",
        "CLE",
        "DAL",
        "DEN",
        "DET",
        "GB",
        "HOU",
        "IND",
    ]
    with caplog.at_level(logging.WARNING):
        teams = _parse_teams([entry("football", t) for t in football])
    assert len(teams) == TEAMS_MAX == 12
    assert [t.team for t in teams] == football[:12]
    assert "only the first 12" in caplog.text


@pytest.mark.parametrize("raw", ["NSH", {"sport": "hockey", "team": "NSH"}, 5])
def test_something_that_is_not_a_list_is_ignored(raw, caplog):
    with caplog.at_level(logging.WARNING):
        assert _parse_teams(raw) == []
    assert "must be a list" in caplog.text


# -- the accessors -----------------------------------------------------------------------------


def test_teams_for_and_rank_of():
    settings = Settings.from_dict(
        {"teams": [entry("hockey", "NSH"), entry("football", "TEN"), entry("hockey", "TOR")]}
    )
    assert settings.teams_for("hockey") == ["NSH", "TOR"]
    assert settings.teams_for("football") == ["TEN"]
    assert (settings.rank_of("hockey", "NSH"), settings.rank_of("football", "TEN")) == (1, 2)
    assert settings.rank_of("hockey", "TOR") == 3
    assert settings.rank_of("football", "NSH") is None
    assert settings.rank_of("hockey", "TEN") is None, "TEN is ranked, but as a football team"


# -- the file ------------------------------------------------------------------------------------

TEMPLATE = """\
# A comment that must survive every save.
[scoreboard]
favourite_team = "NSH"   # and this one

[[teams]]
sport = "hockey"
team = "NSH"

[panel]
rows = 32
"""


def write(tmp_path: Path, text: str = TEMPLATE) -> Settings:
    path = tmp_path / "scoreboard.toml"
    path.write_text(text)
    return Settings.from_toml(path)


def test_the_list_loads_from_the_file(tmp_path):
    assert write(tmp_path).teams == [TeamEntry("hockey", "NSH")]


def test_saving_replaces_the_whole_list_in_order_and_reloads_it(tmp_path):
    settings = write(tmp_path)
    settings.save(
        {"teams": [entry("football", "TEN"), entry("hockey", "NSH"), entry("football", "NYG")]}
    )
    assert settings.teams == [
        TeamEntry("football", "TEN"),
        TeamEntry("hockey", "NSH"),
        TeamEntry("football", "NYG"),
    ]
    assert Settings.from_toml(settings.source_path).teams == settings.teams
    text = settings.source_path.read_text()
    assert text.count("[[teams]]") == 3, "an array of tables, not an inline array"


def test_saving_keeps_the_comments_and_the_other_sections(tmp_path):
    settings = write(tmp_path)
    settings.save({"teams": [entry("football", "TEN")]})
    text = settings.source_path.read_text()
    assert "# A comment that must survive every save." in text and "# and this one" in text
    assert settings.scoreboard.favourite_team == "NSH" and settings.panel.rows == 32


def test_saving_an_empty_list_removes_it(tmp_path):
    settings = write(tmp_path)
    settings.save({"teams": []})
    assert settings.teams == []
    assert "teams" not in settings.source_path.read_text()


def test_saving_other_sections_leaves_the_list_alone(tmp_path):
    settings = write(tmp_path)
    settings.save({"panel": {"brightness": 40}})
    assert settings.teams == [TeamEntry("hockey", "NSH")]


def test_a_hand_edited_bad_row_is_dropped_on_load_not_fatal(tmp_path):
    bad = '\n[[teams]]\nsport = "hockey"\nteam = "XXX"\n'
    good = '\n[[teams]]\nsport = "football"\nteam = "TEN"\n'
    text = TEMPLATE + bad + good
    assert write(tmp_path, text).teams == [TeamEntry("hockey", "NSH"), TeamEntry("football", "TEN")]
