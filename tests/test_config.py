from __future__ import annotations

import pytest

from nhl_scoreboard.config import ConfigWriteError, Settings


def test_defaults_describe_two_chained_64x32_panels():
    settings = Settings()
    assert (settings.panel.width, settings.panel.height) == (128, 32)
    assert settings.panel.hardware_mapping == "regular"


def test_default_favourite_is_nashville_but_overridable(tmp_path):
    assert Settings().scoreboard.favourite_team == "NSH"

    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = ""\n')
    assert Settings.load(path).scoreboard.favourite_team == ""


def test_loads_toml(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        """
        [scoreboard]
        favourite_team = "tor"
        rotate_seconds = 5

        [panel]
        chain_length = 1
        brightness = 40
        """
    )
    settings = Settings.load(path)
    assert settings.scoreboard.favourite_team == "TOR"  # normalised to upper
    assert settings.scoreboard.rotate_seconds == 5
    assert settings.panel.chain_length == 1
    assert settings.panel.width == 64
    assert settings.panel.brightness == 40
    # Untouched keys keep their defaults.
    assert settings.panel.rows == 32
    assert settings.source_path == path


def test_unknown_keys_are_ignored_not_fatal(tmp_path, caplog):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[panel]\nrows = 16\nnonsense = "typo"\n')
    settings = Settings.load(path)
    assert settings.panel.rows == 16
    assert "nonsense" in caplog.text


def test_missing_file_falls_back_to_defaults(tmp_path):
    settings = Settings.load(tmp_path / "absent.toml")
    assert settings.panel.width == 128
    assert settings.source_path is None


def test_auto_brightness_defaults_off():
    panel = Settings().panel
    assert panel.auto_brightness is False
    assert (panel.min_brightness, panel.max_brightness) == (10, 100)


def test_status_server_defaults_off(tmp_path):
    assert Settings().status.enabled is False
    assert Settings().status.port == 8080

    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = true\nport = 9000\n")
    status = Settings.load(path).status
    assert status.enabled is True
    assert status.port == 9000


def test_brightness_clamp_is_kept_within_0_100():
    settings = Settings()
    settings.panel.min_brightness = -5
    settings.panel.max_brightness = 500
    settings.panel.__post_init__()
    assert (settings.panel.min_brightness, settings.panel.max_brightness) == (1, 100)


def test_inverted_brightness_clamp_is_swapped_not_left_broken(caplog):
    from nhl_scoreboard.config import PanelConfig

    panel = PanelConfig(min_brightness=80, max_brightness=20)
    assert (panel.min_brightness, panel.max_brightness) == (20, 80)
    assert "min_brightness" in caplog.text


def test_save_preserves_comments_and_only_changes_targeted_keys(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        """
        # a helpful comment about favourite_team
        [scoreboard]
        favourite_team = "NSH"
        rotate_seconds = 8

        # a helpful comment about brightness
        [panel]
        brightness = 60
        chain_length = 2
        """
    )
    settings = Settings.load(path)
    settings.save({"scoreboard": {"favourite_team": "tor"}, "panel": {"brightness": 80}})

    text = path.read_text()
    assert "# a helpful comment about favourite_team" in text
    assert "# a helpful comment about brightness" in text
    assert 'favourite_team = "tor"' in text
    assert "brightness = 80" in text
    # Untouched keys are byte-for-byte unchanged.
    assert "rotate_seconds = 8" in text
    assert "chain_length = 2" in text

    # In-memory settings reflect the write without a separate reload.
    assert settings.scoreboard.favourite_team == "TOR"  # normalised, same as load
    assert settings.panel.brightness == 80
    assert settings.panel.chain_length == 2


def test_save_adds_a_section_missing_from_the_file(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    settings.save({"audio": {"enabled": False}})
    assert settings.audio.enabled is False
    assert Settings.load(path).audio.enabled is False


def test_save_without_a_loaded_file_raises():
    settings = Settings()
    with pytest.raises(ConfigWriteError):
        settings.save({"scoreboard": {"favourite_team": "TOR"}})


def test_save_failure_is_not_silent(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    path.unlink()
    path.mkdir()  # any write to "path" now fails with IsADirectoryError
    with pytest.raises(ConfigWriteError):
        settings.save({"scoreboard": {"favourite_team": "TOR"}})


def test_physical_size_follows_pitch():
    settings = Settings()
    assert settings.panel.pitch_mm == 2.5
    assert settings.panel.physical_mm == (320.0, 80.0)

    settings.panel.pitch_mm = 2.0
    assert settings.panel.physical_mm == (256.0, 64.0)
