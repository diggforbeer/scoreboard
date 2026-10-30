"""screens.md and docs/screens/ must keep up with the code (#324)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.demo import demo_steps

pytest.importorskip("RGBMatrixEmulator")

ROOT = Path(__file__).resolve().parents[1]


def _render_script():
    spec = importlib.util.spec_from_file_location(
        "render_screens", ROOT / "scripts" / "render-screens.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_images_match_the_demo_scenes():
    """Fails when a layout change leaves docs/screens/ behind; regenerate with
    ``python scripts/render-screens.py`` and look at the diff."""
    script = _render_script()
    images = script.render_all(script.DEFAULT_OUT)
    assert script.stale(script.DEFAULT_OUT, images) == []


def test_every_scene_kind_has_a_section_in_the_guide():
    kinds = re.search(r"``kind`` is one of (.*?)\.\n", Scene.__doc__, re.S).group(1)
    documented = set(re.findall(r"``(\w+)``", kinds))
    guide = (ROOT / "screens.md").read_text()
    missing = [k for k in sorted(documented) if f"`{k}`" not in guide]
    assert missing == [], f"screens.md never mentions scene kind(s): {missing}"


def test_every_image_is_used_in_the_guide():
    from datetime import UTC, datetime

    guide = (ROOT / "screens.md").read_text()
    names = [s.name for s in demo_steps("NSH", datetime(2026, 10, 14, tzinfo=UTC))]
    missing = [n for n in names if f"docs/screens/{n}.png" not in guide]
    assert missing == [], f"screens.md shows no image for: {missing}"
