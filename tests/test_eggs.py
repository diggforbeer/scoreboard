"""``scoreboard --eggs`` (eggs.py): the hidden tour of the Easter eggs, and its fences."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from scoreboard import __main__ as cli
from scoreboard import eggs
from scoreboard.app import Scene, ScoreboardApp
from scoreboard.config import Settings
from scoreboard.display.matrix import Backend
from test_app import FakeClient, FakeClockSource, FakeGraphics, FakeMatrix, FakeOptions

ROOT = Path(__file__).resolve().parent.parent


def make_app(src: FakeClockSource) -> ScoreboardApp:
    return ScoreboardApp(
        Settings(),
        client=FakeClient([]),
        backend=Backend("fake", FakeMatrix, FakeOptions, FakeGraphics),
        clock=lambda: datetime(2026, 11, 17, 9, 0, tzinfo=UTC),
        monotonic=src.monotonic,
        sleep=src.sleep,
    )


def tour(names: tuple[str, ...], seconds: float):
    """Run the tour for ``seconds`` of fake time; the frames as (kind, egg playing, month)."""
    src = FakeClockSource()
    app = make_app(src)
    frames: list[tuple[str, str | None, int]] = []
    draw = app.draw_scene

    def record(scene: Scene) -> None:
        egg = app._egg_show[0] if app._egg_show else None
        frames.append((scene.kind, egg, app.clock().month))
        draw(scene)
        if src.now >= seconds:
            app._running = False

    app.draw_scene = record  # type: ignore[method-assign]
    app.run_eggs(names)
    return frames


@pytest.mark.parametrize("name", ["quote", "squirrel", "fire"])
def test_a_tree_egg_plays_between_plain_tree_frames(name):
    total = eggs.PAUSE_SECONDS * 2 + eggs.seconds(name)
    frames = tour((name,), total - 0.5)
    kinds = {kind for kind, _egg, _month in frames}
    assert kinds == {"christmas_tree"}
    assert frames[0][1] is None, "a calm moment first"
    assert frames[-1][1] is None, "and the plain tree after"
    assert any(egg == name for _kind, egg, _month in frames)
    assert {month for *_rest, month in frames} == {12}, "held in December for the countdown"


def test_the_blowout_plays_its_own_scene():
    frames = tour(("blowout",), eggs.PAUSE_SECONDS * 2 + eggs.seconds("blowout") - 0.5)
    assert {"christmas_tree", "blowout"} <= {kind for kind, _egg, _month in frames}


def test_the_tour_loops_through_every_egg_in_order():
    one_lap = sum(eggs.PAUSE_SECONDS * 2 + eggs.seconds(n) for n in eggs.NAMES)
    frames = tour(eggs.NAMES, one_lap * 1.5)
    played = []
    for _kind, egg, _month in frames:
        if egg and (not played or played[-1] != egg):
            played.append(egg)
    assert played[:3] == ["quote", "squirrel", "fire"]
    assert played.count("quote") >= 2, "it goes round again"


def test_the_real_clock_and_normal_rolls_are_restored_afterwards():
    src = FakeClockSource()
    app = make_app(src)
    real = app.clock
    app.draw_scene = lambda scene: setattr(app, "_running", False)  # type: ignore[method-assign]
    app.run_eggs(("quote",))
    assert app.clock is real
    assert app._egg_show is None and app._demo_drawing is False


def test_the_flag_parses_but_is_not_in_help(capsys):
    parser = cli.build_parser()
    assert parser.parse_args(["--eggs"]).eggs == "all"
    assert parser.parse_args(["--eggs", "fire"]).eggs == "fire"
    with pytest.raises(SystemExit):
        parser.parse_args(["--eggs", "dragon"])
    capsys.readouterr()
    assert "--eggs" not in parser.format_help()


def test_the_cli_runs_the_tour(monkeypatch):
    seen = []
    monkeypatch.setattr(cli.Settings, "load", staticmethod(lambda path=None: Settings()))
    monkeypatch.setattr(ScoreboardApp, "install_signal_handlers", lambda self: None)
    monkeypatch.setattr(ScoreboardApp, "run_eggs", lambda self, names: seen.append(names))
    monkeypatch.setattr(
        "scoreboard.display.matrix.load_backend",
        lambda name=None: Backend("fake", FakeMatrix, FakeOptions, FakeGraphics),
    )
    assert cli.main(["--eggs", "squirrel"]) == 0
    assert cli.main(["--eggs"]) == 0
    assert seen == [("squirrel",), eggs.NAMES]


def test_the_tour_is_kept_out_of_the_readme_and_the_guide():
    for path in ("README.md", "screens.md"):
        assert "--eggs" not in (ROOT / path).read_text(), path
