"""``[football]`` settings, and the retired team settings (epic #470).

Which teams the board follows is the ranked ``[[teams]]`` list now (``test_config_teams.py``); what
is left in ``[football]`` is the rotation, the screen lengths and the toggles.
"""

from __future__ import annotations

import logging

import pytest

from scoreboard import config
from scoreboard.config import FootballConfig, Settings


@pytest.fixture(autouse=True)
def _log_retired_keys_again():
    config._retired_logged.clear()
    yield
    config._retired_logged.clear()


def test_the_football_section_no_longer_has_team_settings():
    cfg = FootballConfig()
    assert not hasattr(cfg, "favourite_team") and not hasattr(cfg, "also_follow")
    assert not hasattr(cfg, "followed_teams")


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("football", "favourite_team", "KC"),
        ("football", "also_follow", ["NYG"]),
        ("scoreboard", "sport", "football"),
        ("scoreboard", "favourite_team", "TOR"),
        ("scoreboard", "also_follow", ["DAL"]),
    ],
)
def test_a_retired_team_setting_in_the_file_is_ignored_with_a_warning_saying_where_it_went(
    section, key, value, caplog
):
    with caplog.at_level(logging.WARNING):
        settings = Settings.from_dict({section: {key: value}, "teams": []})
    assert settings.teams == []
    assert any(key in r.getMessage() and "[[teams]]" in r.getMessage() for r in caplog.records)
    assert not any("unknown config key" in r.getMessage() for r in caplog.records)


def test_the_warning_is_logged_once_per_key_not_on_every_read(caplog):
    raw = {"scoreboard": {"favourite_team": "TOR"}}
    with caplog.at_level(logging.WARNING):
        Settings.from_dict(raw)
        Settings.from_dict(raw)
    assert sum("favourite_team" in r.getMessage() for r in caplog.records) == 1


def test_the_retired_keys_are_dropped_from_the_file_the_next_time_their_section_is_saved(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        '# keep me\n[scoreboard]\nsport = "football"\nfavourite_team = "BUF"\nrotate_seconds = 9\n'
        '[football]\nfavourite_team = "KC"\nalso_follow = ["NYG"]\nfinal_hold_minutes = 30\n'
    )
    settings = Settings.from_toml(path)
    settings.save({"scoreboard": {"rotate_seconds": 11}, "football": {"final_hold_minutes": 45}})
    text = path.read_text()
    assert "# keep me" in text and "favourite_team" not in text and "also_follow" not in text
    assert 'sport = "football"' not in text
    reloaded = Settings.from_toml(path)
    assert reloaded.scoreboard.rotate_seconds == 11 and reloaded.football.final_hold_minutes == 45


def test_a_typo_in_the_section_warns_and_is_ignored(caplog):
    with caplog.at_level(logging.WARNING):
        settings = Settings.from_dict({"football": {"final_hold_minutes": 20, "final_hold": 99}})
    assert settings.football.final_hold_minutes == 20
    assert any("final_hold" in r.getMessage() for r in caplog.records)
