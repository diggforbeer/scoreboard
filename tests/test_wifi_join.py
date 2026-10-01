"""WifiJoinAttempt (#133): orchestration only, not apply_wifi()'s own
join/rollback behaviour (that's test_wifi.py's job) or nhl-scoreboard-setup-
ap's own stop/start behaviour (test_setup_ap.py's). This mocks
nhl_scoreboard.wifi.apply_wifi() and fakes `systemctl` as a tiny recording
script (same idiom as test_scoreboard_provision.py/test_setup_ap.py), so
what's actually under test here is: does a submission get consumed and turn
into the right sequence of `systemctl stop`/apply_wifi/`systemctl start`-or-
not calls, and the right outcome file, in the right states, with the right
timing.

The AP is always driven through its systemd unit, never by running the
setup-ap script directly (#173) -- that bypass orphaned the unit's tracked
dnsmasq and left systemd reporting "active" over a dead radio.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

import pytest

from nhl_scoreboard import wifi_join as wifi_join_module
from nhl_scoreboard.wifi_join import OUTCOME_DISPLAY_SECONDS, SETUP_AP_UNIT, WifiJoinAttempt

STOP = f"stop {SETUP_AP_UNIT}"
START = f"start {SETUP_AP_UNIT}"


def write_fake(bindir: Path, name: str, body: str) -> Path:
    path = bindir / name
    path.write_text(f'#!/bin/sh\necho "$0 $*" >> "$FAKE_CALL_LOG"\n{body}')
    path.chmod(0o755)
    return path


@pytest.fixture
def rig(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    call_log = tmp_path / "calls.log"
    call_log.write_text("")
    systemctl = write_fake(bindir, "systemctl", 'exit "${FAKE_SYSTEMCTL_EXIT:-0}"\n')
    monkeypatch.setenv("FAKE_CALL_LOG", str(call_log))

    attempt = WifiJoinAttempt(
        config_path=tmp_path / "scoreboard.toml",
        connect_timeout=90.0,
        submission_path=tmp_path / "submission.json",
        outcome_path=tmp_path / "outcome.json",
        systemctl_bin=systemctl,
    )

    def calls() -> list[str]:
        # Each line is "<fake's own path> <args>"; only the args matter.
        prefix = f"{systemctl} "
        return [line.removeprefix(prefix) for line in call_log.read_text().splitlines()]

    attempt.calls = calls  # type: ignore[attr-defined]
    return attempt


def fake_apply_wifi(succeeds: bool):
    def _fake(wifi_dict, config_path, *, connect_timeout=None):
        return succeeds

    return _fake


def wait_until_done(attempt: WifiJoinAttempt, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while attempt.in_progress:
        if time.monotonic() >= deadline:
            raise AssertionError("join attempt did not finish in time")
        time.sleep(0.01)


def wait_for_outcome_file(attempt: WifiJoinAttempt, timeout: float = 5.0) -> None:
    """The background thread writes "attempting" asynchronously -- give it
    a moment rather than racing straight into manipulating the file."""
    deadline = time.monotonic() + timeout
    while not attempt.outcome_path.exists():
        if time.monotonic() >= deadline:
            raise AssertionError("outcome file never appeared")
        time.sleep(0.01)


def test_poll_ignores_a_missing_submission(rig):
    rig.poll()
    assert not rig.in_progress
    assert not rig.outcome_path.exists()


def test_successful_join_stops_ap_and_writes_connected(rig, monkeypatch):
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(True))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": "secret"}))

    rig.poll()
    wait_until_done(rig)

    assert not rig.submission_path.exists(), "submission must be consumed"
    outcome = json.loads(rig.outcome_path.read_text())
    assert outcome == {"status": "connected", "ssid": "HomeNet"}
    calls = rig.calls()
    assert calls == [STOP], "success must not restart the AP"


def test_failed_join_restarts_ap_and_writes_failed(rig, monkeypatch):
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(False))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": "wrong"}))

    rig.poll()
    wait_until_done(rig)

    outcome = json.loads(rig.outcome_path.read_text())
    assert outcome == {"status": "failed", "ssid": "HomeNet"}
    calls = rig.calls()
    assert calls == [STOP, START], "a failed join must bring the AP back"


def test_open_network_submission_passes_no_password(rig, monkeypatch):
    seen = {}

    def _fake(wifi_dict, config_path, *, connect_timeout=None):
        seen.update(wifi_dict)
        return True

    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", _fake)
    rig.submission_path.write_text(json.dumps({"ssid": "OpenNet", "password": None}))

    rig.poll()
    wait_until_done(rig)

    assert seen == {"ssid": "OpenNet", "password": ""}


def test_malformed_submission_is_consumed_and_ignored(rig):
    rig.submission_path.write_text("not valid json{{{")
    rig.poll()
    assert not rig.in_progress
    assert not rig.submission_path.exists()
    assert not rig.outcome_path.exists()


def test_poll_does_not_start_a_second_attempt_while_one_is_in_progress(rig, monkeypatch):
    started = []

    def _slow_apply_wifi(wifi_dict, config_path, *, connect_timeout=None):
        started.append(wifi_dict["ssid"])
        time.sleep(0.3)
        return True

    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", _slow_apply_wifi)
    rig.submission_path.write_text(json.dumps({"ssid": "First", "password": ""}))
    rig.poll()
    assert rig.in_progress

    # A second submission arriving mid-attempt must not be picked up yet.
    rig.submission_path.write_text(json.dumps({"ssid": "Second", "password": ""}))
    rig.poll()
    wait_until_done(rig)

    assert started == ["First"]
    # The second submission is still sitting there, untouched, for the next poll().
    assert rig.submission_path.exists()


def test_attempting_outcome_never_expires_while_in_progress(rig, monkeypatch):
    def _slow_apply_wifi(wifi_dict, config_path, *, connect_timeout=None):
        time.sleep(0.3)
        return True

    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", _slow_apply_wifi)
    rig.submission_path.write_text(json.dumps({"ssid": "Slow", "password": ""}))
    rig.poll()
    assert rig.in_progress
    wait_for_outcome_file(rig)

    # Force the outcome file's mtime to look old -- expiry must still not
    # touch it while an attempt is actually running.
    old = time.time() - OUTCOME_DISPLAY_SECONDS - 10

    os.utime(rig.outcome_path, (old, old))
    rig.expire_outcome_if_stale()
    assert rig.outcome_path.exists()
    assert json.loads(rig.outcome_path.read_text())["status"] == "attempting"

    wait_until_done(rig)


def test_outcome_expires_after_display_window_once_finished(rig, monkeypatch):
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(True))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": ""}))
    rig.poll()
    wait_until_done(rig)
    assert rig.outcome_path.exists()

    rig.expire_outcome_if_stale()
    assert rig.outcome_path.exists(), "must not expire before the display window elapses"

    old = time.time() - OUTCOME_DISPLAY_SECONDS - 1

    os.utime(rig.outcome_path, (old, old))
    rig.expire_outcome_if_stale()
    assert not rig.outcome_path.exists()


def test_apply_wifi_crashing_still_restarts_the_ap(rig, monkeypatch):
    """A bug in apply_wifi() itself must not leave the board with the AP
    torn down and no way back in at all."""

    def _boom(wifi_dict, config_path, *, connect_timeout=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", _boom)
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": ""}))
    rig.poll()
    wait_until_done(rig)

    calls = rig.calls()
    assert calls == [STOP, START]
    outcome = json.loads(rig.outcome_path.read_text())
    assert outcome["status"] == "failed"


# --------------------------------------------------------------------------
# systemctl failures (#173): surfaced in the log, never raised, never silent
# --------------------------------------------------------------------------


def _warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == wifi_join_module.log.name and r.levelno == logging.WARNING
    ]


def test_nonzero_systemctl_exit_is_logged_as_a_warning(rig, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_SYSTEMCTL_EXIT", "5")
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(False))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": "wrong"}))

    with caplog.at_level(logging.WARNING, logger=wifi_join_module.log.name):
        rig.poll()
        wait_until_done(rig)

    assert rig.calls() == [STOP, START]
    warnings = _warnings(caplog)
    assert f"systemctl stop {SETUP_AP_UNIT} exited with status 5" in warnings
    assert f"systemctl start {SETUP_AP_UNIT} exited with status 5" in warnings
    # A failing systemctl must not derail the rest of the attempt.
    assert json.loads(rig.outcome_path.read_text()) == {"status": "failed", "ssid": "HomeNet"}


def test_successful_systemctl_logs_no_warning(rig, monkeypatch, caplog):
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(False))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": "wrong"}))

    with caplog.at_level(logging.WARNING, logger=wifi_join_module.log.name):
        rig.poll()
        wait_until_done(rig)

    assert _warnings(caplog) == []


def test_missing_systemctl_binary_is_caught_and_logged_distinctly(rig, monkeypatch, caplog):
    rig.systemctl_bin = rig.outcome_path.parent / "no-such-systemctl"
    monkeypatch.setattr(wifi_join_module.wifi, "apply_wifi", fake_apply_wifi(False))
    rig.submission_path.write_text(json.dumps({"ssid": "HomeNet", "password": "wrong"}))

    with caplog.at_level(logging.WARNING, logger=wifi_join_module.log.name):
        rig.poll()
        wait_until_done(rig)

    warnings = _warnings(caplog)
    assert any(w.startswith(f"Could not run systemctl stop {SETUP_AP_UNIT}") for w in warnings)
    assert any(w.startswith(f"Could not run systemctl start {SETUP_AP_UNIT}") for w in warnings)
    # A launch failure has no exit status -- it must not be reported as one.
    assert not any("exited with status" in w for w in warnings)
    assert json.loads(rig.outcome_path.read_text()) == {"status": "failed", "ssid": "HomeNet"}
