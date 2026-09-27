"""nhl_scoreboard.wifi: the return value and connect_timeout override (#133).

The full join/rollback *behaviour* (profile writing, [Security] compare,
rollback) is already thoroughly covered at the script level in
test_scoreboard_provision.py, which exercises this module's apply_wifi()
through the real scoreboard-provision script unchanged after the #133
extraction -- deliberately not duplicated here. This file covers only what
that extraction actually added: apply_wifi() returning True/False (the
boot-time caller ignores it; #133's live join flow needs it), and
connect_timeout overriding the module-level default.

Same subprocess-per-call approach as test_scoreboard_provision.py's Rig
(fresh env vars each call, since IWD_DIR/STATE_FILE/LAST_GOOD_FILE are
computed once at import time) -- but invoking a small inline script that
imports nhl_scoreboard.wifi directly, so the actual return value is
observable, which running the full scoreboard-provision script never lets a
caller see.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SRC = str(Path(__file__).resolve().parents[1] / "src")


def write_fake(bindir: Path, name: str, body: str) -> None:
    path = bindir / name
    path.write_text(f"#!/bin/sh\n{body}")
    path.chmod(0o755)


@pytest.fixture
def rig(tmp_path: Path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    iwd_dir = tmp_path / "iwd"
    iwd_dir.mkdir()
    write_fake(
        bindir,
        "iw",
        'if [ "$1" = "dev" ]; then\n'
        '  printf "phy#0\\n    Interface %s\\n" "${FAKE_WIFI_DEVICE:-wlan0}"\n'
        "fi\n"
        "exit 0\n",
    )
    write_fake(
        bindir,
        "iwctl",
        'printf "                               Station: %s\\n" "${FAKE_WIFI_DEVICE:-wlan0}"\n'
        'printf "  State                        %s\\n" "${FAKE_IWCTL_STATE:-disconnected}"\n'
        'printf "  Connected network             %s\\n" "${FAKE_IWCTL_SSID:-}"\n'
        "exit 0\n",
    )
    write_fake(bindir, "systemctl", "exit 0")

    def run_apply_wifi(
        ssid: str, password: str, config_toml: str, *, connect_timeout=None, env_extra=None
    ) -> subprocess.CompletedProcess:
        config_path = tmp_path / "scoreboard.toml"
        config_path.write_text(config_toml)
        script = textwrap.dedent(f"""
            from pathlib import Path
            from nhl_scoreboard.wifi import apply_wifi
            result = apply_wifi(
                {{"ssid": {ssid!r}, "password": {password!r}}},
                Path({str(config_path)!r}),
                connect_timeout={connect_timeout!r},
            )
            print("RESULT:", result)
        """)
        env = {
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "NHL_SCOREBOARD_IWD_DIR": str(iwd_dir),
            "NHL_SCOREBOARD_WIFI_TIMEOUT": "1",
            "NHL_SCOREBOARD_WIFI_POLL_INTERVAL": "0.1",
            "PYTHONPATH": SRC,
            **(env_extra or {}),
        }
        return subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    run_apply_wifi.iwd_dir = iwd_dir
    return run_apply_wifi


def _result(proc: subprocess.CompletedProcess) -> bool:
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT:"):
            return line.split(":", 1)[1].strip() == "True"
    raise AssertionError(f"no RESULT line in stdout: {proc.stdout!r} / stderr: {proc.stderr!r}")


def test_successful_join_returns_true(rig):
    proc = rig(
        "NewNet",
        "newpass",
        "",
        env_extra={"FAKE_IWCTL_STATE": "connected", "FAKE_IWCTL_SSID": "NewNet"},
    )
    assert proc.returncode == 0, proc.stderr
    assert _result(proc) is True


def test_failed_join_returns_false(rig):
    proc = rig("BadNet", "badpass", "", env_extra={"FAKE_IWCTL_STATE": "disconnected"})
    assert proc.returncode == 0, proc.stderr
    assert _result(proc) is False


def test_no_ssid_returns_true_as_nothing_to_do(rig):
    proc = rig("", "", "")
    assert proc.returncode == 0, proc.stderr
    assert _result(proc) is True


def test_connect_timeout_override_is_honoured_over_the_env_default(rig):
    """NHL_SCOREBOARD_WIFI_TIMEOUT is set to 1s by the rig; passing
    connect_timeout=0.2 explicitly should make a failed join give up well
    before even that -- proving the parameter, not the env var, won."""
    import time

    start = time.monotonic()
    proc = rig(
        "BadNet",
        "badpass",
        "",
        connect_timeout=0.2,
        env_extra={"FAKE_IWCTL_STATE": "disconnected", "NHL_SCOREBOARD_WIFI_POLL_INTERVAL": "0.05"},
    )
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert _result(proc) is False
    assert elapsed < 1.0, f"took {elapsed:.2f}s; connect_timeout=0.2 override was not honoured"


def test_successful_join_writes_last_good_config(rig):
    proc = rig(
        "NewNet",
        "newpass",
        "",
        env_extra={"FAKE_IWCTL_STATE": "connected", "FAKE_IWCTL_SSID": "NewNet"},
    )
    assert proc.returncode == 0, proc.stderr
    last_good = json.loads((rig.iwd_dir / ".scoreboard-last-good-wifi.json").read_text())
    assert last_good["ssid"] == "NewNet"
