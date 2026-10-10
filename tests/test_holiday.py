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
    CLOUD,
    CONFETTI,
    FIREWORKS,
    FLYBY_SPEED,
    GHOST_BODY,
    GHOST_WIDTH,
    GROUNDHOG,
    GROUNDHOG_FUR,
    GROUNDHOG_SHADOW,
    HEART,
    HEART_OUTLINE,
    HEART_PINK,
    HEART_RED,
    HOLIDAY_NAMES,
    HOLIDAYS,
    NO_OVERLAY_SCENES,
    PRESENT_COLOURS,
    PUMPKIN,
    SANTA,
    SMALL_PRESENT,
    SNOW,
    SNOW_BAND,
    SUN,
    TURKEY,
    HolidayOverlay,
    active_holiday,
)
from nhl_scoreboard.display.matrix import Backend
from test_app import FakeClient, FakeClockSource, FakeGraphics, FakeMatrix, FakeOptions

W, H = 128, 32
HALLOWEEN = HOLIDAYS["halloween"]
CROSSING_SECONDS = (W + GHOST_WIDTH) / FLYBY_SPEED


def draw(
    overlay: HolidayOverlay,
    now: float,
    kind: str = "game",
    holiday=HALLOWEEN,
    gap=(60, 60),
    day: date | None = None,
):
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
        day=day,
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


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        # 2026: Thanksgiving is Thu Nov 26, so the window is Nov 20-26.
        (date(2026, 11, 19), None),
        (date(2026, 11, 20), "thanksgiving"),
        (date(2026, 11, 26), "thanksgiving"),
        (date(2026, 11, 27), None),
        # 2025 moves it: Thu Nov 27, window Nov 21-27.
        (date(2025, 11, 20), None),
        (date(2025, 11, 27), "thanksgiving"),
    ],
)
def test_us_thanksgiving_is_the_week_up_to_the_fourth_thursday(day, expected):
    found = active_holiday(["thanksgiving"], day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        # 2026: 2nd Monday of October is the 12th, so Fri 9th - Mon 12th.
        (date(2026, 10, 8), None),
        (date(2026, 10, 9), "thanksgiving_ca"),
        (date(2026, 10, 12), "thanksgiving_ca"),
        (date(2026, 10, 13), None),
        # 2025: Mon Oct 13, so Fri 10th - Mon 13th.
        (date(2025, 10, 9), None),
        (date(2025, 10, 13), "thanksgiving_ca"),
    ],
)
def test_canadian_thanksgiving_is_the_long_weekend(day, expected):
    found = active_holiday(["thanksgiving_ca"], day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("themes", "day", "expected"),
    [
        (HOLIDAY_NAMES, date(2026, 10, 10), "thanksgiving_ca"),
        (HOLIDAY_NAMES, date(2026, 10, 13), "halloween"),
        (["halloween"], date(2026, 10, 10), "halloween"),
    ],
)
def test_canadian_thanksgiving_wins_its_weekend_over_halloween(themes, day, expected):
    assert active_holiday(themes, day).name == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 11, 30), None),
        (date(2026, 12, 1), "christmas"),
        (date(2026, 12, 26), "christmas"),
        (date(2026, 12, 27), None),
    ],
)
def test_christmas_runs_december_first_to_boxing_day(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 12, 26), "christmas"),
        (date(2026, 12, 30), None),
        (date(2026, 12, 31), "new_year"),
        (date(2027, 1, 1), "new_year"),
        (date(2027, 1, 2), None),
    ],
)
def test_new_years_wraps_the_year(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2027, 2, 6), None),
        (date(2027, 2, 7), "valentines"),
        (date(2027, 2, 14), "valentines"),
        (date(2027, 2, 15), None),
    ],
)
def test_valentines_is_the_week_up_to_the_fourteenth(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2027, 2, 1), None), (date(2027, 2, 2), "groundhog"), (date(2027, 2, 3), None)],
)
def test_groundhog_day_is_one_day(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


#: Fixed by the year seed (see GROUNDHOG.sees_shadow); pinned here so a
#: change to the seed is a deliberate, visible test change.
SHADOW_YEAR, SPRING_YEAR = date(2027, 2, 2), date(2026, 2, 2)


def test_shadow_is_decided_once_per_year_and_varies_between_years():
    assert GROUNDHOG.sees_shadow(SHADOW_YEAR) is True
    assert GROUNDHOG.sees_shadow(SPRING_YEAR) is False
    verdicts = {GROUNDHOG.sees_shadow(date(y, 2, 2)) for y in range(2025, 2035)}
    assert verdicts == {True, False}


def test_both_thanksgivings_share_the_turkey():
    assert HOLIDAYS["thanksgiving"].flyby is HOLIDAYS["thanksgiving_ca"].flyby is TURKEY


def test_an_unticked_holiday_never_shows_in_its_window():
    assert active_holiday([], date(2026, 10, 15)) is None


# -- config -------------------------------------------------------------------


def test_off_by_default_with_every_default_on_holiday_ticked():
    cfg = Settings().holiday
    assert cfg.enabled is False
    assert cfg.themes == [
        "halloween",
        "thanksgiving",
        "christmas",
        "new_year",
        "groundhog",
        "valentines",
    ]
    assert "thanksgiving_ca" in HOLIDAY_NAMES, "known, just not ticked unasked"


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


def test_turkey_walks_along_the_bottom_edge_without_leaving_the_panel():
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    turkey = HOLIDAYS["thanksgiving"]
    t, rows = 0.0, set()
    while True:
        moving, canvas = draw(overlay, t, holiday=turkey)
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        rows |= {y for _, y in canvas.pixels}
        t += ANIMATION_FRAME_INTERVAL
    assert max(rows) == H - 1, "feet on the bottom row"
    assert min(rows) == H - TURKEY.height
    assert t == pytest.approx((W + TURKEY.width) / TURKEY.speed, abs=0.1)


def presents_on(canvas: AsciiCanvas) -> int:
    """How many dropped presents are on the ground.

    By box colour on the bottom row: each present's "CCrCC" base has four
    box pixels there, and Santa (boots on that row) shares none of them --
    unlike the bow row, which his body crosses in matching red and gold.
    """
    boxes = {dict(colours)["C"] for colours in PRESENT_COLOURS}
    bottom = [c for (_, y), c in canvas.pixels.items() if y == H - 1 and c in boxes]
    return len(bottom) // (len(SMALL_PRESENT[-1]) - 1)


def test_santa_drops_presents_behind_him_and_they_linger_after_he_leaves():
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    christmas = HOLIDAYS["christmas"]
    t, counts, santa_gone_at = 0.0, [], None
    while True:
        moving, canvas = draw(overlay, t, holiday=christmas)
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        counts.append(presents_on(canvas))
        if santa_gone_at is None and W - round(t * SANTA.speed) + SANTA.width <= 0:
            santa_gone_at = t
        t += ANIMATION_FRAME_INTERVAL
    assert counts[0] == 0, "nothing on the ground before he's walked anywhere"
    assert counts == sorted(counts), "presents only ever accumulate during a pass"
    assert counts[-1] >= 4
    assert t - santa_gone_at == pytest.approx(SANTA.linger_seconds, abs=0.1)


def test_snow_falls_only_in_the_side_bands_and_keeps_moving():
    overlay = HolidayOverlay()
    christmas = HOLIDAYS["christmas"]
    frames = [draw(overlay, t, kind="clock", holiday=christmas)[1] for t in (0.0, 0.5, 1.0)]
    for canvas in frames:
        flakes = [p for p, c in canvas.pixels.items() if c == SNOW]
        assert flakes, "some snow on screen"
        assert all(x <= SNOW_BAND + 1 or x >= W - SNOW_BAND - 1 for x, _ in flakes)
    snow = [{p for p, c in f.pixels.items() if c == SNOW} for f in frames]
    assert snow[0] != snow[1] != snow[2], "it actually falls"


def test_snow_alone_never_speeds_up_the_loop():
    overlay = HolidayOverlay()
    moving, _ = draw(overlay, 0.0, kind="clock", holiday=HOLIDAYS["christmas"], gap=(600, 600))
    assert moving is False


def test_fireworks_show_bursts_every_rocket_then_schedules_the_next():
    overlay = HolidayOverlay(random.Random(5))
    overlay.start_flyby(0.0)
    new_year = HOLIDAYS["new_year"]
    t, seen = 0.0, set()
    while True:
        moving, canvas = draw(overlay, t, holiday=new_year, gap=(300, 300))
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        seen |= set(canvas.pixels.values())
        t += ANIMATION_FRAME_INTERVAL
    assert t == pytest.approx(FIREWORKS.duration, abs=0.1)
    for rocket in FIREWORKS.rockets:
        assert rocket.colour in seen, f"{rocket.colour} never burst at full colour"
    assert overlay._next_flyby_at == pytest.approx(t + 300)


def test_confetti_twinkles_in_the_side_bands_without_the_fast_loop():
    overlay = HolidayOverlay()
    new_year = HOLIDAYS["new_year"]
    frames = []
    for t in (0.0, 0.5, 1.0):
        moving, canvas = draw(overlay, t, kind="clock", holiday=new_year, gap=(600, 600))
        assert moving is False
        frames.append({p for p, c in canvas.pixels.items() if c in CONFETTI})
    assert all(frames), "some confetti lit every frame"
    assert frames[0] != frames[1] != frames[2], "it twinkles"
    for dots in frames:
        assert all(x <= SNOW_BAND + 1 or x >= W - SNOW_BAND - 1 for x, _ in dots)


def test_flying_heart_is_outlined_so_it_shows_over_a_red_logo():
    for frame in HEART.frames:
        rows = list(frame)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == "R":
                    neighbours = [
                        rows[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    ]
                    assert "." not in neighbours, f"red pixel at {x},{y} touches the background"
    assert dict(HEART.palette)["o"] == HEART_OUTLINE


def test_heart_floats_across_without_leaving_the_panel():
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    t = 0.0
    while True:
        moving, canvas = draw(overlay, t, holiday=HOLIDAYS["valentines"])
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        t += ANIMATION_FRAME_INTERVAL
    assert t == pytest.approx((W + HEART.width) / HEART.speed, abs=0.1)


def test_corner_hearts_beat_out_of_step_without_the_fast_loop():
    overlay = HolidayOverlay()
    sizes = []
    for t in (0.0, 0.5):
        moving, canvas = draw(overlay, t, kind="clock", holiday=HOLIDAYS["valentines"])
        assert moving is False
        red = sum(1 for c in canvas.pixels.values() if c == HEART_RED)
        pink = sum(1 for c in canvas.pixels.values() if c == HEART_PINK)
        sizes.append((red, pink))
    (red0, pink0), (red1, pink1) = sizes
    assert red0 != red1 and pink0 != pink1, "both beat"
    assert (red0 > red1) != (pink0 > pink1), "out of step"


def run_groundhog(day: date) -> tuple[float, bool, int]:
    """(how long it lasted, whether a shadow ever appeared, lowest fur row)."""
    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    t, saw_shadow, lowest = 0.0, False, 0
    while True:
        moving, canvas = draw(overlay, t, holiday=HOLIDAYS["groundhog"], day=day)
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            return t, saw_shadow, lowest
        colours = canvas.pixels.items()
        saw_shadow |= any(c == GROUNDHOG_SHADOW for _, c in colours)
        lowest = max([lowest, *(y for (_, y), c in colours if c == GROUNDHOG_FUR)])
        t += ANIMATION_FRAME_INTERVAL


def test_shadow_year_startles_and_ducks_fast():
    lasted, saw_shadow, lowest = run_groundhog(SHADOW_YEAR)
    assert saw_shadow
    assert lasted == pytest.approx(GROUNDHOG.duration(True), abs=0.1)
    assert lowest < H - len(GROUNDHOG.mound), "never drawn in front of the mound"


def test_spring_year_has_no_shadow_and_stays_up_longer():
    lasted, saw_shadow, _ = run_groundhog(SPRING_YEAR)
    assert not saw_shadow
    assert lasted == pytest.approx(GROUNDHOG.duration(False), abs=0.1)
    assert GROUNDHOG.duration(False) > GROUNDHOG.duration(True)


@pytest.mark.parametrize(
    ("day", "verdict", "other"), [(SHADOW_YEAR, SUN, CLOUD), (SPRING_YEAR, CLOUD, SUN)]
)
def test_clock_shows_the_verdict(day, verdict, other):
    _, canvas = draw(HolidayOverlay(), 0.0, kind="clock", holiday=HOLIDAYS["groundhog"], day=day)
    colours = set(canvas.pixels.values())
    assert verdict in colours and other not in colours


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
