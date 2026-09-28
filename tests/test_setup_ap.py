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

import json
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
        self.state_file = tmp_path / "state.json"
        self.scan_file = tmp_path / "networks.json"

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
            '  scan) exit "${FAKE_IWCTL_SCAN_EXIT:-0}" ;;\n'
            "  get-networks)\n"
            '    printf "%s\\n" "${FAKE_IWCTL_NETWORKS_TABLE-}"\n'
            '    exit "${FAKE_IWCTL_GET_NETWORKS_EXIT:-0}" ;;\n'
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
            "NHL_SCOREBOARD_AP_STATE_FILE": str(self.state_file),
            "NHL_SCOREBOARD_AP_SCAN_FILE": str(self.scan_file),
            # Real scans need to settle asynchronously (see the script's own
            # comment); tests don't have a real radio to wait on.
            "NHL_SCOREBOARD_AP_SCAN_SETTLE_SECONDS": "0",
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
    # Verified live on real hardware: `ap start` fails outright unless the
    # device is explicitly switched into AP mode first -- iwd does not do
    # this itself as part of `ap start` on this driver.
    assert "iwctl station wlan0 disconnect" in result.calls
    assert "iwctl device wlan0 set-property Mode ap" in result.calls
    assert "iwctl ap wlan0 start-open NHL-Scoreboard-Setup" in result.calls
    # start-open succeeded, so the WPA2-PSK fallback must never be tried.
    assert "iwctl ap wlan0 start NHL-Scoreboard-Setup" not in result.calls
    assert "dnsmasq --no-daemon" in result.calls

    conf = rig.dnsmasq_conf.read_text()
    assert "interface=wlan0" in conf
    assert "bind-interfaces" in conf
    assert "address=/#/10.42.0.1" in conf

    # Open network succeeded -- the app must never show/encode a password
    # that isn't actually required to join.
    state = json.loads(rig.state_file.read_text())
    assert state == {"ssid": "NHL-Scoreboard-Setup", "password": None, "open": True}


def test_start_open_unsupported_falls_back_to_psk(rig):
    result = rig.run(
        "start",
        env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_AP_START_OPEN_EXIT": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert "iwctl ap wlan0 start-open NHL-Scoreboard-Setup" in result.calls
    assert "iwctl ap wlan0 start NHL-Scoreboard-Setup scoreboard" in result.calls
    assert "dnsmasq --no-daemon" in result.calls

    state = json.loads(rig.state_file.read_text())
    assert state == {"ssid": "NHL-Scoreboard-Setup", "password": "scoreboard", "open": False}


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
    assert not rig.state_file.exists()


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
# nearby-network scan + cache (#132)
# --------------------------------------------------------------------------

NETWORK_TABLE = "\n".join(
    [
        "                                  Available networks",
        "--------------------------------------------------------------------------------",
        "    Network name                       Security            Signal",
        "--------------------------------------------------------------------------------",
        "    Home Wifi                          psk                 ****",
        "    Guest Network                      open                ***",
        # A currently-connected network is marked with a leading '>' instead
        # of plain indentation, and (being in range from more than one AP,
        # or just re-listed) can repeat -- the cache must still dedupe it.
        ">   Home Wifi                          psk                 ****",
        "--------------------------------------------------------------------------------",
    ]
)


def test_scan_happens_before_switching_to_ap_mode(rig):
    result = rig.run(
        "start", env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_NETWORKS_TABLE": NETWORK_TABLE}
    )
    assert result.returncode == 0, result.stderr

    calls = result.calls.splitlines()
    scan_line = next(i for i, c in enumerate(calls) if "iwctl station wlan0 scan" in c)
    get_networks_line = next(
        i for i, c in enumerate(calls) if "iwctl station wlan0 get-networks" in c
    )
    mode_ap_line = next(
        i for i, c in enumerate(calls) if "iwctl device wlan0 set-property Mode ap" in c
    )
    assert scan_line < get_networks_line < mode_ap_line, result.calls


def test_scan_caches_unique_ssids_as_json(rig):
    result = rig.run(
        "start", env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_NETWORKS_TABLE": NETWORK_TABLE}
    )
    assert result.returncode == 0, result.stderr

    networks = json.loads(rig.scan_file.read_text())
    assert networks == ["Home Wifi", "Guest Network"]


def test_scan_failure_caches_an_empty_list(rig):
    result = rig.run(
        "start",
        env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_GET_NETWORKS_EXIT": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(rig.scan_file.read_text()) == []


def test_scan_with_no_nearby_networks_caches_an_empty_list(rig):
    result = rig.run("start", env_extra={"FAKE_DEFAULT_ROUTE": "", "FAKE_IWCTL_NETWORKS_TABLE": ""})
    assert result.returncode == 0, result.stderr
    assert json.loads(rig.scan_file.read_text()) == []


# --------------------------------------------------------------------------
# tearing the AP down
# --------------------------------------------------------------------------


def test_stop_tears_down_ap_and_removes_conf(rig):
    rig.dnsmasq_conf.write_text("stale config\n")
    rig.state_file.write_text('{"ssid": "stale", "password": "stale", "open": false}\n')
    rig.scan_file.write_text('["stale"]\n')

    result = rig.run("stop")
    assert result.returncode == 0, result.stderr
    assert "iwctl ap wlan0 stop" in result.calls
    # Verified live: the device is left in Mode=ap after `ap stop` -- it
    # does not revert on its own, so #133's later join flow needs this to
    # have any chance of reaching a real network afterward.
    assert "iwctl device wlan0 set-property Mode station" in result.calls
    assert "ip addr flush dev wlan0" in result.calls
    assert not rig.dnsmasq_conf.exists()
    # The app uses this file's presence alone to decide whether to show the
    # setup scene -- a stale one left behind after teardown would wrongly
    # keep showing it once the board is back on a real network.
    assert not rig.state_file.exists()
    assert not rig.scan_file.exists()


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
