from __future__ import annotations

from nhl_scoreboard.config import Settings


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


def test_physical_size_follows_pitch():
    settings = Settings()
    assert settings.panel.pitch_mm == 2.5
    assert settings.panel.physical_mm == (320.0, 80.0)

    settings.panel.pitch_mm = 2.0
    assert settings.panel.physical_mm == (256.0, 64.0)
