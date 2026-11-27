"""The team stats over every timeout of a college game (owner's call, 2026-11-22).

NFL feeds mark an "Official Timeout"; the college feed does not: every stoppage is "Timeout
<team>", TV timeouts included (Georgia has five in one half of Georgia at South Carolina, and a
team gets three). So in a college game **every timeout** is a break that gets the stats card, in
place of the play's animation and sentence, held until the next play.

The stats are a trimmed real ESPN summary (``fixtures/football/live/uga_sc_team_stats.json``).
College's rows are its own: the feed has no yards per play and no sacks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoreboard.app import Scene
from scoreboard.config import ScoreboardConfig
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_stats import TRAILING
from scoreboard.football import api
from scoreboard.football import director as dr
from scoreboard.football.director import Director
from scoreboard.football.mode import FootballMode
from scoreboard.football.stats import COLLEGE_PAGES, PAGES, stats_from_summary
from scoreboard.football.teams import use_directory
from test_football_college import _fbs_directory
from test_football_college_events import ScoresRig
from test_football_events import make_play
from test_football_plays import FakeResponse, FakeSession
from test_football_scenes import H, check_snapshot, renderer
from test_football_stats import run_to_next_play

FBS = _fbs_directory()
RAW = json.loads(
    (
        Path(__file__).parent / "fixtures" / "football" / "live" / "uga_sc_team_stats.json"
    ).read_text()
)
STATS = stats_from_summary(RAW, COLLEGE_PAGES)
RUSH = make_play(0, "rush", off="WSH")
TIMEOUT = make_play(1, "timeout", off="WSH")


def college_rig(stats=STATS):
    rig = ScoresRig()
    rig.director = Director(
        lambda: rig.cfg,
        rig.clock,
        lambda: rig.delay,
        rig.clock.utc,
        scores_only=True,
        stats_at_timeouts=True,
        stats=lambda _game_id: stats,
    )
    rig.poll(RUSH)
    assert rig.run() == [], "the baseline is never shown"
    return rig


# -- the stats ---------------------------------------------------------------------------------


def test_the_real_college_stats_fill_every_row_of_both_pages():
    assert STATS is not None and STATS.layout is COLLEGE_PAGES and STATS.pages == 2
    for page in STATS.layout:
        assert len(page) == 5
        for row in page:
            assert STATS.value("away", row.key) != "-" and STATS.value("home", row.key) != "-", row
    assert (STATS.value("away", "totalYards"), STATS.value("home", "totalYards")) == ("261", "137")
    assert (STATS.value("away", "thirdDownEff"), STATS.value("home", "thirdDownEff")) == (
        "1/6",
        "3/8",
    )
    assert STATS.value("away", "possessionTime") == "23:56"


def test_the_nfl_rows_would_have_shown_dashes_for_the_two_the_college_feed_lacks():
    nfl = stats_from_summary(RAW)
    assert nfl is not None and nfl.layout is PAGES
    assert nfl.value("away", "yardsPerPlay") == "-" and nfl.value("away", "sacksYardsLost") == "-"


def test_the_college_client_keeps_the_college_layout_and_the_nfl_client_its_own():
    payload = {**RAW, "drives": {}}
    college = api.FootballClient(
        league="college-football", session=FakeSession(FakeResponse(payload))
    )
    college._directory = FBS
    college.plays(7)
    assert college.team_stats(7).layout is COLLEGE_PAGES
    nfl = api.FootballClient(session=FakeSession(FakeResponse(payload)))
    nfl.plays(7)
    assert nfl.team_stats(7).layout is PAGES


# -- the director ------------------------------------------------------------------------------


def test_a_timeout_is_the_stats_card_alone_with_no_animation_and_no_sentence():
    rig = college_rig()
    stages = run_to_next_play(rig, RUSH, TIMEOUT)
    assert [s.stage for s in stages] == [dr.STATS]
    assert stages[0].hold, "held until the next play"


def test_an_official_timeout_and_the_two_minute_warning_get_it_too():
    for kind in ("official_timeout", "two_minute_warning"):
        rig = college_rig()
        stages = run_to_next_play(rig, RUSH, make_play(1, kind, off="WSH"))
        assert [s.stage for s in stages] == [dr.STATS], kind


def test_the_feed_listing_one_timeout_twice_shows_it_once():
    rig = college_rig()
    twin = make_play(2, "timeout", off="WSH")  # same period and clock: how the feed repeats it
    stages = run_to_next_play(rig, RUSH, TIMEOUT, twin)
    assert [s.stage for s in stages] == [dr.STATS]


def test_two_timeouts_at_different_times_are_two_cards():
    rig = college_rig()
    rush9 = make_play(9, "rush", off="WSH")
    later = make_play(11, "timeout", off="WSH", clock="2:00")
    first = [s.stage for s in run_to_next_play(rig, RUSH, TIMEOUT)]
    rig.poll(RUSH, TIMEOUT, rush9, later, make_play(12, "rush", off="WSH"))
    second = [s.stage for s in rig.run()]
    assert first == [dr.STATS] and dr.STATS in second


def test_a_queue_that_has_fallen_behind_drops_the_timeouts_first_as_it_always_has():
    rig = college_rig()
    later = make_play(11, "timeout", off="WSH", clock="2:00")
    rig.poll(RUSH, TIMEOUT, later, make_play(4, "rush", off="WSH"), make_play(5, "rush", off="WSH"))
    assert rig.run() == []


def test_with_no_stats_to_show_a_timeout_shows_nothing_at_all():
    rig = college_rig(stats=None)
    rig.poll(RUSH, TIMEOUT, make_play(9, "rush", off="WSH"))
    assert rig.run() == []


def test_ordinary_plays_a_sack_and_a_missed_kick_still_show_nothing():
    rig = college_rig()
    rig.poll(RUSH, make_play(2, "pass_complete", off="WSH"), make_play(3, "sack", off="WSH"))
    assert rig.run() == []


def test_a_score_next_to_a_timeout_still_gets_its_celebration():
    rig = college_rig()
    rig.poll(RUSH, TIMEOUT, make_play(3, "rush_td_pat", score=(0, 7), off="WSH"))
    names = [s.stage for s in rig.run()]
    assert names == [dr.STATS, dr.EVENT, dr.DETAIL]


def test_the_nfl_director_is_unchanged_a_team_timeout_is_still_its_card_and_sentence():
    from test_football_director import Rig

    nfl = Rig()
    nfl.director._stats = lambda _game_id: STATS
    nfl.poll(RUSH)
    nfl.run()
    nfl.poll(RUSH, TIMEOUT)
    assert nfl.names() == [dr.PLAY, dr.PLAYTEXT], "no stats over a team timeout in the NFL"


def test_only_a_college_mode_adds_team_timeouts():
    def mode(league):
        return FootballMode(lambda: ScoreboardConfig(), client_factory=lambda: None, league=league)

    college, nfl = mode("college-football"), mode("nfl")
    assert college.director._breaks == (*dr.STATS_BREAKS, dr.PlayKind.TIMEOUT)
    assert nfl.director._breaks == dr.STATS_BREAKS


# -- the screen --------------------------------------------------------------------------------


def stats_scene(elapsed, stats=STATS):
    from test_football_scenes import game

    with use_directory(FBS):
        g = game("UGA", "SC", "in", 20, 6)
    return Scene(
        "fb_event",
        fb_game=g,
        fb_play=TIMEOUT,
        fb_stage=dr.STATS,
        fb_elapsed=elapsed,
        fb_seconds=12.0,
        fb_stats=stats,
    )


def draw(elapsed, width=128, stats=STATS):
    c = AsciiCanvas(width, H)
    with use_directory(FBS):
        renderer(width).draw_fb_play_scene(c, stats_scene(elapsed, stats))
    assert not c.out_of_bounds
    return c


@pytest.mark.parametrize(
    ("name", "elapsed"), [("fb_stats_college_page1", 1.0), ("fb_stats_college_page2", 13.0)]
)
def test_both_pages_draw_and_match_their_snapshots(update_snapshots, name, elapsed):
    c = draw(elapsed)
    assert c.pixels, "something is drawn"
    check_snapshot(name, c.render(), update_snapshots)


def test_the_pages_turn_and_differ_and_the_side_behind_on_a_row_is_dimmed():
    one, two = draw(1.0), draw(13.0)
    assert one.render() != two.render()
    assert draw(25.0).render() == one.render(), "back to the first page after the second"
    # page 1: Georgia (away, left) is ahead on every yardage row, so South Carolina's numbers
    # (right half) are the dim grey, and Georgia's are in its colour
    right = {rgb for (x, _), rgb in one.pixels.items() if x > 100}
    assert TRAILING in right


def test_a_single_64px_panel_is_never_given_the_split_table():
    mode = FootballMode(
        lambda: ScoreboardConfig(),
        client_factory=lambda: None,
        league="college-football",
        wide=lambda: False,
    )
    mode._stats = {7: STATS}
    assert mode._stats_for(7) is None
    wide = FootballMode(
        lambda: ScoreboardConfig(),
        client_factory=lambda: None,
        league="college-football",
        wide=lambda: True,
    )
    wide._stats = {7: STATS}
    assert wide._stats_for(7) is STATS
