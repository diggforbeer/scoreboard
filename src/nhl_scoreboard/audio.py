"""Goal horn playback.

Mirrors display/logos.py's LogoLibrary: an ordered list of directories, a
team-specific file first, the shipped default as fallback, absence is never
an error. Playback is fire-and-forget via aplay so it never blocks the
render loop (aplay for WAV, mpg123 for MP3); a missing file or broken audio
device is logged and otherwise ignored -- sound is a nice-to-have, not load-bearing.
"""

from __future__ import annotations

import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_STEM = "_default"
DEFAULT_NAME = f"{DEFAULT_STEM}.wav"

#: The "wah wah" sting for the opponent's goals (#307). One shared file, no
#: per-team variants; an upload or drop-in of this name overrides the shipped one.
WAH_WAH_STEM = "_wah_wah"

#: The "ding" for a followed (non-favourite) team's goals (#311); same override rules.
DING_STEM = "_ding"

#: Horn file extensions, in lookup order within one directory. WAV plays
#: through aplay, MP3 through mpg123 (#208) -- aplay can't decode MP3.
HORN_EXTENSIONS: tuple[str, ...] = (".wav", ".mp3")

#: ALSA mixer control names to try, in order, when applying `volume` --
#: which one a given card actually exposes isn't standardised (the kernel's
#: usb-audio driver names it "PCM" or "Speaker" depending on the device;
#: "Master"/"Headphone" cover onboard/HDMI-style cards). The first one that
#: `amixer sset` accepts wins; this has not been verified against real USB
#: audio hardware (see CLAUDE.md's other not-yet-verified hardware notes) --
#: flagged, not proven.
VOLUME_CONTROLS: tuple[str, ...] = ("PCM", "Speaker", "Master", "Headphone")

#: apt package that provides each player command. A board flashed before
#: mpg123 joined the image (#208) has aplay but not mpg123, and the in-app
#: updater can't install packages, so a missing player needs saying plainly.
PLAYER_PACKAGES: dict[str, str] = {"aplay": "alsa-utils", "mpg123": "mpg123"}


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
        wah_wah: bool = False,
        ding: bool = True,
        runner: Callable[[list[str]], None] | None = None,
        mixer_runner: Callable[[list[str]], bool] | None = None,
    ) -> None:
        self.directories = [Path(d) for d in directories]
        self.device = device
        self.enabled = enabled
        self.volume = volume
        self.wah_wah = wah_wah
        self.ding = ding
        self._run = runner or self._popen
        self._run_mixer = mixer_runner or self._amixer
        #: Why the last play() returned False, in words fit for the admin
        #: page; "" after a success or when the cause was just "disabled".
        self.last_error = ""
        self._warned_players: set[str] = set()

    @classmethod
    def default(
        cls,
        device: str = "",
        horn_dir: str = "",
        enabled: bool = True,
        volume: int = 100,
        wah_wah: bool = False,
        ding: bool = True,
    ) -> GoalHornPlayer:
        return cls(
            default_directories(horn_dir),
            device=device,
            enabled=enabled,
            volume=volume,
            wah_wah=wah_wah,
            ding=ding,
        )

    def path_for(self, abbrev: str) -> Path | None:
        """Team-specific file first, the shipped default otherwise.

        Two-tier: every directory is checked for the team file before any
        directory is checked for the default, so specificity beats
        directory order -- a team file anywhere in the search path wins
        over a default earlier in it.
        """
        return self._find(abbrev.strip().upper(), DEFAULT_STEM)

    def wah_wah_path(self) -> Path | None:
        """The opponent-goal sting: uploads and drop-ins first, then the shipped file."""
        return self._find(WAH_WAH_STEM)

    def ding_path(self) -> Path | None:
        """The followed-team ding: uploads and drop-ins first, then the shipped file."""
        return self._find(DING_STEM)

    def _find(self, *stems: str) -> Path | None:
        for stem in stems:
            for directory in self.directories:
                for ext in HORN_EXTENSIONS:
                    candidate = directory / f"{stem}{ext}"
                    if candidate.is_file():
                        return candidate
        return None

    def play(self, abbrev: str) -> bool:
        """Launch playback for ``abbrev``'s horn, or the default. Never raises."""
        self.last_error = ""
        if not self.enabled:
            return False
        path = self.path_for(abbrev)
        if path is None:
            log.debug("No horn for %s and no default available", abbrev)
            return False
        return self._launch(path)

    def play_wah_wah(self, force: bool = False) -> bool:
        """Launch the opponent-goal sting. Off unless ``wah_wah`` is on (``force``
        skips that, for the admin page's Play button); never raises."""
        self.last_error = ""
        if not (self.enabled and (self.wah_wah or force)):
            return False
        path = self.wah_wah_path()
        if path is None:
            log.debug("No wah-wah sound available")
            return False
        return self._launch(path)

    def play_ding(self, force: bool = False) -> bool:
        """Launch the followed-team ding. Off unless ``ding`` is on (``force`` skips
        that, for the admin page's Play button); never raises."""
        self.last_error = ""
        if not (self.enabled and (self.ding or force)):
            return False
        path = self.ding_path()
        if path is None:
            log.debug("No ding sound available")
            return False
        return self._launch(path)

    def _launch(self, path: Path) -> bool:
        if path.suffix.lower() == ".mp3":
            cmd = ["mpg123", "-q"]
            if self.device:
                cmd += ["-a", self.device]
        else:
            cmd = ["aplay", "-q"]
            if self.device:
                cmd += ["-D", self.device]
        cmd.append(str(path))
        try:
            self._run(cmd)
        except FileNotFoundError as exc:
            player = cmd[0]
            package = PLAYER_PACKAGES.get(player, player)
            self.last_error = (
                f"{player} isn't installed on this board, so {path.name} can't play. "
                f"Install it with 'sudo apt-get install {package}', or use a WAV horn."
            )
            # Once per player: this fires on every goal, and the cause won't change.
            if player not in self._warned_players:
                self._warned_players.add(player)
                log.warning("Could not play %s: %s", path, self.last_error)
            else:
                log.debug("Could not play %s: %s", path, exc)
            return False
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"The player command ({cmd[0]}) failed to launch: {exc}"
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
