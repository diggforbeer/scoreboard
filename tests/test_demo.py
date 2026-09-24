"""Tests for the ``--demo`` synthetic scene sequence (#47).

The loop that plays these (``ScoreboardApp.run_demo``) is tested in
``test_app.py`` alongside ``run()``; this file covers only the data.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nhl_scoreboard.demo import DemoStep, demo_steps

NOW = datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
EVERY_KIND = {
    "connecting",
    "preview",
    "countdown",
    "game",
    "goal",
    "standings",
    "clock",
    "no_games",
    "no_data",
}


def games_of(steps: list[DemoStep]):
    return [s.scene.game for s in steps if s.scene.game is not None]


@pytest.mark.parametrize("favourite", ["NSH", "TOR", "DAL", ""])
def test_every_scene_kind_is_covered(favourite):
    steps = demo_steps(favourite, NOW)
    assert {s.scene.kind for s in steps} == EVERY_KIND


@pytest.mark.parametrize("kind", ["game", "goal", "standings"])
def test_both_logo_and_text_layouts_are_shown(kind):
    steps = [s for s in demo_steps("NSH", NOW) if s.scene.kind == kind]
    assert {s.use_logos for s in steps} == {True, False}


def test_every_game_state_and_indicator_is_covered():
    games = games_of(demo_steps("NSH", NOW))
    assert any(g.is_pregame for g in games)
    assert any(g.is_live and not g.in_intermission and g.period_type == "REG" for g in games)
    assert any(g.in_intermission for g in games)
    assert any(g.is_live and g.period_type == "OT" for g in games)
    assert any(g.is_final and g.period_type == "REG" for g in games)
    assert any(g.is_final and g.period_type == "SO" for g in games)
    situations = [g.situation for g in games if g.situation is not None]
    assert any(s.power_play_side() for s in situations)
    assert any(s.empty_net_side() and not s.power_play_side() for s in situations)


def test_upcoming_games_are_in_the_future_relative_to_now():
    steps = demo_steps("NSH", NOW)
    preview = next(s.scene.game for s in steps if s.scene.kind == "preview")
    countdown = next(s.scene.game for s in steps if s.scene.kind == "countdown")
    assert preview.seconds_until_start(NOW) > 24 * 3600
    assert 0 < countdown.seconds_until_start(NOW) < 3600


@pytest.mark.parametrize("favourite", ["NSH", "TOR", "WPG", "SJS", "dal"])
def test_favourite_plays_every_game_and_anchors_the_standings(favourite):
    fav = favourite.upper()
    steps = demo_steps(favourite, NOW)
    # The shootout final is the one deliberately neutral game: a rotation
    # of "all" shows games that don't involve the favourite too.
    involved = [g.involves(fav) for g in games_of(steps)]
    assert involved.count(False) == 1
    for step in steps:
        if step.scene.kind == "standings":
            rows = step.scene.standings
            assert len(rows) == 5
            assert fav in [r.abbrev for r in rows]
            assert [r.conference_sequence for r in rows] == sorted(
                r.conference_sequence for r in rows
            )


def test_no_favourite_still_builds_distinct_matchups_and_a_table():
    steps = demo_steps("", NOW)
    for game in games_of(steps):
        assert game.away.abbrev != game.home.abbrev
    rows = next(s.scene.standings for s in steps if s.scene.kind == "standings")
    assert [r.conference_sequence for r in rows] == [1, 2, 3, 4, 5]


def test_favourite_never_plays_itself():
    for favourite in ("DAL", "COL", "WPG"):
        for game in games_of(demo_steps(favourite, NOW)):
            assert game.away.abbrev != game.home.abbrev


def test_goal_scene_is_the_favourite_scoring():
    steps = demo_steps("NSH", NOW)
    goal = next(s.scene.game for s in steps if s.scene.kind == "goal")
    assert goal.home.abbrev == "NSH"
    assert goal.home.score > goal.away.score


# -- every step actually renders, on panel -----------------------------------


@pytest.mark.parametrize("width", [128, 64])
def test_every_step_renders_on_panel(width):
    """Draw each step through the real renderer; nothing may land off-panel."""
    from zoneinfo import ZoneInfo

    from nhl_scoreboard.display.ascii import AsciiCanvas
    from nhl_scoreboard.display.fonts import FontSet
    from nhl_scoreboard.display.renderer import Renderer

    graphics = pytest.importorskip("RGBMatrixEmulator").graphics
    r = Renderer(graphics, FontSet(graphics), width, 32, ZoneInfo("America/Chicago"))
    for step in demo_steps("NSH", NOW):
        c = AsciiCanvas(width, 32)
        scene = step.scene
        if scene.kind == "game":
            r.draw_game(c, scene.game)
        elif scene.kind == "goal":
            r.draw_goal(c, scene.game)
        elif scene.kind in ("preview", "countdown"):
            getattr(r, f"draw_{scene.kind}")(c, scene.game, NOW)
        elif scene.kind == "standings":
            r.draw_standings(c, scene.standings, "NSH")
        elif scene.kind == "clock":
            r.draw_clock(c, NOW)
        else:
            r.draw_message(c, scene.kind.upper())
        assert c.out_of_bounds == [], f"{scene.kind} drew off-panel"
        assert c.lit(), f"{scene.kind} drew nothing"
