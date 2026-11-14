"""``fb_bye`` (#425): the favourite's bye week, from the scoreboard's ``teamsOnBye``."""

from __future__ import annotations

import json

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.football_idle import next_game_line
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import ByeView, PreviewView, build_bye
from nhl_scoreboard.football.models import FbGame
from test_football_idle_preview import FIXTURES, NYG, SCHEDULE, Logos, utc
from test_football_scenes import H, check_snapshot, renderer

WEEK8 = json.loads((FIXTURES / "scoreboard_week8_byes_trimmed.json").read_text())
BOARD = idle.scoreboard_from_payload(WEEK8, [FbGame.from_api(e) for e in WEEK8["events"]])


def ctx(favourite="NYG", board=BOARD, schedule=SCHEDULE, now=utc(2026, 11, 3, 12)):
    snap = idle.IdleSnapshot(
        scoreboard=board, schedules={NYG: idle.Cached(schedule, 0.0)} if schedule else {}
    )
    return IdleContext(0.0, now, [], snap, FootballConfig(favourite_team=favourite))


def test_the_fixtures_two_sources_agree_on_the_bye():
    """The scoreboard's week 8 lists NYG on a bye and the team schedule says byeWeek 8."""
    assert BOARD.week == 8 and BOARD.on_bye("NYG")
    assert SCHEDULE.bye_week == BOARD.week


def test_shown_for_a_team_on_a_bye_with_its_next_game():
    view = build_bye(ctx())
    assert view.team == "NYG"
    assert (view.next_game.away, view.next_game.home) == ("PHI", "NYG")


def test_not_shown_when_the_favourite_plays_or_nobody_is_followed():
    assert build_bye(ctx(favourite="DAL")) is None  # DAL is not on this week's bye list
    assert build_bye(ctx(favourite="")) is None
    assert build_bye(ctx(favourite="XXX")) is None


def test_not_shown_before_the_scoreboard_has_answered():
    assert build_bye(ctx(board=None)) is None


def test_without_a_schedule_it_is_the_bye_alone():
    view = build_bye(ctx(schedule=None))
    assert view == ByeView("NYG", None)


def test_every_listed_bye_team_gets_the_screen_when_it_is_the_favourite():
    assert set(BOARD.teams_on_bye) == {"NO", "NYG", "SF", "HOU"}
    for team in BOARD.teams_on_bye:
        assert build_bye(ctx(favourite=team)).team == team


def test_the_registry_builds_the_same_view():
    assert IDLE_SCREENS["fb_bye"](ctx()) == build_bye(ctx())
    assert IDLE_SCREENS["fb_bye"](ctx(favourite="DAL")) is None


NEXT = PreviewView("NYG", "DAL", utc(2026, 11, 22, 18), "", "WEEK 11")
HOME = PreviewView("DAL", "NYG", utc(2026, 11, 22, 18), "", "WEEK 11")


def test_the_next_game_line_says_at_for_away_and_vs_for_home():
    r = renderer()
    assert next_game_line(NEXT, "NYG", r) == "SUN 11/22 AT DAL"
    assert next_game_line(HOME, "NYG", r) == "SUN 11/22 VS DAL"


def draw(view, logos=True, width=128):
    r = renderer(width)
    r.nfl_logos = Logos() if logos else None
    c = AsciiCanvas(width, H)
    r.draw_fb_bye(c, view, utc(2026, 11, 3))
    return c


def test_snapshots(update_snapshots):
    for name, view in (("fb_bye", ByeView("NYG", NEXT)), ("fb_bye_no_next", ByeView("NYG"))):
        c = draw(view)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


def test_every_team_and_both_home_and_away_fit_the_panel():
    from nhl_scoreboard.football.teams import TEAMS

    for abbrev in TEAMS:
        for next_game in (None, PreviewView(abbrev, "WSH", NEXT.start_utc, "", ""),
                          PreviewView("KC", abbrev, NEXT.start_utc, "", "")):  # fmt: skip
            c = draw(ByeView(abbrev, next_game), logos=abbrev != "KC")
            assert not c.out_of_bounds and c.pixels, abbrev


def test_the_title_takes_the_teams_colour_and_a_missing_next_game_leaves_it_alone():
    with_next, alone = draw(ByeView("NYG", NEXT)), draw(ByeView("NYG"))
    assert len(alone.pixels) < len(with_next.pixels)
    from nhl_scoreboard.football.teams import team_color

    assert team_color("NYG") in set(alone.pixels.values())


from test_football_idle import Clock, IdleFeed  # noqa: E402
from test_football_scenes import _pixels, app, game  # noqa: E402,F401  (the real-app fixture)


class Feed(IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None


def test_a_favourite_on_a_bye_gets_the_bye_in_the_real_rotation_and_the_app_draws_it(
    app,  # noqa: F811
):
    from nhl_scoreboard.football.mode import NflMode

    other = game("DAL", "PHI", "pre", short="x", start="2026-11-22T18:00Z", game_id=5)
    clock, feed = Clock(960.0), Feed([other])  # the IdleFeed's scoreboard lists CHI on a bye
    cfg = FootballConfig(favourite_team="CHI")
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    seen = {}
    for t in range(0, 60):
        clock.t = 960.0 + t
        scene = mode.scene()
        seen.setdefault(scene.kind, scene)
    assert "fb_bye" in seen and seen["fb_bye"].fb_idle.team == "CHI"
    assert _pixels(app, seen["fb_bye"]), "the app draws it"
    cfg.favourite_team = "NYG"  # plays this week: no bye
    assert "fb_bye" not in {mode.scene().kind for _ in range(1)}
