"""Holiday decorations (#237): calendar, config, fly-by timing, app wiring.

What the decorations look like is snapshotted in ``test_render.py``
alongside every other scene; this file is the logic around them.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, date, datetime

import pytest

from nhl_scoreboard.app import ANIMATION_FRAME_INTERVAL, FRAME_INTERVAL, Scene, ScoreboardApp
from nhl_scoreboard.config import HolidayConfig, Settings
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.holiday import (
    FLYBY_SPEED,
    GHOST_BODY,
    GHOST_WIDTH,
    HOLIDAY_NAMES,
    HOLIDAYS,
    NO_OVERLAY_SCENES,
    PUMPKIN,
    HolidayOverlay,
    active_holiday,
)
from nhl_scoreboard.display.matrix import Backend
from test_app import FakeClient, FakeClockSource, FakeGraphics, FakeMatrix, FakeOptions

W, H = 128, 32
HALLOWEEN = HOLIDAYS["halloween"]
CROSSING_SECONDS = (W + GHOST_WIDTH) / FLYBY_SPEED


def draw(overlay: HolidayOverlay, now: float, kind: str = "game", holiday=HALLOWEEN, gap=(60, 60)):
    canvas = AsciiCanvas(W, H)
    moving = overlay.draw(
        canvas,
        scene_kind=kind,
        holiday=holiday,
        now=now,
        width=W,
        height=H,
        min_gap_seconds=gap[0],
        max_gap_seconds=gap[1],
    )
    return moving, canvas


def ghost_pixels(canvas: AsciiCanvas) -> dict:
    return {p: c for p, c in canvas.pixels.items() if c == GHOST_BODY}


# -- calendar -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 9, 30), None),
        (date(2026, 10, 1), "halloween"),
        (date(2026, 10, 31), "halloween"),
        (date(2026, 11, 1), None),
    ],
)
def test_halloween_window_is_all_of_october(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


def test_an_unticked_holiday_never_shows_in_its_window():
    assert active_holiday([], date(2026, 10, 15)) is None


# -- config -------------------------------------------------------------------


def test_off_by_default_with_every_holiday_ticked():
    cfg = Settings().holiday
    assert cfg.enabled is False
    assert cfg.themes == list(HOLIDAY_NAMES)


def test_unknown_theme_warns_and_is_dropped(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = HolidayConfig(themes=["Halloween", "arbor_day", "halloween"])
    assert cfg.themes == ["halloween"]
    assert "arbor_day" in caplog.text


def test_a_bare_string_theme_is_treated_as_a_one_item_list():
    assert HolidayConfig(themes="halloween").themes == ["halloween"]


def test_flyby_gap_is_floored_and_ordered(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = HolidayConfig(flyby_min_minutes=30, flyby_max_minutes=0)
    assert (cfg.flyby_min_minutes, cfg.flyby_max_minutes) == (1.0, 30.0)
    assert "swapping" in caplog.text


def test_parsed_from_toml_section():
    settings = Settings.from_dict(
        {"holiday": {"enabled": True, "themes": ["halloween"], "flyby_min_minutes": 2}}
    )
    assert settings.holiday.enabled
    assert settings.holiday.flyby_min_minutes == 2


# -- fly-by timing ------------------------------------------------------------


def test_first_flyby_waits_a_random_gap_inside_the_configured_range():
    overlay = HolidayOverlay(random.Random(7))
    assert draw(overlay, 0.0, gap=(300, 1200))[0] is False
    due = overlay._next_flyby_at
    assert 300 <= due <= 1200
    assert draw(overlay, due - 0.01)[0] is False
    assert draw(overlay, due)[0] is True


def test_flyby_crosses_right_to_left_then_schedules_the_next():
    overlay = HolidayOverlay(random.Random(1))
    overlay.start_flyby(0.0)
    xs = []
    t = 0.0
    while t < CROSSING_SECONDS + 1:
        moving, canvas = draw(overlay, t, gap=(300, 300))
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        if ghost := ghost_pixels(canvas):  # the first frame is still just off the edge
            xs.append(min(x for x, _ in ghost))
        t += ANIMATION_FRAME_INTERVAL
    assert xs == sorted(xs, reverse=True), "always moving left"
    assert xs[0] > W - GHOST_WIDTH and xs[-1] == 0, "enters and leaves off the edges"
    assert t == pytest.approx(CROSSING_SECONDS, abs=0.1)
    assert overlay._next_flyby_at == pytest.approx(t + 300)


@pytest.mark.parametrize("kind", sorted(NO_OVERLAY_SCENES))
def test_nothing_draws_on_scoring_or_setup_scenes(kind):
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    moving, canvas = draw(overlay, 2.0, kind=kind)
    assert moving is False
    assert canvas.pixels == {}


def test_a_due_flyby_waits_for_an_allowed_scene_to_start():
    overlay = HolidayOverlay(random.Random(3))
    draw(overlay, 0.0, gap=(60, 60))
    assert draw(overlay, 61.0, kind="goal")[0] is False
    assert overlay._flyby_started is None, "must not start under a goal"
    assert draw(overlay, 62.0, kind="game")[0] is True
    assert overlay._flyby_started == 62.0


def test_out_of_season_forgets_the_schedule():
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    moving, canvas = draw(overlay, 1.0, holiday=None)
    assert (moving, canvas.pixels) == (False, {})
    assert overlay._flyby_started is None
    assert overlay._next_flyby_at is None


def test_pumpkins_only_on_idle_scenes():
    overlay = HolidayOverlay()
    _, clock = draw(overlay, 0.0, kind="clock")
    _, game = draw(overlay, 0.0, kind="game")
    assert PUMPKIN in clock.pixels.values()
    assert PUMPKIN not in game.pixels.values()


# -- app wiring ---------------------------------------------------------------


@pytest.fixture
def holiday_app():
    src = FakeClockSource()
    settings = Settings()
    settings.holiday = HolidayConfig(enabled=True)
    now = {"t": datetime(2026, 10, 10, 18, 0, tzinfo=UTC)}
    app = ScoreboardApp(
        settings,
        client=FakeClient([]),
        backend=Backend("fake", FakeMatrix, FakeOptions, FakeGraphics),
        clock=lambda: now["t"],
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    app.holiday_overlay = HolidayOverlay(random.Random(0))
    return app, src, now


def test_active_only_when_enabled_and_in_season(holiday_app):
    app, _src, now = holiday_app
    assert app.active_holiday() is HALLOWEEN
    app.settings.holiday.enabled = False
    assert app.active_holiday() is None
    app.settings.holiday.enabled = True
    now["t"] = datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    assert app.active_holiday() is None


def test_season_follows_the_board_timezone_not_utc(holiday_app):
    app, _src, now = holiday_app
    # 02:00 UTC on Nov 1 is still the evening of Oct 31 in Chicago.
    now["t"] = datetime(2026, 11, 1, 2, 0, tzinfo=UTC)
    assert app.active_holiday() is HALLOWEEN


def test_loop_speeds_up_only_while_a_flyby_is_crossing(holiday_app):
    app, src, _now = holiday_app
    app.renderer.draw_message = lambda *a: None
    app.draw_scene(Scene("no_games"))
    assert app.frame_interval() == FRAME_INTERVAL

    app.holiday_overlay.start_flyby(src.now)
    app.draw_scene(Scene("no_games"))
    assert app.frame_interval() == ANIMATION_FRAME_INTERVAL

    src.sleep(CROSSING_SECONDS + 1)
    app.draw_scene(Scene("no_games"))
    assert app.frame_interval() == FRAME_INTERVAL


def test_night_blanking_drops_back_to_the_slow_loop(holiday_app):
    app, src, _now = holiday_app
    app.renderer.draw_message = lambda *a: None
    app.holiday_overlay.start_flyby(src.now)
    app.draw_scene(Scene("no_games"))
    assert app.frame_interval() == ANIMATION_FRAME_INTERVAL

    app._night_mode_active = lambda: True
    app.settings.night_mode.dim_brightness = 0
    app.draw()
    assert app.frame_interval() == FRAME_INTERVAL
