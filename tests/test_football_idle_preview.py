"""``fb_preview`` (#424): the favourite's next game, its tags and round labels, and the drawing."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import PreviewView, build_preview, game_tag, week_label
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.teams import TEAMS
from test_football_scenes import H, check_snapshot, raw_game, renderer

FIXTURES = Path(__file__).parent / "fixtures" / "football"
NYG = TEAMS["NYG"].espn_id


def utc(*args):
    return datetime(*args, tzinfo=UTC)


CALENDAR = idle.calendar_from_payload(
    {"leagues": [{"calendar": json.loads((FIXTURES / "season_calendar.json").read_text())}]}
)
SCHEDULE = idle.schedule_from_payload(
    NYG, json.loads((FIXTURES / "schedule_NYG_trimmed.json").read_text())
)


# -- the tag rules, on real dates -------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "tag"),
    [
        (utc(2026, 11, 26, 17, 30), "THANKSGIVING"),  # 4th Thursday of 2026
        (utc(2025, 11, 27, 21, 30), "THANKSGIVING"),  # and of 2025
        (utc(2026, 11, 20, 1, 15), "THU NIGHT"),  # Thursday 8:15 PM ET (Nov 19 is not the 4th)
        (utc(2026, 12, 4, 0, 20), "THU NIGHT"),
        (utc(2026, 11, 17, 1, 15), "MON NIGHT"),  # Monday 8:15 PM ET
        (utc(2025, 12, 25, 18, 0), "CHRISTMAS"),  # a Thursday, and still just Christmas
        (utc(2026, 12, 25, 18, 0), "CHRISTMAS"),  # a Friday
        (utc(2029, 11, 22, 18, 0), "THANKSGIVING"),  # the earliest the 4th Thursday can fall
        (utc(2024, 11, 28, 18, 0), "THANKSGIVING"),  # and the latest
        (utc(2029, 11, 29, 18, 0), ""),  # a fifth Thursday is not Thanksgiving
        (utc(2026, 11, 22, 18, 0), ""),  # Sunday 1 PM ET
        (utc(2026, 11, 23, 1, 20), ""),  # Sunday night: no tag
        (utc(2026, 11, 19, 21, 0), ""),  # a Thursday afternoon
        (utc(2026, 11, 17, 18, 0), ""),  # a Tuesday
        (None, ""),
    ],
)
def test_game_tags(start, tag):
    assert game_tag(start, 2) == tag


def test_preseason_games_carry_no_tag_and_the_night_starts_at_seven_eastern():
    assert game_tag(utc(2026, 8, 21, 0, 0), 1) == ""
    assert game_tag(utc(2026, 12, 4, 0, 0), 2) == "THU NIGHT"  # 7:00 PM ET exactly
    assert game_tag(utc(2026, 12, 3, 23, 59), 2) == ""  # 6:59 PM ET


def test_the_fourth_thursday_is_not_the_fifth_or_the_third():
    assert game_tag(utc(2026, 11, 19, 18, 0), 2) == ""
    assert game_tag(utc(2026, 11, 26, 18, 0), 2) == "THANKSGIVING"
    assert game_tag(utc(2026, 11, 28, 18, 0), 2) == ""


# -- round labels -----------------------------------------------------------------------------


def test_week_labels_for_the_regular_season_preseason_and_each_playoff_round():
    assert week_label(2, 11, utc(2026, 11, 22), CALENDAR) == "WEEK 11"
    assert week_label(1, 2, utc(2026, 8, 22), CALENDAR) == "PRESEASON WK 2"
    assert week_label(2, None, utc(2026, 11, 22), CALENDAR) == ""
    rounds = [
        ("WILD CARD", utc(2027, 1, 17)),
        ("DIVISIONAL", utc(2027, 1, 23)),
        ("CONF CHAMP", utc(2027, 1, 31)),
        ("SUPER BOWL", utc(2027, 2, 14)),
    ]
    for label, day in rounds:
        assert week_label(3, 1, day, CALENDAR) == label
    assert week_label(3, 1, utc(2027, 3, 1), CALENDAR) == "PLAYOFFS"
    wild = next(c for c in CALENDAR if c.short_label == "Wild Card")
    assert week_label(3, 1, wild.start, CALENDAR) == "WILD CARD"  # a round is [start, end)
    assert week_label(3, 1, wild.end, CALENDAR) == "PLAYOFFS"
    assert week_label(3, 1, utc(2027, 1, 17), ()) == "PLAYOFFS"


# -- which game is next -----------------------------------------------------------------------


def ctx(games=(), now=utc(2026, 11, 9, 12), favourite="NYG", schedule=SCHEDULE, week=None):
    snap = idle.IdleSnapshot(
        scoreboard=idle.Scoreboard((), 2, 2026, 10, (), CALENDAR),
        schedules={NYG: idle.Cached(schedule, 0.0)} if schedule else {},
        week_cached=idle.Cached(week, 0.0) if week else None,
    )
    return IdleContext(0.0, now, list(games), snap, FootballConfig(favourite_team=favourite))


def event(away, home, start, state="pre", away_rec="4-5", home_rec="5-3-1", season=2, week=11):
    raw = raw_game(away, home, state, start=start.strftime("%Y-%m-%dT%H:%MZ"), short="x")
    raw["season"] = {"type": season}
    raw["week"] = {"number": week}
    for side in raw["competitions"][0]["competitors"]:
        rec = home_rec if side["homeAway"] == "home" else away_rec
        side["records"] = [{"type": "total", "summary": rec}]
    return FbGame.from_api(raw)


def test_the_next_game_comes_from_the_schedule_and_skips_the_finished_ones():
    view = build_preview(ctx())
    assert (view.away, view.home, view.week) == ("PHI", "NYG", "WEEK 18")
    assert view.start_utc == utc(2027, 1, 10, 5)
    assert (view.away_record, view.home_record) == ("", "")  # not on a scoreboard the board has


def test_records_come_from_the_scoreboard_event_when_the_board_has_it():
    game = event("PHI", "NYG", utc(2027, 1, 10, 5), away_rec="10-6", home_rec="9-7", week=18)
    view = build_preview(ctx(games=[game]))
    assert (view.away_record, view.home_record) == ("10-6", "9-7")
    week = idle.Scoreboard((game,), 2, 2026, 18, (), ())
    assert build_preview(ctx(week=week)).home_record == "9-7"


def test_a_playoff_game_on_the_scoreboard_beats_the_schedule_and_gets_its_round():
    game = event("DAL", "NYG", utc(2027, 1, 16, 21), season=3, week=1)
    view = build_preview(ctx(games=[game], now=utc(2027, 1, 12)))
    assert view.week == "WILD CARD" and view.away == "DAL"


def test_the_earlier_of_the_scoreboard_game_and_the_schedule_wins():
    sooner = event("DAL", "NYG", utc(2026, 12, 1, 18), week=13)
    assert build_preview(ctx(games=[sooner])).away == "DAL"  # Dec 1 beats the Jan 10 schedule game
    later = event("DAL", "NYG", utc(2027, 1, 30, 18), week=19)
    assert build_preview(ctx(games=[later])).away == "PHI"


def test_records_are_never_taken_from_another_meeting_of_the_same_two_teams():
    earlier = event(
        "PHI", "NYG", utc(2026, 11, 8, 18), state="post", away_rec="1-1", home_rec="2-0"
    )
    view = build_preview(ctx(games=[earlier]))
    assert view.start_utc == utc(2027, 1, 10, 5) and view.home_record == ""


def test_a_game_with_a_team_not_yet_known_is_skipped():
    raw = raw_game("DAL", "NYG", "pre", start="2027-01-16T21:00Z", short="x")
    raw["competitions"][0]["competitors"][1]["team"] = {"id": "0", "abbreviation": "TBD"}
    tbd = FbGame.from_api(raw)
    assert not tbd.home.is_nfl or not tbd.away.is_nfl
    view = build_preview(ctx(games=[tbd], now=utc(2027, 1, 12), schedule=None))
    assert view is None


def test_a_live_or_finished_favourite_game_is_not_the_preview():
    for state in ("in", "post"):
        game = event("DAL", "NYG", utc(2026, 11, 8, 18), state=state)
        view = build_preview(ctx(games=[game], now=utc(2026, 11, 8, 20)))
        assert view is None or view.start_utc > utc(2026, 11, 8, 20)


def test_nothing_without_a_favourite_a_schedule_or_a_known_team():
    assert build_preview(ctx(favourite="")) is None
    assert build_preview(ctx(favourite="XXX")) is None
    assert build_preview(ctx(schedule=None)) is None
    assert build_preview(ctx(now=utc(2027, 2, 1))) is None  # season over, next one unpublished


def test_the_registry_builds_the_same_view():
    assert IDLE_SCREENS["fb_preview"](ctx()) == build_preview(ctx())


def test_a_season_of_dates_always_builds_something_that_fits_the_panel():
    start = utc(2026, 9, 1)
    seen = 0
    for day in range(0, 145, 3):
        view = build_preview(ctx(now=start + timedelta(days=day)))
        if view is None:
            continue
        seen += 1
        c = draw(view)
        assert not c.out_of_bounds and c.pixels, day
    assert seen > 30


# -- drawing -----------------------------------------------------------------------------------


class Art:
    def __init__(self, color):
        self.width = self.height = 16
        self.pixels = tuple((x, y, color) for x in range(16) for y in range(16))


class Logos:
    COLORS: ClassVar[dict[str, tuple[int, int, int]]] = {
        "DAL": (10, 10, 250),
        "NYG": (250, 10, 10),
        "PHI": (10, 250, 10),
    }

    def get(self, abbrev, size):
        return Art(self.COLORS.get(abbrev, (9, 9, 9)))


def draw(view, logos=False, width=128):
    r = renderer(width)
    r.nfl_logos = Logos() if logos else None
    c = AsciiCanvas(width, H)
    r.draw_fb_preview(c, view, utc(2026, 11, 20))
    return c


PLAIN = PreviewView("DAL", "NYG", utc(2026, 11, 22, 18), "", "WEEK 11", "4-5", "5-3-1")
NIGHT = PreviewView("NYG", "PHI", utc(2026, 12, 4, 0, 20), "THU NIGHT", "WEEK 13", "5-3-1", "7-2")
TURKEY = PreviewView("DET", "NYG", utc(2026, 11, 26, 17, 30), "THANKSGIVING", "WEEK 12")


@pytest.mark.parametrize(
    ("name", "view"),
    [("fb_preview", PLAIN), ("fb_preview_primetime", NIGHT), ("fb_preview_thanksgiving", TURKEY)],
)
def test_snapshots(name, view, update_snapshots):
    c = draw(view, logos=True)
    check_snapshot(name, c.render(), update_snapshots)
    assert not c.out_of_bounds


def test_away_is_on_the_left_and_home_on_the_right():
    c = draw(PLAIN, logos=True)
    left = [(x, y) for (x, y), col in c.pixels.items() if col == (10, 10, 250)]  # DAL (away)
    right = [(x, y) for (x, y), col in c.pixels.items() if col == (250, 10, 10)]  # NYG (home)
    assert left and right and max(x for x, _ in left) < 64 <= min(x for x, _ in right)
    flipped = PreviewView("NYG", "DAL", PLAIN.start_utc, "", "WEEK 11")
    c = draw(flipped, logos=True)
    assert max(x for (x, _), col in c.pixels.items() if col == (250, 10, 10)) < 64


def test_the_tag_is_amber_and_the_week_is_dim_and_both_are_dropped_to_fit():
    r = renderer()
    from nhl_scoreboard.display.football_idle import preview_top_line

    assert preview_top_line(r, NIGHT, 80) == "THU NIGHT  WEEK 13"
    assert preview_top_line(r, TURKEY, 80) == "THANKSGIVING"  # the week no longer fits
    assert preview_top_line(r, PLAIN, 80) == "WEEK 11"
    assert preview_top_line(r, PreviewView("A", "B", PLAIN.start_utc, "", ""), 80) == ""
    amber = {col for col in draw(NIGHT).pixels.values() if col[0] > 200 and col[2] < 50}
    assert amber, "the tag is drawn in amber"
    assert not {c for c in draw(PLAIN).pixels.values() if c[0] > 200 and c[2] < 50}


def test_a_missing_record_is_left_out():
    bare = PreviewView("DAL", "NYG", PLAIN.start_utc, "", "WEEK 11")
    assert len(draw(bare).pixels) < len(draw(PLAIN).pixels)
    assert [p for p in draw(bare).pixels if p[1] >= 26 and (p[0] < 24 or p[0] > 104)] == []


def test_without_crests_the_abbreviations_stand_in():
    assert len(draw(PLAIN, logos=False).pixels) > 100


def test_the_time_is_in_the_boards_own_zone():
    c = draw(PLAIN)  # 18:00Z is noon in Chicago
    assert c.pixels
    from nhl_scoreboard.display.football_idle import draw_fb_preview  # noqa: F401


from test_football_scenes import _pixels, app  # noqa: E402,F401  (the real-app fixture)


def test_through_the_real_app_the_preview_takes_its_slot_between_games_and_the_clock_the_next(
    app,  # noqa: F811
):
    feed, clock = app.feed, app.clock_box
    app.settings.football = FootballConfig(
        favourite_team="NYG",
        rotation=[{"screen": "fb_preview", "seconds": 8}, {"screen": "clock", "seconds": 6}],
    )
    app.select_scene()
    feed.answers = [[event("WSH", "NYG", utc(2026, 11, 17, 18), week=10)]]
    app._nfl.worker.poll_once()
    clock.t = 14 * 100  # the default rotation: preview 8s then clock 6s (the rest unbuilt)
    scene = app.select_scene()
    assert scene.kind == "fb_preview" and scene.fb_idle.away == "WSH"
    assert scene.fb_idle.week == "WEEK 10" and scene.fb_idle.home_record == "5-3-1"
    assert _pixels(app, scene), "the app draws it"
    clock.t += 9
    assert app.select_scene().kind == "clock"
    feed.answers = [[event("WSH", "NYG", utc(2026, 11, 15, 17, 0), state="in")]]
    app._nfl.worker.poll_once()
    clock.t += 15
    assert app.select_scene().kind in ("fb_field", "fb_scores", "fb_play", "fb_playtext")


def test_a_game_whose_kickoff_has_passed_but_is_not_live_is_not_previewed():
    late = event("DAL", "NYG", utc(2026, 11, 9, 11), state="pre")  # an hour ago, feed behind
    view = build_preview(ctx(games=[late], schedule=None))
    assert view is None
