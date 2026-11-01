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
    BUNNY,
    CANADA_FIREWORKS,
    CLOUD,
    COIN_GOLD,
    CONFETTI,
    FIREWORKS,
    FLAG_BLUE,
    FLAG_RED,
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
    LEPRECHAUN,
    LEPRECHAUN_FRAMES,
    NO_OVERLAY_SCENES,
    PRESENT_COLOURS,
    PUMPKIN,
    SANTA,
    SMALL_PRESENT,
    SNOW,
    SNOW_BAND,
    SUN,
    TURKEY,
    US_FIREWORKS,
    HolidayOverlay,
    active_holiday,
    christmas_countdown,
    easter_sunday,
    egg_teams,
)
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.display.teams import TEAM_COLORS, team_color, team_secondary_color
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
        (date(2026, 11, 1), "thanksgiving"),
    ],
)
def test_halloween_window_is_all_of_october(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 10, 31), None),
        (date(2026, 11, 1), "thanksgiving"),
        (date(2026, 11, 26), "thanksgiving"),
        (date(2026, 11, 27), None),
        (date(2026, 12, 1), None),
        (date(2025, 11, 27), "thanksgiving"),
    ],
)
def test_us_thanksgiving_runs_from_november_first_to_the_day(day, expected):
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


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2027, 3, 13), None),
        (date(2027, 3, 14), "st_patricks"),
        (date(2027, 3, 17), "st_patricks"),
        (date(2027, 3, 18), "easter"),
    ],
)
def test_st_patricks_is_the_days_up_to_the_seventeenth(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2027, date(2027, 3, 28)),
        (2038, date(2038, 4, 25)),  # the latest Easter can fall
        (2285, date(2285, 3, 22)),  # the earliest
    ],
)
def test_easter_sunday(year, expected):
    assert easter_sunday(year) == expected


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        # 2027: Easter is Mar 28, so the 14 days start Mar 15 (St. Patrick's
        # holds Mar 14-17 itself, see below).
        (date(2027, 3, 13), None),
        (date(2027, 3, 18), "easter"),
        (date(2027, 3, 28), "easter"),
        (date(2027, 3, 29), None),
        # 2025: Easter is Apr 20, so the window starts Apr 7.
        (date(2025, 4, 6), None),
        (date(2025, 4, 7), "easter"),
        (date(2025, 4, 20), "easter"),
        (date(2025, 4, 21), None),
    ],
)
def test_easter_is_the_fortnight_up_to_easter_sunday(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


def test_st_patricks_wins_the_overlap_with_easter_fortnight():
    # 2008: Easter Sunday was Mar 23, so its window began on Mar 10.
    assert active_holiday(HOLIDAY_NAMES, date(2008, 3, 13)).name == "easter"
    assert active_holiday(HOLIDAY_NAMES, date(2008, 3, 14)).name == "st_patricks"
    assert active_holiday(HOLIDAY_NAMES, date(2008, 3, 17)).name == "st_patricks"
    assert active_holiday(HOLIDAY_NAMES, date(2008, 3, 18)).name == "easter"


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2027, 6, 30), None),
        (date(2027, 7, 1), "canada_day"),
        (date(2027, 7, 2), None),
        (date(2027, 7, 4), "july_4th"),
        (date(2027, 7, 5), None),
    ],
)
def test_canada_day_and_july_4th(day, expected):
    found = active_holiday(HOLIDAY_NAMES, day)
    assert (found.name if found else None) == expected


def test_canada_day_is_opt_in_like_canadian_thanksgiving():
    assert "canada_day" not in Settings().holiday.themes
    assert active_holiday(Settings().holiday.themes, date(2027, 7, 1)) is None


def test_flag_fireworks_reuse_the_new_year_show_in_flag_colours():
    for show in (US_FIREWORKS, CANADA_FIREWORKS):
        assert [r.x for r in show.rockets] == [r.x for r in FIREWORKS.rockets]
        assert show.duration == FIREWORKS.duration
    us = {r.colour for r in US_FIREWORKS.rockets}
    ca = {r.colour for r in CANADA_FIREWORKS.rockets}
    assert FLAG_RED in us and any(c[2] > 200 and c[0] < 100 for c in us), "red, white and blue"
    assert ca == {FLAG_RED, (255, 255, 255)}, "red and white"


@pytest.mark.parametrize("name", ["july_4th", "canada_day"])
def test_a_flag_flies_either_side_of_the_clock(name):
    _, canvas = draw(HolidayOverlay(), 0.0, kind="clock", holiday=HOLIDAYS[name])
    reds = [x for (x, _), c in canvas.pixels.items() if c == FLAG_RED]
    assert min(reds) < 25 and max(reds) > W - 25
    blue = FLAG_BLUE in canvas.pixels.values()
    assert blue is (name == "july_4th"), "only the US flag has a blue canton"


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
        "st_patricks",
        "easter",
        "july_4th",
    ]
    assert "thanksgiving_ca" in HOLIDAY_NAMES, "known, just not ticked unasked"


def test_unknown_theme_warns_and_is_dropped(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = HolidayConfig(themes=["Halloween", "arbor_day", "halloween"])
    assert cfg.themes == ["halloween"]
    assert "arbor_day" in caplog.text


def test_a_bare_string_theme_is_treated_as_a_one_item_list():
    assert HolidayConfig(themes="halloween").themes == ["halloween"]


def test_flyby_frequency_defaults_to_occasional():
    assert HolidayConfig().flyby_frequency == "occasional"
    assert HolidayConfig().flyby_gap_minutes == (10.0, 30.0)


@pytest.mark.parametrize(
    ("frequency", "gap"),
    [("rare", (30.0, 90.0)), ("occasional", (10.0, 30.0)), ("frequent", (5.0, 15.0))],
)
def test_each_flyby_frequency_is_half_to_one_and_a_half_times_its_average(frequency, gap):
    cfg = HolidayConfig(flyby_frequency=frequency)
    assert cfg.flyby_gap_minutes == gap
    low, high = gap
    assert high == 3 * low


def test_unknown_flyby_frequency_warns_and_falls_back(caplog):
    with caplog.at_level(logging.WARNING):
        cfg = HolidayConfig(flyby_frequency="constantly")
    assert cfg.flyby_frequency == "occasional"
    assert "constantly" in caplog.text


def test_flyby_frequency_is_case_insensitive():
    assert HolidayConfig(flyby_frequency=" Rare ").flyby_frequency == "rare"


def test_parsed_from_toml_section():
    settings = Settings.from_dict(
        {"holiday": {"enabled": True, "themes": ["halloween"], "flyby_frequency": "rare"}}
    )
    assert settings.holiday.enabled
    assert settings.holiday.flyby_frequency == "rare"


def test_old_flyby_minute_keys_are_ignored_and_logged_once(caplog, monkeypatch):
    """Retired, not typos (#277): one INFO line per process, never a warning."""
    from nhl_scoreboard import config

    monkeypatch.setattr(config, "_retired_logged", set())
    raw = {"holiday": {"flyby_min_minutes": 5, "flyby_max_minutes": 20}}
    with caplog.at_level(logging.INFO, logger="nhl_scoreboard.config"):
        settings = Settings.from_dict(raw)
        Settings.from_dict(raw)
    assert settings.holiday.flyby_frequency == "occasional"
    retired = [r for r in caplog.records if "retired config key" in r.getMessage()]
    assert sorted(r.args[0] for r in retired) == ["flyby_max_minutes", "flyby_min_minutes"]
    assert all(r.levelno == logging.INFO for r in retired)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_holiday_save_drops_the_old_flyby_minute_keys(tmp_path):
    path = tmp_path / "scoreboard.toml"
    path.write_text(
        "[holiday]\n"
        "enabled = true\n"
        "flyby_min_minutes = 5\n"
        "flyby_max_minutes = 20\n"
        "\n"
        "[scoreboard]\n"
        'favourite_team = "TOR"\n'
    )
    Settings.load(path).save({"holiday": {"flyby_frequency": "rare"}})
    text = path.read_text()
    assert "flyby_min_minutes" not in text
    assert "flyby_max_minutes" not in text
    reloaded = Settings.load(path)
    assert reloaded.holiday.enabled
    assert reloaded.holiday.flyby_frequency == "rare"
    assert reloaded.scoreboard.favourite_team == "TOR"


def test_saving_another_section_leaves_retired_holiday_keys_alone(tmp_path):
    """Only the section being saved is cleaned; nothing else is touched."""
    path = tmp_path / "scoreboard.toml"
    path.write_text("[holiday]\nflyby_min_minutes = 5\n")
    Settings.load(path).save({"scoreboard": {"favourite_team": "TOR"}})
    assert "flyby_min_minutes = 5" in path.read_text()


def test_a_typo_still_warns_every_time(caplog):
    with caplog.at_level(logging.WARNING):
        Settings.from_dict({"holiday": {"flyby_frequncy": "rare"}})
        Settings.from_dict({"holiday": {"flyby_frequncy": "rare"}})
    assert caplog.text.count("Ignoring unknown config key 'flyby_frequncy'") == 2


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


def test_leprechaun_is_outlined_against_green_logos():
    """No green pixel of the walker touches the background directly."""
    for rows in LEPRECHAUN.frames:
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in "GHC":
                    neighbours = [
                        rows[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    ]
                    assert "." not in neighbours, f"{ch} at {x},{y} touches the background"
    assert len(LEPRECHAUN.frames[0]) == len(LEPRECHAUN_FRAMES[0]) + 2


def test_leprechaun_collects_a_row_of_gold_coins_with_a_sparkle():
    """Reverse of Santa: the coins start on the ground and only disappear.

    Counted on the ground alone -- with him drawn over them, his alternating
    legs cover a coin he's standing near by a pixel more or less per frame.
    """
    counts = []
    for travelled in range(0, W + LEPRECHAUN.width + 1):
        canvas = AsciiCanvas(W, H)
        LEPRECHAUN._draw_drops(canvas, travelled, W, H, sparkles=False)
        counts.append(list(canvas.pixels.values()).count(COIN_GOLD))
    assert counts[0] > 0, "a row of coins waiting from the start"
    assert counts == sorted(counts, reverse=True), "coins only ever get picked up"
    assert counts[-1] == 0, "he collects every one"

    # A sparkle right after the first pickup, gone shortly after.
    first = LEPRECHAUN.drop_spacing
    for travelled, expected in ((first, True), (first + 2, True), (first + 10, False)):
        canvas = AsciiCanvas(W, H)
        LEPRECHAUN._draw_drops(canvas, travelled, W, H, sparkles=True)
        assert bool(canvas.pixels) is expected, f"sparkle at travelled={travelled}"

    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    t = 0.0
    while True:
        moving, canvas = draw(overlay, t, holiday=HOLIDAYS["st_patricks"])
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        t += ANIMATION_FRAME_INTERVAL


def test_bunny_hops_along_the_bottom_and_is_outlined_in_black():
    for rows in BUNNY.frames:
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch in "WPT":
                    neighbours = [
                        rows[y + dy][x + dx] for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    ]
                    assert "." not in neighbours, f"{ch} at {x},{y} touches the background"
    assert dict(BUNNY.palette)["o"] == (0, 0, 0), "an unlit LED, not a colour"

    overlay = HolidayOverlay()
    overlay.start_flyby(0.0)
    t, tops = 0.0, set()
    while True:
        moving, canvas = draw(overlay, t, holiday=HOLIDAYS["easter"])
        assert canvas.out_of_bounds == [], f"off-panel write at t={t}"
        if not moving:
            break
        x = W - round(t * BUNNY.speed)
        if 0 <= x <= W - BUNNY.width:  # whole bunny on-panel, not half-entered
            tops.add(min(y for _, y in canvas.pixels))
        t += ANIMATION_FRAME_INTERVAL
    ground = H - BUNNY.height + 1  # its top row when standing (the outline is unlit)
    assert max(tops) == ground, "lands on the ground"
    assert ground - min(tops) >= 4, "and actually leaves it, by a visible amount"


def test_easter_basket_is_the_favourite_plus_three_teams_that_change_daily():
    days = [date(2027, 3, d) for d in range(22, 29)]
    baskets = [egg_teams("NSH", d) for d in days]
    for basket in baskets:
        assert basket[0] == "NSH", "the favourite's egg comes first"
        assert len(set(basket)) == 4 and "NSH" not in basket[1:]
        assert all(team in TEAM_COLORS for team in basket)
    assert len({b[1:] for b in baskets}) > 1, "a different trio on different days"
    assert egg_teams("NSH", days[0]) == egg_teams("NSH", days[0]), "steady within a day"
    assert len(set(egg_teams("", days[0]))) == 4, "no favourite: four teams, no repeats"


def test_eggs_are_drawn_in_team_colours_either_side_of_the_clock():
    day = date(2027, 3, 27)
    overlay = HolidayOverlay()
    canvas = AsciiCanvas(W, H)
    overlay.draw(
        canvas,
        scene_kind="clock",
        holiday=HOLIDAYS["easter"],
        now=0.0,
        width=W,
        height=H,
        min_gap_seconds=600,
        max_gap_seconds=600,
        day=day,
        favourite="NSH",
    )
    nsh = [x for (x, _), c in canvas.pixels.items() if c == team_color("NSH")]
    assert nsh and max(nsh) < 20, "the Preds egg, gold, on the far left"
    assert team_secondary_color("NSH") in canvas.pixels.values(), "with its blue pattern"
    others = egg_teams("NSH", day)[1:]
    right = {c for (x, _), c in canvas.pixels.items() if x > W - 20}
    assert {team_color(t) for t in others[1:]} <= right


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
    now["t"] = datetime(2026, 12, 28, 18, 0, tzinfo=UTC)
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


@pytest.mark.parametrize(
    ("frequency", "gap_seconds"),
    [("rare", (1800, 5400)), ("occasional", (600, 1800)), ("frequent", (300, 900))],
)
def test_overlay_gets_the_chosen_frequencys_gap(holiday_app, frequency, gap_seconds):
    app, _src, _now = holiday_app
    app.renderer.draw_message = lambda *a: None
    app.settings.holiday.flyby_frequency = frequency
    seen = {}
    real_draw = app.holiday_overlay.draw

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real_draw(*args, **kwargs)

    app.holiday_overlay.draw = spy
    app.draw_scene(Scene("no_games"))
    assert (seen["min_gap_seconds"], seen["max_gap_seconds"]) == gap_seconds


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


# -- the Christmas tree screen (#243) ---------------------------------------------


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 11, 30), None),
        (date(2026, 12, 1), ("24 DAYS", "TO CHRISTMAS")),
        (date(2026, 12, 13), ("12 DAYS", "TO CHRISTMAS")),
        (date(2026, 12, 24), ("1 DAY", "TO CHRISTMAS")),
        (date(2026, 12, 25), ("MERRY", "CHRISTMAS")),
        (date(2026, 12, 26), None),
    ],
)
def test_christmas_countdown(day, expected):
    assert christmas_countdown(day) == expected


def test_holiday_rotation_screen_is_the_tree_only_in_its_season(holiday_app):
    app, _src, now = holiday_app
    assert app._rotation_screen_scene("holiday", None, None) is None, "October: skipped"
    now["t"] = datetime(2026, 12, 13, 18, 0, tzinfo=UTC)
    assert app._rotation_screen_scene("holiday", None, None) == Scene("christmas_tree")
    now["t"] = datetime(2026, 12, 26, 18, 0, tzinfo=UTC)
    assert app._rotation_screen_scene("holiday", None, None) is None, "Boxing Day: skipped"


@pytest.mark.parametrize(
    "switch_off",
    [
        lambda cfg: setattr(cfg, "enabled", False),
        lambda cfg: setattr(cfg, "themes", ["halloween"]),
    ],
    ids=["holiday-cheer-off", "christmas-unticked"],
)
def test_holiday_rotation_screen_follows_the_holiday_cheer_switches(holiday_app, switch_off):
    app, _src, now = holiday_app
    now["t"] = datetime(2026, 12, 13, 18, 0, tzinfo=UTC)
    switch_off(app.settings.holiday)
    assert app._rotation_screen_scene("holiday", None, None) is None


def test_holiday_is_an_opt_in_rotation_screen():
    from nhl_scoreboard.config import VALID_ROTATION_SCREENS

    settings = Settings.from_dict({"rotation": [{"screen": "holiday", "seconds": 10}]})
    assert [e.screen for e in settings.rotation] == ["holiday"]
    assert "holiday" in VALID_ROTATION_SCREENS
