from __future__ import annotations

import logging

import pytest

from nhl_scoreboard.config import (
    PANEL_HARDWARE_MAPPING_CHOICES,
    ConfigWriteError,
    Settings,
    next_hardware_mapping,
    resolve_timezone,
)


def test_defaults_describe_two_chained_64x32_panels():
    settings = Settings()
    assert (settings.panel.width, settings.panel.height) == (128, 32)
    assert settings.panel.hardware_mapping == "regular"
    assert settings.panel.rgb_sequence == "RGB"


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


def test_status_server_defaults_on(tmp_path):
    assert Settings().status.enabled is True
    assert Settings().status.port == 8080

    path = tmp_path / "scoreboard.toml"
    path.write_text("[status]\nenabled = false\nport = 9000\n")
    status = Settings.load(path).status
    assert status.enabled is False
    assert status.port == 9000


def test_wifi_setup_server_defaults_on_port_80(tmp_path):
    assert Settings().wifi_setup.enabled is True
    assert Settings().wifi_setup.port == 80

    path = tmp_path / "scoreboard.toml"
    path.write_text("[wifi_setup]\nenabled = false\nport = 8000\n")
    wifi_setup = Settings.load(path).wifi_setup
    assert wifi_setup.enabled is False
    assert wifi_setup.port == 8000


def test_wifi_connect_timeout_defaults_to_90_and_is_overridable(tmp_path):
    assert Settings().wifi.connect_timeout_seconds == 90.0

    path = tmp_path / "scoreboard.toml"
    path.write_text('[wifi]\nssid = "MyNetwork"\nconnect_timeout_seconds = 30\n')
    settings = Settings.load(path)
    assert settings.wifi.connect_timeout_seconds == 30.0


def test_wifi_ssid_password_country_are_not_modelled_and_do_not_warn(tmp_path, caplog):
    """ssid/password/country live in the same [wifi] section but are read
    directly out of raw TOML by scoreboard-provision, not through WifiConfig
    -- this pins down that loading a normal [wifi] section never trips
    _build()'s "unknown key" warning for any of them."""
    caplog.set_level(logging.WARNING)
    path = tmp_path / "scoreboard.toml"
    path.write_text('[wifi]\nssid = "MyNetwork"\npassword = "hunter2"\ncountry = "US"\n')
    Settings.load(path)
    assert "unknown config key" not in caplog.text.lower()


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


def test_static_brightness_is_clamped_like_min_and_max():
    from nhl_scoreboard.config import PanelConfig

    assert PanelConfig(brightness=0).brightness == 1
    assert PanelConfig(brightness=500).brightness == 100


def test_bad_poll_intervals_are_floored_instead_of_defeating_rate_limiting(tmp_path, caplog):
    """A 0 or negative interval must not make the run loop poll every frame (#64)."""
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        "[scoreboard]\npoll_seconds = 0\nlive_poll_seconds = -5\nrotate_seconds = 0.01\n"
    )
    scoreboard = Settings.load(path).scoreboard
    assert scoreboard.poll_seconds == 1.0
    assert scoreboard.live_poll_seconds == 1.0
    assert scoreboard.rotate_seconds == 1.0
    assert "poll_seconds" in caplog.text


def test_bad_brightness_poll_seconds_is_floored(caplog):
    from nhl_scoreboard.config import PanelConfig

    assert PanelConfig(brightness_poll_seconds=0).brightness_poll_seconds == 1.0
    assert "brightness_poll_seconds" in caplog.text


def test_reasonable_poll_intervals_are_left_alone():
    settings = Settings()
    assert settings.scoreboard.poll_seconds == 60.0
    assert settings.scoreboard.live_poll_seconds == 15.0
    assert settings.scoreboard.rotate_seconds == 8.0
    assert settings.panel.brightness_poll_seconds == 5.0


def test_resolve_timezone_passes_through_a_valid_zone():
    assert str(resolve_timezone("America/New_York")) == "America/New_York"


def test_resolve_timezone_falls_back_to_the_default_with_no_fallback_given(caplog):
    assert str(resolve_timezone("America/Chicagoo")) == "America/Chicago"
    assert "America/Chicagoo" in caplog.text


def test_resolve_timezone_keeps_the_given_fallback_instead_of_the_default(caplog):
    from zoneinfo import ZoneInfo

    fallback = ZoneInfo("America/New_York")
    assert resolve_timezone("America/Chicagoo", fallback=fallback) is fallback
    assert "America/Chicagoo" in caplog.text


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


def test_night_mode_defaults_off_without_a_section(tmp_path):
    from datetime import time

    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    night = Settings.load(path).night_mode
    assert night.enabled is False
    assert (night.start, night.end) == (time(22, 30), time(7, 0))
    assert night.dim_brightness == 0
    assert night.suppress_scope == "tracked"
    assert night.cooldown_minutes == 15.0


def test_night_mode_parses_valid_times(tmp_path):
    from datetime import time

    path = tmp_path / "scoreboard.toml"
    path.write_text('[night_mode]\nenabled = true\nstart_time = "23:15"\nend_time = "06:45"\n')
    night = Settings.load(path).night_mode
    assert night.enabled is True
    assert (night.start, night.end) == (time(23, 15), time(6, 45))


@pytest.mark.parametrize("bad", ["25:99", "not-a-time", ""])
def test_night_mode_malformed_times_fall_back_with_a_warning(bad, caplog):
    from datetime import time

    from nhl_scoreboard.config import NightModeConfig

    night = NightModeConfig(start_time=bad, end_time=bad)
    assert (night.start_time, night.end_time) == ("22:30", "07:00")
    assert (night.start, night.end) == (time(22, 30), time(7, 0))
    assert "start_time" in caplog.text
    assert "end_time" in caplog.text


@pytest.mark.parametrize(("given", "expected"), [(-10, 0), (0, 0), (40, 40), (250, 100)])
def test_night_mode_dim_brightness_clamped_to_0_100(given, expected):
    from nhl_scoreboard.config import NightModeConfig

    assert NightModeConfig(dim_brightness=given).dim_brightness == expected


def test_night_mode_bad_suppress_scope_falls_back_to_tracked(caplog):
    from nhl_scoreboard.config import NightModeConfig

    assert NightModeConfig(suppress_scope="everyone").suppress_scope == "tracked"
    assert "suppress_scope" in caplog.text


@pytest.mark.parametrize(("given", "expected"), [("tracked", "tracked"), (" ALL ", "all")])
def test_night_mode_valid_suppress_scope_passes_through(given, expected, caplog):
    from nhl_scoreboard.config import NightModeConfig

    assert NightModeConfig(suppress_scope=given).suppress_scope == expected
    assert "suppress_scope" not in caplog.text


def test_night_mode_cooldown_clamped_to_zero():
    from nhl_scoreboard.config import NightModeConfig

    assert NightModeConfig(cooldown_minutes=-5).cooldown_minutes == 0
    assert NightModeConfig(cooldown_minutes=0).cooldown_minutes == 0


def test_button_defaults_off_without_a_section(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    button = Settings.load(path).button
    assert button.enabled is False
    assert button.pin == 26
    assert button.mute_minutes == 60.0
    assert button.hold_seconds == 1.0


def test_button_parses_its_section(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text("[button]\nenabled = true\npin = 16\nmute_minutes = 15\nhold_seconds = 2\n")
    button = Settings.load(path).button
    assert (button.enabled, button.pin, button.mute_minutes, button.hold_seconds) == (
        True,
        16,
        15.0,
        2,
    )


def test_button_mute_minutes_clamped_to_zero(caplog):
    from nhl_scoreboard.config import ButtonConfig

    assert ButtonConfig(mute_minutes=-5).mute_minutes == 0
    assert ButtonConfig(mute_minutes=0).mute_minutes == 0
    assert "mute_minutes" not in caplog.text, "0 is valid; clamping it isn't worth a warning"


@pytest.mark.parametrize("given", [0, 0.1, -1])
def test_button_hold_seconds_floored_with_a_warning(given, caplog):
    from nhl_scoreboard.config import MIN_HOLD_SECONDS, ButtonConfig

    with caplog.at_level(logging.WARNING):
        assert ButtonConfig(hold_seconds=given).hold_seconds == MIN_HOLD_SECONDS
    assert "hold_seconds" in caplog.text


def test_button_reasonable_hold_seconds_left_alone(caplog):
    from nhl_scoreboard.config import ButtonConfig

    assert ButtonConfig(hold_seconds=0.5).hold_seconds == 0.5
    assert ButtonConfig(hold_seconds=3).hold_seconds == 3
    assert "hold_seconds" not in caplog.text


def test_night_mode_derived_times_are_not_settable_from_toml(tmp_path, caplog):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[night_mode]\nstart = "01:00"\n')
    night = Settings.load(path).night_mode  # must not raise
    assert night.start_time == "22:30"
    assert "start" in caplog.text


# -- configurable idle rotation (#150) ---------------------------------------


def test_rotation_absent_from_file_defaults_to_an_empty_list():
    """app.py derives the old implicit default list itself when this is empty."""
    assert Settings().rotation == []


def test_rotation_parses_screen_and_seconds_in_file_order(tmp_path):
    from nhl_scoreboard.config import RotationEntry

    path = tmp_path / "scoreboard.toml"
    path.write_text(
        """
        [[rotation]]
        screen = "countdown_preview"
        seconds = 10

        [[rotation]]
        screen = "standings"
        seconds = 15

        [[rotation]]
        screen = "clock"
        seconds = 8
        """
    )
    assert Settings.load(path).rotation == [
        RotationEntry("countdown_preview", 10.0),
        RotationEntry("standings", 15.0),
        RotationEntry("clock", 8.0),
    ]


def test_rotation_accepts_the_opt_in_matchup_screen(tmp_path):
    """#157: only reachable by listing it explicitly -- see test_flow's default-rotation test."""
    from nhl_scoreboard.config import RotationEntry

    path = tmp_path / "scoreboard.toml"
    path.write_text('[[rotation]]\nscreen = "matchup"\nseconds = 6\n')
    assert Settings.load(path).rotation == [RotationEntry("matchup", 6.0)]


def test_rotation_entry_with_unknown_screen_is_dropped_with_a_warning(tmp_path, caplog):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[[rotation]]\nscreen = "weather"\nseconds = 10\n')
    assert Settings.load(path).rotation == []
    assert "weather" in caplog.text


@pytest.mark.parametrize("bad_seconds", [0, -5, "soon"])
def test_rotation_entry_with_non_positive_or_non_numeric_seconds_is_dropped(bad_seconds, caplog):
    from nhl_scoreboard.config import _parse_rotation

    entries = _parse_rotation([{"screen": "clock", "seconds": bad_seconds}])
    assert entries == []
    assert "clock" in caplog.text


def test_rotation_valid_entries_kept_alongside_dropped_invalid_ones(tmp_path):
    from nhl_scoreboard.config import RotationEntry

    path = tmp_path / "scoreboard.toml"
    path.write_text(
        """
        [[rotation]]
        screen = "clock"
        seconds = 5

        [[rotation]]
        screen = "bogus"
        seconds = 5
        """
    )
    assert Settings.load(path).rotation == [RotationEntry("clock", 5.0)]


def test_save_writes_rotation_as_an_array_of_tables(tmp_path):
    from nhl_scoreboard.config import RotationEntry

    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\nfavourite_team = "NSH"\n')
    settings = Settings.load(path)
    settings.save(
        {
            "rotation": [
                {"screen": "countdown_preview", "seconds": 10},
                {"screen": "clock", "seconds": 8},
            ]
        }
    )

    assert settings.rotation == [
        RotationEntry("countdown_preview", 10.0),
        RotationEntry("clock", 8.0),
    ]
    reloaded = Settings.load(path)
    assert reloaded.rotation == settings.rotation
    text = path.read_text()
    assert "[[rotation]]" in text
    # The untouched [scoreboard] section survives the write.
    assert 'favourite_team = "NSH"' in text


def test_next_hardware_mapping_cycles_through_all_documented_choices():
    assert next_hardware_mapping("regular") == "adafruit-hat"
    assert next_hardware_mapping("adafruit-hat") == "adafruit-hat-pwm"
    assert next_hardware_mapping("adafruit-hat-pwm") == "regular"


def test_next_hardware_mapping_unknown_value_starts_over_at_the_first_choice():
    assert next_hardware_mapping("some-hand-edited-value") == PANEL_HARDWARE_MAPPING_CHOICES[0]
