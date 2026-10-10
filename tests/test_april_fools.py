"""April Fools' on a Predators board (#248): the logic, and the app's fences.

What the pranked standings screen looks like is snapshotted in
``test_render.py`` with every other scene.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from nhl_scoreboard import april_fools
from nhl_scoreboard.app import Scene, ScoreboardApp
from nhl_scoreboard.config import Settings
from nhl_scoreboard.display.logos import LogoLibrary, default_directories
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.display.teams import GUEST_COLORS, TEAM_COLORS, team_color
from nhl_scoreboard.nhl.models import Game, StandingsRow
from test_app import FakeClient, FakeClockSource, FakeGraphics, FakeMatrix, FakeOptions

# 10:00 CDT on April 1 2027 -- inside the window for the default timezone.
APRIL_1_MORNING = datetime(2027, 4, 1, 15, 0, tzinfo=UTC)


def row(abbrev: str, seq: int, gp: int = 70) -> StandingsRow:
    return StandingsRow(
        abbrev=abbrev,
        conference="W",
        division="C",
        division_sequence=1,
        wildcard_sequence=0,
        conference_sequence=seq,
        clinch_indicator="",
        points=100 - seq * 3,
        games_played=gp,
        wins=40 - seq,
        losses=20 + seq,
        ot_losses=10,
    )


def conference(nsh_at: int, size: int = 16) -> list[StandingsRow]:
    names = ["WPG", "DAL", "VGK", "LAK", "COL", "EDM", "MIN", "STL", "CGY", "VAN", "UTA"]
    names += ["ANA", "SEA", "CHI", "SJS"]
    names.insert(nsh_at - 1, "NSH")
    return [row(name, i) for i, name in enumerate(names[:size], start=1)]


def game(away: str, home: str, state: str = "FUT") -> Game:
    return Game.from_api(
        {
            "id": 1,
            "gameState": state,
            "startTimeUTC": "2027-04-01T23:00:00Z",
            "awayTeam": {"abbrev": away, "score": 2},
            "homeTeam": {"abbrev": home, "score": 3},
            "clock": {"timeRemaining": "10:00", "running": state == "LIVE"},
        }
    )


# -- the window -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("favourite", "local", "expected"),
    [
        ("NSH", datetime(2027, 4, 1, 0, 0), True),
        ("NSH", datetime(2027, 4, 1, 23, 59), True),
        ("NSH", datetime(2027, 4, 2, 0, 0), False),
        ("NSH", datetime(2027, 3, 31, 10, 0), False),
        ("NSH", datetime(2027, 4, 2, 10, 0), False),
        ("DAL", datetime(2027, 4, 1, 10, 0), False),
        ("", datetime(2027, 4, 1, 10, 0), False),
    ],
)
def test_only_a_preds_board_only_on_april_first(favourite, local, expected):
    assert april_fools.active(favourite, local) is expected


# -- the pranks -----------------------------------------------------------------


def test_game_swap_relabels_only_the_preds_side():
    original = game("DAL", "NSH")
    swapped = april_fools.swap_game(original)
    assert (swapped.away.abbrev, swapped.home.abbrev) == ("DAL", "MIL")
    assert (swapped.away.score, swapped.home.score) == (2, 3)
    assert swapped.start_utc == original.start_utc


def test_mid_table_preds_drop_to_last_winless():
    pranked = april_fools.prank_conference(conference(nsh_at=6))
    assert "NSH" not in [r.abbrev for r in pranked]
    last = pranked[-1]
    assert last.abbrev == "MIL"
    assert (last.wins, last.losses, last.ot_losses, last.points) == (0, 70, 0, 0)
    assert [r.conference_sequence for r in pranked] == list(range(1, 17))
    assert [r.abbrev for r in pranked[:5]] == ["WPG", "DAL", "VGK", "LAK", "COL"]


def test_preds_already_last_jump_to_first_unbeaten_instead():
    pranked = april_fools.prank_conference(conference(nsh_at=16))
    first = pranked[0]
    assert first.abbrev == "MIL"
    assert (first.wins, first.losses, first.points) == (70, 0, 140)
    assert pranked[-1].abbrev != "MIL", "never shown in their true spot"
    assert [r.conference_sequence for r in pranked] == list(range(1, 17))


def test_admirals_logo_and_colours_ship_without_becoming_an_nhl_team():
    logo = LogoLibrary(default_directories(32, "dark")).get("MIL")
    assert logo is not None
    assert (logo.width, logo.height) == (32, 32)
    assert team_color("MIL") == GUEST_COLORS["MIL"]
    assert "MIL" not in TEAM_COLORS, "TEAM_COLORS drives logo fetching and horn uploads"


# -- the app's fences ------------------------------------------------------------


@pytest.fixture
def app():
    src = FakeClockSource()
    now = {"t": APRIL_1_MORNING}
    application = ScoreboardApp(
        Settings(),
        client=FakeClient([]),
        backend=Backend("fake", FakeMatrix, FakeOptions, FakeGraphics),
        clock=lambda: now["t"],
        monotonic=src.monotonic,
        sleep=src.sleep,
    )
    calls: list[tuple[str, tuple]] = []
    for name in ("draw_game", "draw_goal", "draw_countdown", "draw_clock", "draw_standings"):
        setattr(application.renderer, name, lambda *a, _n=name: calls.append((_n, a[1:])))
    application.calls = calls
    application.now = now
    return application


def test_clock_and_countdown_are_pranked(app):
    app.draw_scene(Scene("clock"))
    app.draw_scene(Scene("countdown", game("DAL", "NSH")))
    (_, clock_args), (_, countdown_args) = app.calls
    assert clock_args[1] == "MIL"
    assert countdown_args[0].home.abbrev == "MIL"


@pytest.mark.parametrize("kind", ["game", "goal"])
def test_a_real_game_is_never_pranked(app, kind):
    app.draw_scene(Scene(kind, game("DAL", "NSH", state="LIVE")))
    ((_, args),) = app.calls
    assert args[0].home.abbrev == "NSH"


def test_it_lasts_until_local_midnight(app):
    app.now["t"] = datetime(2027, 4, 2, 4, 59, tzinfo=UTC)  # 23:59 CDT, Apr 1
    app.draw_scene(Scene("clock"))
    app.now["t"] = datetime(2027, 4, 2, 5, 0, tzinfo=UTC)  # 00:00 CDT, Apr 2
    app.draw_scene(Scene("clock"))
    assert [c[1][1] for c in app.calls] == ["MIL", "NSH"]


def test_it_ignores_the_holiday_cheer_switch(app):
    app.settings.holiday = dataclasses.replace(app.settings.holiday, enabled=False)
    assert app.april_fools_active()


def test_standings_scene_is_built_from_the_pranked_conference(app):
    app._refresh_standings = lambda **_: conference(nsh_at=6)
    scene = app._standings_scene()
    assert scene.standings[-1].abbrev == "MIL"
    assert scene.standings[-1].points == 0
    app.draw_scene(scene)
    assert app.calls[-1][1][1] == "MIL", "MIL highlighted and its logo drawn"
