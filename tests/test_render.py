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
import logging
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
from nhl_scoreboard.display.teams import team_color, team_secondary_color
from nhl_scoreboard.nhl.models import (
    AssistDetail,
    Game,
    GoalEvent,
    GoalieLine,
    SeasonSeriesRecord,
    Situation,
    SkaterLine,
    StandingsRow,
    Star,
    TeamLeaders,
)

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
FIXTURE_TEAMS = ("SEA", "CGY", "CAR", "FLA", "NYI", "NJD", "WSH", "BOS", "TOR", "MTL", "EDM", "NSH")


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
    assert c.colors(0, 0, W - 1, 16) == {WHITE}
    assert c.colors(0, 20, W - 1, H - 1) == {SUBDUED}
    check_snapshot("clock", art, update_snapshots)


def test_clock_scene_favourite(update_snapshots):
    """A favourite configured colours the clock; #123."""
    c = canvas()
    make_renderer().draw_clock(c, datetime(2026, 9, 20, 23, 5, tzinfo=UTC), favourite="NSH")
    art = show("clock, favourite NSH", c)

    assert not c.out_of_bounds
    assert_centered(c, 0, 16, "time")
    assert_centered(c, 20, H - 1, "date")
    assert c.colors(0, 0, W - 1, 16) == {team_color("NSH")}
    assert c.colors(0, 20, W - 1, H - 1) == {Renderer._dim(team_secondary_color("NSH"))}
    check_snapshot("clock_favourite", art, update_snapshots)


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
# AP setup (#131 follow-up): SSID/password + join QR code
# --------------------------------------------------------------------------


def test_ap_setup_scene_wpa(update_snapshots):
    """A deliberately small, hand-built matrix -- qrcode's own output is
    exercised at the app.py level; this only needs *some* module grid to
    check the renderer positions and colours it correctly."""
    c = canvas()
    qr_matrix = tuple(tuple((x + y) % 3 == 0 for x in range(21)) for y in range(21))
    make_renderer().draw_ap_setup(c, "NHL-Scoreboard-Setup", "scoreboard", qr_matrix)
    art = show("ap_setup_wpa", c)

    assert not c.out_of_bounds
    # The QR's white background fill covers the entire right half exactly --
    # confined there so it never straddles the seam between the two chained
    # 64x32 panels at x=64. Dark QR modules are pure black, which
    # AsciiCanvas (like the real SetPixel binding) treats as "off"/unlit,
    # not a second tracked colour -- so the right half reads as solid WHITE
    # here even though the QR pattern is visible in the snapshot's ASCII art.
    box = c.bbox(HALF, 0, W - 1, H - 1)
    assert box is not None
    assert (box.x0, box.y0, box.x1, box.y1) == (HALF, 0, W - 1, H - 1)
    assert c.colors(HALF, 0, W - 1, H - 1) == {WHITE}
    # Left half: SSID/password text only, never spilling into the QR's own
    # half (that would show up as an unexpected colour above).
    assert c.colors(0, 0, HALF - 1, H - 1) <= {WHITE, SUBDUED}
    check_snapshot("ap_setup_wpa", art, update_snapshots)


def test_ap_setup_scene_open_network_shows_no_password(update_snapshots):
    c = canvas()
    make_renderer().draw_ap_setup(c, "TestNet", None, None)
    art = show("ap_setup_open", c)

    assert not c.out_of_bounds
    assert c.colors(0, 0, HALF - 1, H - 1) <= {WHITE, SUBDUED}
    # No QR matrix given (e.g. qrcode failed) -- the right half must stay
    # untouched rather than half-drawing a background with nothing on it.
    assert c.bbox(HALF, 0, W - 1, H - 1) is None
    check_snapshot("ap_setup_open", art, update_snapshots)


def test_ap_setup_scene_oversized_qr_degrades_to_text_only(update_snapshots, caplog):
    """Caught live: the qrcode library's own default quiet zone alone was
    enough to blow a 29x29-module code out to 37x37, past the panel's 32px
    height, with nothing raising anywhere -- app.py's border=0 fix is the
    real fix, but the renderer must also never half-draw a background with
    no QR on it, and must say why out loud instead of failing silently."""
    caplog.set_level(logging.WARNING)
    c = canvas()
    too_big = tuple(tuple(True for _ in range(37)) for _ in range(37))
    make_renderer().draw_ap_setup(c, "TestNet", "hunter2", too_big)
    art = show("ap_setup_oversized_qr", c)

    assert not c.out_of_bounds
    assert c.bbox(HALF, 0, W - 1, H - 1) is None
    assert "doesn't fit" in caplog.text
    check_snapshot("ap_setup_oversized_qr", art, update_snapshots)


def test_ap_setup_scene_long_ssid_never_overflows_its_half(update_snapshots):
    """The default SSID is 20 characters -- 80px at 4px/char on the tiny
    font, against only ~62px available on one panel half. Pins down that
    _fit_text actually engages instead of DrawText silently overflowing
    into the QR's half or off the panel entirely."""
    c = canvas()
    make_renderer().draw_ap_setup(c, "NHL-Scoreboard-Setup", "scoreboard", None)
    art = show("ap_setup_long_ssid", c)

    assert not c.out_of_bounds
    box = c.bbox(0, 0, HALF - 1, H - 1)
    assert box is not None
    assert box.x1 < HALF
    check_snapshot("ap_setup_long_ssid", art, update_snapshots)


# --------------------------------------------------------------------------
# WiFi join outcome (#133)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "status", "ssid", "expect_color"),
    [
        ("wifi_join_attempting", "attempting", "HomeNetwork", WHITE),
        ("wifi_join_connected", "connected", "HomeNetwork", LIVE),
        ("wifi_join_failed", "failed", "HomeNetwork", ACCENT),
    ],
)
def test_wifi_join_scene(name, status, ssid, expect_color, update_snapshots):
    c = canvas()
    make_renderer().draw_wifi_join(c, status, ssid)
    art = show(name, c)

    assert not c.out_of_bounds
    # tolerance=2: text_center's integer division of an odd pixel width can
    # land a wider string like "CONNECTED!" up to ~1.5px off perfect centre
    # -- same font-glyph-width allowance CLAUDE.md documents elsewhere, not
    # a real layout bug.
    assert_centered(c, 0, 16, "title", tolerance=2.0)
    assert_centered(c, 20, H - 1, "subtitle", tolerance=2.0)
    assert expect_color in c.colors(0, 0, W - 1, 16)
    check_snapshot(name, art, update_snapshots)


def test_wifi_join_failed_rendering_does_not_depend_on_ssid():
    """The AP's real name might not be the default -- ap_setup's own scene
    (about to show next once this one's display window ends) is the one
    place that names it, from its own state file. Naming it here too would
    just be a second place it could go stale, so the "failed" message is
    fixed text regardless of which ssid is passed -- proven here by two
    wildly different ssids rendering identically."""
    renderer = make_renderer()
    first = canvas()
    renderer.draw_wifi_join(first, "failed", "SomeSpecificNetworkName")
    second = canvas()
    renderer.draw_wifi_join(second, "failed", "AnEntirelyDifferentNetwork")
    assert first.pixels == second.pixels


def test_wifi_join_long_ssid_never_overflows_the_panel():
    c = canvas()
    make_renderer().draw_wifi_join(c, "attempting", "A" * 60)
    assert not c.out_of_bounds


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
# matchup: season-series tally for the upcoming game (#157)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "record", "tally"),
    [
        ("matchup", SeasonSeriesRecord(away_wins=2, home_wins=1), "2-1"),
        ("matchup_preseason", SeasonSeriesRecord(away_wins=0, home_wins=0), "0-0"),
    ],
)
def test_matchup_logo_layout(synthetic_logos, name, record, tally, update_snapshots):
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_matchup(c, UPCOMING, record)
    art = show(f"logos, {name}: {tally} / SEASON SERIES", c)

    assert not c.out_of_bounds
    for x0, side in ((0, UPCOMING.away), (MID_RIGHT, UPCOMING.home)):
        assert team_color(side.abbrev) in c.colors(x0, 0, x0 + LOGO - 1, H - 1), (
            f"{side.abbrev} logo"
        )
    tally_box = c.bbox(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 1)
    assert tally_box and abs(tally_box.center_x - (W - 1) / 2) <= 1, "tally not centred"
    assert c.colors(MID_LEFT, 0, MID_RIGHT - 1, RULE_Y - 1) == {WHITE}
    assert c.lit(MID_LEFT + 3, RULE_Y, MID_RIGHT - 4, RULE_Y), "rule missing"
    assert_centered(c, STATUS_TOP, H - 1, "caption")
    assert status_color(c, MID_LEFT, MID_RIGHT - 1) == {SUBDUED}
    check_snapshot(f"logo_{name}", art, update_snapshots)


def test_matchup_text_layout(update_snapshots):
    c = canvas()
    make_renderer().draw_matchup(c, UPCOMING, SeasonSeriesRecord(2, 1))
    art = show("text, matchup: TOR 2-1 MTL / SEASON SERIES", c)

    assert not c.out_of_bounds
    top = c.colors(0, 0, W - 1, RULE_Y - 1)
    assert top == {team_color("TOR"), team_color("MTL"), WHITE}, "abbrevs in colour, tally white"
    assert_centered(c, 0, RULE_Y - 1, "tally line")
    assert c.row_is_solid(RULE_Y)
    assert_centered(c, STATUS_TOP, H - 1, "caption")
    assert status_color(c) == {SUBDUED}
    # Away on the left, like every other scene: TOR's colour sits left of MTL's.
    tor_x = [x for (x, _y), rgb in c.pixels.items() if rgb == team_color("TOR")]
    mtl_x = [x for (x, _y), rgb in c.pixels.items() if rgb == team_color("MTL")]
    assert max(tor_x) < min(mtl_x)
    check_snapshot("text_matchup", art, update_snapshots)


def test_matchup_missing_logo_falls_back_to_text(synthetic_logos):
    game = dataclasses.replace(UPCOMING, home=dataclasses.replace(UPCOMING.home, abbrev="ZZZ"))
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_matchup(c, game, SeasonSeriesRecord(1, 1))
    assert not c.out_of_bounds
    assert c.row_is_solid(RULE_Y), "text layout's full-width rule"


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


def assert_standings_layout(
    c: AsciiCanvas, rows: list[StandingsRow], favourite: str, *, logo_width: int = 0
) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    if logo_width:
        logo_region = c.lit(0, 0, logo_width - 1, H - 1)
        assert logo_region, "no logo drawn for the favourite"
        assert team_color(favourite) in set(logo_region.values()), "favourite logo colour wrong"
    for i, row in enumerate(rows):
        y0, y1 = i * STANDINGS_ROW_HEIGHT, i * STANDINGS_ROW_HEIGHT + STANDINGS_ROW_HEIGHT - 1
        band = c.bbox(logo_width, y0, W - 1, y1)
        assert band is not None, f"row {i} ({row.abbrev}) not drawn"
        colors = c.colors(logo_width, y0, W - 1, y1)
        highlight = ACCENT if row.abbrev == favourite else WHITE
        assert colors <= {highlight, team_color(row.abbrev)}, (
            f"row {i} ({row.abbrev}) has unexpected colours: {colors}"
        )
        assert team_color(row.abbrev) in colors, f"row {i} ({row.abbrev}) not in its team colour"


def test_leaders_layout_labels_conference_and_fits_five_rows(update_snapshots):
    names = ["COL", "DAL", "NSH", "STL", "WPG"]
    rows = [standings_row(a, i, 60 - i) for i, a in enumerate(names, 1)]
    c = canvas()
    make_renderer().draw_conference_leaders(c, rows, "NSH")
    art = show("leaders, west, favourite present", c)
    assert not c.out_of_bounds
    label = c.lit(0, 0, 31, H - 1)
    assert label, "conference label missing"
    assert set(label.values()) == {WHITE}
    for i, row in enumerate(rows):
        y0 = i * STANDINGS_ROW_HEIGHT
        colors = c.colors(32, y0, W - 1, y0 + STANDINGS_ROW_HEIGHT - 1)
        assert team_color(row.abbrev) in colors
        assert colors <= {ACCENT if row.abbrev == "NSH" else WHITE, team_color(row.abbrev)}
    check_snapshot("leaders_west", art, update_snapshots)


def test_standings_logo_layout_favourite_centred(synthetic_logos, update_snapshots):
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_standings(c, FAVOURITE_WINDOW, "NSH")
    art = show("standings w/ logo, favourite centred (NSH 6th)", c)

    assert_standings_layout(c, FAVOURITE_WINDOW, "NSH", logo_width=LOGO)
    assert ACCENT in c.colors(LOGO, 2 * STANDINGS_ROW_HEIGHT, W - 1, 3 * STANDINGS_ROW_HEIGHT - 1)
    check_snapshot("standings_logo_favourite_centred", art, update_snapshots)


def test_standings_logo_layout_favourite_clamped_to_top(synthetic_logos, update_snapshots):
    window = [
        standings_row("NSH", 1, 50),
        standings_row("WPG", 2, 48),
        standings_row("DAL", 3, 46),
        standings_row("STL", 4, 44),
        standings_row("COL", 5, 42),
    ]
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_standings(c, window, "NSH")
    art = show("standings w/ logo, favourite 1st (extra rows below)", c)

    assert_standings_layout(c, window, "NSH", logo_width=LOGO)
    assert ACCENT in c.colors(LOGO, 0, W - 1, STANDINGS_ROW_HEIGHT - 1)
    check_snapshot("standings_logo_favourite_top", art, update_snapshots)


def test_standings_text_layout_no_logo_library(update_snapshots):
    """No ``LogoLibrary`` at all -- same fallback precedent as the game scene."""
    c = canvas()
    make_renderer().draw_standings(c, FAVOURITE_WINDOW, "NSH")
    art = show("standings, no logo library", c)

    assert_standings_layout(c, FAVOURITE_WINDOW, "NSH")
    check_snapshot("standings_text_fallback", art, update_snapshots)


def test_standings_missing_favourite_logo_falls_back_to_text(synthetic_logos, tmp_path):
    """A library that just doesn't have the favourite's crest: same fallback."""
    from PIL import Image

    without_nsh = tmp_path / "partial"
    without_nsh.mkdir()
    Image.open(synthetic_logos.path_for("SEA")).save(without_nsh / "SEA.png")
    c = canvas()
    make_renderer(logos=LogoLibrary([without_nsh])).draw_standings(c, FAVOURITE_WINDOW, "NSH")
    assert_standings_layout(c, FAVOURITE_WINDOW, "NSH")  # logo_width=0: the text layout's signature


def test_standings_layout_only_favourite_is_highlighted(synthetic_logos):
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_standings(c, FAVOURITE_WINDOW, "NSH")
    for i, row in enumerate(FAVOURITE_WINDOW):
        y0, y1 = i * STANDINGS_ROW_HEIGHT, i * STANDINGS_ROW_HEIGHT + STANDINGS_ROW_HEIGHT - 1
        colors = c.colors(LOGO, y0, W - 1, y1)
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


# --------------------------------------------------------------------------
# goal detail (#122 phase 2): scorer + season goals, assister(s) + season assists
# --------------------------------------------------------------------------


def goal_event(
    team: str, scorer="F. FORSBERG", goals=12, assists=(), strength="ev", player_id=8480000
) -> GoalEvent:
    return GoalEvent(
        team_abbrev=team,
        scorer_name=scorer,
        scorer_goals_to_date=goals,
        scorer_player_id=player_id,
        assists=tuple(
            AssistDetail(name=n, assists_to_date=a, sweater_number=0) for n, a in assists
        ),
        strength=strength,
    )


def assert_goal_detail_layout(c: AsciiCanvas, left: int, right: int) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    cx = (left + right) // 2

    name_box = c.bbox(left, 0, right - 1, 8)
    assert name_box is not None, "scorer name missing"
    assert abs(name_box.center_x - cx) <= 2, f"scorer name not centred: {name_box.center_x}"
    assert ACCENT in c.colors(left, 0, right - 1, 8), "scorer name should be amber"

    assert c.bbox(left, 12, right - 1, 16) is not None, "season goal total missing"
    assert c.colors(left, 12, right - 1, 16) == {WHITE}

    assist_region = c.lit(left, 18, right - 1, H - 1)
    assert assist_region, "assist line missing"
    assert set(assist_region.values()) == {SUBDUED}


@pytest.mark.parametrize(
    ("name", "assists"),
    [
        ("unassisted", ()),
        ("one_assist", (("J. SMITH", 5),)),
        ("two_assists", (("J. SMITH", 5), ("B. JOHNSON", 9))),
    ],
)
def test_logo_layout_goal_detail(games, synthetic_logos, name, assists, update_snapshots):
    game = games["live"]  # SEA 2 @ CGY 1
    event = goal_event(game.home.abbrev, assists=assists)
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_goal_detail(c, game, event)
    art = show(f"logos, goal detail ({name}): {event.scorer_name} #{event.scorer_goals_to_date}", c)

    assert_goal_detail_layout(c, MID_LEFT, MID_RIGHT)
    for x0, side in ((0, game.away), (MID_RIGHT, game.home)):
        logo_colors = c.colors(x0, 0, x0 + LOGO - 1, H - 1)
        assert team_color(side.abbrev) in logo_colors, f"{side.abbrev} logo"
    check_snapshot(f"logo_goal_detail_{name}", art, update_snapshots)


def test_text_layout_goal_detail(games, update_snapshots):
    game = games["live"]
    event = goal_event(game.home.abbrev, assists=(("J. SMITH", 5),))
    c = canvas()
    make_renderer().draw_goal_detail(c, game, event)
    art = show(f"text, goal detail: {event.scorer_name} #{event.scorer_goals_to_date}", c)

    assert_goal_detail_layout(c, 0, W)
    check_snapshot("text_goal_detail", art, update_snapshots)


def test_goal_detail_strength_badge_only_shown_when_not_even_strength(games, synthetic_logos):
    game = games["live"]
    ev = goal_event(game.home.abbrev, scorer="T. NOVAK", strength="ev")
    pp = goal_event(game.home.abbrev, scorer="T. NOVAK", strength="pp")
    r = make_renderer(logos=synthetic_logos)

    c_ev = canvas()
    r.draw_goal_detail(c_ev, game, ev)
    # Same scorer name in both cases -> the name's own pixels land in the
    # same place regardless of strength; the badge (if any) is to its right.
    name_box = c_ev.bbox(MID_LEFT, 0, MID_RIGHT - 1, 8)
    assert c_ev.colors(name_box.x1 + 1, 0, MID_RIGHT - 1, 8) == set(), "no badge at even strength"

    c_pp = canvas()
    r.draw_goal_detail(c_pp, game, pp)
    assert ACCENT in c_pp.colors(name_box.x1 + 1, 0, MID_RIGHT - 1, 8), "PP badge missing"


def test_goal_detail_falls_back_to_text_when_a_logo_is_missing(games, synthetic_logos, tmp_path):
    """Same fallback precedent as draw_game/draw_standings: a library missing
    just one side's crest still gets the text layout, not a crash."""
    from PIL import Image

    game = games["live"]
    event = goal_event(game.home.abbrev)
    without_home = tmp_path / "partial"
    without_home.mkdir()
    Image.open(synthetic_logos.path_for(game.away.abbrev)).save(
        without_home / f"{game.away.abbrev}.png"
    )
    c = canvas()
    make_renderer(logos=LogoLibrary([without_home])).draw_goal_detail(c, game, event)
    assert_goal_detail_layout(c, 0, W)  # full width: the text layout's signature


def test_goal_detail_reflects_the_actual_event(games, synthetic_logos):
    """A distinct scorer/assist must actually show up, not a stale one."""
    game = games["live"]
    c1 = canvas()
    make_renderer(logos=synthetic_logos).draw_goal_detail(
        c1, game, goal_event(game.home.abbrev, scorer="A. AHO", goals=30)
    )
    c2 = canvas()
    make_renderer(logos=synthetic_logos).draw_goal_detail(
        c2, game, goal_event(game.home.abbrev, scorer="J. TKACHUK", goals=2)
    )
    assert c1.pixels != c2.pixels


# --------------------------------------------------------------------------
# three stars (#156): title + one line per star, all on one frame
# --------------------------------------------------------------------------

# Rows each part of the frame owns: title, then star 1/2/3 (tiny face,
# baselines 6/14/22/30 in the renderer).
THREE_STARS_TITLE_ROWS = (0, 7)
THREE_STARS_LINE_ROWS = ((8, 15), (16, 23), (24, 31))


def a_star(rank: int, team: str, name: str, goals: int = 0, assists: int = 0, pos="C") -> Star:
    return Star(
        star=rank,
        player_id=8470000 + rank,
        team_abbrev=team,
        name=name,
        sweater_no=rank,
        position=pos,
        goals=goals,
        assists=assists,
        points=goals + assists,
    )


def three_stars_for(game: Game) -> tuple[Star, ...]:
    """Both teams represented, a multi-point skater, and a goalie with no skater stat."""
    return (
        a_star(1, game.home.abbrev, "N. Kadri", goals=2, assists=1),
        a_star(2, game.away.abbrev, "J. Eberle", goals=1),
        a_star(3, game.home.abbrev, "D. Vladar", pos="G"),
    )


def assert_three_stars_layout(c: AsciiCanvas, stars, left: int, right: int) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    cx = (left + right) // 2
    top, bottom = THREE_STARS_TITLE_ROWS
    title = c.bbox(left, top, right - 1, bottom)
    assert title is not None, "title missing"
    assert abs(title.center_x - cx) <= 2, f"title not centred: {title.center_x}"
    assert c.colors(left, top, right - 1, bottom) == {ACCENT}

    for (y0, y1), s in zip(THREE_STARS_LINE_ROWS, stars, strict=False):
        line = c.bbox(left, y0, right - 1, y1)
        assert line is not None, f"star {s.star} line missing"
        assert line.x0 >= left and line.x1 < right, f"star {s.star} spills out of its column"
        # Rank leads the line, in amber.
        assert c.colors(left, y0, left + 4, y1) == {ACCENT}, f"star {s.star} rank"
        colors = c.colors(left, y0, right - 1, y1)
        assert team_color(s.team_abbrev) in colors, f"star {s.star} name not in team colour"
        has_stat = bool(s.goals or s.assists)
        assert (WHITE in colors) == has_stat, f"star {s.star} stat shown iff it has points"


@pytest.mark.parametrize("layout", ["logo", "text"])
def test_three_stars(games, synthetic_logos, layout, update_snapshots):
    game = games["live"]  # SEA @ CGY
    stars = three_stars_for(game)
    c = canvas()
    make_renderer(logos=synthetic_logos if layout == "logo" else None).draw_three_stars(
        c, game, stars
    )
    art = show(f"{layout}, three stars: {', '.join(s.name for s in stars)}", c)

    if layout == "logo":
        assert_three_stars_layout(c, stars, MID_LEFT, MID_RIGHT)
        for x0, side in ((0, game.away), (MID_RIGHT, game.home)):
            assert team_color(side.abbrev) in c.colors(x0, 0, x0 + LOGO - 1, H - 1)
    else:
        assert_three_stars_layout(c, stars, 0, W)
    check_snapshot(f"{layout}_three_stars", art, update_snapshots)


def test_three_stars_all_from_one_team_are_all_drawn(games):
    """Whoever the NHL named -- nothing filters stars to the favourite's side."""
    game = games["live"]
    stars = tuple(a_star(i, game.away.abbrev, f"P. Away{i}", goals=1) for i in (1, 2, 3))
    c = canvas()
    make_renderer().draw_three_stars(c, game, stars)
    assert_three_stars_layout(c, stars, 0, W)
    for y0, y1 in THREE_STARS_LINE_ROWS:
        assert team_color(game.home.abbrev) not in c.colors(0, y0, W - 1, y1)


def test_three_stars_long_name_falls_back_to_the_surname_between_logos(games, synthetic_logos):
    game = games["live"]
    long = a_star(1, game.home.abbrev, "R. Nugent-Hopkins", goals=1)
    r = make_renderer(logos=synthetic_logos)

    c = canvas()
    r.draw_three_stars(c, game, (long,))
    assert_three_stars_layout(c, (long,), MID_LEFT, MID_RIGHT)
    # The stat (white) keeps its own slot at the column's right edge: the
    # rank and name (everything else on the line) never run into it.
    y0, y1 = THREE_STARS_LINE_ROWS[0]
    line = {x: rgb for (x, y), rgb in c.lit(MID_LEFT, y0, MID_RIGHT - 1, y1).items()}
    others = [x for x, rgb in line.items() if rgb != WHITE]
    stat = [x for x, rgb in line.items() if rgb == WHITE]
    assert stat and max(others) < min(stat), "name overlaps the stat"

    tiny = r.fonts.tiny
    assert Renderer._fit_name(tiny, "N. Kadri", 40) == "N. Kadri", "fits: kept whole"
    assert Renderer._fit_name(tiny, "R. Nugent-Hopkins", 56) == "Nugent-Hopkins"
    assert Renderer._fit_name(tiny, "R. Nugent-Hopkins", 44) == "Nugent-H..."


def test_three_stars_stat_is_one_token():
    assert Renderer._star_stat(a_star(1, "NSH", "A", goals=2)) == "2G"
    assert Renderer._star_stat(a_star(1, "NSH", "A", assists=1)) == "1A"
    assert Renderer._star_stat(a_star(1, "NSH", "A", goals=2, assists=1)) == "3P"
    assert Renderer._star_stat(a_star(1, "NSH", "A", pos="G")) == ""


def test_three_stars_falls_back_to_text_when_a_logo_is_missing(games, synthetic_logos, tmp_path):
    from PIL import Image

    game = games["live"]
    stars = three_stars_for(game)
    without_home = tmp_path / "partial"
    without_home.mkdir()
    Image.open(synthetic_logos.path_for(game.away.abbrev)).save(
        without_home / f"{game.away.abbrev}.png"
    )
    c = canvas()
    make_renderer(logos=LogoLibrary([without_home])).draw_three_stars(c, game, stars)
    assert_three_stars_layout(c, stars, 0, W)  # full width: the text layout's signature


# --------------------------------------------------------------------------
# narrow panel: a single 64x32 (chain_length=1), not the default 128x32
# chain -- #38. Two full 32px logos would meet with zero room left for the
# score column, so each logo crops its centre-facing edge (Renderer.
# _logo_span) instead of shrinking. NARROW_VISIBLE mirrors that: half the
# full logo, the floor the renderer never crops past.
# --------------------------------------------------------------------------

NARROW_W = 64
NARROW_VISIBLE = LOGO // 2
NARROW_LEFT, NARROW_RIGHT = NARROW_VISIBLE, NARROW_W - NARROW_VISIBLE
NARROW_CENTRE = (NARROW_LEFT + NARROW_RIGHT) // 2


def make_narrow_renderer(logos: LogoLibrary | None = None) -> Renderer:
    return Renderer(
        graphics=graphics, fonts=FontSet(graphics), width=NARROW_W, height=H, tz=TZ, logos=logos
    )


def assert_narrow_logo_layout(c: AsciiCanvas, game: Game) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"

    away_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(game.away.abbrev)}
    home_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(game.home.abbrev)}
    assert away_px, f"no logo drawn for {game.away.abbrev}"
    assert home_px, f"no logo drawn for {game.home.abbrev}"
    # The crop must actually hold: nothing of either logo may reach into the
    # column reserved for scores, unlike a full 32px logo at this width.
    assert max(x for x, _ in away_px) < NARROW_LEFT, "away logo bleeds past its cropped edge"
    assert min(x for x, _ in home_px) >= NARROW_RIGHT, "home logo bleeds past its cropped edge"

    away_box = c.bbox(NARROW_LEFT, 0, NARROW_CENTRE - 1, SCORE_BASELINE)
    home_box = c.bbox(NARROW_CENTRE, 0, NARROW_RIGHT - 1, SCORE_BASELINE)
    assert away_box is not None, f"no score drawn for {game.away.abbrev}"
    assert home_box is not None, f"no score drawn for {game.home.abbrev}"
    assert away_box.x1 < home_box.x0, "scores collide on a narrow panel"


def test_logo_layout_narrow_panel(games, synthetic_logos, update_snapshots):
    game = games["live"]  # SEA 2 @ CGY 1
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_game(c, game)
    art = show(
        f"narrow logos, live: {game.away.abbrev} {game.away.score} @ "
        f"{game.home.abbrev} {game.home.score}",
        c,
    )
    assert_narrow_logo_layout(c, game)
    box = c.bbox(NARROW_LEFT, STATUS_TOP, NARROW_RIGHT - 1, H - 1)
    assert box is not None, "status line missing"
    assert abs(box.center_x - (NARROW_CENTRE - 0.5)) <= 1, f"status not centred: {box.center_x}"
    check_snapshot("logo_narrow_live", art, update_snapshots)


def test_logo_layout_narrow_panel_two_digit_scores(
    big_score_game, synthetic_logos, update_snapshots
):
    """The tightest case: two-digit scores must still clear each other (#38)."""
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_game(c, big_score_game)
    art = show("narrow logos, big score: EDM 12 @ CGY 10", c)
    assert_narrow_logo_layout(c, big_score_game)
    check_snapshot("logo_narrow_big_score", art, update_snapshots)


def test_logo_layout_narrow_panel_goal(games, synthetic_logos, update_snapshots):
    game = games["live"]
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_goal(c, game)
    art = show(f"narrow logos, goal: {game.away.abbrev} {game.away.score}-{game.home.score}", c)

    assert not c.out_of_bounds
    away_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(game.away.abbrev)}
    home_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(game.home.abbrev)}
    assert away_px and max(x for x, _ in away_px) < NARROW_LEFT
    assert home_px and min(x for x, _ in home_px) >= NARROW_RIGHT
    goal_box = c.bbox(NARROW_LEFT, 0, NARROW_RIGHT - 1, RULE_Y - 1)
    assert goal_box is not None, "GOAL text missing"
    check_snapshot("logo_narrow_goal", art, update_snapshots)


def test_upcoming_logo_layout_narrow_panel(synthetic_logos, update_snapshots):
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_preview(c, UPCOMING, PUCK_DROP - timedelta(hours=9))
    art = show("narrow logos, preview: TONIGHT / 8:00P", c)

    assert not c.out_of_bounds
    away_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(UPCOMING.away.abbrev)}
    home_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(UPCOMING.home.abbrev)}
    assert away_px and max(x for x, _ in away_px) < NARROW_LEFT
    assert home_px and min(x for x, _ in home_px) >= NARROW_RIGHT
    top_box = c.bbox(NARROW_LEFT, 0, NARROW_RIGHT - 1, RULE_Y - 1)
    assert top_box is not None, "top line missing"
    check_snapshot("logo_narrow_preview", art, update_snapshots)


def test_matchup_logo_layout_narrow_panel(synthetic_logos, update_snapshots):
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_matchup(c, UPCOMING, SeasonSeriesRecord(2, 1))
    art = show("narrow logos, matchup: 2-1 / SERIES", c)

    assert not c.out_of_bounds
    away_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(UPCOMING.away.abbrev)}
    home_px = {xy for xy, rgb in c.pixels.items() if rgb == team_color(UPCOMING.home.abbrev)}
    assert away_px and max(x for x, _ in away_px) < NARROW_LEFT
    assert home_px and min(x for x, _ in home_px) >= NARROW_RIGHT
    tally_box = c.bbox(NARROW_LEFT, 0, NARROW_RIGHT - 1, RULE_Y - 1)
    assert tally_box is not None, "tally missing"
    caption = c.bbox(NARROW_LEFT, STATUS_TOP, NARROW_RIGHT - 1, H - 1)
    assert caption is not None, "caption missing"
    assert c.colors(NARROW_LEFT, STATUS_TOP, NARROW_RIGHT - 1, H - 1) == {SUBDUED}
    check_snapshot("logo_narrow_matchup", art, update_snapshots)


def test_matchup_text_layout_narrow_panel(update_snapshots):
    """The large face doesn't fit "TOR 2-1 MTL" in 64px; the small one does."""
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer().draw_matchup(c, UPCOMING, SeasonSeriesRecord(2, 1))
    art = show("narrow text, matchup: TOR 2-1 MTL / SEASON SERIES", c)

    assert not c.out_of_bounds
    top = c.colors(0, 0, NARROW_W - 1, RULE_Y - 1)
    assert {team_color("TOR"), team_color("MTL"), WHITE} <= top
    caption = c.bbox(0, STATUS_TOP, NARROW_W - 1, H - 1)
    assert caption is not None and abs(caption.center_x - (NARROW_W - 1) / 2) <= 1
    check_snapshot("text_narrow_matchup", art, update_snapshots)


def test_goal_detail_narrow_panel_stays_on_panel(games, synthetic_logos):
    """No dedicated crop guarantee for this scene's text the way _logo_span
    gives game/goal/preview (#38): a scorer/assister name has no fixed max
    length the way a score or "GOAL" does. This only promises no off-panel
    pixels on the narrowest supported panel, not zero visual overlap with
    the cropped logo art beside it for an unusually long name."""
    game = games["live"]
    event = goal_event(
        game.home.abbrev, scorer="F. FORSBERG", assists=(("B. JOHNSON", 9),), strength="pp"
    )
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_goal_detail(c, game, event)
    assert not c.out_of_bounds


def test_three_stars_narrow_panel_stays_in_the_middle_column(games, synthetic_logos):
    """At 64px the column between cropped logos is 32px: names shrink to a
    truncated surname, but nothing leaves the column or the panel (#38)."""
    game = games["live"]
    stars = three_stars_for(game)
    c = AsciiCanvas(NARROW_W, H)
    make_narrow_renderer(synthetic_logos).draw_three_stars(c, game, stars)
    assert not c.out_of_bounds
    for y0, y1 in THREE_STARS_LINE_ROWS:
        line = c.bbox(NARROW_LEFT, y0, NARROW_RIGHT - 1, y1)
        assert line is not None
        assert line.x0 >= NARROW_LEFT and line.x1 < NARROW_RIGHT


# --------------------------------------------------------------------------
# leaders: the favourite's top players (#201)
# --------------------------------------------------------------------------

LEADERS = TeamLeaders(
    goals=SkaterLine(1, "F. Forsberg", 14, 9, 23),
    points=SkaterLine(2, "R. Oreilly", 9, 17, 26),
    goalies=(
        GoalieLine(3, "J. Saros", 22, 13, 7, 2, 0.915),
        GoalieLine(4, "J. Wright", 9, 4, 3, 1, 0.902),
    ),
)


def assert_leaders_layout(c: AsciiCanvas, rows: int, *, logo_width: int = 0) -> None:
    assert not c.out_of_bounds, f"drew outside the panel at {c.out_of_bounds[:5]}"
    if logo_width:
        assert team_color("NSH") in c.colors(0, 0, logo_width - 1, H - 1), "favourite logo missing"
    assert c.bbox(logo_width, 0, W - 1, 5) is not None, "title missing"
    for i in range(1, rows + 1):
        y0 = i * STANDINGS_ROW_HEIGHT
        band = c.bbox(logo_width, y0, W - 1, y0 + STANDINGS_ROW_HEIGHT - 1)
        assert band is not None, f"row {i} not drawn"
    assert c.bbox(logo_width, (rows + 1) * STANDINGS_ROW_HEIGHT, W - 1, H - 1) is None


def test_leaders_logo_layout(synthetic_logos):
    c = canvas()
    make_renderer(logos=synthetic_logos).draw_leaders(c, LEADERS, "NSH")
    show("leaders w/ logo", c)
    assert_leaders_layout(c, 4, logo_width=LOGO)


def test_leaders_text_layout_no_logo_library():
    c = canvas()
    make_renderer().draw_leaders(c, LEADERS, "NSH")
    show("leaders, no logo library", c)
    assert_leaders_layout(c, 4)


def test_leaders_missing_rows_close_up(synthetic_logos):
    c = canvas()
    only_goalie = TeamLeaders(goals=None, points=None, goalies=LEADERS.goalies[:1])
    make_renderer(logos=synthetic_logos).draw_leaders(c, only_goalie, "NSH")
    assert_leaders_layout(c, 1, logo_width=LOGO)


def test_leaders_long_name_never_leaves_the_panel(synthetic_logos):
    c = canvas()
    long = TeamLeaders(
        goals=SkaterLine(1, "A. Wolfeschlegelsteinhausen", 10, 0, 10),
        points=None,
        goalies=(),
    )
    make_renderer(logos=synthetic_logos).draw_leaders(c, long, "NSH")
    assert not c.out_of_bounds
