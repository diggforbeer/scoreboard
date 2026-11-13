"""``[football]``: the NFL favourite and followed teams (#348)."""

from __future__ import annotations

import logging

from nhl_scoreboard.config import FootballConfig, ScoreboardConfig, Settings


def test_there_is_no_default_favourite_and_nobody_is_followed():
    cfg = FootballConfig()
    assert cfg.favourite_team == "" and cfg.also_follow == [] and cfg.followed_teams == []
    assert Settings().football == cfg


def test_a_valid_favourite_and_followed_teams_are_kept_normalised():
    cfg = FootballConfig(favourite_team=" kc ", also_follow=["nyg", " WSH"])
    assert cfg.favourite_team == "KC" and cfg.also_follow == ["NYG", "WSH"]
    assert cfg.followed_teams == ["KC", "NYG", "WSH"]


def test_followed_teams_without_a_favourite_are_still_followed():
    cfg = FootballConfig(also_follow=["NYG"])
    assert cfg.followed_teams == ["NYG"]


def test_the_favourite_is_not_also_followed_and_duplicates_collapse():
    cfg = FootballConfig(favourite_team="KC", also_follow=["KC", "NYG", "NYG", "kc"])
    assert cfg.also_follow == ["NYG"]


def test_an_nhl_only_abbreviation_is_ignored_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = FootballConfig(favourite_team="NSH", also_follow=["TOR", "KC"])
    assert cfg.favourite_team == "" and cfg.also_follow == ["KC"]
    messages = " ".join(r.getMessage() for r in caplog.records)
    assert "'NSH'" in messages and "'TOR'" in messages


def test_junk_values_never_raise():
    assert FootballConfig(favourite_team=None, also_follow=None).also_follow == []  # type: ignore[arg-type]
    assert FootballConfig(also_follow="KC").also_follow == ["KC"]  # a bare string is one team
    assert FootballConfig(also_follow=[1, None, "KC", {}]).also_follow == ["KC"]  # type: ignore[list-item]
    assert FootballConfig(also_follow=7).also_follow == []  # type: ignore[arg-type]


def test_buf_is_a_different_team_in_each_sport_and_the_settings_are_independent():
    settings = Settings.from_dict(
        {"scoreboard": {"favourite_team": "BUF"}, "football": {"favourite_team": "BUF"}}
    )
    assert settings.scoreboard.favourite_team == "BUF" and settings.football.favourite_team == "BUF"
    # Changing one does not touch the other.
    other = Settings.from_dict(
        {"scoreboard": {"favourite_team": "TOR"}, "football": {"favourite_team": "BUF"}}
    )
    assert other.scoreboard.favourite_team == "TOR" and other.football.favourite_team == "BUF"
    assert Settings().scoreboard.favourite_team == ScoreboardConfig().favourite_team == "NSH"


def test_an_nfl_abbreviation_is_not_accepted_as_an_nhl_team_that_does_not_exist():
    # KC is an NFL team only: the NHL side must still reject it.
    cfg = ScoreboardConfig(also_follow=["KC", "TOR"])
    assert cfg.also_follow == ["TOR"]


def test_the_section_round_trips_through_the_toml_file(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('# my comment\n[scoreboard]\nfavourite_team = "BUF"\nsport = "nfl"\n')
    settings = Settings.from_toml(path)
    settings.save({"football": {"favourite_team": "KC", "also_follow": ["NYG", "WSH"]}})
    text = path.read_text()
    assert "# my comment" in text and 'favourite_team = "BUF"' in text  # NHL untouched
    reloaded = Settings.from_toml(path)
    assert reloaded.football.favourite_team == "KC" and reloaded.football.also_follow == [
        "NYG",
        "WSH",
    ]
    assert reloaded.scoreboard.favourite_team == "BUF"
    # The in-memory object saw the change too.
    assert settings.football.followed_teams == ["KC", "NYG", "WSH"]


def test_saving_the_nhl_side_leaves_the_nfl_choices_alone(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[football]\nfavourite_team = "KC"\nalso_follow = ["NYG"]\n')
    settings = Settings.from_toml(path)
    settings.save({"scoreboard": {"favourite_team": "TOR", "sport": "nhl"}})
    again = Settings.from_toml(path)
    assert again.scoreboard.favourite_team == "TOR"
    assert again.football.favourite_team == "KC" and again.football.also_follow == ["NYG"]
    settings.save({"scoreboard": {"sport": "nfl"}})
    settings.save({"scoreboard": {"sport": "nhl"}})
    assert Settings.from_toml(path).football.also_follow == ["NYG"], "switching back keeps them"


def test_a_typo_in_the_section_warns_and_is_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        settings = Settings.from_dict(
            {"football": {"favourite_team": "KC", "favorite_team": "NYG"}}
        )
    assert settings.football.favourite_team == "KC"
    assert any("favorite_team" in r.getMessage() for r in caplog.records)
