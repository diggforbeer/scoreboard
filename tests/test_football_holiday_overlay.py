"""The holiday overlay in NFL mode (#430): only Thanksgiving and Christmas games, NFL colours."""

from __future__ import annotations

from datetime import UTC, date
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard.app import NFL_GAME_SCENES, Scene
from nhl_scoreboard.display import holiday
from nhl_scoreboard.display.holiday import HOLIDAYS, egg_teams, use_sport
from nhl_scoreboard.display.teams import TEAM_COLORS
from nhl_scoreboard.football import teams as nfl_teams
from nhl_scoreboard.football.idle_views import PreviewView, game_holiday, is_thanksgiving
from test_football_idle_preview import utc
from test_football_scenes import _pixels, app, game  # noqa: F401  (the real-app fixture)

CHICAGO = ZoneInfo("America/Chicago")


# -- the date rules, pure -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (utc(2026, 11, 26, 18), "thanksgiving"),
        (utc(2025, 11, 27, 18), "thanksgiving"),
        (utc(2024, 11, 28, 18), "thanksgiving"),
        (utc(2028, 11, 23, 18), "thanksgiving"),  # a leap year
        (utc(2028, 12, 25, 18), "christmas"),  # a leap year's Christmas
        (utc(2026, 12, 25, 18), "christmas"),
        (utc(2026, 11, 25, 18), None),  # the day before
        (utc(2026, 11, 27, 18), None),  # the day after (Black Friday)
        (utc(2026, 11, 19, 18), None),  # a Thursday that is not the 4th
        (utc(2026, 12, 24, 18), None),
        (utc(2026, 12, 26, 18), None),
        (utc(2026, 10, 31, 18), None),  # Halloween: not a game-screen holiday
        (None, None),
    ],
)
def test_game_holiday_by_the_boards_own_date(start, expected):
    assert game_holiday(start, CHICAGO) == expected


def test_the_boards_zone_decides_the_day():
    late = utc(2026, 11, 27, 3, 0)  # 9 PM on Thanksgiving in Chicago, already Friday in UTC
    assert game_holiday(late, CHICAGO) == "thanksgiving"
    assert game_holiday(late, UTC) is None
    early = utc(2026, 11, 27, 7, 0)  # 1 AM Friday in Chicago
    assert game_holiday(early, CHICAGO) is None
    assert is_thanksgiving(date(2026, 11, 26)) and not is_thanksgiving(date(2026, 11, 19))


# -- NFL colours --------------------------------------------------------------------------------


def test_the_overlay_takes_nfl_colours_in_nfl_mode_and_nhl_colours_otherwise():
    with use_sport("nfl"):
        assert holiday.team_color("KC") == nfl_teams.team_color("KC")
        assert holiday.team_secondary_color("KC") == nfl_teams.team_secondary_color("KC")
        assert set(holiday.team_codes()) == set(nfl_teams.TEAMS)
    assert holiday.team_color("NSH") == holiday.nhl_team_color("NSH")  # back to the NHL table
    assert set(holiday.team_codes()) == set(TEAM_COLORS)


def test_the_easter_basket_picks_only_teams_of_the_sport_in_use():
    with use_sport("nfl"):
        picks = egg_teams("NYG", date(2027, 3, 28))
    assert picks[0] == "NYG" and set(picks) <= set(nfl_teams.TEAMS)
    nhl = egg_teams("NSH", date(2027, 3, 28))
    assert set(nhl) <= set(TEAM_COLORS)


def test_the_sport_resets_even_when_drawing_raises():
    with pytest.raises(RuntimeError), use_sport("nfl"):
        raise RuntimeError
    assert holiday.team_color("NSH") == holiday.nhl_team_color("NSH")


# -- the app: which scenes get a holiday ----------------------------------------------------------


def nfl_game(day_utc, state="pre"):
    return game("DAL", "NYG", state, 0, 0, short="x", start=day_utc.strftime("%Y-%m-%dT%H:%MZ"))


def with_holiday(app, themes=("thanksgiving", "christmas", "halloween"), enabled=True):  # noqa: F811
    app.settings.holiday.enabled = enabled
    app.settings.holiday.themes = list(themes)
    app.select_scene()
    return app


def test_a_thanksgiving_game_screen_gets_the_thanksgiving_holiday_whatever_today_is(app):  # noqa: F811
    with_holiday(app)  # the app's own date is 2026-11-15
    g = nfl_game(utc(2026, 11, 26, 18))
    for kind in sorted(NFL_GAME_SCENES - {"fb_preview"}):
        scene = Scene(kind, fb_game=g)
        assert app._nfl_game_holiday(scene, None) is HOLIDAYS["thanksgiving"], kind
    preview = Scene("fb_preview", fb_idle=PreviewView("DAL", "NYG", g.start_utc, "", "WEEK 12"))
    assert app._nfl_game_holiday(preview, None) is HOLIDAYS["thanksgiving"]


def test_christmas_day_game(app):  # noqa: F811
    with_holiday(app)
    scene = Scene("fb_scores", fb_game=nfl_game(utc(2026, 12, 25, 18)))
    assert app._nfl_game_holiday(scene, None) is HOLIDAYS["christmas"]


def test_an_ordinary_game_gets_nothing_even_inside_a_holiday_window(app):  # noqa: F811
    with_holiday(app)
    october = Scene("fb_field", fb_game=nfl_game(utc(2026, 10, 25, 18)))  # Halloween season
    assert app._nfl_game_holiday(october, HOLIDAYS["halloween"]) is None
    dec = Scene("fb_scores", fb_game=nfl_game(utc(2026, 12, 13, 18)))  # inside Christmas's window
    assert app._nfl_game_holiday(dec, HOLIDAYS["christmas"]) is None
    day_after = Scene("fb_scores", fb_game=nfl_game(utc(2026, 11, 27, 18)))
    assert app._nfl_game_holiday(day_after, HOLIDAYS["thanksgiving"]) is None


def test_the_setting_off_or_the_theme_unticked_means_no_decoration(app):  # noqa: F811
    scene = Scene("fb_scores", fb_game=nfl_game(utc(2026, 11, 26, 18)))
    with_holiday(app, enabled=False)
    assert app._nfl_game_holiday(scene, None) is None
    with_holiday(app, themes=("christmas",))
    assert app._nfl_game_holiday(scene, None) is None  # Thanksgiving is not ticked
    with_holiday(app, themes=())
    assert app._nfl_game_holiday(scene, None) is None


def test_scenes_that_are_not_a_game_keep_the_seasons_holiday(app):  # noqa: F811
    with_holiday(app)
    season = HOLIDAYS["halloween"]
    for kind in ("clock", "fb_standings", "fb_week", "fb_schedule", "fb_bye", "fb_no_games"):
        assert app._nfl_game_holiday(Scene(kind), season) is season, kind


def test_a_game_scene_with_no_game_or_no_start_time_gets_nothing(app):  # noqa: F811
    with_holiday(app)
    assert app._nfl_game_holiday(Scene("fb_final"), HOLIDAYS["halloween"]) is None
    odd = Scene("fb_preview", fb_idle=object())
    assert app._nfl_game_holiday(odd, HOLIDAYS["halloween"]) is None


# -- drawn over the real screens ------------------------------------------------------------------


def drawn(app, scene, *, holidays, flyby=True):  # noqa: F811
    """``scene``'s pixels with the holiday setting on or off and a fly-by crossing (or not)."""
    app.settings.holiday.enabled = holidays
    app.holiday_overlay.reset()
    if flyby:
        app.holiday_overlay.start_flyby(app.monotonic() - 4.0)  # mid-crossing
    return _pixels(app, scene)


def test_a_thanksgiving_preview_is_decorated_and_an_ordinary_one_is_not(app):  # noqa: F811
    with_holiday(app)
    turkey = Scene(
        "fb_preview", fb_idle=PreviewView("DET", "NYG", utc(2026, 11, 26, 17, 30), "", "WEEK 12")
    )
    ordinary = Scene(
        "fb_preview", fb_idle=PreviewView("DET", "NYG", utc(2026, 11, 22, 18), "", "WEEK 11")
    )
    assert drawn(app, turkey, holidays=True) != drawn(app, turkey, holidays=False)
    assert drawn(app, ordinary, holidays=True) == drawn(app, ordinary, holidays=False)


def test_each_game_screen_kind_is_decorated_on_a_thanksgiving_game_and_stays_inside_the_panel(
    app,  # noqa: F811
):
    with_holiday(app)
    g = nfl_game(utc(2026, 11, 26, 18))
    for kind in ("fb_scores", "fb_countdown"):
        scene = Scene(kind, fb_game=g)
        assert drawn(app, scene, holidays=True) != drawn(app, scene, holidays=False), kind
        assert not app.matrix.shown.out_of_bounds, kind


def test_a_christmas_game_is_decorated(app):  # noqa: F811
    with_holiday(app)
    scene = Scene("fb_scores", fb_game=nfl_game(utc(2026, 12, 25, 18)))
    assert drawn(app, scene, holidays=True) != drawn(app, scene, holidays=False)
    assert not app.matrix.shown.out_of_bounds


def test_the_same_game_a_day_later_is_not(app):  # noqa: F811
    with_holiday(app)
    scene = Scene("fb_scores", fb_game=nfl_game(utc(2026, 12, 26, 18)))
    assert drawn(app, scene, holidays=True) == drawn(app, scene, holidays=False)


def test_nhl_mode_colours_are_untouched():
    assert holiday.team_color("NSH") == holiday.nhl_team_color("NSH")
    assert holiday.team_secondary_color("NSH") == holiday.nhl_team_secondary_color("NSH")


def test_snapshots_of_each_overlay_over_an_nfl_screen(app, update_snapshots):  # noqa: F811
    from nhl_scoreboard.display.ascii import AsciiCanvas
    from test_football_scenes import check_snapshot

    with_holiday(app)
    cases = {
        "fb_holiday_thanksgiving_preview": Scene(
            "fb_preview",
            fb_idle=PreviewView("DET", "NYG", utc(2026, 11, 26, 17, 30), "THANKSGIVING", "WEEK 12"),
        ),
        "fb_holiday_christmas_scores": Scene("fb_scores", fb_game=nfl_game(utc(2026, 12, 25, 18))),
    }
    for name, scene in cases.items():
        pixels = drawn(app, scene, holidays=True)
        art = AsciiCanvas(128, 32, pixels=dict(pixels)).render()
        check_snapshot(name, art, update_snapshots)
