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
import tomllib
from pathlib import Path
from typing import NamedTuple

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


class AdminPage(NamedTuple):
    url: str
    config_path: Path
    state_path: Path

    def config(self) -> dict:
        return tomllib.loads(self.config_path.read_text())


@pytest.fixture
def admin_page(tmp_path):
    """Start a real admin_server.py subprocess serving the real built
    frontend/dist, and hand back its URL and the config file it writes. A subprocess,
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
    env["NHL_SCOREBOARD_UPDATE_STATE"] = str(tmp_path / "update-state.json")
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
        yield AdminPage(f"http://{HOST}:{PORT}/", config_path, tmp_path / "update-state.json")
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


def test_admin_page_loads_and_saves_a_real_change(admin_page):
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
            page.goto(admin_page.url)
            page.wait_for_selector("#sb-favourite-team", timeout=15000)

            connection_value = page.locator(".card-body", has_text="Connection").locator(".fs-5")
            assert connection_value.inner_text() == "open"

            # Autosave (#273): picking a team is the whole save, no button.
            page.select_option("#sb-favourite-team", "TOR")
            page.wait_for_selector("text=saved ✓", timeout=15000)

            assert page.input_value("#sb-favourite-team") == "TOR"
            assert admin_page.config()["scoreboard"]["favourite_team"] == "TOR"
        finally:
            browser.close()


def test_update_card_lists_image_level_changes(admin_page):
    """A release that changes scripts/units/packages says so, with the apt
    command, and the board with no record gets the reflash notice (#284)."""
    import json

    from playwright.sync_api import sync_playwright

    def write(changes):
        admin_page.state_path.write_text(
            json.dumps(
                {
                    "installed": "v2026.09.01",
                    "latest": "v2026.09.02",
                    "available": True,
                    "applicable": True,
                    "image_changes": changes,
                }
            )
        )

    write(
        {
            "status": "differs",
            "files": ["scripts/nhl-scoreboard-setup-ap"],
            "packages": ["mpg123"],
            "command": "sudo apt-get install -y mpg123",
        }
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            differs = page.get_by_test_id("image-changes-differs")
            differs.wait_for(timeout=15000)
            assert "scripts/nhl-scoreboard-setup-ap" in differs.inner_text()
            assert "sudo apt-get install -y mpg123" in differs.inner_text()
            assert page.get_by_role("button", name="Install v2026.09.02").is_visible()

            # The server pushes a changed state file without a reload.
            write({"status": "unknown", "files": [], "packages": [], "command": ""})
            page.get_by_test_id("image-changes-unknown").wait_for(timeout=15000)
            assert page.get_by_test_id("image-changes-differs").count() == 0
        finally:
            browser.close()


def _sent_saves(page) -> list[str]:
    """Every ``save`` frame the page sends over its WebSocket, as raw JSON."""
    frames: list[str] = []
    page.on(
        "websocket",
        lambda ws: ws.on(
            "framesent",
            lambda payload: frames.append(payload) if '"type":"save"' in str(payload) else None,
        ),
    )
    return frames


def test_typing_saves_once_after_a_pause(admin_page):
    """A typed field waits for the pause: every keystroke would apply a
    half-typed value to the board (#273)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            frames = _sent_saves(page)
            page.goto(admin_page.url)
            field = page.locator("#sb-rotate_seconds")
            field.wait_for(timeout=15000)

            field.click()
            field.press("Control+a")
            field.press_sequentially("12", delay=150)
            assert frames == [], "saved mid-typing"

            page.wait_for_selector("text=saved ✓", timeout=15000)
            assert len(frames) == 1, frames
            assert admin_page.config()["scoreboard"]["rotate_seconds"] == 12
        finally:
            browser.close()


def test_undo_reverts_the_last_save(admin_page):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            box = page.locator("#sb-scores_grid")
            box.wait_for(timeout=15000)

            box.check()
            page.wait_for_selector("text=saved ✓", timeout=15000)
            assert admin_page.config()["scoreboard"]["scores_grid"] is True

            page.get_by_role("button", name="Undo").click()
            page.wait_for_selector("text=reverted ✓", timeout=15000)
            assert admin_page.config()["scoreboard"]["scores_grid"] is False
            assert not box.is_checked()
        finally:
            browser.close()


def test_a_cleared_number_box_is_never_saved(admin_page):
    """Clearing a box to retype it must not save 0 to the live board, even
    after the pause or on blur (#273, ported from #275)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            frames = _sent_saves(page)
            page.goto(admin_page.url)
            field = page.locator("#sb-rotate_seconds")
            field.wait_for(timeout=15000)

            field.fill("")
            page.wait_for_timeout(1500)  # past the typing pause
            field.blur()
            page.wait_for_timeout(500)
            assert frames == [], "an empty box was saved"
            assert "rotate_seconds" not in admin_page.config_path.read_text()

            field.fill("9")
            page.wait_for_selector("text=saved ✓", timeout=15000)
            assert len(frames) == 1, frames
            assert admin_page.config()["scoreboard"]["rotate_seconds"] == 9
        finally:
            browser.close()


@pytest.fixture
def live_admin_page(tmp_path, monkeypatch):
    """The admin server the way ScoreboardApp runs it -- in-process, on its
    own thread, with a panel Mirror (#268) -- plus a stand-in render loop
    that publishes a snapshot whenever one is asked for, each a different
    colour in the top-left LED. The standalone `python -m
    nhl_scoreboard.admin_server` above has no panel to mirror, so it can't
    exercise the live view."""
    if not (DIST_DIR / "index.html").is_file():
        pytest.skip(f"{DIST_DIR}/index.html missing -- run `npm run build` in frontend/ first")
    import threading
    from datetime import UTC, datetime

    from nhl_scoreboard import admin_server
    from nhl_scoreboard.display.mirror import Mirror

    monkeypatch.setattr(admin_server, "ADMIN_DIR", DIST_DIR)
    config_path = tmp_path / "scoreboard.toml"
    config_path.write_text("")
    mirror = Mirror(128, 32)
    stop = threading.Event()
    colours = [(255, 0, 0), (0, 255, 0)]

    def render_loop():
        while not stop.wait(0.2):
            if mirror.requested:
                mirror.requested = False
                mirror.clear()
                mirror.set_pixel(
                    0,
                    0,
                    *colours[
                        min(len(colours) - 1, (mirror.latest().seq if mirror.latest() else 0))
                    ],
                )
                mirror.publish(80, datetime.now(UTC))

    loop = threading.Thread(target=render_loop, daemon=True)
    loop.start()
    server = admin_server.AdminServer(str(config_path), port=0, mirror=mirror, host=HOST)
    server.start()
    try:
        yield f"http://{HOST}:{server.port}/", mirror
    finally:
        server.stop()
        stop.set()
        loop.join(timeout=2)


def _top_left_led(canvas):
    return canvas.evaluate(
        "c => Array.from(c.getContext('2d').getImageData(4, 4, 1, 1).data).slice(0, 3)"
    )


def test_live_view_shows_a_snapshot_and_refreshes(live_admin_page):
    """#268's own acceptance: the page opens the live view and gets a
    frame -- checked on the canvas itself, not just that a canvas element
    appeared -- and Refresh replaces it with a newer one."""
    from playwright.sync_api import expect, sync_playwright

    url, mirror = live_admin_page
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url)
            page.get_by_role("button", name="Show live view").click()
            canvas = page.get_by_test_id("live-view")
            canvas.wait_for(timeout=10_000)
            assert _top_left_led(canvas) == [255, 0, 0]
            expect(page.get_by_text("the panel is set to 80%")).to_be_visible()
            assert mirror.watching

            page.get_by_role("button", name="Refresh").click()
            deadline = time.monotonic() + 5
            while _top_left_led(canvas) != [0, 255, 0] and time.monotonic() < deadline:
                time.sleep(0.1)
            assert _top_left_led(canvas) == [0, 255, 0]

            page.get_by_role("button", name="Hide").click()
            deadline = time.monotonic() + 5
            while mirror.watching and time.monotonic() < deadline:
                time.sleep(0.1)
            assert not mirror.watching, "closing the live view must stop the snapshots"
        finally:
            browser.close()
