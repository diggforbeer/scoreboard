"""Real end-to-end smoke test: a real Chromium browser against a real
admin_server.py subprocess serving the real built frontend/dist (#178
story 10). Every story of the React admin page rebuild was verified this
same way by hand -- browser, real save round trip, real file on disk --
but only ever manually, once, in a session; this codifies the smallest
useful slice of that so CI catches a regression in the "static page +
WebSocket on one port" mechanism itself, not just a `tsc`/lint pass.

Deliberately NOT part of the hermetic, offline, sub-second default
`pytest` run CLAUDE.md documents: marked `e2e` and excluded by
pyproject.toml's own `addopts` (`-m 'not e2e'`). Run explicitly:

    pip install -e '.[dev,e2e]'
    playwright install chromium
    npm run build --prefix frontend        # frontend/dist must exist
    pytest -m e2e

The dedicated `e2e` CI job (ci.yml) does exactly this on every PR.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = REPO_ROOT / "frontend" / "dist"
HOST = "127.0.0.1"
PORT = 8765

pytestmark = pytest.mark.e2e


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"admin_server.py never opened {host}:{port}")


@pytest.fixture
def admin_page_url(tmp_path):
    """Start a real admin_server.py subprocess serving the real built
    frontend/dist, and hand back the URL it's listening on. A subprocess,
    not an in-process thread (the way AdminServer itself runs inside
    ScoreboardApp) -- this test wants the real `python -m
    nhl_scoreboard.admin_server` entry point too, the same thing systemd
    actually execs on the device.
    """
    if not (DIST_DIR / "index.html").is_file():
        pytest.skip(f"{DIST_DIR}/index.html missing -- run `npm run build` in frontend/ first")

    config_path = tmp_path / "scoreboard.toml"
    config_path.write_text("")

    env = os.environ.copy()
    env["NHL_SCOREBOARD_CONFIG"] = str(config_path)
    env["NHL_SCOREBOARD_ADMIN_DIR"] = str(DIST_DIR)
    env["NHL_SCOREBOARD_ADMIN_HOST"] = HOST
    env["NHL_SCOREBOARD_ADMIN_PORT"] = str(PORT)

    proc = subprocess.Popen(
        [sys.executable, "-m", "nhl_scoreboard.admin_server"],
        env=env,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_port(HOST, PORT)
        yield f"http://{HOST}:{PORT}/"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        # returncode is None if wait() above already reaped it via
        # terminate(); -15 is a clean SIGTERM exit. Anything else is a
        # real crash worth seeing in the CI log.
        if proc.returncode not in (0, None, -15) and proc.stdout is not None:
            print(proc.stdout.read())


def test_admin_page_loads_and_saves_a_real_change(admin_page_url):
    """The actual point of this test: a real browser can load the built
    page from admin_server.py's own static serving, and a save genuinely
    round-trips over its WebSocket on that same port -- the two halves
    of story 10's "one port serves both" design, exercised together
    exactly the way a real board would be used.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page_url)
            page.wait_for_selector("text=Save Scoreboard", timeout=15000)

            connection_value = page.locator(".card-body", has_text="Connection").locator(".fs-5")
            assert connection_value.inner_text() == "open"

            page.select_option("#sb-favourite-team", "TOR")
            page.click("text=Save Scoreboard")
            page.wait_for_selector("text=Saved.", timeout=15000)

            assert page.input_value("#sb-favourite-team") == "TOR"
        finally:
            browser.close()
