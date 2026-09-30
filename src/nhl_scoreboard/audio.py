"""Goal horn playback.

Mirrors display/logos.py's LogoLibrary: an ordered list of directories, a
team-specific file first, the shipped default as fallback, absence is never
an error. Playback is fire-and-forget via aplay so it never blocks the
render loop; a missing file or broken audio device is logged and otherwise
ignored -- sound is a nice-to-have, not load-bearing.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_NAME = "_default.wav"

#: ALSA mixer control names to try, in order, when applying `volume` --
#: which one a given card actually exposes isn't standardised (the kernel's
#: usb-audio driver names it "PCM" or "Speaker" depending on the device;
#: "Master"/"Headphone" cover onboard/HDMI-style cards). The first one that
#: `amixer sset` accepts wins; this has not been verified against real USB
#: audio hardware (see CLAUDE.md's other not-yet-verified hardware notes) --
#: flagged, not proven.
VOLUME_CONTROLS: tuple[str, ...] = ("PCM", "Speaker", "Master", "Headphone")


def upload_directory() -> Path:
    """Where the admin page's horn uploads live (#193).

    Persistent and writable, unlike the image-baked /usr/share directory,
    which a reflash would wipe (same class of bug #185 fixed for the admin
    frontend). Checked before that directory, so an upload overrides the
    shipped horn.
    """
    return Path(os.environ.get("NHL_SCOREBOARD_UPLOAD_HORN_DIR", "/var/lib/nhl-scoreboard/horns"))


def default_directories(override: str = "") -> list[Path]:
    """Where to look for horn files, most specific first."""
    dirs: list[Path] = []
    if override:
        dirs.append(Path(override))
    env = os.environ.get("NHL_SCOREBOARD_HORN_DIR")
    if env:
        dirs.append(Path(env))
    dirs.append(upload_directory())
    dirs.append(Path("/usr/share/nhl-scoreboard/horns"))
    dirs.append(Path(__file__).resolve().parents[2] / "assets" / "horns")
    return dirs


class GoalHornPlayer:
    def __init__(
        self,
        directories: Sequence[Path],
        device: str = "",
        enabled: bool = True,
        volume: int = 100,
        runner: Callable[[list[str]], None] | None = None,
        mixer_runner: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.directories = [Path(d) for d in directories]
        self.device = device
        self.enabled = enabled
        self.volume = volume
        self._run = runner or self._popen
        self._run_mixer = mixer_runner or self._amixer

    @classmethod
    def default(
        cls, device: str = "", horn_dir: str = "", enabled: bool = True, volume: int = 100
    ) -> GoalHornPlayer:
        return cls(default_directories(horn_dir), device=device, enabled=enabled, volume=volume)

    def path_for(self, abbrev: str) -> Path | None:
        """Team-specific file first, the shipped default otherwise.

        Two-tier: every directory is checked for the team file before any
        directory is checked for the default, so specificity beats
        directory order -- a team file anywhere in the search path wins
        over a default earlier in it.
        """
        for name in (f"{abbrev.strip().upper()}.wav", DEFAULT_NAME):
            for directory in self.directories:
                candidate = directory / name
                if candidate.is_file():
                    return candidate
        return None

    def play(self, abbrev: str) -> bool:
        """Launch playback for ``abbrev``'s horn, or the default. Never raises."""
        if not self.enabled:
            return False
        path = self.path_for(abbrev)
        if path is None:
            log.debug("No horn for %s and no default available", abbrev)
            return False
        cmd = ["aplay", "-q"]
        if self.device:
            cmd += ["-D", self.device]
        cmd.append(str(path))
        try:
            self._run(cmd)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("Could not play %s: %s", path, exc)
            return False
        log.debug("Playing %s", path)
        return True

    def apply_volume(self) -> bool:
        """Set the ALSA mixer to `self.volume`, trying VOLUME_CONTROLS in turn.

        Unlike play(), this blocks (a bounded `amixer` call, not `aplay`
        playing a multi-second file) and is meant to be called explicitly
        at the points GoalHornPlayer itself is (re)built from settings --
        startup and a live [audio] reload/test -- not from inside play(),
        which must stay non-blocking for the render loop. Returns whether
        any control accepted it; never raises, same "sound is a nice-to-
        have" doctrine as play().
        """
        base = ["amixer", "-q"]
        if self.device:
            base += ["-D", self.device]
        for control in VOLUME_CONTROLS:
            cmd = [*base, "sset", control, f"{self.volume}%"]
            try:
                if self._run_mixer(cmd):
                    log.debug("Set volume to %d%% via %s", self.volume, control)
                    return True
            except (OSError, subprocess.SubprocessError) as exc:
                log.debug("Could not set volume via %s: %s", control, exc)
        log.warning("Could not set volume via any of %s (device=%r)", VOLUME_CONTROLS, self.device)
        return False

    @staticmethod
    def _popen(cmd: list[str]) -> None:
        # Fire-and-forget: the render loop must not block on playback, and
        # we have no use for the exit status once it's launched.
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    @staticmethod
    def _amixer(cmd: list[str]) -> bool:
        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2
        )
        return result.returncode == 0
