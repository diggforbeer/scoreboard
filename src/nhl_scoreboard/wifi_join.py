"""Attempts to join the network submitted via the AP setup page (#133).

The setup page (#132, setup_server.py) only ever writes a submission file --
it never touches iwd/iwctl itself. This module is what actually acts on it:
tear down the AP, hand the credentials to nhl_scoreboard.wifi's shared join/
rollback path, and report the outcome back to the panel.

Runs the join on a background thread, off ScoreboardApp's render loop
(poll() is called every frame and must never block): a real join attempt
can take up to connect_timeout seconds (90s by default), and freezing score
polling/rendering for that long would defeat the whole point of a scoreboard
that's still trying to show something during setup.

The panel is the feedback channel, not the HTTP response that triggered the
attempt (decided in #133's own issue discussion): tearing down the AP to
attempt the join kills the phone's connection to the page that submitted it,
before any HTTP response describing success/failure could reach it. So the
outcome is written to its own state file, read the same way #141's AP-setup
scene already reads its own -- ScoreboardApp.select_scene() shows it with
top priority, independent of whatever happened to the request that started
this.

A failed join restarts nhl-scoreboard-setup-ap (also decided in #133) so the
AP comes back and the person can reconnect and retry -- expected to happen
routinely, not treated as some rare edge case.
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import wifi

log = logging.getLogger(__name__)

DEFAULT_SETUP_AP_SCRIPT = Path("/usr/local/sbin/nhl-scoreboard-setup-ap")
#: How long "Connected!"/"Failed..." stays up once the attempt is over,
#: before scene selection falls through to whatever's next (normal game
#: data if actually online, or the ap_setup SSID/QR scene if the AP came
#: back after a failure) -- long enough to read, short enough not to sit
#: there once the outcome no longer needs announcing. Not used for
#: "attempting", which has no fixed duration of its own: it just stays up
#: for exactly as long as the attempt is actually running.
OUTCOME_DISPLAY_SECONDS = 15.0


class WifiJoinAttempt:
    """Runs one join attempt on a background thread when a submission appears.

    Both the submission and outcome files live in /run by default, matching
    every other AP-setup-mode state file (#131/#132/#141) -- never survive a
    reboot stale.
    """

    def __init__(
        self,
        config_path: Path,
        connect_timeout: float,
        submission_path: Path,
        outcome_path: Path,
        setup_ap_script: Path | None = None,
        wall_clock: Callable[[], float] | None = None,
    ) -> None:
        self.config_path = config_path
        self.connect_timeout = connect_timeout
        self.submission_path = submission_path
        self.outcome_path = outcome_path
        self.setup_ap_script = setup_ap_script or DEFAULT_SETUP_AP_SCRIPT
        #: Wall clock, not monotonic: compared against the outcome file's
        #: own mtime (st_mtime is wall-clock), which a monotonic clock isn't
        #: meaningfully comparable to. Injectable for tests only.
        self._wall_clock = wall_clock or time.time
        self._thread: threading.Thread | None = None

    @property
    def in_progress(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def poll(self) -> None:
        """Check for a new submission and start a join attempt if idle.

        Cheap (a stat, maybe a read) -- call every frame from
        ScoreboardApp.run()'s loop, same as the other AP-setup state-file
        polls. Never blocks: the actual join runs on its own thread. A
        submission that shows up mid-attempt is left alone -- consumed
        (read + deleted) only once this one finishes, same "one at a time"
        precedent as the rest of this app's polling.
        """
        if self.in_progress:
            return
        try:
            raw = self.submission_path.read_text()
        except FileNotFoundError:
            return
        except OSError as exc:
            log.warning("Could not read WiFi setup submission: %s", exc)
            return
        try:
            self.submission_path.unlink()
        except OSError as exc:
            log.warning("Could not remove consumed WiFi setup submission: %s", exc)
        try:
            data = json.loads(raw)
            ssid = str(data["ssid"])
            password = data.get("password")
            password = str(password) if password is not None else None
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("Malformed WiFi setup submission: %s", exc)
            return
        self._thread = threading.Thread(
            target=self._attempt, args=(ssid, password), daemon=True, name="wifi-join"
        )
        self._thread.start()

    def expire_outcome_if_stale(self) -> None:
        """Remove the outcome file once it's been shown long enough.

        Separate from poll(): that one starts attempts, this one is
        lifecycle cleanup for rendering -- deliberately never touches the
        outcome file while an attempt is actually in progress ("attempting"
        has no timer of its own; it stays up for exactly as long as the
        thread is running).
        """
        if self.in_progress:
            return
        try:
            mtime = self.outcome_path.stat().st_mtime
        except OSError:
            return
        if self._wall_clock() - mtime >= OUTCOME_DISPLAY_SECONDS:
            self.outcome_path.unlink(missing_ok=True)

    def _attempt(self, ssid: str, password: str | None) -> None:
        try:
            self._write_outcome("attempting", ssid)
            self._run_setup_ap("stop")
            succeeded = wifi.apply_wifi(
                {"ssid": ssid, "password": password or ""},
                self.config_path,
                connect_timeout=self.connect_timeout,
            )
            if succeeded:
                self._write_outcome("connected", ssid)
            else:
                self._run_setup_ap("start")
                self._write_outcome("failed", ssid)
        except Exception:
            # Never let a crash here leave "attempting" up forever with no
            # way to reach the board at all -- the AP is already down by
            # the time anything past _run_setup_ap("stop") could raise, so
            # this is the last chance to bring it back.
            log.exception("WiFi join attempt for %r crashed", ssid)
            self._run_setup_ap("start")
            self._write_outcome("failed", ssid)

    def _run_setup_ap(self, subcommand: str) -> None:
        try:
            subprocess.run([str(self.setup_ap_script), subcommand], check=False, timeout=30)
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("nhl-scoreboard-setup-ap %s failed: %s", subcommand, exc)

    def _write_outcome(self, status: str, ssid: str) -> None:
        """Atomic tmp+replace, same convention as Settings.save()/setup_server.py's
        own submission write -- a reader never sees a half-written file."""
        payload = json.dumps({"status": status, "ssid": ssid})
        tmp_path = self.outcome_path.with_name(self.outcome_path.name + ".tmp")
        try:
            tmp_path.write_text(payload)
            tmp_path.replace(self.outcome_path)
        except OSError as exc:
            log.warning("Could not write WiFi join outcome: %s", exc)
