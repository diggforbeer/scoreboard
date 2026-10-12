"""The admin page's live view (#268): the mirror must be the panel, exactly."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from nhl_scoreboard.app import DEMO_SCENE_SECONDS, ScoreboardApp
from nhl_scoreboard.config import Settings
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.display.mirror import (
    Mirror,
    MirrorCanvas,
    MirrorGraphics,
    _line,
    parse_bdf,
)
from nhl_scoreboard.display.teams import TEAM_COLORS, team_color
from test_app import FakeClient, FakeOptions

emulator = pytest.importorskip("RGBMatrixEmulator")

W, H = 128, 32
FONTS = Path(__file__).resolve().parents[1] / "fonts"


class AsciiMatrix:
    """Two AsciiCanvases swapped like the real driver's double buffer, so a
    test sees what the panel would show after each swap."""

    def __init__(self, options=None) -> None:
        self.canvases = [AsciiCanvas(W, H), AsciiCanvas(W, H)]
        self.shown: AsciiCanvas | None = None

    def CreateFrameCanvas(self):  # noqa: N802
        return self.canvases[0]

    def SwapOnVSync(self, canvas):  # noqa: N802
        assert isinstance(canvas, AsciiCanvas), "the driver must get its own canvas"
        self.shown = canvas
        return self.canvases[1] if canvas is self.canvases[0] else self.canvases[0]


@pytest.fixture
def app(tmp_path) -> ScoreboardApp:
    backend = Backend(
        name="ascii",
        RGBMatrix=AsciiMatrix,
        RGBMatrixOptions=FakeOptions,
        graphics=emulator.graphics,
    )
    now = [1000.0]
    settings = Settings()
    settings.status.enabled = False
    app = ScoreboardApp(
        settings,
        client=FakeClient([]),
        backend=backend,
        clock=lambda: datetime(2026, 12, 20, 19, 30, tzinfo=UTC),
        monotonic=lambda: now[0],
        ap_setup_state_path=tmp_path / "no-ap",
        hw_mapping_trial_path=tmp_path / "no-trial",
    )
    app.now = now  # type: ignore[attr-defined]
    return app


def as_pixels(frame_pixels: bytes) -> dict[tuple[int, int], tuple[int, int, int]]:
    out = {}
    for i in range(0, len(frame_pixels), 3):
        rgb = tuple(frame_pixels[i : i + 3])
        if any(rgb):
            out[((i // 3) % W, (i // 3) // W)] = rgb
    return out


def test_every_demo_scene_mirrors_pixel_for_pixel(app, tmp_path):
    """The acceptance test: every scene the board can show (the demo walks
    them all, both layouts, holidays included), recorded by the mirror and
    by the panel's canvas, must be the same pixels in the same colours."""
    from PIL import Image, ImageDraw

    for abbrev in TEAM_COLORS:
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((2, 2, 29, 29), fill=(*team_color(abbrev), 255))
        im.save(tmp_path / f"{abbrev}.png")
    app.renderer.logos = LogoLibrary([tmp_path])
    app.mirror.active = True
    app.swap_canvas()
    app.set_demo_mode(True)

    compared = 0
    for _ in range(80):
        app.draw()
        frame = app.mirror.latest()
        shown = app.matrix.shown
        assert frame is not None and shown is not None
        assert as_pixels(frame.pixels) == shown.pixels, f"frame {frame.seq} differs"
        compared += bool(shown.pixels)
        app.now[0] += DEMO_SCENE_SECONDS / 2
    assert compared > 40


def test_nothing_is_recorded_until_someone_watches(app):
    app.draw()
    assert not isinstance(app.canvas, MirrorCanvas)
    assert app.mirror.latest() is None

    app.mirror.active = True
    app.swap_canvas()  # the next canvas is wrapped; nothing drawn yet to publish
    assert isinstance(app.canvas, MirrorCanvas)
    assert app.mirror.latest() is None
    app.draw()
    assert app.mirror.latest() is not None

    app.mirror.active = False
    app.draw()
    assert not isinstance(app.canvas, MirrorCanvas)
    assert app.mirror.latest() is None, "a stale frame must not greet the next viewer"


def test_frame_carries_the_applied_brightness(app):
    app._applied_brightness = 37
    app.mirror.active = True
    app.swap_canvas()
    app.draw()
    assert app.mirror.latest().brightness == 37


def test_night_mode_blanking_mirrors_as_black(app):
    app.settings.night_mode.enabled = True
    app.settings.night_mode.dim_brightness = 0
    app._night_mode_active = lambda: True
    app.mirror.active = True
    app.swap_canvas()
    app.draw()
    frame = app.mirror.latest()
    assert frame is not None and not any(frame.pixels)


def test_mirror_graphics_leaves_unwrapped_canvases_to_the_backend():
    graphics = MirrorGraphics(emulator.graphics)
    font = graphics.Font()
    font.LoadFont(str(FONTS / "5x7.bdf"))
    canvas = AsciiCanvas(W, H)
    width = graphics.DrawText(canvas, font, 2, 10, graphics.Color(255, 0, 0), "NSH")
    assert width == 15
    assert canvas.pixels
    assert font._glyphs is None, "fonts are only parsed once someone watches"


def test_parse_bdf_places_glyphs_like_the_driver():
    glyphs = parse_bdf(FONTS / "7x13B.bdf")
    g = glyphs[ord("g")]  # a descender: BBX y offset below the baseline
    assert g.y_offset < 0
    assert g.advance == 7
    assert 0xFFFD in glyphs


def test_unknown_characters_draw_the_replacement_glyph():
    graphics = MirrorGraphics(emulator.graphics)
    font = graphics.Font()
    font.LoadFont(str(FONTS / "5x7.bdf"))
    assert font.glyph(0x1F3D2) == font.glyph(0xFFFD)


def test_line_covers_both_ends():
    assert _line(0, 0, 3, 0) == [(0, 0), (1, 0), (2, 0), (3, 0)]
    assert _line(2, 3, 2, 1) == [(2, 3), (2, 2), (2, 1)]
    assert _line(0, 0, 2, 2) == [(0, 0), (1, 1), (2, 2)]


def test_mirror_clips_off_panel_pixels():
    mirror = Mirror(4, 2)
    canvas = MirrorCanvas(AsciiCanvas(4, 2), mirror)
    canvas.SetPixel(-1, 0, 255, 255, 255)
    canvas.SetPixel(4, 1, 255, 255, 255)
    canvas.SetPixel(3, 1, 1, 2, 3)
    assert mirror.buffer[-3:] == bytes((1, 2, 3))
    assert sum(mirror.buffer) == 6
