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
from nhl_scoreboard.nhl.models import Game, GoalEvent, StandingsRow, Star
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
def test_live_games_are_relabelled_too_but_the_score_is_real(app, kind):
    app.draw_scene(Scene(kind, game("DAL", "NSH", state="LIVE")))
    ((_, args),) = app.calls
    assert args[0].home.abbrev == "MIL"
    assert (args[0].away.score, args[0].home.score) == (2, 3)


def test_goal_detail_and_three_stars_relabel_in_step_with_the_game():
    event = GoalEvent(
        team_abbrev="NSH",
        scorer_name="F. Forsberg",
        scorer_goals_to_date=10,
        scorer_player_id=1,
        assists=(),
        strength="ev",
    )
    star = Star(1, 2, "NSH", "J. Saros", 74, "G", 0, 0, 0)
    scene = ScoreboardApp._april_fools_scene(
        Scene("goal_detail", game("DAL", "NSH"), goal_event=event, stars=(star,))
    )
    assert scene.game.home.abbrev == scene.goal_event.team_abbrev == "MIL"
    assert scene.stars[0].team_abbrev == "MIL"


def test_conference_leaders_relabel_without_moving_anyone():
    rows = tuple(conference(nsh_at=3)[:5])
    scene = ScoreboardApp._april_fools_scene(Scene("conference_leaders", standings=rows))
    assert [r.abbrev for r in scene.standings] == ["WPG", "DAL", "MIL", "VGK", "LAK"]
    assert [r.points for r in scene.standings] == [r.points for r in rows]


def test_it_lasts_until_local_midnight(app):
    app.now["t"] = datetime(2027, 4, 2, 4, 59, tzinfo=UTC)  # 23:59 CDT, Apr 1
    app.draw_scene(Scene("clock"))
    app.now["t"] = datetime(2027, 4, 2, 5, 0, tzinfo=UTC)  # 00:00 CDT, Apr 2
    app.draw_scene(Scene("clock"))
    assert [c[1][1] for c in app.calls] == ["MIL", "NSH"]


def test_it_ignores_the_holiday_cheer_switch(app):
    app.settings.holiday = dataclasses.replace(app.settings.holiday, enabled=False)
    assert app.april_fools_active()


@pytest.mark.parametrize("kind", ["standings", "conference_leaders"])
def test_standings_relabel_in_their_real_spot_with_their_real_record(app, kind):
    rows = tuple(conference(nsh_at=6)[3:8])
    scene = ScoreboardApp._april_fools_scene(Scene(kind, standings=rows))
    assert [r.abbrev for r in scene.standings] == ["LAK", "COL", "MIL", "EDM", "MIN"]
    nsh, mil = rows[2], scene.standings[2]
    assert (mil.conference_sequence, mil.points, mil.record_label()) == (
        nsh.conference_sequence,
        nsh.points,
        nsh.record_label(),
    )
    app.draw_scene(Scene("standings", standings=rows))
    assert app.calls[-1][1][1] == "MIL", "MIL highlighted and its logo drawn"
