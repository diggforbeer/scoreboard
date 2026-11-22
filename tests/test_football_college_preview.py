"""The lead college team's next game (#554): ``cfb_preview``, the kickoff countdown and their ranks.

Hermetic. The fixtures are real captures (2026-11-20) cut down: UGA's schedule (with a bye in week
8, FLEX notes, an FCS opponent in week 1) and the postseason scoreboard (bowls named in
``notes[].headline`` with both teams still ``TBD``). A bowl with its teams chosen is that capture
with two real teams written in: ESPN has none of those yet.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scoreboard.display import college_idle as ci
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_idle import draw_fb_countdown
from scoreboard.display.football_scenes import RANK_COLOR
from scoreboard.football.api import _parse_events
from scoreboard.football.college_rankings import polls_from_payload
from scoreboard.football.idle import (
    Cached,
    IdleSnapshot,
    Scoreboard,
    schedule_from_payload,
)
from scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from scoreboard.football.idle_views import _bowl_label, build_college_preview
from scoreboard.football.teams import use_directory
from teamcfg import fcfg
from test_football_college import _fbs_directory
from test_football_scenes import H, check_snapshot, game, renderer

FX = Path(__file__).parent / "fixtures" / "football"


def load(name):
    return json.loads((FX / name).read_text())


SCHEDULE = load("college_schedule_UGA_trimmed.json")
POSTSEASON = load("college_postseason_trimmed.json")
POLLS = polls_from_payload(load("college_rankings_trimmed.json"))
FBS = _fbs_directory()
UGA, TEX, ND = 61, 251, 87
NOV20 = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def as_of(date_prefix):
    """UGA's schedule as it stood on ``date_prefix``: later games not yet played."""
    payload = copy.deepcopy(SCHEDULE)
    for event in payload["events"]:
        if event["date"] > date_prefix:
            event["competitions"][0]["status"]["type"].update(
                state="pre", completed=False, name="STATUS_SCHEDULED"
            )
            for side in event["competitions"][0]["competitors"]:
                side.pop("score", None)
    return payload


def schedule(payload=SCHEDULE):
    return schedule_from_payload(UGA, payload)


def bowl(away=("UGA", UGA), home=("TEX", TEX), index=0, season_type=3, headline=None):
    raw = copy.deepcopy(POSTSEASON["events"][index])
    sides = raw["competitions"][0]["competitors"]
    for side, (abbrev, tid), where in zip(sides, (away, home), ("away", "home"), strict=True):
        side["id"] = side["team"]["id"] = str(tid)
        side["team"]["abbreviation"] = abbrev
        side["homeAway"] = where
    raw["season"]["type"] = season_type
    if headline is not None:
        raw["competitions"][0]["notes"] = [{"type": "event", "headline": headline}]
    return _parse_events([raw])[0]


def ctx(
    now=NOV20,
    favourite="UGA",
    payload=SCHEDULE,
    games=(),
    week_games=(),
    board=None,
    polls=POLLS,
    **cfg,
):
    snap = IdleSnapshot(
        scoreboard=board,
        schedules={UGA: Cached(schedule(payload), 0.0)} if payload is not None else {},
        polls_cached=Cached(polls, 0.0) if polls is not None else None,
        week_cached=Cached(Scoreboard(games=tuple(week_games), season_type=3), 0.0)
        if week_games
        else None,
    )
    cfg.setdefault("college_poll", "ap")  # the snapshots were made with the AP's numbers
    return IdleContext(0.0, now, list(games), snap, fcfg(favourite_team=favourite, **cfg))


def view_of(**kw):
    with use_directory(FBS):
        return build_college_preview(ctx(**kw))


# -- the game's headline ------------------------------------------------------------------------


def test_a_bowl_is_named_by_its_note_and_only_in_the_postseason():
    assert bowl().headline == "Cricket Celebration Bowl"
    regular = bowl(season_type=2, headline="FLEX: 3:30 - 4:30pm OR 6 - 8pm ET start")
    assert regular.headline == "", "a regular-season note is a scheduling remark, not a name"
    assert bowl(headline="").headline == ""
    assert game("WSH", "NYG", "pre", short="x", start="2026-11-22T18:00Z").headline == ""


def test_the_bowl_label_keeps_a_short_name_and_trims_a_long_one():
    assert _bowl_label("Rose Bowl") == "ROSE BOWL"
    assert _bowl_label("Cricket Celebration Bowl") == "CRICKET CELEBRATION"
    assert _bowl_label("TransPerfect San Juan Bowl") == "TRANSPERFECT SAN JUAN"
    assert _bowl_label("Frisco Football Classic") == "FRISCO FOOTBALL CLASSIC"
    assert _bowl_label("") == "POSTSEASON" and _bowl_label("  ") == "POSTSEASON"


# -- the builder --------------------------------------------------------------------------------


def test_the_next_game_comes_from_the_schedule_with_the_week_and_the_poll_numbers():
    view = view_of()
    assert (view.away, view.home) == ("UGA", "SC")
    assert view.week == "WEEK 12" and view.tag == ""
    assert view.away_rank == 1 and view.start_utc == datetime(2026, 11, 22, 0, 30, tzinfo=UTC)
    with use_directory(FBS):
        assert IDLE_SCREENS["cfb_preview"](ctx()) is not None


def test_an_fcs_opponent_is_a_real_game_not_a_skipped_one():
    """The NFL's builder skips a side the table does not know; Tennessee State is just FCS."""
    view = view_of(now=datetime(2026, 8, 30, 12, 0, tzinfo=UTC), payload=as_of("2026-08-30"))
    assert (view.away, view.home) == ("TNST", "UGA") or (view.away, view.home) == ("UGA", "TNST")
    assert "TNST" in (view.away, view.home) and view.week == "WEEK 1"
    assert 1 in (view.away_rank, view.home_rank) and None in (view.away_rank, view.home_rank)


def test_a_tbd_bowl_is_never_shown_as_a_matchup():
    tbd = _parse_events(POSTSEASON["events"])
    assert all(g.away.abbrev == "TBD" for g in tbd)
    finished = copy.deepcopy(SCHEDULE)  # the regular season is over
    for event in finished["events"]:
        event["competitions"][0]["status"]["type"].update(state="post", completed=True)
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    assert view_of(now=now, payload=finished, week_games=tbd) is None
    assert view_of(now=now, payload=finished, games=tbd) is None
    with use_directory(FBS):
        assert IDLE_SCREENS["cfb_preview"](ctx(now=now, payload=finished, week_games=tbd)) is None


def test_a_game_with_one_side_still_to_be_decided_is_skipped_too():
    """The favourite is in it but the opponent is not chosen: "UGA vs TBD" is not a matchup."""
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    finished = copy.deepcopy(SCHEDULE)
    for event in finished["events"]:
        event["competitions"][0]["status"]["type"].update(state="post", completed=True)
    half = bowl(away=("UGA", UGA), home=("TBD", -2))
    assert view_of(now=now, payload=finished, games=[half]) is None
    assert view_of(now=now, payload=finished, week_games=[half]) is None
    # and a schedule whose next game has a TBD side (the postseason entry before it is set)
    open_ended = copy.deepcopy(finished)
    last = open_ended["events"][-1]
    last["competitions"][0]["status"]["type"].update(state="pre", completed=False)
    last["competitions"][0]["competitors"][0]["team"].update(id="-1", abbreviation="TBD")
    assert view_of(now=NOV20, payload=open_ended) is None


def test_a_bowl_with_its_teams_chosen_is_named():
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    view = view_of(now=now, week_games=[bowl()])
    assert (view.away, view.home) == ("UGA", "TEX")
    assert view.week == "CRICKET CELEBRATION" and view.tag == ""
    assert view.away_rank == 1 and view.home_rank is not None


def test_a_bowl_on_the_scoreboard_itself_counts_too():
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    assert view_of(now=now, games=[bowl(headline="Rose Bowl")]).week == "ROSE BOWL"


def test_a_bowl_without_a_name_says_postseason():
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    assert view_of(now=now, games=[bowl(headline="")]).week == "POSTSEASON"


def test_the_earliest_of_the_scoreboards_game_and_the_schedules_wins():
    sooner = dataclasses.replace(
        bowl(season_type=2, headline=""),
        start_utc=datetime(2026, 11, 21, 12, 0, tzinfo=UTC),
        week=12,
        id=99,
    )
    assert view_of(games=[sooner]).start_utc == datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
    later = dataclasses.replace(sooner, start_utc=datetime(2026, 12, 1, 12, 0, tzinfo=UTC))
    assert view_of(games=[later]).start_utc == datetime(2026, 11, 22, 0, 30, tzinfo=UTC)


def test_a_game_that_has_started_or_is_past_is_not_the_next_game():
    started = dataclasses.replace(bowl(season_type=2), state="in")
    assert view_of(games=[started]).start_utc == datetime(2026, 11, 22, 0, 30, tzinfo=UTC)


@pytest.mark.parametrize("favourite", ["", "ZZZZ", "TNST"])
def test_nothing_without_a_lead_team_the_table_knows(favourite):
    assert view_of(favourite=favourite) is None


def test_nothing_with_nothing_upcoming_or_no_schedule_yet():
    done = copy.deepcopy(SCHEDULE)
    for event in done["events"]:
        event["competitions"][0]["status"]["type"].update(state="post", completed=True)
    assert view_of(payload=done) is None
    assert view_of(payload=None) is None, "not fetched yet: skipped, never blank"


def test_the_poll_numbers_follow_the_chosen_poll():
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    played = bowl(away=("UGA", UGA), home=("ND", ND))
    for poll, expected in (("ap", 3), ("cfp", 6)):
        view = view_of(now=now, week_games=[played], college_poll=poll)
        assert view.home_rank == expected, poll
    assert view_of(now=now, week_games=[played], polls=None).home_rank is None


# -- bye weeks ----------------------------------------------------------------------------------

WEEK_8 = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def board(week, season_type=2):
    return Scoreboard(games=(), season_type=season_type, season_year=2026, week=week)


def test_the_week_without_a_game_is_the_bye_and_the_next_game_follows():
    view = view_of(now=WEEK_8, payload=as_of("2026-10-24"), board=board(8))
    assert view.tag == "BYE WEEK" and view.week == "NEXT WK 9"
    assert {view.away, view.home} == {"UGA", "FLA"}


def test_it_is_a_bye_only_in_the_week_that_has_no_game():
    assert view_of(now=WEEK_8, payload=as_of("2026-10-24"), board=board(7)).tag == ""
    assert view_of(now=WEEK_8, payload=as_of("2026-10-24"), board=board(9)).tag == ""
    assert view_of(board=board(12)).tag == "", "a week with a game"
    assert view_of(now=WEEK_8, payload=as_of("2026-10-24")).tag == "", "week unknown"
    assert view_of(now=WEEK_8, payload=as_of("2026-10-24"), board=board(8, 3)).tag == ""


def test_before_the_first_and_after_the_last_game_there_is_no_bye():
    assert (
        view_of(
            now=datetime(2026, 8, 30, 12, 0, tzinfo=UTC),
            payload=as_of("2026-08-30"),
            board=board(0),
        ).tag
        == ""
    )
    done = copy.deepcopy(SCHEDULE)
    for event in done["events"][:-1]:
        event["competitions"][0]["status"]["type"].update(state="post", completed=True)
    last = view_of(payload=done, board=board(14))
    assert last is None or last.tag == ""


# -- drawing ------------------------------------------------------------------------------------


def draw(view):
    c = AsciiCanvas(128, H)
    with use_directory(FBS):
        renderer().draw_fb_preview(c, view, NOV20)
    return c


def test_snapshots(update_snapshots):
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    cases = {
        "cfb_preview_ranked": view_of(),
        "cfb_preview_bye": view_of(now=WEEK_8, payload=as_of("2026-10-24"), board=board(8)),
        "cfb_preview_bowl": view_of(now=now, week_games=[bowl()]),
    }
    for name, view in cases.items():
        c = draw(view)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds, name


def test_the_rank_sits_in_front_of_the_record_under_each_crest():
    now = datetime(2026, 12, 6, 12, 0, tzinfo=UTC)
    view = dataclasses.replace(view_of(now=now, week_games=[bowl()]), away_record="9-1")
    c = draw(view)
    violet = {p for p, rgb in c.lit(0, 24, 127, 31).items() if rgb == RANK_COLOR}
    assert violet and all(y >= 26 for _, y in violet)
    left = [x for x, _ in violet if x < 64]
    assert min(left) >= 4 and max(left) < 30
    # the record follows its number, dim
    assert c.lit(min(left) + 6, 26, 27, 31), "the record"
    unranked = dataclasses.replace(view, away_rank=None, home_rank=None)
    assert not [1 for rgb in draw(unranked).lit(0, 24, 127, 31).values() if rgb == RANK_COLOR]


def test_the_nfl_preview_line_is_unchanged_without_ranks():
    from scoreboard.football.idle_views import PreviewView as View
    from test_football_idle_preview import PreviewView  # noqa: F401 - the NFL's own view type

    nfl = View("WSH", "NYG", NOV20, "", "WEEK 11", "7-2", "5-4")
    c = AsciiCanvas(128, H)
    renderer().draw_fb_preview(c, nfl, NOV20)
    assert not [1 for rgb in c.lit(0, 24, 127, 31).values() if rgb == RANK_COLOR]


def test_the_countdown_shows_each_teams_number_before_its_record(update_snapshots):
    g = game(
        "TEX", "ALA", "pre", 0, 0, short="11/22 - 12:00 PM EST", period=0, name="STATUS_SCHEDULED"
    )
    g = dataclasses.replace(
        g,
        start_utc=datetime(2026, 11, 22, 17, 0, tzinfo=UTC),
        away=dataclasses.replace(g.away, rank=5, record="8-2"),
        home=dataclasses.replace(g.home, rank=3, record="9-1"),
    )
    c = AsciiCanvas(128, H)
    draw_fb_countdown(renderer(), c, g, datetime(2026, 11, 22, 16, 17, tzinfo=UTC))
    check_snapshot("cfb_countdown_ranked", c.render(), update_snapshots)
    assert not c.out_of_bounds
    violet = {p for p, rgb in c.lit(0, 24, 127, 31).items() if rgb == RANK_COLOR}
    assert len({x < 64 for x, _ in violet}) == 2, "a number on each side"


def test_the_college_drawer_is_the_preview_layout():
    assert ci.COLLEGE_DRAWERS["cfb_preview"].__name__ == "_draw_preview"


# -- in the mode --------------------------------------------------------------------------------


class RealFeed:
    """A college feed with UGA's real schedule and the real polls, nothing else."""

    league = "college-football"
    last_error = ""
    directory = FBS  # what a real client has once its team table has loaded

    def __init__(self):
        self.games = [
            game("MIZ", "UGA", "post", 20, 31, short="Final", name="STATUS_FINAL", game_id=1)
        ]

    def scoreboard(self):
        return Scoreboard(tuple(self.games), 2, 2026, 12, (), ())

    def schedule(self, team_id):
        return schedule_from_payload(team_id, SCHEDULE)

    def college_rankings(self):
        return POLLS

    def close(self):
        pass


def test_a_college_board_rotates_to_the_next_game_with_its_rank():
    from scoreboard.football.mode import FootballMode

    clock = {"t": 1000.0}
    cfg = fcfg(favourite_team="UGA", rotation=[{"screen": "cfb_preview", "seconds": 8}])
    feed = RealFeed()
    mode = FootballMode(
        client_factory=lambda: feed,
        monotonic=lambda: clock["t"],
        football=lambda: cfg,
        utc_now=lambda: NOV20,
        league="college-football",
    )
    mode.idle_origin = 1000.0
    mode.worker.poll_once()
    with use_directory(FBS):
        scene = mode.scene()
    assert scene.kind == "cfb_preview", scene.kind
    assert scene.fb_idle.home == "SC" and scene.fb_idle.away_rank == 1
