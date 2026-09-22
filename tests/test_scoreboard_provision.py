"""scoreboard-provision's Wi-Fi rollback (#51), the script run for real.

Same approach as test_grow_rootfs.py: the actual script, invoked as a
subprocess, with every external tool it shells out to (iw, iwctl, systemctl)
faked on a prepended PATH so this runs without root or real Wi-Fi hardware.
IWD_DIR is redirected to a tmp directory via NHL_SCOREBOARD_IWD_DIR (the same
override convention nhl-scoreboard-grow-rootfs uses for its own state dir).

What this does NOT verify: that iwd actually reconnects to a known profile
the way ``is_connected``/``wifi_device`` assume, or that ``iwctl station ...
show`` really is formatted the way the fakes here assume. That needs real
hardware (#4) and is explicitly still open per #51.

The rollback path specifically is mutation-tested per CLAUDE.md's guidance
for disk/network-state-changing scripts: test_failed_connect_* below proves
the *old* profile survives and scoreboard.toml is reverted when the new
network never comes up -- deliberately the exact behaviour the old
"delete the stale profile immediately" code did NOT have.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "image" / "files" / "scripts" / "scoreboard-provision"
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
        self.iwd_dir = tmp_path / "iwd"
        self.iwd_dir.mkdir()
        self.call_log = tmp_path / "calls.log"
        self.config_path = tmp_path / "scoreboard.toml"

        write_fake(
            self.bindir,
            "iw",
            'if [ "$1" = "dev" ]; then\n'
            '  if [ -n "${FAKE_WIFI_DEVICE-wlan0}" ]; then\n'
            '    printf "phy#0\\n    Interface %s\\n" "${FAKE_WIFI_DEVICE-wlan0}"\n'
            "  fi\n"
            "fi\n"
            "exit 0\n",
        )
        write_fake(
            self.bindir,
            "iwctl",
            'printf "                               Station: %s\\n" "${FAKE_WIFI_DEVICE:-wlan0}"\n'
            'printf "  State                        %s\\n" "${FAKE_IWCTL_STATE:-disconnected}"\n'
            'printf "  Connected network             %s\\n" "${FAKE_IWCTL_SSID:-}"\n'
            "exit 0\n",
        )
        write_fake(self.bindir, "systemctl", "exit 0")

    def seed_profile(self, ssid: str, password: str) -> Path:
        profile = self.iwd_dir / f"{ssid}.psk"
        profile.write_text(f"[Security]\nPassphrase={password}\n")
        return profile

    def seed_state(self, profile_name: str) -> None:
        (self.iwd_dir / ".scoreboard-managed").write_text(f"{profile_name}\n")

    def seed_last_good(self, ssid: str, password: str, country: str = "") -> None:
        (self.iwd_dir / ".scoreboard-last-good-wifi.json").write_text(
            json.dumps({"ssid": ssid, "password": password, "country": country})
        )

    def run(self, wifi_toml: str, *, env_extra: dict | None = None) -> subprocess.CompletedProcess:
        self.call_log.write_text("")
        self.config_path.write_text(wifi_toml)
        repo_src = str(Path(__file__).resolve().parents[1] / "src")
        env = {
            "PATH": f"{self.bindir}:{os.environ['PATH']}",
            "FAKE_CALL_LOG": str(self.call_log),
            "NHL_SCOREBOARD_IWD_DIR": str(self.iwd_dir),
            "NHL_SCOREBOARD_WIFI_TIMEOUT": "1",
            "NHL_SCOREBOARD_WIFI_POLL_INTERVAL": "0.1",
            "PYTHONPATH": repo_src,
            **(env_extra or {}),
        }
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(self.config_path)],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        result.calls = self.call_log.read_text()
        return result


@pytest.fixture
def rig(tmp_path) -> Rig:
    return Rig(tmp_path)


WIFI_TOML = '[wifi]\nssid = "{ssid}"\npassword = "{password}"\n'


# --------------------------------------------------------------------------
# successful connect
# --------------------------------------------------------------------------


def test_successful_connect_drops_old_profile_and_records_state(rig):
    rig.seed_profile("OldNet", "oldpass")
    rig.seed_state("OldNet.psk")

    result = rig.run(
        WIFI_TOML.format(ssid="NewNet", password="newpass"),
        env_extra={"FAKE_IWCTL_STATE": "connected", "FAKE_IWCTL_SSID": "NewNet"},
    )
    assert result.returncode == 0, result.stderr

    assert (rig.iwd_dir / "NewNet.psk").is_file()
    assert not (rig.iwd_dir / "OldNet.psk").is_file()
    assert (rig.iwd_dir / ".scoreboard-managed").read_text().strip() == "NewNet.psk"

    last_good = json.loads((rig.iwd_dir / ".scoreboard-last-good-wifi.json").read_text())
    assert last_good["ssid"] == "NewNet"

    # scoreboard.toml is untouched on success -- rollback only fires on failure.
    assert 'ssid = "NewNet"' in rig.config_path.read_text()
    assert "systemctl restart iwd" in result.calls


def test_unchanged_profile_short_circuits_without_touching_iwd(rig):
    rig.seed_profile("SameNet", "samepass")
    rig.seed_state("SameNet.psk")

    result = rig.run(WIFI_TOML.format(ssid="SameNet", password="samepass"))
    assert result.returncode == 0, result.stderr
    assert "systemctl" not in result.calls
    assert "iwctl" not in result.calls


# --------------------------------------------------------------------------
# failed connect -> rollback (mutation-tested: the point of #51)
# --------------------------------------------------------------------------


def test_failed_connect_keeps_the_old_profile_and_reverts_config(rig):
    rig.seed_profile("GoodNet", "goodpass")
    rig.seed_state("GoodNet.psk")
    rig.seed_last_good("GoodNet", "goodpass", "US")

    result = rig.run(
        WIFI_TOML.format(ssid="BadNet", password="badpass"),
        env_extra={"FAKE_IWCTL_STATE": "disconnected"},
    )
    assert result.returncode == 0, result.stderr

    # The network that never came up must not survive...
    assert not (rig.iwd_dir / "BadNet.psk").is_file()
    # ...and the previously-working one must still be there, untouched.
    assert (rig.iwd_dir / "GoodNet.psk").is_file()
    assert (rig.iwd_dir / "GoodNet.psk").read_text() == "[Security]\nPassphrase=goodpass\n"
    assert (rig.iwd_dir / ".scoreboard-managed").read_text().strip() == "GoodNet.psk"

    # scoreboard.toml itself must be reverted, or the next boot repeats this.
    text = rig.config_path.read_text()
    assert 'ssid = "GoodNet"' in text
    assert 'password = "goodpass"' in text
    assert "BadNet" not in text

    assert "systemctl restart iwd" in result.calls
    assert result.calls.count("systemctl restart iwd") == 2  # once to try, once to fall back


def test_failed_connect_with_no_prior_good_config_does_not_crash(rig):
    """First-ever Wi-Fi setup fails: nothing to roll back to, but must still be safe."""
    result = rig.run(
        WIFI_TOML.format(ssid="BadNet", password="badpass"),
        env_extra={"FAKE_IWCTL_STATE": "disconnected"},
    )
    assert result.returncode == 0, result.stderr
    assert not (rig.iwd_dir / "BadNet.psk").is_file()
    assert not (rig.iwd_dir / ".scoreboard-managed").is_file()
    # No known-good state existed, so the (bad) config is left as-is.
    assert 'ssid = "BadNet"' in rig.config_path.read_text()


def test_no_wireless_interface_is_treated_as_a_failed_connect(rig):
    rig.seed_profile("GoodNet", "goodpass")
    rig.seed_state("GoodNet.psk")
    rig.seed_last_good("GoodNet", "goodpass")

    result = rig.run(
        WIFI_TOML.format(ssid="BadNet", password="badpass"),
        env_extra={"FAKE_WIFI_DEVICE": ""},
    )
    assert result.returncode == 0, result.stderr
    assert not (rig.iwd_dir / "BadNet.psk").is_file()
    assert (rig.iwd_dir / "GoodNet.psk").is_file()


# --------------------------------------------------------------------------
# no ssid configured
# --------------------------------------------------------------------------


def test_no_ssid_leaves_iwd_untouched(rig):
    result = rig.run('[wifi]\nssid = ""\n')
    assert result.returncode == 0, result.stderr
    assert "systemctl" not in result.calls
    assert "iwctl" not in result.calls
