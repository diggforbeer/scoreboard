"""Render every scene to ASCII, print it, and check it.

Two layers of checking:

* A snapshot compare against ``tests/snapshots/<scene>.txt``. Regenerate with
  ``pytest --update-snapshots`` after an intentional layout change, then read
  the diff in git before committing it.
* Structural assertions that hold regardless of snapshot: nothing drawn off
  the panel, status text centred, scores right-aligned, colours as expected.

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
from nhl_scoreboard.nhl.models import Game, Situation, StandingsRow

graphics = pytest.importorskip("RGBMatrixEmulator").graphics

W, H = 128, 32
HALF = W // 2
TZ = ZoneInfo("America/Chicago")
SNAPSHOTS = Path(__file__).parent / "snapshots"

# Layout constants the renderer uses; asserting on them keeps the two honest.
SCORE_BASELINE = 13
RULE_Y = 19  # preview/countdown/goal only -- _draw_upcoming/draw_goal, untouched by #70
STATUS_TOP = RULE_Y + 1
TEXT_LEFT = 3
TEXT_RIGHT_PAD = 3
# The live-game rule/indicator band moved to row 20 for #70 (one more blank
# row above the PP/SOG line than PR #42 already added), independent of the
# RULE_Y=19 above -- that one belongs to _draw_upcoming/draw_goal, which
# didn't change.
GAME_RULE_Y = 20
INDICATOR_TOP, INDICATOR_BOTTOM = SCORE_BASELINE + 2, GAME_RULE_Y
# Old STATUS_TOP (=20) now collides with GAME_RULE_Y (also 20) -- the game
# layout's status-line sampling needs its own boundary one row further down.
GAME_STATUS_TOP = GAME_RULE_Y + 1
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
        "pregame": by_away["TOR"],  # 7:00P
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


def make_renderer(logos: LogoLibrary | None = None) -> Renderer:
    return Renderer(
        graphics=graphics,
        fonts=FontSet(graphics),
        width=W,
        height=H,
        tz=TZ,
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


def assert_game_layout(c: AsciiCanvas, game: Game) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    # TeamSide.sog is always present, so the indicator band always shows
    # SOG here rather than a plain rule (#70) -- unless a situation (PP/EN)
    # is active, which none of this helper's callers set up.
    assert_sog(c, TEXT_LEFT, W - 4, allow={DIM})
    assert all((HALF - 1, y) in c.pixels for y in range(2, GAME_RULE_Y - 3)), "divider missing"

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

        # Sampled right of the abbreviation/score gap already checked above.
        score_colors = c.colors(x0 + 26, 0, right_edge, SCORE_BASELINE)
        assert score_colors == {WHITE}, f"{side.abbrev} score should be white, got {score_colors}"

    assert_centered(c, GAME_STATUS_TOP, H - 1, "status line")


def assert_logo_layout(c: AsciiCanvas, game: Game) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"

    for x0, side in ((0, game.away), (MID_RIGHT, game.home)):
        region = c.lit(x0, 0, x0 + LOGO - 1, H - 1)
        assert region, f"no logo drawn for {side.abbrev}"
        assert team_color(side.abbrev) in set(region.values()), f"{side.abbrev} logo colour wrong"

    # Scores sit centred in each half of the middle column.
    for cx, side in ((AWAY_CX, game.away), (HOME_CX, game.home)):
        box = c.bbox(cx - 12, 0, cx + 12, SCORE_BASELINE)
        assert box is not None, f"no score drawn for {side.abbrev}"
        assert abs(box.center_x - cx) <= 1, f"{side.abbrev} score off-centre: {box.center_x}"
        score_colors = c.colors(cx - 12, 0, cx + 12, SCORE_BASELINE)
        assert score_colors == {WHITE}, f"{side.abbrev} score should be white, got {score_colors}"

    mid = (MID_LEFT + MID_RIGHT) // 2
    assert all((mid - 1, y) in c.pixels for y in range(3, SCORE_BASELINE + 1)), "divider missing"
    # TeamSide.sog is always present, so the indicator band always shows
    # SOG here rather than a plain rule (#70) -- unless a situation (PP/EN)
    # is active, which none of this helper's callers set up.
    assert_sog(c, MID_LEFT + 3, MID_RIGHT - 4)

    box = c.bbox(MID_LEFT, GAME_STATUS_TOP, MID_RIGHT - 1, H - 1)
    assert box is not None, "status line missing"
    assert abs(box.center_x - (mid - 0.5)) <= 1, f"status not centred: {box.center_x}"


def status_color(c: AsciiCanvas, x0: int = 0, x1: int = W - 1, y0: int = STATUS_TOP) -> set:
    return c.colors(x0, y0, x1, H - 1)


# --------------------------------------------------------------------------
# game scenes
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("scene", "expected_color"),
    [
        ("live", LIVE),
        ("intermission", INTERMISSION),
        ("final", FINAL),
        ("shootout", FINAL),
        ("pregame", PREGAME),
    ],
)
def test_text_layout(games, scene, expected_color, update_snapshots):
    """Fallback layout, used when a logo is unavailable."""
    game = games[scene]
    c = canvas()
    make_renderer().draw_game(c, game)

    art = show(
        f"{scene}: {game.away.abbrev} {game.away.score} @ "
        f"{game.home.abbrev} {game.home.score} [{game.status_label(TZ)}]",
        c,
    )

    assert_game_layout(c, game)
    assert status_color(c, y0=GAME_STATUS_TOP) == {expected_color}
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
    ("scene", "expected_color"),
    [
        ("live", LIVE),
        ("intermission", INTERMISSION),
        ("final", FINAL),
        ("shootout", FINAL),
        ("pregame", PREGAME),
    ],
)
def test_logo_layout(games, synthetic_logos, scene, expected_color, update_snapshots):
    game = games[scene]
    c = canvas()
    make_renderer(synthetic_logos).draw_game(c, game)

    art = show(
        f"logos, {scene}: {game.away.abbrev} {game.away.score} @ "
        f"{game.home.abbrev} {game.home.score} [{game.status_label(TZ)}]",
        c,
    )
    assert_logo_layout(c, game)
    assert status_color(c, MID_LEFT, MID_RIGHT - 1, y0=GAME_STATUS_TOP) == {expected_color}
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


# --------------------------------------------------------------------------
# non-game scenes
# --------------------------------------------------------------------------


def test_clock_scene(update_snapshots):
    c = canvas()
    # 23:05 UTC on 2026-09-20 is 6:05 PM CDT: exercises both time and date lines.
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


def with_sog(game: Game, away_sog: int, home_sog: int) -> Game:
    """Distinct SOG values, via TeamSide.sog -- always present on a real
    Game already (#70 turned out to be able to use it directly, straight
    from the score feed, rather than a separate fetch)."""
    return dataclasses.replace(
        game,
        away=dataclasses.replace(game.away, sog=away_sog),
        home=dataclasses.replace(game.home, sog=home_sog),
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


def assert_sog(c: AsciiCanvas, x0: int, x1: int, allow=frozenset()) -> None:
    """Plain white, centred text in the indicator band (#70) -- never amber,
    so it can't be mistaken for the PP/EN indicator it's a fallback for."""
    band = {xy: rgb for xy, rgb in c.lit(x0, INDICATOR_TOP, x1, INDICATOR_BOTTOM).items()}
    white = {xy for xy, rgb in band.items() if rgb == WHITE}
    assert white, "SOG not drawn"
    colours = set(band.values())
    assert colours <= {WHITE, *allow}, f"unexpected colours in SOG band: {colours}"
    xs = [x for x, _ in white]
    centre = (x0 + x1) // 2
    assert abs((min(xs) + max(xs)) / 2 - centre) <= 2, f"SOG not centred: got {xs}"


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
    assert status_color(c, MID_LEFT, MID_RIGHT - 1, y0=GAME_STATUS_TOP) == {LIVE}
    check_snapshot(f"logo_{name}", art, update_snapshots)


def test_text_layout_special_teams(games, update_snapshots):
    game = with_situation(games["live"], home=["PP"], away_strength=4)
    c = canvas()
    make_renderer().draw_game(c, game)
    art = show("text, pp_home: PP 1:23", c)

    assert not c.out_of_bounds
    assert_indicator(c, "home", TEXT_LEFT, W - 4, allow={DIM})
    assert status_color(c, y0=GAME_STATUS_TOP) == {LIVE}
    check_snapshot("text_pp_home", art, update_snapshots)


def test_logo_layout_sog(games, synthetic_logos, update_snapshots):
    """5v5, no PP/EN -- shots on goal fill the indicator band instead (#70)."""
    game = with_sog(games["live"], away_sog=18, home_sog=14)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, game)
    art = show(f"logos, sog: {game.away.sog}-{game.home.sog}", c)

    assert not c.out_of_bounds
    assert_sog(c, MID_LEFT + 3, MID_RIGHT - 4)
    for cx in (AWAY_CX, HOME_CX):
        assert WHITE in c.colors(cx - 12, 0, cx + 12, SCORE_BASELINE)
    assert status_color(c, MID_LEFT, MID_RIGHT - 1, y0=GAME_STATUS_TOP) == {LIVE}
    check_snapshot("logo_sog", art, update_snapshots)


def test_text_layout_sog(games, update_snapshots):
    game = with_sog(games["live"], away_sog=18, home_sog=14)
    c = canvas()
    make_renderer().draw_game(c, game)
    art = show(f"text, sog: {game.away.sog}-{game.home.sog}", c)

    assert not c.out_of_bounds
    assert_sog(c, TEXT_LEFT, W - 4, allow={DIM})
    assert status_color(c, y0=GAME_STATUS_TOP) == {LIVE}
    check_snapshot("text_sog", art, update_snapshots)


def test_sog_suppressed_when_situation_is_active(games, synthetic_logos):
    """PP always wins over SOG, even when both are available (#70)."""
    game = with_sog(with_situation(games["live"], home=["PP"], away_strength=4), 18, 14)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, game)
    assert_indicator(c, "home", MID_LEFT + 3, MID_RIGHT - 4)
    band = c.lit(MID_LEFT + 3, INDICATOR_TOP, MID_RIGHT - 4, INDICATOR_BOTTOM)
    assert WHITE not in band.values(), "SOG should not appear alongside an active PP"


def test_sog_shown_at_4_on_4(games, synthetic_logos):
    """4-on-4 is a Situation with no indicator code -- falls through to SOG,
    same as plain even strength (#70 removed the old "draws nothing
    special" case entirely: TeamSide.sog is always present now)."""
    game = with_sog(with_situation(games["live"], away_strength=4, home_strength=4), 10, 11)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_game(c, game)
    assert_sog(c, MID_LEFT + 3, MID_RIGHT - 4, allow={DIM})


# --------------------------------------------------------------------------
# preview and countdown (favourite mode)
# --------------------------------------------------------------------------

PUCK_DROP = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)  # 7:00 PM Chicago
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


# --------------------------------------------------------------------------
# goal celebration
# --------------------------------------------------------------------------


def test_logo_layout_goal(games, synthetic_logos, update_snapshots):
    game = games["live"]  # SEA 2 @ CGY 1
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_goal(c, game)
    art = show(f"logos, goal: {game.away.abbrev} {game.away.score}-{game.home.score}", c)

    assert not c.out_of_bounds
    for x0, side in ((0, game.away), (MID_RIGHT, game.home)):
        logo_colors = c.colors(x0, 0, x0 + LOGO - 1, H - 1)
        assert team_color(side.abbrev) in logo_colors, f"{side.abbrev} logo"
    goal_box = c.bbox(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 1)
    assert goal_box is not None, "GOAL text missing"
    assert abs(goal_box.center_x - (W - 1) / 2) <= 1, "GOAL not centred"
    assert c.colors(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 1) == {ACCENT}, "GOAL must be amber only"
    # No rule, no power-play band: this frame owns the whole panel.
    assert not c.row_is_solid(RULE_Y)
    assert_centered(c, STATUS_TOP, H - 1, "score line")
    assert status_color(c, MID_LEFT, MID_RIGHT - 1) == {WHITE}
    check_snapshot("logo_goal", art, update_snapshots)


def test_text_layout_goal(games, update_snapshots):
    game = games["live"]
    c = canvas()
    make_renderer().draw_goal(c, game)
    art = show(f"text, goal: {game.away.abbrev} {game.away.score}-{game.home.score}", c)

    assert not c.out_of_bounds
    goal_box = c.bbox(0, 0, W - 1, RULE_Y - 1)
    assert goal_box is not None
    assert c.colors(0, 0, W - 1, RULE_Y - 1) == {ACCENT}, "GOAL must be amber only"
    assert abs(goal_box.center_x - (W - 1) / 2) <= 1, "GOAL not centred"
    assert_centered(c, STATUS_TOP, H - 1, "score line")
    assert status_color(c) == {WHITE}
    check_snapshot("text_goal", art, update_snapshots)


def test_goal_score_reflects_the_current_score(games, synthetic_logos):
    """A distinct score from the fixture must actually show up, not a stale one."""
    game = dataclasses.replace(
        games["live"],
        home=dataclasses.replace(games["live"].home, score=9),
        away=dataclasses.replace(games["live"].away, score=7),
    )
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_goal(c, game)
    # "9-7" and "2-1" (the un-doctored score) are different widths/shapes;
    # a bbox-based smoke check that something in the score band changed
    # would be weak, so instead render the real score for comparison.
    c2 = canvas()
    make_renderer(logos=synthetic_logos).draw_goal(c2, games["live"])
    assert c.pixels != c2.pixels


def standings_row(abbrev: str, seq: int, points: int, record=(10, 5, 2)) -> StandingsRow:
    wins, losses, otl = record
    return StandingsRow(
        abbrev=abbrev,
        conference="W",
        division="C",
        division_sequence=1,
        wildcard_sequence=0,
        conference_sequence=seq,
        clinch_indicator="",
        points=points,
        games_played=sum(record),
        wins=wins,
        losses=losses,
        ot_losses=otl,
    )


STANDINGS_ROW_HEIGHT = 6
FAVOURITE_WINDOW = [
    standings_row("STL", 4, 45),
    standings_row("WPG", 5, 43),
    standings_row("NSH", 6, 42),
    standings_row("DAL", 7, 40),
    standings_row("COL", 8, 38),
]


def assert_standings_layout(c: AsciiCanvas, rows: list[StandingsRow], favourite: str) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    for i, row in enumerate(rows):
        y0, y1 = i * STANDINGS_ROW_HEIGHT, i * STANDINGS_ROW_HEIGHT + STANDINGS_ROW_HEIGHT - 1
        band = c.bbox(0, y0, W - 1, y1)
        assert band is not None, f"row {i} ({row.abbrev}) not drawn"
        colors = c.colors(0, y0, W - 1, y1)
        highlight = ACCENT if row.abbrev == favourite else WHITE
        assert colors <= {highlight, team_color(row.abbrev)}, (
            f"row {i} ({row.abbrev}) has unexpected colours: {colors}"
        )
        assert team_color(row.abbrev) in colors, f"row {i} ({row.abbrev}) not in its team colour"


def test_standings_layout_favourite_centred(update_snapshots):
    c = canvas()
    make_renderer().draw_standings(c, FAVOURITE_WINDOW, "NSH")
    art = show("standings, favourite centred (NSH 6th)", c)

    assert_standings_layout(c, FAVOURITE_WINDOW, "NSH")
    assert ACCENT in c.colors(0, 2 * STANDINGS_ROW_HEIGHT, W - 1, 3 * STANDINGS_ROW_HEIGHT - 1)
    check_snapshot("standings_favourite_centred", art, update_snapshots)


def test_standings_layout_favourite_clamped_to_top(update_snapshots):
    window = [
        standings_row("NSH", 1, 50),
        standings_row("WPG", 2, 48),
        standings_row("DAL", 3, 46),
        standings_row("STL", 4, 44),
        standings_row("COL", 5, 42),
    ]
    c = canvas()
    make_renderer().draw_standings(c, window, "NSH")
    art = show("standings, favourite 1st (extra rows below)", c)

    assert_standings_layout(c, window, "NSH")
    assert ACCENT in c.colors(0, 0, W - 1, STANDINGS_ROW_HEIGHT - 1)
    check_snapshot("standings_favourite_top", art, update_snapshots)


def test_standings_layout_only_favourite_is_highlighted():
    c = canvas()
    make_renderer().draw_standings(c, FAVOURITE_WINDOW, "NSH")
    for i, row in enumerate(FAVOURITE_WINDOW):
        y0, y1 = i * STANDINGS_ROW_HEIGHT, i * STANDINGS_ROW_HEIGHT + STANDINGS_ROW_HEIGHT - 1
        colors = c.colors(0, y0, W - 1, y1)
        if row.abbrev == "NSH":
            assert ACCENT in colors
        else:
            assert ACCENT not in colors


def test_standings_layout_no_favourite_uses_no_accent():
    """Shouldn't happen in practice, but nothing should crash or highlight wrongly."""
    c = canvas()
    make_renderer().draw_standings(c, FAVOURITE_WINDOW, "ZZZ")
    assert ACCENT not in c.colors()


def test_goal_scene_ignores_situation(games, synthetic_logos):
    """draw_goal never reads game.situation -- there is no room for a
    power-play band on the celebration screen."""
    game = games["live"]
    with_situation = dataclasses.replace(
        game,
        situation=Situation.from_api(
            {
                "awayTeam": {"strength": 4},
                "homeTeam": {"strength": 5, "situationDescriptions": ["PP"]},
                "timeRemaining": "1:23",
            }
        ),
    )
    c1, c2 = canvas(), canvas()
    r = make_renderer(logos=synthetic_logos)
    r.draw_goal(c1, game)
    r.draw_goal(c2, with_situation)
    assert c1.pixels == c2.pixels
