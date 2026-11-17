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
    """Run the tour for ``seconds`` of fake time; the frames drawn, as dicts."""
    src = FakeClockSource()
    app = make_app(src)
    frames: list[dict] = []
    draw = app.draw_scene

    def record(scene: Scene) -> None:
        frames.append(
            {
                "kind": scene.kind,
                "egg": app._egg_show[0] if app._egg_show else None,
                "month": app.clock().month,
                "prank": app.april_fools_active(),
                "home": scene.game.home.abbrev if scene.game else None,
            }
        )
        draw(scene)
        if src.now >= seconds:
            app._running = False

    app.draw_scene = record  # type: ignore[method-assign]
    app.run_eggs(names)
    return frames


def total(name: str) -> float:
    return sum(p.seconds for p in eggs.plan(name))


@pytest.mark.parametrize("name", ["quote", "squirrel", "fire"])
def test_a_tree_egg_plays_between_plain_tree_frames(name):
    frames = tour((name,), total(name) - 0.5)
    assert {f["kind"] for f in frames} == {"christmas_tree"}
    assert frames[0]["egg"] is None, "a calm moment first"
    assert frames[-1]["egg"] is None, "and the plain tree after"
    assert any(f["egg"] == name for f in frames)
    assert {f["month"] for f in frames} == {12}, "held in December for the countdown"


def test_the_blowout_plays_its_own_scene():
    frames = tour(("blowout",), total("blowout") - 0.5)
    assert {"christmas_tree", "blowout"} <= {f["kind"] for f in frames}


def test_april_fools_shows_the_plain_screens_then_the_admirals():
    frames = tour(("april_fools",), total("april_fools") - 0.5)
    assert frames[0]["prank"] is False and frames[-1]["prank"] is False
    assert any(f["prank"] for f in frames)
    assert {"game", "standings"} <= {f["kind"] for f in frames if f["prank"]}
    assert not any(f["prank"] for f in tour(("quote",), total("quote") - 0.5))


def test_the_tour_loops_through_every_egg_in_order():
    one_lap = sum(total(n) for n in eggs.NAMES)
    frames = tour(eggs.NAMES, one_lap * 1.5)
    played = []
    for f in frames:
        egg = f["egg"] or ("blowout" if f["kind"] == "blowout" else None)
        egg = egg or ("april_fools" if f["prank"] else None)
        if egg and (not played or played[-1] != egg):
            played.append(egg)
    assert played[:5] == ["quote", "squirrel", "fire", "blowout", "april_fools"]
    assert played.count("quote") >= 2, "it goes round again"


def test_the_real_clock_and_normal_rolls_are_restored_afterwards():
    src = FakeClockSource()
    app = make_app(src)
    real = app.clock
    app.draw_scene = lambda scene: setattr(app, "_running", False)  # type: ignore[method-assign]
    app.run_eggs(("april_fools",))
    assert app.clock is real
    assert app._egg_show is None and app._demo_drawing is False
    assert "april_fools_active" not in vars(app), "the forced prank is cleared"


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
