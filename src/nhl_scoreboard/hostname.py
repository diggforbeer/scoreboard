"""The board's mDNS name (#292): validation, applying a chosen name, and the
plain ``scoreboard.local`` alias.

``scoreboard-provision`` picks ``scoreboard-xxxx`` from the MAC once; an owner
can replace it with a friendlier name (``[status] hostname``). Applied the same
way in both places so a boot-time and a live change behave identically.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

HOSTNAME_FILE = Path("/etc/hostname")
HOSTS_FILE = Path("/etc/hosts")
#: Existence means a name was chosen and must never be re-derived from the MAC.
HOSTNAME_STATE = Path("/var/lib/nhl-scoreboard/hostname-chosen")

ALIAS_NAME = "scoreboard"
_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def normalise_hostname(value: str) -> str:
    return value.strip().lower().removesuffix(".local")


def valid_hostname_label(value: str) -> bool:
    """A single RFC 1123 label: letters, digits, inner hyphens, 1-63 chars."""
    return bool(_LABEL.match(value))


def current_hostname() -> str:
    return socket.gethostname()


def apply_hostname(
    name: str,
    *,
    hostname_file: Path = HOSTNAME_FILE,
    hosts_file: Path = HOSTS_FILE,
    state_file: Path = HOSTNAME_STATE,
    run: Callable[..., object] = subprocess.run,
) -> bool:
    """Make ``name`` the board's hostname and re-announce it. Never raises.

    Returns whether the files were written. The state file is written too, so
    ``scoreboard-provision`` never re-derives a MAC name over an owner's choice.
    """
    try:
        hostname_file.write_text(f"{name}\n")
        if hosts_file.exists():
            lines = [ln for ln in hosts_file.read_text().splitlines() if "127.0.1.1" not in ln]
            hosts_file.write_text("\n".join([*lines, f"127.0.1.1\t{name}"]) + "\n")
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(f"{name}\n")
    except OSError as exc:
        log.error("Could not set hostname: %s", exc)
        return False
    log.info("Hostname set to %s", name)
    # avahi reads the hostname at startup, so it has to be restarted to
    # announce the new one. Best-effort.
    for cmd in (["hostname", name], ["systemctl", "restart", "avahi-daemon.service"]):
        try:
            run(cmd, check=False, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("%s failed: %s", cmd[0], exc)
    return True


class AliasPublisher:
    """Publishes ``scoreboard.local`` for this board's IP while it is free.

    ``avahi-publish-address`` (no ``-R``) probes first and exits non-zero if
    another host already owns the name, which is how the second board on a
    network ends up without it: the alias only ever goes to whoever got there
    first. Who holds it may change after a power cut, which is why it is an
    alias and the board's own stored name is what to bookmark.
    """

    def __init__(self, popen: Callable[..., subprocess.Popen] = subprocess.Popen) -> None:
        self._popen = popen
        self._proc: subprocess.Popen | None = None
        self._ip: str | None = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def sync(self, wanted: bool, ip: str | None) -> None:
        """Start, move or stop the alias to match ``wanted`` and the current IP."""
        if not wanted or ip is None:
            self.stop()
            return
        if self._ip == ip and self._proc is not None:
            # Already tried for this IP. A process that has exited means the
            # name is taken (or avahi-utils is absent); retrying every tick
            # would just spam it. A new IP is a fresh attempt.
            return
        self.stop()
        try:
            self._proc = self._popen(
                ["avahi-publish-address", f"{ALIAS_NAME}.local", ip],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            log.warning("Could not publish %s.local: %s", ALIAS_NAME, exc)
            self._proc = None
        self._ip = ip

    def stop(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None
        self._ip = None
