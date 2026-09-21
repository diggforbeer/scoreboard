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


def default_directories(override: str = "") -> list[Path]:
    """Where to look for horn files, most specific first."""
    dirs: list[Path] = []
    if override:
        dirs.append(Path(override))
    env = os.environ.get("NHL_SCOREBOARD_HORN_DIR")
    if env:
        dirs.append(Path(env))
    dirs.append(Path("/usr/share/nhl-scoreboard/horns"))
    dirs.append(Path(__file__).resolve().parents[2] / "assets" / "horns")
    return dirs


class GoalHornPlayer:
    def __init__(
        self,
        directories: Sequence[Path],
        device: str = "",
        enabled: bool = True,
        runner: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.directories = [Path(d) for d in directories]
        self.device = device
        self.enabled = enabled
        self._run = runner or self._popen

    @classmethod
    def default(cls, device: str = "", horn_dir: str = "", enabled: bool = True) -> GoalHornPlayer:
        return cls(default_directories(horn_dir), device=device, enabled=enabled)

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

    @staticmethod
    def _popen(cmd: list[str]) -> None:
        # Fire-and-forget: the render loop must not block on playback, and
        # we have no use for the exit status once it's launched.
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
