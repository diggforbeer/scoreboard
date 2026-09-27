"""Joining a WiFi network via iwd, with rollback (#51).

Originally boot-time-only code inside ``scoreboard-provision`` (still the
only caller until #133); factored out here so #133's live join flow (from
the AP setup page's submission, #132) can call the exact same tested path
instead of a second reimplementation of "try new credentials, roll back on
failure". ``scoreboard-provision`` now just calls ``apply_wifi`` with the
``[wifi]`` section it already parses out of ``scoreboard.toml``.

A new profile is written *alongside* the previous one (not in place of it),
iwd is restarted, and this waits for a real connection before dropping the
old profile. If the new network never comes up, the new profile is removed,
iwd is restarted again so it falls back to the still-present old profile,
and the last known-good ``[wifi]`` values are written back into
``scoreboard.toml`` itself -- otherwise the *next* boot would read the same
bad SSID/password and repeat the failed attempt forever.
"""

from __future__ import annotations

import configparser
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from .config import ConfigWriteError, Settings

#: Overridable so tests can run this for real without touching the system's
#: actual iwd state (same convention as nhl-scoreboard-grow-rootfs's
#: NHL_SCOREBOARD_STATE_DIR).
IWD_DIR = Path(os.environ.get("NHL_SCOREBOARD_IWD_DIR", "/var/lib/iwd"))
#: The profile filename we wrote last time, so a future call knows what to
#: drop once a new one is confirmed working (and what to fall back to if it
#: isn't).
STATE_FILE = IWD_DIR / ".scoreboard-managed"
#: The last [wifi] values that were actually confirmed to connect. Rolling
#: back to "whatever was in the profile before" isn't enough on its own --
#: this is what actually gets written back into scoreboard.toml on failure.
LAST_GOOD_FILE = IWD_DIR / ".scoreboard-last-good-wifi.json"

# iwd uses the SSID as the profile filename when it is plainly printable;
# anything else has to be hex-encoded. See iwd.network(5).
SAFE_SSID = re.compile(r"^[A-Za-z0-9_ .\-]+$")

#: Default for how long to wait for a newly-written Wi-Fi profile to
#: actually connect before deciding it failed and rolling back -- the same
#: number `[wifi] connect_timeout_seconds` defaults to (#133). Overridable
#: so tests don't have to wait for a real 90s timeout to prove the failure
#: path works.
WIFI_CONNECT_TIMEOUT = float(os.environ.get("NHL_SCOREBOARD_WIFI_TIMEOUT", "90"))
WIFI_POLL_INTERVAL = float(os.environ.get("NHL_SCOREBOARD_WIFI_POLL_INTERVAL", "2"))

log = logging.getLogger(__name__)


def apply_wifi(wifi: dict, config_path: Path, *, connect_timeout: float | None = None) -> bool:
    """Join the network described by ``wifi`` (a parsed ``[wifi]`` section).

    Returns whether the board ended up connected -- ``True`` for "already
    connected"/"nothing to do" as well as a genuinely new successful join,
    ``False`` only when a real attempt was made and the new network never
    came up. The boot-time caller (``scoreboard-provision``) ignores this;
    #133's live join flow needs it to decide whether to show "Connected!"
    or restart AP mode for a retry.

    ``connect_timeout`` overrides ``WIFI_CONNECT_TIMEOUT`` -- #133's live
    caller passes ``[wifi] connect_timeout_seconds`` through explicitly
    rather than relying on the module-level default, since that default is
    tuned for "nobody's watching" (boot time), not a person looking at the
    panel waiting for a result.
    """
    ssid = str(wifi.get("ssid") or "").strip()
    password = str(wifi.get("password") or "")
    country = str(wifi.get("country") or "").strip().upper()
    timeout = WIFI_CONNECT_TIMEOUT if connect_timeout is None else connect_timeout

    # Before the SSID check, not after: the image promises regdom is applied
    # from scoreboard.toml every boot, and an ethernet-only board with a
    # country set is still owed that (#67).
    apply_regulatory_domain(country)

    if not ssid:
        log.info("No Wi-Fi SSID configured; relying on ethernet")
        return True

    profile = IWD_DIR / iwd_profile_name(ssid)
    contents = f"[Security]\nPassphrase={password}\n"

    if _profile_matches(profile, password):
        log.info("Wi-Fi profile for %r already current", ssid)
        return True

    previous_profile = read_state_file()
    try:
        IWD_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        profile.write_text(contents)
        profile.chmod(0o600)
    except OSError as exc:
        log.error("Could not write Wi-Fi profile: %s", exc)
        return False

    # Deliberately NOT removing the previous profile yet -- iwd can hold
    # several saved profiles at once, and dropping the old one here (as this
    # used to) would destroy the last known-good network at the exact moment
    # the new, possibly-wrong one is written, before anything has confirmed
    # it actually works.
    log.info("Wrote Wi-Fi profile for %r; verifying connectivity before dropping old one", ssid)
    run(["systemctl", "restart", "iwd"])

    if wait_for_connection(ssid, timeout, WIFI_POLL_INTERVAL):
        log.info("Connected to %r", ssid)
        remove_profile_if_different(previous_profile, keep=profile.name)
        STATE_FILE.write_text(f"{profile.name}\n")
        write_last_good(ssid, password, country)
        return True

    log.error("Could not connect to %r within %.0fs; rolling back", ssid, timeout)
    profile.unlink(missing_ok=True)
    run(["systemctl", "restart", "iwd"])
    rollback_config(config_path)
    return False


def _profile_matches(profile: Path, password: str) -> bool:
    """Whether the existing profile's [Security] Passphrase already matches.

    Checks only the field this module actually manages, not the whole file
    byte-for-byte -- iwd itself commonly appends other sections (e.g.
    [Settings]) after a successful connection, and a byte-for-byte compare
    would treat that as "changed" and rewrite/restart iwd every time even
    though nothing we manage actually changed (#68).
    """
    if not profile.exists():
        return False
    # interpolation=None: '%' is legal in a WPA passphrase, and the default
    # BasicInterpolation raises on a bare one.
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(profile, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        # Unreadable or corrupt profile: rewrite it rather than crash over
        # it, same as scoreboard-provision's read_config() does for bad TOML.
        return False
    return parser.get("Security", "Passphrase", fallback=None) == password


def read_state_file() -> str:
    if not STATE_FILE.is_file():
        return ""
    return STATE_FILE.read_text().strip()


def remove_profile_if_different(previous_name: str, keep: str) -> None:
    """Drop the profile from before this call, now that ``keep`` is confirmed working."""
    if previous_name and previous_name != keep:
        stale = IWD_DIR / previous_name
        stale.unlink(missing_ok=True)
        log.info("Removed previous Wi-Fi profile %s", previous_name)


def iwd_profile_name(ssid: str) -> str:
    if SAFE_SSID.match(ssid) and not ssid.startswith("."):
        return f"{ssid}.psk"
    return "=" + ssid.encode().hex() + ".psk"


def apply_regulatory_domain(country: str) -> None:
    # `iw reg set` talks straight to the kernel's cfg80211, which carries its
    # own regulatory database; no userspace agent or config file is involved.
    # This used to also write /etc/default/crda, but crda isn't installed in
    # this image (Debian dropped the package), so nothing ever read it (#67).
    if len(country) != 2 or not country.isalpha():
        return
    run(["iw", "reg", "set", country])


# -- connectivity check (#51) -----------------------------------------------


def wait_for_connection(ssid: str, timeout: float, poll_interval: float) -> bool:
    """Poll iwd for a real connection to ``ssid``, bounded by ``timeout`` seconds."""
    device = wifi_device()
    if device is None:
        log.error("No wireless interface found")
        return False
    deadline = time.monotonic() + timeout
    while True:
        if is_connected(device, ssid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


def wifi_device() -> str | None:
    try:
        result = subprocess.run(
            ["iw", "dev"], capture_output=True, text=True, timeout=10, check=True
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match = re.search(r"Interface\s+(\S+)", result.stdout)
    return match.group(1) if match else None


def is_connected(device: str, ssid: str) -> bool:
    try:
        result = subprocess.run(
            ["iwctl", "station", device, "show"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    state = station_field(result.stdout, "State")
    connected_network = station_field(result.stdout, "Connected network")
    return state == "connected" and connected_network == ssid


def station_field(output: str, field: str) -> str:
    """Pull one ``key  value`` field out of ``iwctl station ... show`` output.

    iwctl right-pads field names to a fixed column width rather than using a
    single delimiter, so the field/value split is "two or more spaces", not
    a literal separator character.
    """
    for line in output.splitlines():
        parts = re.split(r"\s{2,}", line.strip(), maxsplit=1)
        if len(parts) == 2 and parts[0] == field:
            return parts[1].strip()
    return ""


# -- rollback (#51) -----------------------------------------------------


def write_last_good(ssid: str, password: str, country: str) -> None:
    payload = {"ssid": ssid, "password": password, "country": country}
    try:
        LAST_GOOD_FILE.write_text(json.dumps(payload))
        LAST_GOOD_FILE.chmod(0o600)
    except OSError as exc:
        log.warning("Could not record last-good Wi-Fi config: %s", exc)


def rollback_config(config_path: Path) -> None:
    """Write the last known-good [wifi] values back into scoreboard.toml.

    Without this, the next boot reads the same bad SSID/password out of the
    config file and repeats the same failed connection attempt forever.
    Goes through the same tomlkit write-back Settings.save() uses (#51) so
    comments in the file survive, same as any other config edit.
    """
    if not LAST_GOOD_FILE.is_file():
        log.warning("No known-good Wi-Fi config to roll back to; leaving scoreboard.toml as-is")
        return
    try:
        last_good = json.loads(LAST_GOOD_FILE.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.error("Could not read last-good Wi-Fi config: %s", exc)
        return
    try:
        Settings.load(config_path).save({"wifi": last_good})
        log.info("Rolled back scoreboard.toml [wifi] to %r", last_good.get("ssid"))
    except ConfigWriteError as exc:
        log.error("Could not roll back scoreboard.toml: %s", exc)


def run(cmd: list[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        log.info("ran %s", " ".join(cmd))
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("Command %s failed: %s", " ".join(cmd), exc)
