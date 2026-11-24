"""The college demo steps (#559): drawn in the demo's own FBS directory and the college logo set."""

from __future__ import annotations

from datetime import UTC, datetime

from scoreboard.app import Scene
from scoreboard.demo import DemoStep
from scoreboard.football import teams as nfl
from scoreboard.football.college_demo import _POLL, DEMO_DIRECTORY, college_demo_steps
from scoreboard.football.demo import football_demo_steps
from test_app import (
    TICKS_PER_SCENE,
    demo_app,
    run_demo_for_frames,
    stub_renderer,
)
from test_app import fake_backend as fake_backend  # fixtures, re-exported
from test_app import games as games

NOW = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)


def test_the_steps_are_college_ones_with_unique_college_names():
    steps = college_demo_steps(NOW)
    assert steps and all(s.college for s in steps)
    names = [s.name for s in steps]
    assert len(names) == len(set(names)) and all(n.startswith("cfb_") for n in names)


def test_the_football_demo_ends_with_them_and_the_nfl_steps_are_not_college():
    steps = football_demo_steps(NOW)
    tail = steps[-len(college_demo_steps(NOW)) :]
    assert [s.name for s in tail] == [s.name for s in college_demo_steps(NOW)]
    assert not any(s.college for s in steps[: -len(tail)])


def test_the_directory_is_the_fbs_one_and_holds_every_team_the_demo_names():
    assert DEMO_DIRECTORY.league == "college-football"
    for abbrev, *_ in _POLL:
        assert DEMO_DIRECTORY.by_abbrev.get(abbrev), abbrev
    for step in college_demo_steps(NOW):
        game = step.scene.fb_game
        if game is not None:
            assert DEMO_DIRECTORY.by_abbrev.get(game.away.abbrev), step.name
            assert DEMO_DIRECTORY.by_abbrev.get(game.home.abbrev), step.name


def test_a_college_step_is_drawn_with_the_college_logos_in_the_demo_directory(fake_backend, games):
    app, _ = demo_app(fake_backend, games)
    nfl_set, college_set = object(), object()
    app.renderer.football_logos = nfl_set
    app.renderer.college_logos = college_set
    seen = {}

    def spy(scene):
        seen["logos"] = app.renderer.football_logos
        seen["directory"] = nfl.active_directory()

    app._draw_scene = spy
    app._demo_college = True
    app.draw_scene(Scene("fb_scores"))
    assert seen["logos"] is college_set and seen["directory"] is DEMO_DIRECTORY
    assert app.renderer.football_logos is nfl_set and nfl.active_directory() is nfl.NFL_DIRECTORY
    app._demo_college = False
    app.draw_scene(Scene("fb_scores"))
    assert seen["logos"] is nfl_set and seen["directory"] is nfl.NFL_DIRECTORY


def test_the_demo_loop_marks_each_step_college_or_not(fake_backend, games, monkeypatch):
    plain = DemoStep(Scene("fb_no_games"), name="plain")
    college = DemoStep(Scene("fb_no_games"), name="college", college=True)
    monkeypatch.setattr(
        "scoreboard.football.demo.football_demo_steps", lambda now: [plain, college, plain]
    )
    app, src = demo_app(fake_backend, games)
    app._sport = "football"
    stub_renderer(app)
    flags = []
    app._draw_scene = lambda scene: flags.append(app._demo_college)
    run_demo_for_frames(app, src, 3 * TICKS_PER_SCENE)
    assert flags[:3] == [False, True, False]
