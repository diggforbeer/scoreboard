"""nhl-scoreboard-setup-ap: the shell script, run for real (#131).

Same approach as test_grow_rootfs.py and test_scoreboard_provision.py: the
actual script, invoked as a subprocess, with every external tool it shells
out to (ip, iwctl, dnsmasq, logger) faked on a prepended PATH so this runs
without root, a real wireless interface, or a real dnsmasq binary.

What this does NOT verify: that `iwctl ap <dev> start-open` actually exists
on the iwd version this image ships, that a real phone's OS actually shows
a captive-portal prompt for the resulting network, or that iwd's AP mode
and dnsmasq cooperate the way the script assumes on a real radio. All of
that needs real hardware (#4) and is explicitly unverified per the script's
own header comment.

The trigger condition is the one part worth mutation-testing per CLAUDE.md's
guidance for network-state-changing scripts: test_already_online_is_a_noop
below asserts not just a clean exit but that *no* AP/dnsmasq calls happened
at all -- an inverted "online" check would still exit 0 on its own, so the
return code alone would not catch that regression.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "image" / "files" / "scripts" / "nhl-scoreboard-setup-ap"
)


def write_fake(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text(f'#!/bin/sh\necho "$0 $*" >> "$FAKE_CALL_LOG"\n{body}')
    path.chmod(0o755)


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.bindir = tmp_path / "bin"
        self.bindir.mkdir()
        self.call_log = tmp_path / "calls.log"
        self.dnsmasq_conf = tmp_path / "dnsmasq.conf"

        write_fake(
            self.bindir,
            "ip",
            'if [ "$1 $2 $3" = "route show default" ]; then\n'
            '  printf "%s" "${FAKE_DEFAULT_ROUTE-}"\n'
            "fi\n"
            "exit 0\n",
        )
        write_fake(
            self.bindir,
            "iwctl",
            'case "$3" in\n'
            '  start-open) exit "${FAKE_IWCTL_AP_START_OPEN_EXIT:-0}" ;;\n'
            '  start) exit "${FAKE_IWCTL_AP_START_EXIT:-0}" ;;\n'
            '  stop) exit "${FAKE_IWCTL_AP_STOP_EXIT:-0}" ;;\n'
            "esac\n"
            "exit 0\n",
        )
        write_fake(self.bindir, "dnsmasq", "exit 0")
        write_fake(self.bindir, "logger", "exit 0")

    def run(self, *args: str, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        self.call_log.write_text("")
        env = {
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "FAKE_CALL_LOG": str(self.call_log),
            "NHL_SCOREBOARD_AP_DNSMASQ_CONF": str(self.dnsmasq_conf),
            **(env_extra or {}),
        }
        result = subprocess.run(
            ["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=10
        )
        result.calls = self.call_log.read_text()
        return result


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


# --------------------------------------------------------------------------
# trigger condition
# --------------------------------------------------------------------------


def test_already_online_is_a_noop(rig):
    result = rig.run("start", env_extra={"FAKE_DEFAULT_ROUTE": "default via 192.0.2.1 dev eth0"})
    assert result.returncode == 0, result.stderr
    assert "iwctl" not in result.calls
    assert "dnsmasq" not in result.calls
    assert "addr add" not in result.calls
    assert "addr flush" not in result.calls
    assert "link set" not in result.calls


def test_check_reports_online_via_exit_code(rig):
    result = rig.run("check", env_extra={"FAKE_DEFAULT_ROUTE": "default via 192.0.2.1 dev eth0"})
    assert result.returncode == 0, result.stderr


def test_check_reports_offline_via_exit_code(rig):
    result = rig.run("check", env_extra={"FAKE_DEFAULT_ROUTE": ""})
    assert result.returncode == 1


# --------------------------------------------------------------------------
# bringing the AP up
# --------------------------------------------------------------------------


def test_offline_brings_up_open_ap_and_starts_dnsmasq(rig):
    result = rig.run("start", env_extra={"FAKE_DEFAULT_ROUTE": ""})
    assert result.returncode == 0, result.stderr

    assert "ip addr add 10.42.0.1/24 dev wlan0" in result.calls
    assert "ip link set wlan0 up" in result.calls
    assert "iwctl ap wlan0 start-open NHL-Scoreboard-Setup" in result.calls
    # start-open succeeded, so the WPA2-PSK fallback must never be tried.
    assert "iwctl ap wlan0 start NHL-Scoreboard-Setup" not in result.calls
    assert "dnsmasq --no-daemon" in result.calls

    conf = rig.dnsmasq_conf.read_text()
    assert "interface=wlan0" in conf
    assert "bind-interfaces" in conf
    assert "address=/#/10.42.0.1" in conf


def test_start_open_unsupported_falls_back_to_psk(rig):
    result = rig.run(
        "start",
        env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_AP_START_OPEN_EXIT": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "iwctl ap wlan0 start-open NHL-Scoreboard-Setup" in result.calls
    assert "iwctl ap wlan0 start NHL-Scoreboard-Setup scoreboard" in result.calls
    assert "dnsmasq --no-daemon" in result.calls


def test_ap_totally_unavailable_never_starts_dnsmasq(rig):
    result = rig.run(
        "start",
        env_extra={
            "FAKE_DEFAULT_ROUTE": "",
            "FAKE_IWCTL_AP_START_OPEN_EXIT": "1",
            "FAKE_IWCTL_AP_START_EXIT": "1",
        },
    )
    assert result.returncode != 0
    assert "dnsmasq" not in result.calls


def test_ap_settings_are_overridable(rig):
    result = rig.run(
        "start",
        env_extra={
            "FAKE_DEFAULT_ROUTE": "",
            "NHL_SCOREBOARD_AP_IFACE": "wlan1",
            "NHL_SCOREBOARD_AP_SSID": "TestSetupNet",
            "NHL_SCOREBOARD_AP_ADDR": "192.168.99.1",
            "NHL_SCOREBOARD_AP_PREFIX": "28",
        },
    )
    assert result.returncode == 0, result.stderr
    assert "ip addr add 192.168.99.1/28 dev wlan1" in result.calls
    assert "iwctl ap wlan1 start-open TestSetupNet" in result.calls


# --------------------------------------------------------------------------
# tearing the AP down
# --------------------------------------------------------------------------


def test_stop_tears_down_ap_and_removes_conf(rig):
    rig.dnsmasq_conf.write_text("stale config\n")

    result = rig.run("stop")
    assert result.returncode == 0, result.stderr
    assert "iwctl ap wlan0 stop" in result.calls
    assert "ip addr flush dev wlan0" in result.calls
    assert not rig.dnsmasq_conf.exists()


def test_stop_is_safe_when_never_started(rig):
    """No stale conf file, and iwctl/ip report nothing to tear down --
    ExecStopPost always runs `stop`, including for the online no-op case."""
    result = rig.run(
        "stop",
        env_extra={"FAKE_IWCTL_AP_STOP_EXIT": "1"},
    )
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------
# usage
# --------------------------------------------------------------------------


def test_unknown_subcommand_is_rejected(rig):
    result = rig.run("bogus")
    assert result.returncode == 2
    assert "usage" in result.stderr
