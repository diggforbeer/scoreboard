"""The blowout Easter egg (#326): the rule, the drawing, and the fences.

The end-to-end flow (the flash, then the three stars, then the held final)
is in ``test_flow.py`` beside the three-stars tests.

Like ``april_fools.py`` this is kept out of the README, ``screens.md``, demo
mode and the rendered snapshots (owner's call: the joke is finding it), so
nothing here snapshots it, and the fence tests below fail if a later pass
adds it to any of them -- including a "complete the screen guide" sweep.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard import blowout
from nhl_scoreboard.app import Scene
from nhl_scoreboard.demo import demo_steps
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.fonts import FontSet
from nhl_scoreboard.display.renderer import Renderer
from test_flow import FAV, NEXT_DROP, PUCK_DROP, game, score

ROOT = Path(__file__).resolve().parents[1]


def final(home: int, away: int, *, period_type: str = "REG", state: str = "FINAL"):
    g = score(game(1, "TBL", FAV, PUCK_DROP, state), home=home, away=away)
    return dataclasses.replace(g, period_type=period_type)


@pytest.mark.parametrize(
    ("home", "away", "expected"),
    [(1, 6, True), (0, 5, True), (0, 7, True), (2, 6, False), (3, 4, False), (6, 1, False)],
)
def test_only_a_loss_by_five_or_more(home, away, expected):
    assert blowout.is_blowout_loss(final(home, away), FAV) is expected


def test_the_favourite_losing_away_counts_too():
    g = score(game(1, FAV, "TBL", PUCK_DROP, "FINAL"), away=1, home=6)
    assert blowout.is_blowout_loss(g, FAV)


def test_only_a_finished_regulation_game():
    assert not blowout.is_blowout_loss(final(0, 6, state="LIVE"), FAV)
    assert not blowout.is_blowout_loss(final(0, 6, period_type="OT"), FAV)


def test_only_on_a_predators_board_and_only_the_favourites_game():
    assert not blowout.is_blowout_loss(final(1, 6), "TBL")
    other = score(game(2, "COL", "DAL", NEXT_DROP, "FINAL"), away=1, home=7)
    assert not blowout.is_blowout_loss(other, FAV)


@pytest.mark.parametrize("width", [128, 64])
def test_it_draws_on_the_panel(width):
    graphics = pytest.importorskip("RGBMatrixEmulator").graphics
    r = Renderer(graphics, FontSet(graphics), width, 32, ZoneInfo("America/Chicago"))
    canvas = AsciiCanvas(width, 32)
    r.draw_blowout(canvas, final(1, 6), FAV)
    assert canvas.out_of_bounds == []
    assert canvas.lit()
    colours = set(canvas.pixels.values())
    assert blowout._COLORS["B"] in colours, "the toilet is on screen"
    if width == 128:
        assert (255, 40, 40) in colours, "and so is the caption"


# -- fences ---------------------------------------------------------------


def test_it_is_not_a_documented_scene_kind():
    assert "blowout" not in Scene.__doc__


def test_demo_mode_never_shows_it():
    from datetime import UTC, datetime

    steps = demo_steps("NSH", datetime(2026, 10, 14, tzinfo=UTC))
    assert "blowout" not in {s.scene.kind for s in steps}


@pytest.mark.parametrize("path", ["README.md", "screens.md", "src/nhl_scoreboard/demo.py"])
def test_it_is_kept_out_of_the_guide_readme_and_demo(path):
    text = (ROOT / path).read_text().lower()
    assert "blowout" not in text and "toilet" not in text


def test_no_screen_image_is_made_of_it():
    assert not [p.name for p in (ROOT / "docs" / "screens").glob("*blowout*")]
    assert not list((ROOT / "tests" / "snapshots").glob("*blowout*"))
