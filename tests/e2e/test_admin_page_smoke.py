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
    scoreboard.admin_server` entry point too, the same thing systemd
    actually execs on the device.
    """
    if not (DIST_DIR / "index.html").is_file():
        pytest.skip(f"{DIST_DIR}/index.html missing -- run `npm run build` in frontend/ first")

    config_path = tmp_path / "scoreboard.toml"
    config_path.write_text("")

    env = os.environ.copy()
    env["SCOREBOARD_CONFIG"] = str(config_path)
    env["SCOREBOARD_ADMIN_DIR"] = str(DIST_DIR)
    env["SCOREBOARD_UPDATE_STATE"] = str(tmp_path / "update-state.json")
    env["SCOREBOARD_ADMIN_HOST"] = HOST
    env["SCOREBOARD_ADMIN_PORT"] = str(PORT)

    proc = subprocess.Popen(
        [sys.executable, "-m", "scoreboard.admin_server"],
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
            page.wait_for_selector("#teams-add", timeout=15000)

            connection_value = page.locator(".card-body", has_text="Connection").locator(".fs-5")
            assert connection_value.inner_text() == "open"

            # Autosave (#273): adding a team is the whole save, no button.
            page.select_option("#teams-add", "hockey:TOR")
            page.click("#teams-add-button")
            page.wait_for_selector("text=saved ✓", timeout=15000)

            assert page.locator("#teams-list li[data-team='TOR']").count() == 1
            _wait_until(
                lambda: admin_page.config()["teams"] == [{"sport": "hockey", "team": "TOR"}]
            )
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
            "files": ["scripts/scoreboard-setup-ap"],
            "packages": ["mpg123"],
            "command": "sudo apt-get install -y mpg123",
        }
    )
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.get_by_role("button", name="Setup", exact=True).click()
            differs = page.get_by_test_id("image-changes-differs")
            differs.wait_for(timeout=15000)
            assert "scripts/scoreboard-setup-ap" in differs.inner_text()
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
            page.get_by_role("button", name="Display", exact=True).click()
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
            page.get_by_role("button", name="Display", exact=True).click()
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
            page.get_by_role("button", name="Display", exact=True).click()
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


def test_brightness_on_display_saves_only_its_own_fields(admin_page):
    """Brightness lives on the Display tab but is one slice of [panel]. Its
    Save must not drag the restart-required Setup fields along (#449)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.get_by_role("button", name="Setup", exact=True).click()
            rows = page.locator("#panel-rows")
            rows.wait_for(timeout=15000)
            rows.fill("16")  # an unsaved Setup edit that must not be sent

            page.get_by_role("button", name="Display", exact=True).click()
            page.locator("#panel-brightness").fill("40")
            page.get_by_role("button", name="Save brightness").click()
            page.wait_for_selector("text=Saved", timeout=15000)

            panel = admin_page.config()["panel"]
            assert panel["brightness"] == 40
            assert "rows" not in panel, panel
        finally:
            browser.close()


@pytest.fixture
def live_admin_page(tmp_path, monkeypatch):
    """The admin server the way ScoreboardApp runs it -- in-process, on its
    own thread, with a panel Mirror (#268) -- plus a stand-in render loop
    that publishes a snapshot whenever one is asked for, each a different
    colour in the top-left LED. The standalone `python -m
    scoreboard.admin_server` above has no panel to mirror, so it can't
    exercise the live view."""
    if not (DIST_DIR / "index.html").is_file():
        pytest.skip(f"{DIST_DIR}/index.html missing -- run `npm run build` in frontend/ first")
    import threading
    from datetime import UTC, datetime

    from scoreboard import admin_server
    from scoreboard.display.mirror import Mirror

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


def _wait_until(condition, timeout=15.0):
    """Poll ``condition`` until it is true. The config file is rewritten by another process, so a
    read can land on a half-written or not-yet-populated file (no ``[scoreboard]`` yet, or a TOML
    error): that is "not yet", not a failure (it flaked once in CI)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if condition():
                return
        except (KeyError, FileNotFoundError, tomllib.TOMLDecodeError):
            pass
        time.sleep(0.1)
    raise AssertionError("condition never became true")


def test_one_idle_rotation_mixes_hockey_and_football_screens_and_football_has_its_own_card(
    admin_page,
):
    """Epic #470: the one Idle rotation card takes hockey, football and clock rows (saved as
    ``[[rotation]]``, nothing under ``[football]``); football's section of that card (hold times
    and toggles) shows once a football team is ranked or while nothing is."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.wait_for_selector("#teams-add", timeout=15000)
            football = page.get_by_role("heading", name="Football between games")
            rotation = page.get_by_role("heading", name="Idle rotation", exact=True)
            rotation.wait_for(timeout=15000)  # the Idle rotation card is on the Home tab
            page.get_by_role("button", name="Display", exact=True).click()
            football.wait_for(timeout=15000)
            assert football.count() == 1, "nothing ranked: football's card shows"

            page.get_by_role("button", name="Home", exact=True).click()
            page.select_option("#teams-add", "hockey:NSH")
            page.click("#teams-add-button")
            page.get_by_role("button", name="Display", exact=True).click()
            _wait_until(lambda: football.count() == 0)  # only a hockey team is ranked

            page.get_by_role("button", name="Home", exact=True).click()
            page.select_option("#teams-add", "football:TEN")
            page.click("#teams-add-button")

            # One list, both sports: a hockey row, a football row, the clock.
            card = rotation.locator("xpath=ancestor::*[contains(@class, 'card-body')]")
            for _ in range(3):
                card.get_by_role("button", name="Add row").click()
            page.select_option('[aria-label="rotation screen 1"]', "standings")
            page.select_option('[aria-label="rotation screen 2"]', "fb_week")
            page.fill('[aria-label="rotation seconds 2"]', "12")
            page.select_option('[aria-label="rotation screen 3"]', "clock")
            page.keyboard.press("Tab")
            _wait_until(
                lambda: (
                    [r["screen"] for r in admin_page.config().get("rotation", [])]
                    == ["standings", "fb_week", "clock"]
                )
            )
            assert admin_page.config()["rotation"][1]["seconds"] == 12
            assert "rotation" not in admin_page.config().get("football", {})

            # Football's own card (Display tab) saves its lengths and toggles under [football].
            page.get_by_role("button", name="Display", exact=True).click()
            football.wait_for(timeout=15000)
            page.fill("#football-final-hold", "45")
            page.fill("#football-page-seconds", "4")
            page.uncheck("#football-show_bye")
            page.keyboard.press("Tab")
            page.fill("#football-timing-score", "10")
            page.keyboard.press("Tab")
            _wait_until(lambda: admin_page.config()["football"].get("final_hold_minutes") == 45)
            _wait_until(lambda: admin_page.config()["football"].get("show_bye") is False)
            _wait_until(lambda: admin_page.config()["football"].get("page_seconds") == 4)
            _wait_until(lambda: admin_page.config()["football"].get("score_seconds") == 10)

            page.reload()
            page.wait_for_selector('[aria-label="rotation screen 2"]', timeout=15000)
            assert page.input_value('[aria-label="rotation screen 2"]') == "fb_week"
            page.get_by_role("button", name="Display", exact=True).click()
            page.wait_for_selector("#football-final-hold", timeout=15000)
            assert page.input_value("#football-final-hold") == "45"
        finally:
            browser.close()


def test_my_teams_card_adds_reorders_and_removes_teams_and_marks_the_horn_teams(admin_page):
    """Epic #470 (#473): one ranked list for both sports. The first team of each sport carries the
    horn mark, the first row the top-priority mark, and both follow the order; every change saves
    to ``[[teams]]`` in order and survives a reload."""
    from playwright.sync_api import sync_playwright

    def saved():
        return [(t["sport"], t["team"]) for t in admin_page.config().get("teams", [])]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.wait_for_selector("#teams-add", timeout=15000)
            assert page.locator("#teams-empty").is_visible(), "an empty list prompts for a team"

            for choice in ("hockey:NSH", "football:TEN", "hockey:TOR"):
                page.select_option("#teams-add", choice)
                page.click("#teams-add-button")
            page.wait_for_selector("#teams-list li[data-team='TOR']")
            assert not page.locator("#teams-empty").count()
            _wait_until(
                lambda: saved() == [("hockey", "NSH"), ("football", "TEN"), ("hockey", "TOR")]
            )

            def horn(team):
                return page.locator(f"#teams-list li[data-team='{team}'] .teams-horn").count()

            # NSH leads hockey and TEN leads football; TOR is second in hockey.
            assert (horn("NSH"), horn("TEN"), horn("TOR")) == (1, 1, 0)
            assert page.locator("#teams-list li[data-team='NSH'] .teams-top").count() == 1

            # A ranked team is no longer offered; the same abbreviation in the other sport still is.
            assert page.locator("#teams-add option[value='hockey:NSH']").count() == 0
            assert page.locator("#teams-add option[value='football:NYG']").count() == 1

            # Move Toronto above Nashville: the horn and the top mark move with the order.
            for _ in range(2):
                page.get_by_role("button", name="Move Toronto Maple Leafs up").click()
            _wait_until(
                lambda: saved() == [("hockey", "TOR"), ("hockey", "NSH"), ("football", "TEN")]
            )
            assert (horn("TOR"), horn("NSH"), horn("TEN")) == (1, 0, 1)
            assert page.locator("#teams-list li[data-team='TOR'] .teams-top").count() == 1
            assert page.locator("#teams-list li").first.get_attribute("data-team") == "TOR"

            page.reload()
            page.wait_for_selector("#teams-list li[data-team='TEN']", timeout=15000)
            order = [li.get_attribute("data-team") for li in page.locator("#teams-list li").all()]
            assert order == ["TOR", "NSH", "TEN"]

            # Removing the lead gives the horn back to the next hockey team.
            page.get_by_role("button", name="Remove Toronto Maple Leafs").click()
            _wait_until(lambda: saved() == [("hockey", "NSH"), ("football", "TEN")])
            assert page.locator("#teams-list li[data-team='NSH'] .teams-horn").count() == 1
        finally:
            browser.close()


def test_the_cache_tab_opens_and_offers_to_clear(admin_page):
    """The Cache tab asks the board what it has cached; a bare admin server has nothing, so it says
    so, and the clear buttons are there (clearing itself is covered by unit tests)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.wait_for_selector("#teams-add", timeout=15000)
            page.get_by_role("button", name="Cache", exact=True).click()
            page.get_by_role("heading", name="Cached data").wait_for(timeout=15000)
            page.get_by_text("Nothing cached right now.").wait_for(timeout=15000)
            assert page.get_by_role("button", name="Clear everything").count() == 1
            assert page.get_by_role("button", name="Clear hockey").count() == 1
            assert page.get_by_role("button", name="Clear football").count() == 1
        finally:
            browser.close()


def test_important_dates_card_adds_edits_and_removes_a_date(admin_page):
    """#524: a date picker, a text box limited to what the panel can draw, icon radios and the
    show-years / window controls. A new date is held back until it has text; every change then
    saves to ``[[dates]]`` as a real TOML date and survives a reload."""
    from datetime import date

    from playwright.sync_api import sync_playwright

    def saved():
        return admin_page.config().get("dates", [])

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            frames = _sent_saves(page)
            page.goto(admin_page.url)
            page.wait_for_selector("#dates-add-button", timeout=15000)
            assert page.locator("#dates-empty").is_visible()

            # A new row has no text yet: it shows, but nothing is sent.
            page.click("#dates-add-button")
            page.wait_for_selector("[data-date-row='0']")
            page.wait_for_timeout(1500)
            assert [f for f in frames if '"section":"dates"' in f] == [], "saved an empty date"
            assert not admin_page.config_path.read_text().count("[[dates]]")

            # Lower case becomes capitals and characters the panel can't draw are dropped.
            page.fill('[aria-label="date 1"]', "2018-03-14")
            page.fill('[aria-label="text 1"]', "mom <3 & dad")
            assert page.input_value('[aria-label="text 1"]') == "MOM 3 & DAD"
            page.fill('[aria-label="text 1"]', "mom")
            _wait_until(lambda: saved() and saved()[0]["text"] == "MOM")
            assert saved()[0]["date"] == date(2018, 3, 14)  # a real TOML date, not a string
            assert saved()[0]["icon"] == "cake" and saved()[0]["repeat"] is True
            assert saved()[0]["days_before"] == 30

            # The label stops at 14 characters.
            page.fill('[aria-label="text 1"]', "A" * 20)
            assert len(page.input_value('[aria-label="text 1"]')) == 14
            page.fill('[aria-label="text 1"]', "MOM")

            # Icons are radios, and the others are plain clicks that save at once.
            page.check("#dates-icon-0-heart")
            _wait_until(lambda: saved()[0]["icon"] == "heart")
            page.check("#dates-years-0")
            _wait_until(lambda: saved()[0]["show_years"] is True)
            page.fill("#dates-days-0", "10")
            _wait_until(lambda: saved()[0]["days_before"] == 10)

            # "Every year" off is a one-off, which has no years to count.
            page.uncheck("#dates-repeat-0")
            _wait_until(lambda: saved()[0]["repeat"] is False)
            assert saved()[0]["show_years"] is False
            assert page.locator("#dates-years-0").is_disabled()

            page.reload()
            page.wait_for_selector("[data-date-row='0']", timeout=15000)
            assert page.input_value('[aria-label="date 1"]') == "2018-03-14"
            assert page.input_value('[aria-label="text 1"]') == "MOM"
            assert page.locator("#dates-icon-0-heart").is_checked()

            page.get_by_role("button", name="Remove date 1").click()
            _wait_until(lambda: "dates" not in admin_page.config())
            assert page.locator("#dates-empty").is_visible()
        finally:
            browser.close()


def test_a_removed_blank_date_never_blocks_saving_the_others(admin_page):
    """The page holds back a date with no text by its position, so removing that row has to forget
    the mark or no later save would ever be sent."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.wait_for_selector("#dates-add-button", timeout=15000)
            page.click("#dates-add-button")
            page.fill('[aria-label="text 1"]', "ONE")
            _wait_until(lambda: admin_page.config()["dates"][0]["text"] == "ONE")

            page.click("#dates-add-button")  # a blank second row, held back
            page.wait_for_selector("[data-date-row='1']")
            page.get_by_role("button", name="Remove date 2").click()
            page.wait_for_selector("[data-date-row='1']", state="detached")

            page.check("#dates-icon-0-gift")
            _wait_until(lambda: admin_page.config()["dates"][0]["icon"] == "gift")
        finally:
            browser.close()


def test_the_dates_card_offers_to_add_the_screen_to_a_rotation_that_lacks_it(admin_page):
    """Dates only show through a ``dates`` rotation row. With a rotation but no such row the card
    says so and can add one; with no rotation (the built-in default) it explains instead, since
    adding a lone row would replace the default."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(admin_page.url)
            page.wait_for_selector("#dates-hint", timeout=15000)
            assert page.get_by_role("button", name="Add to rotation").count() == 0
            assert "Add a dates row" in page.locator("#dates-hint").inner_text()

            rotation = page.get_by_role("heading", name="Idle rotation", exact=True)
            card = rotation.locator("xpath=ancestor::*[contains(@class, 'card-body')]")
            card.get_by_role("button", name="Add row").click()
            page.select_option('[aria-label="rotation screen 1"]', "clock")
            page.get_by_role("button", name="Add to rotation").click()
            _wait_until(
                lambda: [r["screen"] for r in admin_page.config()["rotation"]] == ["clock", "dates"]
            )
            assert page.locator("#dates-hint").count() == 0
        finally:
            browser.close()
