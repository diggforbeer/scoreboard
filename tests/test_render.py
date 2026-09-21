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

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.fonts import FontSet
from nhl_scoreboard.display.logos import LogoLibrary
from nhl_scoreboard.display.renderer import (
    ACCENT,
    DIM,
    FINAL,
    INTERMISSION,
    LIVE,
    PREGAME,
    SUBDUED,
    WHITE,
    Renderer,
)
from nhl_scoreboard.display.teams import team_color
from nhl_scoreboard.nhl.models import Game, Situation

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
INDICATOR_TOP, INDICATOR_BOTTOM = SCORE_BASELINE + 1, RULE_Y - 1  # the band the rule normally uses
LOGO = 32
MID_LEFT, MID_RIGHT = LOGO, W - LOGO  # the column between the logos
AWAY_CX, HOME_CX = MID_LEFT + 16, MID_RIGHT - 16
FIXTURE_TEAMS = ("SEA", "CGY", "CAR", "FLA", "NYI", "NJD", "WSH", "BOS", "TOR", "MTL", "EDM")


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


@pytest.fixture(scope="module")
def synthetic_logos(tmp_path_factory) -> LogoLibrary:
    """A filled circle per team in its colour: deterministic, and no NHL artwork."""
    from PIL import Image, ImageDraw

    root = tmp_path_factory.mktemp("logos")
    for abbrev in FIXTURE_TEAMS:
        im = Image.new("RGBA", (LOGO, LOGO), (0, 0, 0, 0))
        ImageDraw.Draw(im).ellipse((2, 2, LOGO - 3, LOGO - 3), fill=(*team_color(abbrev), 255))
        im.save(root / f"{abbrev}.png")
    return LogoLibrary([root])


def make_renderer(favourite: str = "", logos: LogoLibrary | None = None) -> Renderer:
    return Renderer(
        graphics=graphics,
        fonts=FontSet(graphics),
        width=W,
        height=H,
        tz=TZ,
        favourite=favourite,
        logos=logos,
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


def assert_logo_layout(c: AsciiCanvas, game: Game, favourite: str = "") -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"

    for x0, side in ((0, game.away), (MID_RIGHT, game.home)):
        region = c.lit(x0, 0, x0 + LOGO - 1, H - 1)
        assert region, f"no logo drawn for {side.abbrev}"
        assert team_color(side.abbrev) in set(region.values()), f"{side.abbrev} logo colour wrong"

    # Scores sit centred in each half of the middle column, in white.
    for cx, side in ((AWAY_CX, game.away), (HOME_CX, game.home)):
        box = c.bbox(cx - 12, 0, cx + 12, SCORE_BASELINE)
        assert box is not None, f"no score drawn for {side.abbrev}"
        assert abs(box.center_x - cx) <= 1, f"{side.abbrev} score off-centre: {box.center_x}"
        assert WHITE in c.colors(cx - 12, 0, cx + 12, SCORE_BASELINE)

        underline = c.lit(cx - 12, UNDERLINE_Y, cx + 12, UNDERLINE_Y)
        should = bool(favourite) and side.abbrev == favourite
        state = "missing" if should else "present"
        assert bool(underline) == should, f"{side.abbrev}: underline {state}"
        if underline:
            assert set(underline.values()) == {ACCENT}

    mid = (MID_LEFT + MID_RIGHT) // 2
    assert all((mid - 1, y) in c.pixels for y in range(3, SCORE_BASELINE + 1)), "divider missing"
    rule = c.lit(MID_LEFT + 3, RULE_Y, MID_RIGHT - 4, RULE_Y)
    assert len(rule) == MID_RIGHT - 4 - (MID_LEFT + 3) + 1, "rule should span the middle column"

    box = c.bbox(MID_LEFT, STATUS_TOP, MID_RIGHT - 1, H - 1)
    assert box is not None, "status line missing"
    assert abs(box.center_x - (mid - 0.5)) <= 1, f"status not centred: {box.center_x}"


def status_color(c: AsciiCanvas, x0: int = 0, x1: int = W - 1) -> set:
    return c.colors(x0, STATUS_TOP, x1, H - 1)


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
def test_text_layout(games, scene, favourite, expected_color, update_snapshots):
    """Fallback layout, used when a logo is unavailable."""
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
    check_snapshot(f"text_{scene}", art, update_snapshots)


def test_text_layout_two_digit_scores(big_score_game, update_snapshots):
    c = canvas()
    make_renderer().draw_game(c, big_score_game)
    art = show("text, big score: EDM 12 @ CGY 10", c)
    assert_game_layout(c, big_score_game)
    check_snapshot("text_big_score", art, update_snapshots)


# --------------------------------------------------------------------------
# logo layout
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
def test_logo_layout(games, synthetic_logos, scene, favourite, expected_color, update_snapshots):
    game = games[scene]
    c = canvas()
    make_renderer(favourite, synthetic_logos).draw_game(c, game)

    art = show(
        f"logos, {scene}: {game.away.abbrev} {game.away.score} @ "
        f"{game.home.abbrev} {game.home.score} [{game.status_label(TZ)}]",
        c,
    )
    assert_logo_layout(c, game, favourite)
    assert status_color(c, MID_LEFT, MID_RIGHT - 1) == {expected_color}
    check_snapshot(f"logo_{scene}", art, update_snapshots)


def test_logo_layout_two_digit_scores(big_score_game, synthetic_logos, update_snapshots):
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, big_score_game)
    art = show("logos, big score: EDM 12 @ CGY 10", c)
    assert_logo_layout(c, big_score_game)
    check_snapshot("logo_big_score", art, update_snapshots)


def test_missing_logo_falls_back_to_text(games, synthetic_logos, tmp_path):
    """One side without artwork means the whole frame uses the text layout."""
    from PIL import Image

    only_away = tmp_path / "partial"
    only_away.mkdir()
    Image.open(synthetic_logos.path_for("SEA")).save(only_away / "SEA.png")
    c = canvas()
    make_renderer(logos=LogoLibrary([only_away])).draw_game(c, games["live"])
    assert_game_layout(c, games["live"])  # full-width rule etc: the text layout's signature


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


# --------------------------------------------------------------------------
# special teams
# --------------------------------------------------------------------------


def with_situation(game: Game, away=(), home=(), away_strength=5, home_strength=5, time="1:23"):
    return dataclasses.replace(
        game,
        situation=Situation.from_api(
            {
                "awayTeam": {"strength": away_strength, "situationDescriptions": list(away)},
                "homeTeam": {"strength": home_strength, "situationDescriptions": list(home)},
                "timeRemaining": time,
                "secondsRemaining": 83,
            }
        ),
    )


def assert_indicator(c: AsciiCanvas, side: str, x0: int, x1: int, allow=frozenset()) -> None:
    """Amber text in the indicator band, hugging the given side; no rule.

    ``allow`` lists other colours that may legitimately share the band -- the
    text layout's vertical divider runs through it.
    """
    band = {xy: rgb for xy, rgb in c.lit(x0, INDICATOR_TOP, x1, INDICATOR_BOTTOM).items()}
    amber = {xy for xy, rgb in band.items() if rgb == ACCENT}
    assert amber, "indicator not drawn"
    colours = set(band.values())
    assert colours <= {ACCENT, *allow}, f"unexpected colours in band: {colours}"
    xs = [x for x, _ in amber]
    # Glyphs in the 4x6 face can have a blank edge column, hence the 1px slack.
    if side == "away":
        assert x0 <= min(xs) <= x0 + 1, f"away indicator should start at x={x0}, got {min(xs)}"
    else:
        assert x1 - 1 <= max(xs) <= x1, f"home indicator should end at x={x1}, got {max(xs)}"
    assert not c.lit(x0, RULE_Y, x1, RULE_Y), "rule should give way to the indicator"


@pytest.mark.parametrize(
    ("name", "kwargs", "side"),
    [
        ("pp_home", {"home": ["PP"], "away_strength": 4}, "home"),
        ("pp_away", {"away": ["PP"], "home_strength": 4}, "away"),
        ("pp_5v3", {"home": ["PP"], "away_strength": 3}, "home"),
        ("empty_net", {"away": ["EN"], "away_strength": 6}, "away"),
    ],
)
def test_logo_layout_special_teams(games, synthetic_logos, name, kwargs, side, update_snapshots):
    game = with_situation(games["live"], **kwargs)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, game)
    art = show(f"logos, {name}: {game.situation.label()} ({side})", c)

    assert not c.out_of_bounds
    assert_indicator(c, side, MID_LEFT + 3, MID_RIGHT - 4)
    # Scores and status are untouched by the indicator.
    for cx in (AWAY_CX, HOME_CX):
        assert WHITE in c.colors(cx - 12, 0, cx + 12, SCORE_BASELINE)
    assert status_color(c, MID_LEFT, MID_RIGHT - 1) == {LIVE}
    check_snapshot(f"logo_{name}", art, update_snapshots)


def test_text_layout_special_teams(games, update_snapshots):
    game = with_situation(games["live"], home=["PP"], away_strength=4)
    c = canvas()
    make_renderer().draw_game(c, game)
    art = show("text, pp_home: PP 1:23", c)

    assert not c.out_of_bounds
    assert_indicator(c, "home", TEXT_LEFT, W - 4, allow={DIM})
    assert status_color(c) == {LIVE}
    check_snapshot("text_pp_home", art, update_snapshots)


def test_even_strength_situation_draws_nothing_special(games, synthetic_logos):
    """4-on-4 arrives as a situation object but is not an advantage."""
    game = with_situation(games["live"], away_strength=4, home_strength=4)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, game)
    assert_logo_layout(c, game)  # includes: the rule is present
    assert not c.lit(MID_LEFT + 3, INDICATOR_TOP, MID_RIGHT - 4, INDICATOR_BOTTOM)


# --------------------------------------------------------------------------
# preview and countdown (favourite mode)
# --------------------------------------------------------------------------

PUCK_DROP = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)  # 8:00 PM Toronto
UPCOMING = Game.from_api(
    {
        "id": 77,
        "gameState": "FUT",
        "startTimeUTC": "2026-09-23T00:00:00Z",
        "awayTeam": {"abbrev": "TOR"},
        "homeTeam": {"abbrev": "MTL"},
    }
)


@pytest.mark.parametrize(
    ("name", "method", "now", "top", "bottom", "bottom_color"),
    [
        (
            "preview_tonight",
            "draw_preview",
            PUCK_DROP - timedelta(hours=9),
            "TONIGHT",
            "8:00P",
            WHITE,
        ),
        (
            "preview_tomorrow",
            "draw_preview",
            PUCK_DROP - timedelta(days=1, hours=4),
            "TOMORROW",
            "8:00P",
            WHITE,
        ),
        (
            "preview_date",
            "draw_preview",
            PUCK_DROP - timedelta(days=5),
            "TUE SEP 22",
            "8:00P",
            WHITE,
        ),
        (
            "countdown_hours",
            "draw_countdown",
            PUCK_DROP - timedelta(hours=1, minutes=29),
            "8:00P",
            "IN 1H 29M",
            ACCENT,
        ),
        (
            "countdown_minutes",
            "draw_countdown",
            PUCK_DROP - timedelta(minutes=12, seconds=34),
            "8:00P",
            "IN 12:34",
            ACCENT,
        ),
    ],
)
def test_upcoming_logo_layout(
    synthetic_logos, name, method, now, top, bottom, bottom_color, update_snapshots
):
    c = canvas()
    getattr(make_renderer(logos=synthetic_logos), method)(c, UPCOMING, now)
    art = show(f"logos, {name}: {top} / {bottom}", c)

    assert not c.out_of_bounds
    for x0, side in ((0, UPCOMING.away), (MID_RIGHT, UPCOMING.home)):
        assert team_color(side.abbrev) in c.colors(x0, 0, x0 + LOGO - 1, H - 1), (
            f"{side.abbrev} logo"
        )
    top_box = c.bbox(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 1)
    assert top_box and abs(top_box.center_x - (W - 1) / 2) <= 1, "top line not centred"
    assert c.colors(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 2) == {WHITE}
    assert c.lit(MID_LEFT + 3, RULE_Y, MID_RIGHT - 4, RULE_Y), "rule missing"
    assert_centered(c, STATUS_TOP, H - 1, "bottom line")
    assert status_color(c, MID_LEFT, MID_RIGHT - 1) == {bottom_color}
    check_snapshot(f"logo_{name}", art, update_snapshots)


@pytest.mark.parametrize(
    ("name", "method", "now", "bottom_color"),
    [
        ("preview_tonight", "draw_preview", PUCK_DROP - timedelta(hours=9), WHITE),
        ("countdown_hours", "draw_countdown", PUCK_DROP - timedelta(hours=1, minutes=29), ACCENT),
    ],
)
def test_upcoming_text_layout(name, method, now, bottom_color, update_snapshots):
    c = canvas()
    getattr(make_renderer(), method)(c, UPCOMING, now)
    art = show(f"text, {name}", c)

    assert not c.out_of_bounds
    matchup = c.colors(0, 0, W - 1, RULE_Y - 1)
    assert {team_color("TOR"), team_color("MTL"), SUBDUED} <= matchup, "matchup colours"
    assert_centered(c, 0, RULE_Y - 1, "matchup")
    assert c.row_is_solid(RULE_Y)
    assert_centered(c, STATUS_TOP, H - 1, "bottom line")
    assert status_color(c) == {bottom_color}
    check_snapshot(f"text_{name}", art, update_snapshots)
