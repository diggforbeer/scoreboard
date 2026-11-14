"""Which idle screen the NFL board picks (#422): the ladder in ``NflMode._idle_kind``.

The screens themselves arrive in #423-#429, so these tests register stand-ins in
``IDLE_SCREENS`` (restored after each test)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nhl_scoreboard.config import FootballConfig, RotationEntry, Settings
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS
from nhl_scoreboard.football.mode import NflMode
from test_football_idle import Clock, pregame
from test_football_idle import IdleFeed as _IdleFeed
from test_football_scenes import game

BASE = 960.0  # a multiple of 24 and 30, so rotation offsets read straight off the clock
KICKOFF = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def stand_ins():
    saved = dict(IDLE_SCREENS)
    IDLE_SCREENS.clear()
    yield IDLE_SCREENS
    IDLE_SCREENS.clear()
    IDLE_SCREENS.update(saved)


def register(*names, show=True):
    for name in names:
        IDLE_SCREENS[name] = lambda ctx, show=show: show


class IdleFeed(_IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None


class Utc:
    def __init__(self, at=KICKOFF):
        self.at = at

    def __call__(self):
        return self.at


def build(
    games, *, favourite="NYG", follow=(), rotation=(), wide=True, utc=None, clock=None, **cfg
):
    clock = clock or Clock(BASE)
    config = FootballConfig(
        favourite_team=favourite,
        also_follow=list(follow),
        rotation=[{"screen": s, "seconds": sec} for s, sec in rotation],
        **cfg,
    )
    feed = IdleFeed(games)
    mode = NflMode(
        client_factory=lambda: feed,
        monotonic=clock,
        football=lambda: config,
        utc_now=utc or Utc(),
        wide=lambda: wide,
    )
    mode.worker.poll_once()
    return mode, clock


def kinds(mode, clock, seconds):
    out = []
    for t in seconds:
        clock.t = BASE + t
        out.append(mode.scene().kind)
    return out


def nyg_game(state="pre", **kw):
    if state == "pre":
        return game("DAL", "NYG", "pre", short="x", start="2026-11-22T18:00Z", game_id=7, **kw)
    if state == "post":
        return game("DAL", "NYG", "post", 20, 17, short="Final", game_id=7, **kw)
    return game("DAL", "NYG", "in", 3, 0, game_id=7, **kw)


def test_the_default_rotation_is_preview_standings_week_schedule_clock():
    cfg = FootballConfig()
    assert [(e.screen, e.seconds) for e in cfg.idle_rotation] == [
        ("fb_preview", 8.0), ("fb_standings", 8.0), ("fb_week", 10.0),
        ("fb_schedule", 8.0), ("clock", 6.0),
    ]  # fmt: skip


def test_a_live_followed_game_beats_everything():
    register("fb_countdown", "fb_final", "fb_preview")
    mode, _ = build([nyg_game("in"), nyg_game("pre")])
    assert mode.scene().kind in ("fb_field", "fb_scores")


def test_the_favourites_pregame_inside_the_window_is_the_countdown():
    register("fb_countdown", "fb_preview")
    utc = Utc(datetime(2026, 11, 22, 17, 5, tzinfo=UTC))
    mode, _ = build([nyg_game("pre")], utc=utc)
    scene = mode.scene()
    assert scene.kind == "fb_countdown" and scene.fb_game.id == 7
    utc.at = datetime(2026, 11, 22, 16, 59, tzinfo=UTC)  # 61 minutes out
    assert mode.scene().kind != "fb_countdown"


def test_the_countdown_window_is_configurable():
    register("fb_countdown")
    utc = Utc(datetime(2026, 11, 22, 16, 0, tzinfo=UTC))
    mode, _ = build([nyg_game("pre")], utc=utc, countdown_minutes=180)
    assert mode.scene().kind == "fb_countdown"


def test_a_game_seen_live_then_final_holds_for_the_hold_then_rotates():
    register("fb_final", "fb_preview")
    clock = Clock(BASE)
    feed = IdleFeed([nyg_game("in")])
    config = FootballConfig(favourite_team="NYG", rotation=[{"screen": "fb_preview", "seconds": 5}])
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: config)
    mode.worker.poll_once()
    mode.scene()  # seen live
    feed.games = [nyg_game("post")]
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_final"
    for _ in range(59):  # a poll a minute keeps the feed fresh
        clock.t += 60
        mode.worker.poll_once()
    assert mode.scene().kind == "fb_final"
    for _ in range(2):
        clock.t += 60
        mode.worker.poll_once()
    assert mode.scene().kind == "fb_preview"


def test_a_board_that_joins_after_the_end_gets_no_hold():
    register("fb_final", "fb_preview")
    mode, _ = build([nyg_game("post")], rotation=[("fb_preview", 5)])
    assert mode.scene().kind == "fb_preview"


def test_rotation_slots_follow_the_clock_and_the_clock_counts_with_company():
    register("fb_preview", "fb_week")
    mode, clock = build([pregame()], rotation=[("fb_preview", 8), ("fb_week", 10), ("clock", 6)])
    assert kinds(mode, clock, [0, 7.9, 8, 17.9, 18, 23.9, 24]) == [
        "fb_preview", "fb_preview", "fb_week", "fb_week", "clock", "clock", "fb_preview",
    ]  # fmt: skip


def test_screens_without_data_drop_out_and_a_lone_clock_is_not_a_rotation():
    register("fb_week")
    IDLE_SCREENS["fb_preview"] = lambda ctx: False
    mode, clock = build([pregame()], rotation=[("fb_preview", 8), ("fb_week", 10), ("clock", 6)])
    assert set(kinds(mode, clock, range(0, 16))) == {"fb_week", "clock"}
    IDLE_SCREENS["fb_week"] = lambda ctx: False
    # nothing resolved: the board falls through to the game pool, never a bare clock rotation
    assert kinds(mode, clock, [0, 3])[0] == "fb_scores"


def test_unregistered_screens_are_skipped_so_the_board_behaves_as_before():
    mode, _ = build([pregame()])
    assert mode.scene().kind == "fb_scores"


def test_a_bye_week_adds_the_bye_screen():
    register("fb_bye", "fb_week")
    mode, clock = build([pregame()], favourite="CHI", rotation=[("fb_week", 10)])
    assert set(kinds(mode, clock, range(0, 20))) == {"fb_week", "fb_bye"}
    mode, clock = build([pregame()], favourite="NYG", rotation=[("fb_week", 10)])
    assert set(kinds(mode, clock, range(0, 20))) == {"fb_week"}


def test_no_favourite_means_no_idle_rotation():
    register("fb_preview", "fb_week")
    mode, _ = build([pregame()], favourite="")
    assert mode.scene().kind == "fb_scores"


def test_an_empty_slate_shows_the_clock_or_no_games():
    mode, _ = build([], favourite="")
    assert mode.scene().kind == "clock"
    mode, _ = build([], rotation=[("fb_week", 10)])
    assert mode.scene().kind == "fb_no_games"


def test_a_64px_panel_skips_the_idle_screens():
    register("fb_countdown", "fb_preview", "fb_final")
    utc = Utc(datetime(2026, 11, 22, 17, 30, tzinfo=UTC))
    mode, _ = build([nyg_game("pre")], utc=utc, wide=False)
    assert mode.scene().kind == "fb_scores"
    mode, _ = build([], wide=False)
    assert mode.scene().kind == "clock"
    mode, _ = build([], wide=False, rotation=[("fb_week", 10)])
    assert mode.scene().kind == "fb_no_games"


def test_a_live_game_nobody_follows_does_not_stop_the_idle_rotation():
    register("fb_preview")
    other = game("MIA", "IND", "in", 3, 3, game_id=2)
    mode, _ = build([other, pregame()], rotation=[("fb_preview", 5)])
    assert mode.scene().kind == "fb_preview"


def test_the_nfl_rotation_round_trips_through_the_config_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[football]\nfavourite_team = 'NYG'\n")
    Settings.load(path).save(
        {"football": {"rotation": [{"screen": "fb_week", "seconds": 5}], "final_hold_minutes": 30}}
    )
    cfg = Settings.load(path).football
    assert cfg.rotation == [RotationEntry("fb_week", 5.0)]
    assert (cfg.final_hold_minutes, cfg.favourite_team) == (30.0, "NYG")
    assert "[[football.rotation]]" in path.read_text()


def test_bad_rotation_entries_and_minutes_fall_back():
    cfg = FootballConfig(
        rotation=[{"screen": "scores_grid", "seconds": 5}, {"screen": "fb_week", "seconds": -1}],
        final_hold_minutes=-5,
        countdown_minutes="soon",
    )
    assert cfg.rotation == []
    assert (cfg.final_hold_minutes, cfg.countdown_minutes) == (60.0, 60.0)
    assert idle  # the module under test imports cleanly


# -- the screens the board adds by itself can be turned off (#443) -----------------------------


def test_the_countdown_can_be_turned_off():
    register("fb_countdown", "fb_preview")
    utc = Utc(datetime(2026, 11, 22, 17, 5, tzinfo=UTC))
    mode, _ = build([nyg_game("pre")], utc=utc, rotation=[("fb_preview", 5)], show_countdown=False)
    assert mode.scene().kind == "fb_preview"
    on, _ = build([nyg_game("pre")], utc=utc, rotation=[("fb_preview", 5)])
    assert on.scene().kind == "fb_countdown"


def test_the_final_hold_can_be_turned_off():
    register("fb_final", "fb_preview")
    for show, expected in ((True, "fb_final"), (False, "fb_preview")):
        clock = Clock(BASE)
        feed = IdleFeed([nyg_game("in")])
        feed.plays = lambda game_id: []
        feed.core_plays = lambda game_id: None
        cfg = FootballConfig(
            favourite_team="NYG", rotation=[{"screen": "fb_preview", "seconds": 5}], show_final=show
        )
        mode = NflMode(
            client_factory=lambda feed=feed: feed, monotonic=clock, football=lambda cfg=cfg: cfg
        )
        mode.worker.poll_once()
        mode.scene()
        feed.games = [nyg_game("post")]
        mode.worker.poll_once()
        assert mode.scene().kind == expected, show


def test_the_bye_screen_can_be_turned_off():
    register("fb_bye", "fb_week")
    mode, clock = build([pregame()], favourite="CHI", rotation=[("fb_week", 10)], show_bye=False)
    assert set(kinds(mode, clock, range(0, 20))) == {"fb_week"}
