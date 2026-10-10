"""App-layer self-update (#32): check for a newer release, apply it on demand.

The app on the image is a plain source tree on PYTHONPATH
(``/opt/nhl-scoreboard``), not a pip install, so an update is "replace that
directory and restart the service". Two deliberately separate steps:

* ``check`` -- daily (``nhl-scoreboard-update.timer``) or on the admin
  page's button -- asks GitHub for the latest release and records in
  ``update-state.json`` whether it is newer and hot-applicable. Downloads
  nothing.
* ``apply`` -- only ever started by the admin page's button -- downloads the
  bundle, checks its sha256, and swaps it in with the same shape as
  ``wifi.apply_wifi()``: the new tree is written *alongside* the live one,
  swapped in by rename, the service is restarted and must actually come up,
  and if it doesn't the previous tree is renamed back and the service
  restarted again.

Both run as their own systemd oneshot units, not inside the app: an apply
restarts ``nhl-scoreboard.service``, which would kill it if it were running
as a thread of the app. Stdlib only, so it needs nothing beyond the base
image.

"Healthy" is deliberately just "the service stayed active for
``HEALTH_SECONDS``" -- with ``Restart=always`` a crash-looping release goes
``activating (auto-restart)`` and fails that check. It does not prove the
panel is rendering; that was considered and left out on purpose (#32).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Overridable so tests run the real code against temp dirs, same convention
#: as wifi.IWD_DIR.
APP_DIR = Path(os.environ.get("NHL_SCOREBOARD_APP_DIR", "/opt/nhl-scoreboard"))
STATE_FILE = Path(
    os.environ.get("NHL_SCOREBOARD_UPDATE_STATE", "/var/lib/nhl-scoreboard/update-state.json")
)
#: Full commit of the HUB75 driver this image compiled, written at image
#: build time. The compiled ``rgbmatrix`` can't be rebuilt on the device (the
#: toolchain is purged, #11), so a release pinning a different one needs a
#: reflash.
DRIVER_COMMIT_FILE = Path(
    os.environ.get("NHL_SCOREBOARD_DRIVER_COMMIT", "/usr/share/nhl-scoreboard/driver-commit")
)
RELEASE_URL = os.environ.get(
    "NHL_SCOREBOARD_RELEASE_URL",
    "https://api.github.com/repos/diggforbeer/scoreboard/releases/latest",
)
#: Where admin_server.py serves the built React page from; same env var, so
#: the updater and the server can't disagree about it. The bundle's optional
#: top-level ``admin/`` directory (frontend/dist) is swapped in here (#185).
ADMIN_DIR = Path(os.environ.get("NHL_SCOREBOARD_ADMIN_DIR", "/usr/share/nhl-scoreboard/admin"))
BUNDLE_ASSET = "nhl-scoreboard-app.tar.gz"
MANIFEST_ASSET = "manifest.json"
SERVICE = "nhl-scoreboard.service"
HEALTH_SECONDS = float(os.environ.get("NHL_SCOREBOARD_UPDATE_HEALTH_SECONDS", "20"))
HEALTH_POLL_SECONDS = float(os.environ.get("NHL_SCOREBOARD_UPDATE_HEALTH_POLL", "1"))
HTTP_TIMEOUT = 30

_CALVER = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$")


# -- state ---------------------------------------------------------------


def read_state() -> dict[str, Any]:
    try:
        data = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(STATE_FILE)
    except OSError as exc:
        log.error("Could not write %s: %s", STATE_FILE, exc)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def installed_version() -> str:
    """The release tag this tree was built from; ``""`` if unknown (a fresh image)."""
    try:
        return (APP_DIR / "VERSION").read_text().strip()
    except OSError:
        return ""


def _version_key(tag: str) -> tuple[int, ...] | None:
    match = _CALVER.match(tag)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(latest: str, installed: str) -> bool:
    if not installed:
        return True  # unknown -- a freshly flashed image carries no VERSION
    latest_key, installed_key = _version_key(latest), _version_key(installed)
    if latest_key is None or installed_key is None:
        return latest != installed
    return latest_key > installed_key


def _drivers_match(wanted: str) -> bool:
    try:
        have = DRIVER_COMMIT_FILE.read_text().strip()
    except OSError:
        have = ""
    if not wanted or not have:
        return True  # can't tell; don't block on missing information
    return have.startswith(wanted) or wanted.startswith(have)


# -- check ---------------------------------------------------------------


def _fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": "nhl-scoreboard"}
    )
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
        return json.load(response)


def _download(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "nhl-scoreboard"})
    with (
        urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response,
        dest.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)


def check() -> dict[str, Any]:
    """Look up the latest release and record whether it can be applied."""
    state = read_state()
    state["checked_at"] = _now()
    state["installed"] = installed_version()
    try:
        release = _fetch_json(RELEASE_URL)
        tag = str(release["tag_name"])
        assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
        state.update(latest=tag, error="", available=False, applicable=False, reason="")
        if not is_newer(tag, state["installed"]):
            state["reason"] = "Up to date"
        elif BUNDLE_ASSET not in assets or MANIFEST_ASSET not in assets:
            state["reason"] = "This release has no app bundle (reflash to update)"
        else:
            manifest = _fetch_json(assets[MANIFEST_ASSET])
            state["available"] = True
            if not _drivers_match(str(manifest.get("driver_commit", ""))):
                state["reason"] = "Needs a reflash: the HUB75 driver changed"
            else:
                state.update(
                    applicable=True,
                    bundle_url=assets[BUNDLE_ASSET],
                    sha256=str(manifest["sha256"]),
                )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # URLError/HTTPError are OSErrors; JSON errors are ValueErrors.
        log.warning("Update check failed: %s", exc)
        state["error"] = f"Could not check for updates: {exc}"
    _write_state(state)
    return state


# -- apply ---------------------------------------------------------------


def _systemctl(*args: str) -> bool:
    try:
        subprocess.run(["systemctl", *args], check=True, capture_output=True, timeout=60)
        return True
    except (subprocess.SubprocessError, OSError) as exc:
        log.error("systemctl %s failed: %s", " ".join(args), exc)
        return False


def _service_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE], capture_output=True, text=True, timeout=10
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return result.stdout.strip() == "active"


def wait_until_healthy(seconds: float, poll: float) -> bool:
    """True if the service is active at every poll for ``seconds``."""
    deadline = time.monotonic() + seconds
    while True:
        if not _service_active():
            return False
        if time.monotonic() >= deadline:
            return True
        time.sleep(poll)


def _extract(bundle: Path, dest: Path) -> None:
    """Unpack ``bundle`` into ``dest``, refusing anything but plain files/dirs inside it."""
    dest.mkdir(parents=True)
    with tarfile.open(bundle) as tar:
        members = tar.getmembers()
        for member in members:
            target = (dest / member.name).resolve()
            if not target.is_relative_to(dest.resolve()) or not (member.isfile() or member.isdir()):
                raise ValueError(f"unsafe path in bundle: {member.name}")
        tar.extractall(dest, members=members)
    if not (dest / "nhl_scoreboard" / "__init__.py").is_file():
        raise ValueError("bundle does not contain nhl_scoreboard/")


def _record(state: dict[str, Any], outcome: str, detail: str) -> None:
    state["last_apply"] = {"outcome": outcome, "detail": detail, "at": _now()}
    _write_state(state)


def apply() -> bool:
    """Install the release ``check()`` found. True if it is now running and healthy."""
    state = read_state()
    if not (state.get("available") and state.get("applicable") and state.get("bundle_url")):
        log.error("No applicable update recorded; run a check first")
        _record(state, "failed", "No applicable update to install")
        return False

    tag = state["latest"]
    _record(state, "in_progress", f"Installing {tag}")
    new_dir = APP_DIR.with_name(APP_DIR.name + ".new")
    prev_dir = APP_DIR.with_name(APP_DIR.name + ".prev")
    new_admin = ADMIN_DIR.with_name(ADMIN_DIR.name + ".new")
    prev_admin = ADMIN_DIR.with_name(ADMIN_DIR.name + ".prev")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / BUNDLE_ASSET
            _download(state["bundle_url"], bundle)
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            if digest != state.get("sha256"):
                raise ValueError("checksum mismatch")
            shutil.rmtree(new_dir, ignore_errors=True)
            shutil.rmtree(new_admin, ignore_errors=True)
            _extract(bundle, new_dir)
            (new_dir / "VERSION").write_text(f"{tag}\n")
            # The frontend rides in the same (already checksummed) bundle so
            # the page can't lag the backend it talks to. Staged next to the
            # live directory now so the swap below is only renames.
            if (new_dir / "admin").is_dir():
                shutil.move(str(new_dir / "admin"), new_admin)
    except (OSError, ValueError, tarfile.TarError) as exc:
        log.error("Could not prepare %s: %s", tag, exc)
        shutil.rmtree(new_dir, ignore_errors=True)
        shutil.rmtree(new_admin, ignore_errors=True)
        _record(state, "failed", f"Download failed, nothing changed: {exc}")
        return False

    # Swap by rename: the live tree stays intact as .prev until the new one
    # has proven itself, like apply_wifi() keeping the old iwd profile.
    shutil.rmtree(prev_dir, ignore_errors=True)
    APP_DIR.rename(prev_dir)
    new_dir.rename(APP_DIR)
    swapped_admin = new_admin.is_dir()
    if swapped_admin:
        shutil.rmtree(prev_admin, ignore_errors=True)
        if ADMIN_DIR.exists():
            ADMIN_DIR.rename(prev_admin)
        new_admin.rename(ADMIN_DIR)
    log.info("Installed %s alongside the previous tree; restarting %s", tag, SERVICE)

    if _systemctl("restart", SERVICE) and wait_until_healthy(HEALTH_SECONDS, HEALTH_POLL_SECONDS):
        log.info("%s is running %s", SERVICE, tag)
        shutil.rmtree(prev_dir, ignore_errors=True)
        shutil.rmtree(prev_admin, ignore_errors=True)
        state.update(installed=tag, available=False, applicable=False, reason="Up to date")
        _record(state, "success", f"Updated to {tag}")
        return True

    log.error("%s did not come up on %s; rolling back", SERVICE, tag)
    failed_dir = APP_DIR.with_name(APP_DIR.name + ".failed")
    shutil.rmtree(failed_dir, ignore_errors=True)
    APP_DIR.rename(failed_dir)
    prev_dir.rename(APP_DIR)
    shutil.rmtree(failed_dir, ignore_errors=True)
    if swapped_admin:
        shutil.rmtree(ADMIN_DIR, ignore_errors=True)
        if prev_admin.exists():
            prev_admin.rename(ADMIN_DIR)
    _systemctl("restart", SERVICE)
    _record(state, "rolled_back", f"{tag} did not start; restored the previous version")
    return False


# -- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nhl_scoreboard.updater")
    parser.add_argument("action", choices=("check", "apply"))
    parser.add_argument("--force", action="store_true", help="check even if [update] is disabled")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.action == "check":
        if not args.force:
            from .config import Settings

            if not Settings.load(args.config).update.enabled:
                log.info("Update checks are disabled ([update] enabled = false)")
                return 0
        return 0 if not check().get("error") else 1
    return 0 if apply() else 1


if __name__ == "__main__":
    sys.exit(main())
