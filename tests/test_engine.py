"""The engine runs the real app on the software backend and hands back frames."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scoreboard.config import Settings
from scoreboard.display import software
from scoreboard.engine import Engine
from test_app import FakeClient

SRC = Path(__file__).resolve().parents[1] / "src" / "scoreboard"


def _engine() -> Engine:
    return Engine(Settings(), client=FakeClient([]))


def test_engine_draws_a_frame_with_no_hardware() -> None:
    engine = _engine()
    engine.start()
    frame = engine.step()
    assert frame is not None
    assert (frame.width, frame.height) == (128, 32)
    assert len(frame.pixels) == 128 * 32 * 3
    assert any(frame.pixels), "the panel should not be dark"


def test_step_reports_a_frame_only_when_one_was_shown() -> None:
    engine = _engine()
    engine.start()
    assert engine.latest_frame() is not None
    assert engine.latest_frame() is None


def test_engine_turns_the_shell_off() -> None:
    engine = _engine()
    assert engine.app.admin_server is None
    assert engine.app.horn.enabled is False


def test_software_text_matches_the_mirror_glyphs() -> None:
    graphics = software.backend().graphics
    font = graphics.Font()
    font.LoadFont(str(SRC.parent.parent / "fonts" / "5x7.bdf"))
    canvas = software.Canvas(16, 8)
    width = graphics.DrawText(canvas, font, 0, 7, graphics.Color(255, 0, 0), "A")
    assert width == font.CharacterWidth(ord("A")) > 0
    assert any(canvas.pixels)


def test_software_canvas_clips_out_of_range_pixels() -> None:
    canvas = software.Canvas(4, 4)
    canvas.SetPixel(-1, 0, 1, 1, 1)
    canvas.SetPixel(4, 4, 1, 1, 1)
    assert not any(canvas.pixels)


#: Modules that drive the board: hardware, audio, the admin and setup pages, the updater.
SHELL = {
    "app", "admin_server", "audio", "button", "light_sensor", "setup_server", "wifi_join",
    "wifi", "updater", "hostname", "network", "engine", "__main__",
}  # fmt: skip


def _imports(path: Path) -> set[str]:
    """Top-level ``scoreboard`` modules a file imports (anywhere in it), and hardware libs."""
    found: set[str] = set()
    package = path.relative_to(SRC).parts[:-1]
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                target = list(base) + (node.module.split(".") if node.module else [])
                if target:
                    found.add(target[0])
                if not node.module:
                    found.update(alias.name for alias in node.names)
            elif node.module:
                found.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
    return found


@pytest.mark.parametrize("package", ["display", "hockey", "football"])
def test_drawing_and_data_code_never_import_the_shell(package: str) -> None:
    offenders = []
    for path in sorted((SRC / package).rglob("*.py")):
        bad = _imports(path) & (SHELL | {"rgbmatrix", "gpiozero", "RGBMatrixEmulator"})
        if path.name == "matrix.py":  # the one place that picks a hardware backend, lazily
            bad -= {"rgbmatrix", "RGBMatrixEmulator"}
        if bad:
            offenders.append(f"{path.relative_to(SRC)}: {sorted(bad)}")
    assert not offenders, "\n".join(offenders)
