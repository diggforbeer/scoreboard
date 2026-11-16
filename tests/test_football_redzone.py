"""The red zone alert over the idle screens: the watcher, the screen, the mode and the settings."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from scoreboard.config import FootballConfig
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.football import redzone as rz
from scoreboard.football.mode import FootballMode
from scoreboard.football.models import FbGame, FbSituation
from scoreboard.football.redzone import RedZoneWatcher, attacking_team
from scoreboard.football.teams import TEAMS
from teamcfg import fcfg
from test_football_idle import Clock
from test_football_idle_selection import (
    BASE,
    IdleFeed,
    Utc,
    nyg_game,
    register,
    stand_ins,  # noqa: F401 - the autouse fixture that puts the idle screens back after each test
)
from test_football_scenes import game, renderer

NYG, DAL, KC, LV = (TEAMS[a].espn_id for a in ("NYG", "DAL", "KC", "LV"))


def with_situation(g: FbGame, team_id: int | None, red: bool = True, spot="DAL 14") -> FbGame:
    sit = FbSituation(
        down=2, distance=7, yard_line=14, short_down_distance_text="2nd & 7",
        down_distance_text=f"2nd & 7 at {spot}", possession_text=spot,
        possession_team_id=team_id, is_red_zone=red, home_timeouts=3, away_timeouts=3,
        last_play=None,
    )  # fmt: skip
    return dataclasses.replace(g, situation=sit)


def live(away="DAL", home="NYG", game_id=1):
    return game(away, home, "in", 7, 10, game_id=game_id)


def watcher():
    clock = Clock(BASE)
    return RedZoneWatcher(clock), clock


# -- who is in the zone ------------------------------------------------------------------------


def test_only_a_live_game_with_the_flag_and_a_known_possessor_is_in_the_zone():
    g = live()
    assert attacking_team(with_situation(g, NYG)) == NYG
    assert attacking_team(with_situation(g, NYG, red=False)) is None
    assert attacking_team(with_situation(g, None)) is None
    assert attacking_team(with_situation(g, 999)) is None, "a team that is not in this game"
    assert attacking_team(g) is None, "no situation"
    final = game("DAL", "NYG", "post", 7, 10, short="Final")
    assert attacking_team(with_situation(final, NYG)) is None


# -- the watcher --------------------------------------------------------------------------------


def test_a_game_already_in_the_zone_when_first_seen_does_not_alert():
    w, _ = watcher()
    w.observe([with_situation(live(), NYG)])
    assert w.waiting == 0 and w.current([live()], 6.0) is None


def test_going_into_the_zone_alerts_once_and_staying_there_does_not_repeat():
    w, clock = watcher()
    outside = with_situation(live(), NYG, red=False)
    inside = with_situation(live(), NYG)
    w.observe([outside])
    w.observe([inside])
    shown = w.current([inside], 6.0)
    assert shown is not None and shown[0].id == 1 and shown[1] == 0.0
    clock.t += 3
    w.observe([inside])
    assert w.current([inside], 6.0)[1] == 3.0 and w.waiting == 0


def test_the_alert_lasts_its_seconds_then_the_idle_screen_returns():
    w, clock = watcher()
    w.observe([with_situation(live(), NYG, red=False)])
    inside = with_situation(live(), NYG)
    w.observe([inside])
    assert w.current([inside], 6.0) is not None
    clock.t += 6.0
    assert w.current([inside], 6.0) is None


def test_a_game_that_flickers_at_the_edge_alerts_once_per_cooldown():
    w, clock = watcher()
    out, inn = with_situation(live(), NYG, red=False), with_situation(live(), NYG)
    w.observe([out])
    w.observe([inn])
    w.current([inn], 6.0)
    clock.t += 7
    w.observe([out])
    w.observe([inn])  # back in 7 seconds later: inside the cooldown
    assert w.waiting == 0
    clock.t += rz.COOLDOWN
    w.observe([out])
    w.observe([inn])
    assert w.waiting == 1


def test_two_games_entering_together_queue_one_after_the_other():
    w, clock = watcher()
    a_out, b_out = (
        with_situation(live(game_id=1), NYG, False),
        with_situation(live("LV", "KC", 2), KC, False),
    )
    w.observe([a_out, b_out])
    a_in, b_in = with_situation(live(game_id=1), NYG), with_situation(live("LV", "KC", 2), KC)
    w.observe([a_in, b_in])
    games = [a_in, b_in]
    assert w.current(games, 6.0)[0].id == 1
    clock.t += 6
    assert w.current(games, 6.0)[0].id == 2


def test_an_alert_that_waited_too_long_is_dropped():
    w, clock = watcher()
    outside = with_situation(live(), NYG, red=False)
    inside = with_situation(live(), NYG)
    w.observe([outside])
    w.observe([inside])
    clock.t += rz.STALE_AFTER + 1
    assert w.current([inside], 6.0) is None


def test_the_other_team_getting_the_ball_in_the_zone_is_a_new_alert():
    w, clock = watcher()
    w.observe([with_situation(live(), NYG, red=False)])
    w.observe([with_situation(live(), NYG)])
    w.current([with_situation(live(), NYG)], 6.0)
    clock.t += rz.COOLDOWN + 7
    w.observe([with_situation(live(), DAL)])  # a turnover: DAL now has it in the zone
    assert w.waiting == 1


# -- the screen ---------------------------------------------------------------------------------


@pytest.mark.parametrize("seconds", [0.0, 0.2, 0.6, 3.3])
@pytest.mark.parametrize("width", [128])
def test_the_alert_stays_on_the_panel_and_pulses(seconds, width):
    c = AsciiCanvas(width, 32)
    r = renderer(width)
    r.draw_fb_redzone(c, with_situation(live(), NYG, spot="DAL 14"), seconds)
    assert not c.out_of_bounds and c.pixels


def test_red_zone_text_pulses_between_bright_and_dim():
    r = renderer(128)
    g = with_situation(live(), NYG)

    def top_colors(seconds):
        c = AsciiCanvas(128, 32)
        r.draw_fb_redzone(c, g, seconds)
        return {color for (x, y), color in c.pixels.items() if y < 9 and 30 < x < 100}

    assert top_colors(0.1) != top_colors(0.7)


def test_a_long_spot_is_fitted_and_a_missing_one_is_left_out():
    r = renderer(128)
    c = AsciiCanvas(128, 32)
    r.draw_fb_redzone(
        c, with_situation(live("WSH", "NYG"), NYG, spot="A VERY LONG SPOT NAME 14"), 0.1
    )
    assert not c.out_of_bounds
    c = AsciiCanvas(128, 32)
    r.draw_fb_redzone(c, with_situation(live(), NYG, spot=""), 0.1)
    assert not c.out_of_bounds
    assert not [p for p in c.pixels if p[1] >= 28 and 30 < p[0] < 98], "no line without a spot"


# -- the mode -----------------------------------------------------------------------------------


def build(games, *, show=True, wide=True, follow=(), rotation=("fb_preview",)):
    from scoreboard.config import RotationEntry  # noqa: F401

    clock = Clock(BASE)
    cfg = fcfg(
        favourite_team="NYG", also_follow=list(follow),
        rotation=[{"screen": s, "seconds": 8} for s in rotation], show_redzone=show,
    )  # fmt: skip
    feed = IdleFeed(games)
    mode = FootballMode(
        client_factory=lambda: feed, monotonic=clock, football=lambda: cfg,
        utc_now=Utc(datetime(2026, 11, 22, 9, 0, tzinfo=UTC)), wide=lambda: wide,
    )  # fmt: skip
    mode._feed = feed  # type: ignore[attr-defined]
    mode.worker.poll_once()
    return mode, clock


def elsewhere(red=False):
    """A live game nobody follows (KC v LV), with the ball in the red zone or not."""
    return with_situation(game("LV", "KC", "in", 3, 7, game_id=9), KC, red=red, spot="LV 12")


def test_an_alert_takes_over_an_idle_screen_then_gives_it_back():
    register("fb_preview")
    mode, clock = build([nyg_game("pre"), elsewhere()])
    assert mode.scene().kind == "fb_preview"
    mode._feed.games = [nyg_game("pre"), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    scene = mode.scene()
    assert scene.kind == "fb_redzone" and scene.fb_game.id == 9
    assert scene.animating and scene.fb_seconds == 6.0
    clock.t += 7
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_preview"


def test_the_alert_can_be_turned_off():
    register("fb_preview")
    mode, clock = build([nyg_game("pre"), elsewhere()], show=False)
    mode.scene()
    mode._feed.games = [nyg_game("pre"), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_preview"


def test_no_alert_on_a_64px_panel():
    mode, clock = build([nyg_game("pre"), elsewhere()], wide=False)
    mode.scene()
    mode._feed.games = [nyg_game("pre"), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().kind != "fb_redzone"


def test_no_alert_while_a_game_scene_is_up():
    """The favourite's live game is on the panel: its own field already shows the red zone."""
    register("fb_preview")
    mine = with_situation(nyg_game("in"), NYG, red=False)
    mode, clock = build([mine, elsewhere()])
    mode.scene()
    mode._feed.games = [with_situation(nyg_game("in"), NYG, red=True), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().kind != "fb_redzone"


def test_the_length_is_the_settings():
    register("fb_preview")
    clock = Clock(BASE)
    cfg = fcfg(favourite_team="NYG", rotation=[{"screen": "fb_preview", "seconds": 8}],
                         redzone_seconds=11.0)  # fmt: skip
    feed = IdleFeed([nyg_game("pre"), elsewhere()])
    mode = FootballMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg,
                        utc_now=Utc(datetime(2026, 11, 22, 9, 0, tzinfo=UTC)))  # fmt: skip
    mode.worker.poll_once()
    mode.scene()
    feed.games = [nyg_game("pre"), elsewhere(red=True)]
    clock.t += 15
    mode.worker.poll_once()
    assert mode.scene().fb_seconds == 11.0
    clock.t += 8
    assert mode.scene().kind == "fb_redzone", "still up after the default 6 seconds"


# -- the settings -------------------------------------------------------------------------------


def test_the_settings_default_on_and_clamp():
    cfg = FootballConfig()
    assert cfg.show_redzone is True and cfg.redzone_seconds == 6.0
    assert FootballConfig(redzone_seconds=99).redzone_seconds == 15.0
    assert FootballConfig(redzone_seconds=0).redzone_seconds == 3.0
    assert FootballConfig(show_redzone=0).show_redzone is False
