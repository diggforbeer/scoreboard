"""``fb_schedule`` (#429): the favourite's next three games."""

from __future__ import annotations

from datetime import timedelta

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display import football_idle
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle import ScheduleGame, TeamSchedule
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import (
    SCHEDULE_ROWS,
    ScheduleRow,
    ScheduleView,
    build_schedule,
)
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.teams import TEAMS
from test_football_idle import Clock, IdleFeed
from test_football_idle_preview import NYG, SCHEDULE, utc
from test_football_scenes import H, check_snapshot, game, renderer

START = utc(2026, 11, 22, 18)


def sg(week, days, away, home, done=False, start=True):
    return ScheduleGame(
        event_id=week, week=week, season_type=2,
        start_utc=START + timedelta(days=days) if start else None,
        home=home, away=away, home_score=None, away_score=None,
        status_name="STATUS_FINAL" if done else "STATUS_SCHEDULED", completed=done,
    )  # fmt: skip


def sched(*games):
    return TeamSchedule(NYG, 2026, 8, tuple(games))


FULL = sched(
    sg(10, -7, "NYG", "WSH", done=True),
    sg(11, 0, "NYG", "DAL"),
    sg(12, 4, "DET", "NYG"),
    sg(13, 14, "NYG", "PHI"),
    sg(14, 21, "NYG", "SEA"),
    sg(15, 28, "KC", "NYG"),
)


def ctx(schedule=FULL, favourite="NYG", now=utc(2026, 11, 20)):
    snap = idle.IdleSnapshot(schedules={NYG: idle.Cached(schedule, 0.0)} if schedule else {})
    return IdleContext(0.0, now, [], snap, FootballConfig(favourite_team=favourite))


# -- the builder ------------------------------------------------------------------------------


def test_the_next_three_games_in_order_with_home_and_away():
    view = build_schedule(ctx())
    assert [(r.week, r.opponent, r.home) for r in view.rows] == [
        (11, "DAL", False), (12, "DET", True), (13, "PHI", False),
    ]  # fmt: skip
    assert view.team == "NYG" and len(view.rows) == SCHEDULE_ROWS == 3


def test_a_played_game_is_never_listed_and_a_bye_week_is_passed_over():
    # Weeks 12 -> 14: the bye leaves week 13 out of the feed, so the rows simply run on.
    gapped = sched(sg(12, 0, "NYG", "DAL"), sg(14, 14, "NYG", "PHI"), sg(15, 21, "KC", "NYG"))
    assert [r.week for r in build_schedule(ctx(gapped)).rows] == [12, 14, 15]
    assert 10 not in [r.week for r in build_schedule(ctx()).rows]


def test_a_game_without_a_week_number_or_kickoff_is_passed_over():
    odd = sched(
        ScheduleGame(1, None, 2, START, "DAL", "NYG", None, None, "S", False),  # no week: the bye
        sg(12, 3, "NYG", "DAL", start=False),
        sg(13, 7, "NYG", "PHI"),
    )
    assert [r.week for r in build_schedule(ctx(odd)).rows] == [13]


def test_fewer_than_three_left_shows_what_is_left_and_none_left_skips_the_screen():
    end = sched(sg(17, 0, "NYG", "DAL"), sg(18, 7, "PHI", "NYG"))
    assert len(build_schedule(ctx(end)).rows) == 2
    assert build_schedule(ctx(end, now=utc(2027, 3, 1))) is None
    assert build_schedule(ctx(sched(sg(1, -3, "NYG", "DAL", done=True)))) is None


def test_the_real_fixtures_only_unplayed_game_is_the_last_week():
    view = build_schedule(ctx(SCHEDULE, now=utc(2026, 11, 9)))
    assert [(r.week, r.opponent, r.home) for r in view.rows] == [(18, "PHI", True)]


def test_nothing_without_a_favourite_a_schedule_or_a_known_team():
    assert build_schedule(ctx(favourite="")) is None
    assert build_schedule(ctx(favourite="XXX")) is None
    assert build_schedule(ctx(schedule=None)) is None
    assert IDLE_SCREENS["fb_schedule"](ctx()) == build_schedule(ctx())


def test_an_opponent_that_is_not_known_yet_is_passed_over():
    tbd = sched(sg(12, 3, "NYG", "TBD"), sg(13, 7, "NYG", "PHI"))
    assert [r.week for r in build_schedule(ctx(tbd)).rows] == [13]


# -- drawing ----------------------------------------------------------------------------------


def draw(view, width=128):
    r = renderer(width)
    c = AsciiCanvas(width, H)
    r.draw_fb_schedule(c, view, utc(2026, 11, 20))
    return c


def test_snapshots(update_snapshots):
    view = build_schedule(ctx())
    for name, v in (
        ("fb_schedule", view),
        ("fb_schedule_last", ScheduleView("NYG", view.rows[2:])),
    ):
        c = draw(v)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


@pytest.mark.parametrize(
    ("start", "label"),
    [
        (utc(2026, 11, 22, 18, 0), "12:00P"),
        (utc(2026, 11, 27, 1, 20), "7:20P"),
        (utc(2026, 11, 22, 15, 30), "9:30A"),
        (utc(2026, 11, 23, 6, 5), "12:05A"),
    ],
)
def test_the_kickoff_time_in_the_boards_zone(start, label):
    row = ScheduleRow(11, start, "DAL", False)
    assert football_idle.schedule_time(row, renderer()) == label


def test_every_team_as_opponent_home_and_away_fits_the_panel():
    for opponent in TEAMS:
        rows = tuple(
            ScheduleRow(12 + i, utc(2026, 12, 20 + i, 18 + i), opponent, i % 2 == 0)
            for i in range(3)
        )
        c = draw(ScheduleView("NYG", rows))
        assert c.pixels and not c.out_of_bounds, opponent


def test_a_two_digit_day_and_week_and_a_late_kickoff_fit():
    rows = (
        ScheduleRow(18, utc(2027, 1, 10, 4, 25), "LAC", True),
        ScheduleRow(19, utc(2027, 1, 17, 21, 0), "WSH", False),
    )
    assert not draw(ScheduleView("WSH", rows)).out_of_bounds


def test_home_reads_vs_and_away_reads_at():
    away = draw(ScheduleView("NYG", (ScheduleRow(11, START, "DAL", False),)))
    home = draw(ScheduleView("NYG", (ScheduleRow(11, START, "DAL", True),)))
    assert away.pixels != home.pixels


def test_rows_stack_from_the_top_one_row_per_game():
    one = draw(ScheduleView("NYG", (ScheduleRow(11, START, "DAL", False),)))
    three = draw(build_schedule(ctx()))
    assert max(y for _, y in one.pixels) < max(y for _, y in three.pixels)


# -- through the real mode ---------------------------------------------------------------------


class Feed(IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None

    def schedule(self, team_id):
        self.calls.append(("schedule", team_id))
        return FULL


def test_the_schedule_takes_its_slot_in_the_real_rotation():
    clock = Clock(960.0)
    feed = Feed([game("DAL", "PHI", "pre", short="x", start="2026-11-22T18:00Z", game_id=5)])
    cfg = FootballConfig(
        favourite_team="NYG",
        rotation=[{"screen": "fb_schedule", "seconds": 8}, {"screen": "clock", "seconds": 4}],
    )
    mode = NflMode(
        client_factory=lambda: feed, monotonic=clock, football=lambda: cfg,
        utc_now=lambda: utc(2026, 11, 20),
    )  # fmt: skip
    mode.worker.poll_once()
    scene = mode.scene()  # 960 % 12 == 0: the first slot
    assert scene.kind == "fb_schedule" and len(scene.fb_idle.rows) == 3
    clock.t += 9
    assert mode.scene().kind == "clock"
