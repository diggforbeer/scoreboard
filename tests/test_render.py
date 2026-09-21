"""Render every scene to ASCII, print it, and check it.

Two layers of checking:

* A snapshot compare against ``tests/snapshots/<scene>.txt``. Regenerate with
  ``pytest --update-snapshots`` after an intentional layout change, then read
  the diff in git before committing it.
* Structural assertions that hold regardless of snapshot: nothing drawn off
  the panel, status text centred, scores right-aligned, colours as expected,
  the favourite underline only where it belongs.

Run with ``pytest -s tests/test_render.py`` to see every frame.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.fonts import FontSet
from nhl_scoreboard.display.renderer import (
    ACCENT,
    FINAL,
    INTERMISSION,
    LIVE,
    PREGAME,
    SUBDUED,
    Renderer,
)
from nhl_scoreboard.display.teams import team_color
from nhl_scoreboard.nhl.models import Game

graphics = pytest.importorskip("RGBMatrixEmulator").graphics

W, H = 128, 32
HALF = W // 2
TZ = ZoneInfo("America/Toronto")
SNAPSHOTS = Path(__file__).parent / "snapshots"

# Layout constants the renderer uses; asserting on them keeps the two honest.
SCORE_BASELINE = 13
RULE_Y = 19
UNDERLINE_Y = SCORE_BASELINE + 2
STATUS_TOP = RULE_Y + 1
TEXT_LEFT = 3
TEXT_RIGHT_PAD = 3


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def games() -> dict[str, Game]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())
    by_away = {g["awayTeam"]["abbrev"]: Game.from_api(g) for g in payload["games"]}
    return {
        "live": by_away["SEA"],  # 1ST 05:05
        "intermission": by_away["CAR"],  # INT2
        "final": by_away["NYI"],  # FINAL
        "shootout": by_away["WSH"],  # F/SO
        "pregame": by_away["TOR"],  # 7:00P, favourite involved
    }


@pytest.fixture
def big_score_game(games) -> Game:
    """A blowout: two-digit scores must still fit beside the abbreviations."""
    live = games["live"]
    return Game(
        **{
            **{f: getattr(live, f) for f in live.__dataclass_fields__},
            "away": live.away.__class__(abbrev="EDM", name="Oilers", score=12, sog=40),
            "home": live.home.__class__(abbrev="CGY", name="Flames", score=10, sog=38),
        }
    )


def make_renderer(favourite: str = "") -> Renderer:
    return Renderer(
        graphics=graphics, fonts=FontSet(graphics), width=W, height=H, tz=TZ, favourite=favourite
    )


def canvas() -> AsciiCanvas:
    return AsciiCanvas(W, H)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def show(name: str, c: AsciiCanvas) -> str:
    art = c.render()
    print(f"\n[{name}]\n{art}")
    return art


def check_snapshot(name: str, art: str, update: bool) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if update or not path.exists():
        path.write_text(art + "\n")
        if not update:
            pytest.fail(f"Wrote new snapshot {path.name}; re-run to verify it", pytrace=False)
        return
    expected = path.read_text().rstrip("\n")
    assert art == expected, (
        f"{name} rendering changed. If intentional: pytest --update-snapshots, "
        f"then review the diff of {path.relative_to(SNAPSHOTS.parent.parent)}"
    )


def assert_centered(c: AsciiCanvas, y0: int, y1: int, what: str, tolerance: float = 1.0) -> None:
    box = c.bbox(0, y0, W - 1, y1)
    assert box is not None, f"{what}: nothing drawn in rows {y0}-{y1}"
    assert abs(box.center_x - (W - 1) / 2) <= tolerance, (
        f"{what} not centred: spans x={box.x0}..{box.x1}, centre {box.center_x}"
    )


def assert_game_layout(c: AsciiCanvas, game: Game, favourite: str = "") -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    assert c.row_is_solid(RULE_Y), "horizontal rule missing"
    assert all((HALF - 1, y) in c.pixels for y in range(2, RULE_Y - 3)), "divider missing"

    for x0, side in ((0, game.away), (HALF, game.home)):
        # Stop short of the divider column, which sits at HALF - 1.
        top = c.bbox(x0, 0, x0 + HALF - 2, SCORE_BASELINE)
        assert top is not None, f"nothing drawn for {side.abbrev}"
        assert top.x0 == x0 + TEXT_LEFT, f"{side.abbrev} not at the block's left margin"
        right_edge = x0 + HALF - 1 - TEXT_RIGHT_PAD
        assert right_edge - 1 <= top.x1 <= right_edge, f"{side.abbrev} score not right-aligned"

        # Abbreviation and score must not touch: the 7x13B abbreviation spans
        # about 21px from the margin, a two-digit score about 14px from the
        # right, leaving a gap that must stay empty.
        gap = c.lit(x0 + 26, 0, x0 + HALF - 1 - TEXT_RIGHT_PAD - 16, SCORE_BASELINE)
        assert not gap, f"{side.abbrev}: abbreviation and score collide"

        abbrev_colors = c.colors(x0 + TEXT_LEFT, 0, x0 + 24, SCORE_BASELINE)
        assert team_color(side.abbrev) in abbrev_colors, f"{side.abbrev} not in its team colour"

        underline = c.lit(x0 + TEXT_LEFT, UNDERLINE_Y, x0 + 24, UNDERLINE_Y)
        should_underline = bool(favourite) and side.abbrev == favourite
        assert bool(underline) == should_underline, (
            f"{side.abbrev}: favourite underline {'missing' if should_underline else 'present'}"
        )
        if underline:
            assert set(underline.values()) == {ACCENT}

    assert_centered(c, STATUS_TOP, H - 1, "status line")


def status_color(c: AsciiCanvas) -> set:
    return c.colors(0, STATUS_TOP, W - 1, H - 1)


# --------------------------------------------------------------------------
# game scenes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scene", "favourite", "expected_color"),
    [
        ("live", "", LIVE),
        ("intermission", "", INTERMISSION),
        ("final", "", FINAL),
        ("shootout", "", FINAL),
        ("pregame", "TOR", PREGAME),
    ],
)
def test_game_scene(games, scene, favourite, expected_color, update_snapshots):
    game = games[scene]
    c = canvas()
    make_renderer(favourite).draw_game(c, game)

    art = show(
        f"{scene}: {game.away.abbrev} {game.away.score} @ "
        f"{game.home.abbrev} {game.home.score} [{game.status_label(TZ)}]",
        c,
    )

    assert_game_layout(c, game, favourite)
    assert status_color(c) == {expected_color}
    check_snapshot(f"game_{scene}", art, update_snapshots)


def test_two_digit_scores_fit(big_score_game, update_snapshots):
    c = canvas()
    make_renderer().draw_game(c, big_score_game)
    art = show("big score: EDM 12 @ CGY 10", c)
    assert_game_layout(c, big_score_game)
    check_snapshot("game_big_score", art, update_snapshots)


def test_favourite_underline_follows_the_team(games):
    """Same game, favourite on the other side: underline moves with it."""
    game = games["pregame"]  # TOR @ MTL
    for fav, x0 in (("TOR", 0), ("MTL", HALF)):
        c = canvas()
        make_renderer(fav).draw_game(c, game)
        assert c.lit(x0 + TEXT_LEFT, UNDERLINE_Y, x0 + 24, UNDERLINE_Y), f"no underline for {fav}"
        other = HALF - x0
        assert not c.lit(other + TEXT_LEFT, UNDERLINE_Y, other + 24, UNDERLINE_Y)


# --------------------------------------------------------------------------
# non-game scenes
# --------------------------------------------------------------------------


def test_clock_scene(update_snapshots):
    c = canvas()
    # 23:05 UTC on 2026-09-20 is 7:05 PM EDT: exercises both time and date lines.
    make_renderer().draw_clock(c, datetime(2026, 9, 20, 23, 5, tzinfo=UTC))
    art = show("clock", c)

    assert not c.out_of_bounds
    assert_centered(c, 0, 16, "time")
    assert_centered(c, 20, H - 1, "date")
    check_snapshot("clock", art, update_snapshots)


@pytest.mark.parametrize(
    ("name", "title", "subtitle"),
    [
        ("message_connecting", "NHL", "CONNECTING"),
        ("message_no_data", "NO DATA", "CHECK NETWORK"),
        ("message_no_games", "NO GAMES", ""),
    ],
)
def test_message_scene(name, title, subtitle, update_snapshots):
    c = canvas()
    make_renderer().draw_message(c, title, subtitle)
    art = show(name, c)

    assert not c.out_of_bounds
    if subtitle:
        assert_centered(c, 0, 14, "title")
        assert_centered(c, 20, H - 1, "subtitle")
        assert status_color(c) == {SUBDUED}
    else:
        assert_centered(c, 0, H - 1, "title")
    check_snapshot(name, art, update_snapshots)
