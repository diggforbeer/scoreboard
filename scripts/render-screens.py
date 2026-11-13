#!/usr/bin/env python3
"""Render every demo screen to a PNG of round LED dots, for screens.md (#324).

Walks ``demo_steps()`` -- the same synthetic scenes ``nhl-scoreboard --demo``
loops -- through the real app's ``draw_scene()``, records each frame with the
live view's mirror (``display/mirror.py``), and saves it as ``<step name>.png``.
So the guide's pictures come from the code that draws the panel and can't
drift from it.

    python scripts/render-screens.py            # write docs/screens/*.png
    python scripts/render-screens.py --check    # fail if the committed ones are stale
    python scripts/render-screens.py --real-logos   # use assets/logos (not for committing)
    python scripts/render-screens.py --sport nfl    # write docs/football/*.png (#359)
    python scripts/render-screens.py --sport nfl --check

``--sport nfl`` does the same for ``football.demo.nfl_demo_steps()`` and never touches
``docs/screens/``. A football step named like a hand-drawn mockup (``scripts/football-mockups.py``)
replaces it; mockups with no real screen yet stay, and are not reported as orphans. When the last
mockup is replaced, delete ``scripts/football-mockups.py`` (a test fails while it lists a name that
a real step also produces, so the two never overlap).

Team logos are NHL artwork and git-ignored, so the committed images use plain
circles in each team's colours, as the tests do.

Animated screens are stills: a shootout shows its settled look, a holiday its
fly-by two seconds in, a scrolling table its top.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from nhl_scoreboard.app import ScoreboardApp  # noqa: E402
from nhl_scoreboard.config import Settings  # noqa: E402
from nhl_scoreboard.demo import demo_steps  # noqa: E402
from nhl_scoreboard.display.ascii import AsciiCanvas  # noqa: E402
from nhl_scoreboard.display.logos import LogoLibrary  # noqa: E402
from nhl_scoreboard.display.matrix import Backend  # noqa: E402
from nhl_scoreboard.display.mirror import Frame  # noqa: E402
from nhl_scoreboard.display.teams import TEAM_COLORS, team_color  # noqa: E402

DEFAULT_OUT = REPO_ROOT / "docs" / "screens"
NFL_OUT = REPO_ROOT / "docs" / "football"
MOCKUPS = REPO_ROOT / "scripts" / "football-mockups.py"
#: A fixed clock keeps every image reproducible: the clock face, the
#: countdown and the "in two days" preview read the same on every run.
NOW = datetime(2026, 10, 14, 19, 30, tzinfo=ZoneInfo("America/Chicago"))
#: The Christmas tree's countdown only exists Dec 1-25.
DECEMBER = datetime(2026, 12, 20, 19, 30, tzinfo=ZoneInfo("America/Chicago"))
#: Seconds into a holiday fly-by to capture, when the sprite is mid-panel.
FLYBY_STILL_SECONDS = 2.0
#: Seconds into a shootout step: past the pop-in, so the settled grid shows.
SHOOTOUT_SETTLED_SECONDS = 2.0
#: Seconds into the goal light: everything has landed and the shimmer is mid-GOAL.
GOAL_STILL_SECONDS = 3.3

CELL = 8  # output pixels per LED
UNLIT = (14, 14, 14)


class _Matrix:
    """The driver's double buffer, over canvases that just discard pixels."""

    def __init__(self, options=None) -> None:
        self.canvases = [AsciiCanvas(128, 32), AsciiCanvas(128, 32)]

    def CreateFrameCanvas(self):  # noqa: N802
        return self.canvases[0]

    def SwapOnVSync(self, canvas):  # noqa: N802
        return self.canvases[1] if canvas is self.canvases[0] else self.canvases[0]


class _Options:
    pass


class _NoClient:
    """The app is never asked to fetch: scenes are handed straight to draw_scene()."""

    def close(self) -> None:
        pass


def synthetic_logos(directory: Path) -> LogoLibrary:
    for abbrev in TEAM_COLORS:
        im = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((2, 2, 29, 29), fill=(*team_color(abbrev), 255))
        im.save(directory / f"{abbrev}.png")
    return LogoLibrary([directory])


def make_app(logos: LogoLibrary) -> ScoreboardApp:
    from RGBMatrixEmulator import graphics

    settings = Settings()
    settings.status.enabled = False
    backend = Backend(
        name="render-screens",
        RGBMatrix=_Matrix,
        RGBMatrixOptions=_Options,
        graphics=graphics,
    )
    now = [1000.0]
    clock = [NOW]
    app = ScoreboardApp(
        settings,
        client=_NoClient(),
        backend=backend,
        clock=lambda: clock[0],
        monotonic=lambda: now[0],
        ap_setup_state_path=Path("/nonexistent/ap"),
        hw_mapping_trial_path=Path("/nonexistent/trial"),
    )
    app._now = now  # type: ignore[attr-defined]
    app._clock_box = clock  # type: ignore[attr-defined]
    app._demo_real_logos = logos
    app._demo_drawing = True
    return app


def capture(app: ScoreboardApp, step) -> Frame:
    """The frame ``step`` shows, as the live view would snapshot it."""
    scene = step.scene
    app._clock_box[0] = DECEMBER if scene.kind == "christmas_tree" else NOW
    app._set_demo_logos(step.use_logos)
    app._start_demo_holiday(step)
    app._start_demo_shootout(step)
    app._start_demo_goal(step)
    if step.animate_goal:
        app._now[0] += GOAL_STILL_SECONDS
    if step.holiday:
        app._now[0] += FLYBY_STILL_SECONDS
    if step.animate_shootout:
        app._now[0] += SHOOTOUT_SETTLED_SECONDS
    if step.scroll_seconds:
        scene = app._scroll_conference(scene, 0.0, step.scroll_seconds)
    # Mid-animation frames are held back from snapshots, which is right for
    # the live view but not for a still of an animated screen.
    app._overlay_animating = app._shootout_animating = app._scroll_animating = False
    app._goal_building = False
    if scene.animating:  # a still of an NFL play scene: not held back as mid-animation
        scene = dataclasses.replace(scene, animating=False)
    app.mirror.requested = True
    before = app.mirror.latest()
    app.draw_scene(scene)
    frame = app.mirror.latest()
    if frame is None or frame is before:
        raise RuntimeError(f"{step.name}: no frame was snapshotted")
    return frame


def _dot() -> Image.Image:
    """An antialiased round LED as an alpha mask."""
    big = Image.new("L", (CELL * 8, CELL * 8), 0)
    pad = CELL * 8 // 10
    ImageDraw.Draw(big).ellipse((pad, pad, CELL * 8 - pad, CELL * 8 - pad), fill=255)
    return big.resize((CELL, CELL), Image.LANCZOS)


def to_image(frame: Frame) -> Image.Image:
    img = Image.new("RGB", (frame.width * CELL, frame.height * CELL), (0, 0, 0))
    dot = _dot()
    for i in range(0, len(frame.pixels), 3):
        rgb = tuple(frame.pixels[i : i + 3])
        n = i // 3
        x, y = (n % frame.width) * CELL, (n // frame.width) * CELL
        img.paste(rgb if any(rgb) else UNLIT, (x, y), dot)
    return img


def render_all(out: Path, real_logos: bool = False, sport: str = "nhl") -> dict[str, Image.Image]:
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return _render(real_logos, sport)
    finally:
        logging.disable(previous)  # a test calling this must not mute the rest of the suite


def _render(real_logos: bool, sport: str) -> dict[str, Image.Image]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        logos = LogoLibrary.default() if real_logos else synthetic_logos(root)
        app = make_app(logos)
        if sport == "nfl":
            from nhl_scoreboard.display.logos import LogoSet
            from nhl_scoreboard.football.demo import nfl_demo_steps

            sys.path.insert(0, str(REPO_ROOT / "tests"))
            from nfl_logos import write_synthetic_nfl_logos

            if real_logos:
                app.renderer.nfl_logos = LogoSet("nfl")
            else:
                base = write_synthetic_nfl_logos(root / "nfl-logos") / "nfl"
                # Every size a screen asks for must be synthetic: a size missing here would fall
                # back to the real (git-ignored) artwork and end up in the committed images.
                libraries = {
                    size: LogoLibrary([base / str(size) / "dark"], size) for size in (12, 16)
                }
                app.renderer.nfl_logos = LogoSet("nfl", "dark", libraries)
            steps = nfl_demo_steps(NOW)
        else:
            steps = demo_steps(app.settings.scoreboard.favourite_team, NOW)
        images = {step.name: to_image(capture(app, step)) for step in steps}
    return images


def same_pixels(a: Image.Image, b: Image.Image) -> bool:
    return a.size == b.size and a.convert("RGB").tobytes() == b.convert("RGB").tobytes()


def mockup_names() -> set[str]:
    """The hand-drawn football mockups still standing (empty once that script is deleted)."""
    if not MOCKUPS.exists():
        return set()
    import importlib.util

    spec = importlib.util.spec_from_file_location("football_mockups", MOCKUPS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return set(module.SCREENS)


def stale(
    out: Path, images: dict[str, Image.Image], keep: frozenset[str] | set[str] = frozenset()
) -> list[str]:
    """Names whose committed PNG is missing or differs, plus orphaned files.

    ``keep`` names files that belong to something else and are not orphans (the football mockups).
    """
    problems = []
    for name, img in images.items():
        path = out / f"{name}.png"
        if not path.exists() or not same_pixels(Image.open(path), img):
            problems.append(f"{name}.png is missing or out of date")
    problems += [
        f"{p.name} belongs to no demo step"
        for p in sorted(out.glob("*.png"))
        if p.stem not in images and p.stem not in keep
    ]
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sport", choices=("nhl", "nfl"), default="nhl", help="Which demo steps")
    parser.add_argument("--out", type=Path, default=None, help="Output directory")
    parser.add_argument("--check", action="store_true", help="Compare, don't write")
    parser.add_argument("--real-logos", action="store_true", help="Use assets/logos")
    args = parser.parse_args(argv)

    nfl = args.sport == "nfl"
    out = args.out or (NFL_OUT if nfl else DEFAULT_OUT)
    keep = mockup_names() if nfl else set()
    images = render_all(out, args.real_logos, args.sport)
    if args.check:
        problems = stale(out, images, keep)
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            print(
                "Run: python scripts/render-screens.py" + (" --sport nfl" if nfl else ""),
                file=sys.stderr,
            )
        return 1 if problems else 0

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        if old.stem not in images and old.stem not in keep:
            old.unlink()
    for name, img in images.items():
        img.save(out / f"{name}.png", optimize=True)
    print(f"Wrote {len(images)} images to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
