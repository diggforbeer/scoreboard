"""football_screen.md and docs/football/ must keep up with the code (#359)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("RGBMatrixEmulator")

from nhl_scoreboard.football.demo import nfl_demo_steps
from nhl_scoreboard.football.mode import FB_SCENE_KINDS
from test_screens_doc import _render_script

ROOT = Path(__file__).resolve().parents[1]
GUIDE = (ROOT / "football_screen.md").read_text()
NOW = datetime(2026, 10, 14, tzinfo=UTC)


def test_committed_football_images_match_the_demo_steps():
    """Fails when a layout change leaves docs/football/ behind; regenerate with
    ``python scripts/render-screens.py --sport nfl`` and look at the diff."""
    script = _render_script()
    images = script.render_all(script.NFL_OUT, sport="nfl")
    assert script.stale(script.NFL_OUT, images, script.mockup_names()) == []


def test_every_fb_scene_kind_is_in_the_guide_and_in_the_demo():
    missing = [k for k in FB_SCENE_KINDS if f"`{k}`" not in GUIDE]
    assert missing == [], f"football_screen.md never mentions: {missing}"
    shown = {s.scene.kind for s in nfl_demo_steps(NOW)}
    assert set(FB_SCENE_KINDS) <= shown, f"no demo step for {set(FB_SCENE_KINDS) - shown}"


def test_every_demo_image_is_shown_in_the_guide():
    names = [s.name for s in nfl_demo_steps(NOW)]
    assert len(names) == len(set(names)), "demo step names must be unique"
    missing = [n for n in names if f"docs/football/{n}.png" not in GUIDE]
    assert missing == [], f"football_screen.md shows no image for: {missing}"


def test_a_mockup_and_a_real_step_never_share_an_image():
    """A name in both would be written by two scripts; replacing a mockup means removing it from
    football-mockups.py's SCREENS. Once that script is gone there is nothing to check."""
    script = _render_script()
    names = {s.name for s in nfl_demo_steps(NOW)}
    mockups = script.MOCKUPS
    if not mockups.exists():
        return
    source = mockups.read_text()
    listed = set(re.findall(r'^    "(\w+)": \w+,$', source, re.M))
    shared = sorted(names & script.mockup_names())
    # They may overlap only while the mockup still exists to be replaced; the script then skips
    # them, so check that is true rather than forbidding the overlap.
    assert "def real_screens" in source or not shared
    assert listed >= set(shared)
