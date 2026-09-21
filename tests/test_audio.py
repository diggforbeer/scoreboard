"""GoalHornPlayer: lookup order, fallback, and that playback never raises.

A fake runner replaces subprocess.Popen so these never touch real audio
hardware or aplay, and run identically with or without ALSA installed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nhl_scoreboard.audio import DEFAULT_NAME, GoalHornPlayer, default_directories


class RecordingRunner:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self.raises = raises

    def __call__(self, cmd: list[str]) -> None:
        self.calls.append(cmd)
        if self.raises:
            raise self.raises


def touch(path: Path) -> Path:
    path.write_bytes(b"RIFF....WAVEfmt ")
    return path


def test_team_file_found_first(tmp_path):
    touch(tmp_path / "NSH.wav")
    touch(tmp_path / DEFAULT_NAME)
    player = GoalHornPlayer([tmp_path])
    assert player.path_for("nsh") == tmp_path / "NSH.wav"  # case-insensitive


def test_falls_back_to_default_when_team_file_missing(tmp_path):
    touch(tmp_path / DEFAULT_NAME)
    player = GoalHornPlayer([tmp_path])
    assert player.path_for("NSH") == tmp_path / DEFAULT_NAME


def test_no_file_and_no_default_is_none_not_an_error(tmp_path):
    player = GoalHornPlayer([tmp_path])
    assert player.path_for("NSH") is None
    assert player.play("NSH") is False


def test_team_file_beats_default_across_all_directories(tmp_path):
    """Specificity wins over directory order: a team file anywhere in the
    search path is preferred over a default earlier in it. Every directory
    is checked for the team file before any is checked for the default."""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    touch(a / DEFAULT_NAME)
    touch(b / "NSH.wav")
    player = GoalHornPlayer([a, b])
    assert player.path_for("NSH") == b / "NSH.wav"


def test_directory_order_still_applies_within_a_tier(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    touch(a / "NSH.wav")
    touch(b / "NSH.wav")
    player = GoalHornPlayer([a, b])
    assert player.path_for("NSH") == a / "NSH.wav"


def test_play_launches_aplay_with_the_resolved_path(tmp_path):
    touch(tmp_path / "NSH.wav")
    runner = RecordingRunner()
    player = GoalHornPlayer([tmp_path], runner=runner)
    assert player.play("NSH") is True
    assert runner.calls == [["aplay", "-q", str(tmp_path / "NSH.wav")]]


def test_device_is_passed_through(tmp_path):
    touch(tmp_path / DEFAULT_NAME)
    runner = RecordingRunner()
    player = GoalHornPlayer([tmp_path], device="plughw:1,0", runner=runner)
    player.play("NSH")
    assert runner.calls == [["aplay", "-q", "-D", "plughw:1,0", str(tmp_path / DEFAULT_NAME)]]


def test_disabled_never_launches_anything(tmp_path):
    touch(tmp_path / DEFAULT_NAME)
    runner = RecordingRunner()
    player = GoalHornPlayer([tmp_path], enabled=False, runner=runner)
    assert player.play("NSH") is False
    assert runner.calls == []


def test_broken_runner_is_caught_not_raised(tmp_path):
    touch(tmp_path / DEFAULT_NAME)
    runner = RecordingRunner(raises=OSError("no such device"))
    player = GoalHornPlayer([tmp_path], runner=runner)
    assert player.play("NSH") is False  # logged, not raised


def test_default_directories_respects_override_and_env(monkeypatch, tmp_path):
    monkeypatch.delenv("NHL_SCOREBOARD_HORN_DIR", raising=False)
    dirs = default_directories()
    assert str(tmp_path) not in [str(d) for d in dirs]

    dirs = default_directories(str(tmp_path))
    assert dirs[0] == tmp_path

    monkeypatch.setenv("NHL_SCOREBOARD_HORN_DIR", str(tmp_path))
    dirs = default_directories()
    assert tmp_path in dirs


def test_default_horn_ships_and_is_a_valid_wav():
    """The synthesized siren is committed to the repo; sanity-check it."""
    import wave

    player = GoalHornPlayer.default()
    path = player.path_for("ZZZ")  # no team; falls through to the shipped default
    assert path is not None
    assert path.name == DEFAULT_NAME
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getnframes() > 0


@pytest.mark.parametrize("enabled", [True, False])
def test_default_constructor_wires_enabled_through(enabled):
    player = GoalHornPlayer.default(enabled=enabled)
    assert player.enabled is enabled
