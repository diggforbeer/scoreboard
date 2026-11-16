"""The team stats over a TV timeout: parsing, who is ahead, when the stage is added, the screen.

The payload is a trimmed real ESPN ``summary`` (JAX at TEN, 2026-11-15, second quarter).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from football_logos import write_synthetic_football_logos
from scoreboard.app import Scene
from scoreboard.display import football_stats as fs
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.logos import LogoLibrary, LogoSet
from scoreboard.football import api
from scoreboard.football import director as dr
from scoreboard.football.demo import DEMO_STATS
from scoreboard.football.stats import (
    PAGES,
    GameStats,
    StatRow,
    display,
    stats_from_summary,
)
from scoreboard.football.teams import team_color
from test_football_director import started, td
from test_football_events import make_game, make_play
from test_football_plays import FakeResponse, FakeSession
from test_football_scenes import check_snapshot, renderer

FIXTURE = Path(__file__).parent / "fixtures" / "football" / "summary_team_stats.json"
RAW = json.loads(FIXTURE.read_text())
OFFICIAL = make_play(1, "official_timeout", off="NYG")
WARNING = make_play(1, "two_minute_warning", off="NYG")
TIMEOUT = make_play(1, "timeout", off="NYG")


# -- parsing ---------------------------------------------------------------------------------


def test_the_real_payload_reads_into_both_sides():
    stats = stats_from_summary(RAW)
    assert stats is not None
    assert (stats.value("away", "totalYards"), stats.value("home", "totalYards")) == ("197", "46")
    assert (stats.value("away", "rushingYards"), stats.value("home", "rushingYards")) == ("36", "7")
    assert stats.value("home", "possessionTime") == "6:51"  # the feed pads it: " 6:51"
    assert stats.value("away", "thirdDownEff") == "4/5"


def test_sides_are_matched_by_home_away_never_by_order():
    flipped = {"boxscore": {"teams": list(reversed(RAW["boxscore"]["teams"]))}}
    assert stats_from_summary(flipped) == stats_from_summary(RAW)


@pytest.mark.parametrize(
    "payload",
    [{}, {"boxscore": None}, {"boxscore": {"teams": "no"}}, {"boxscore": {"teams": []}},
     {"boxscore": {"teams": [{"homeAway": "home", "statistics": []}]}}],
)  # fmt: skip
def test_a_payload_without_usable_stats_is_none_and_never_raises(payload):
    assert stats_from_summary(payload) is None


def test_a_game_with_no_yards_yet_is_not_worth_a_screen():
    team = {"statistics": [{"name": "totalYards", "displayValue": ""}]}
    payload = {"boxscore": {"teams": [{**team, "homeAway": "home"}, {**team, "homeAway": "away"}]}}
    assert stats_from_summary(payload) is None


def test_malformed_entries_are_skipped():
    teams = [dict(t) for t in RAW["boxscore"]["teams"]]
    teams[0]["statistics"] = ["junk", {"name": 3}, *teams[0]["statistics"]]
    stats = stats_from_summary({"boxscore": {"teams": teams}})
    assert stats is not None and stats.value("away", "totalYards") == "197"


def test_the_displayed_text():
    assert (display(" 6:51"), display("4-5"), display(""), display("7.9")) == (
        "6:51", "4/5", "-", "7.9")  # fmt: skip


# -- who is ahead ----------------------------------------------------------------------------


def stats(key, away, home):
    return GameStats(away={key: away}, home={key: home})


def test_more_is_ahead_for_yards_and_a_dash_is_not_a_minus_sign():
    row = StatRow("x", "X")
    assert stats("x", "197", "46").leader(row) == "away"
    assert stats("x", "-2", "5").leader(row) == "home"  # a real negative number
    assert stats("x", "7.9", "2.7").leader(row) == "away"


def test_third_downs_are_compared_as_a_rate_not_by_the_first_number():
    row = StatRow("x", "X", "ratio")
    assert stats("x", "4-5", "1-5").leader(row) == "away"  # the dash was once read as "-5"
    assert stats("x", "1-1", "3-6").leader(row) == "away"  # 100% beats 50% on fewer tries
    assert stats("x", "0-0", "0-0").leader(row) is None


def test_fewer_is_ahead_for_turnovers_and_penalties():
    row = StatRow("x", "X", "lower")
    assert stats("x", "0", "2").leader(row) == "away"
    assert stats("x", "1-0", "0-0").leader(row) == "home"


def test_possession_compares_as_time_and_a_tie_or_unreadable_value_has_no_leader():
    row = StatRow("x", "X")
    assert stats("x", "13:10", "6:51").leader(row) == "away"
    assert stats("x", "9:59", "10:00").leader(row) == "home"
    assert stats("x", "5", "5").leader(row) is None
    assert stats("x", "", "5").leader(row) is None
    assert stats("x", "n/a", "5").leader(row) is None
    assert stats("x", "5", "3").leader(StatRow("x", "X", "none")) is None


# -- the client keeps them from the plays request --------------------------------------------


def test_the_stats_come_from_the_plays_request_with_no_second_one():
    payload = {**RAW, "drives": {}}
    session = FakeSession(FakeResponse(payload))
    client = api.FootballClient(session=session)
    assert client.team_stats(7) is None
    assert client.plays(7) == []
    assert client.team_stats(7) == stats_from_summary(RAW)
    assert len(session.calls) == 1


def test_a_failed_plays_request_keeps_the_last_stats():
    session = FakeSession(FakeResponse({**RAW, "drives": {}}), FakeResponse({}, 500))
    client = api.FootballClient(session=session)
    client.plays(7)
    assert client.plays(7) is None
    assert client.team_stats(7) is not None


# -- the director adds the stage -------------------------------------------------------------


def run_to_next_play(rig, *plays):
    """Poll ``plays`` (the break last) with the next play already behind it, and return what was
    shown: the held stats stage gives way to that play at once."""
    rig.poll(*plays, make_play(9, "rush", off="WSH"))
    return rig.run()


def rig_with(stats, *first):
    rig = started(*first)
    rig.director._stats = lambda _game_id: stats
    return rig


@pytest.mark.parametrize("play", [OFFICIAL, WARNING])
def test_a_tv_timeout_ends_on_the_team_stats_instead_of_the_sentence(play):
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    names = [s.stage for s in run_to_next_play(rig, make_play(0, "rush", off="WSH"), play)]
    assert names[:2] == [dr.PLAY, dr.STATS]


def test_the_stats_page_length_is_the_owners_and_is_clamped():
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    rig.director._timings = lambda: dr.Timings(stats=9.0)
    stages = run_to_next_play(rig, make_play(0, "rush", off="WSH"), OFFICIAL)
    assert [s.seconds for s in stages if s.stage == dr.STATS] == [9.0]
    assert dr.Timings(stats=1.0).clamped().stats == 3.0
    assert dr.Timings(stats=99.0).clamped().stats == 40.0


def test_without_stats_the_play_text_still_follows_as_before():
    rig = started(make_play(0, "rush", off="WSH"))
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL)
    assert rig.names() == [dr.PLAY, dr.PLAYTEXT]


def test_a_team_timeout_and_ordinary_plays_never_get_the_stats():
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    rig.poll(make_play(0, "rush", off="WSH"), TIMEOUT)
    assert rig.names() == [dr.PLAY, dr.PLAYTEXT]
    rig.poll(make_play(0, "rush", off="WSH"), TIMEOUT, td(3))
    assert dr.STATS not in {s.stage for s in rig.run()}


def test_a_late_stats_fetch_is_read_when_the_play_is_built_not_when_it_arrives():
    holder = {}
    rig = started(make_play(0, "rush", off="WSH"))
    rig.director._stats = lambda game_id: holder.get(game_id)
    holder[rig.game.id] = DEMO_STATS
    stages = run_to_next_play(rig, make_play(0, "rush", off="WSH"), OFFICIAL)
    assert dr.STATS in [s.stage for s in stages]


# -- the screen -----------------------------------------------------------------------------


def scene(share=0.0, stats=DEMO_STATS, game=None):
    return Scene(
        "fb_event", fb_game=game or make_game(), fb_play=OFFICIAL, fb_stage="stats",
        fb_stats=stats, fb_elapsed=share, fb_seconds=12.0, animating=True,
    )  # fmt: skip


def draw(share=0.0, logos=None, width=128, **kw):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.football_logos = logos
    r.draw_fb_play_scene(canvas, scene(share, **kw))
    assert not canvas.out_of_bounds
    return canvas


def synthetic_logos(tmp_path):
    base = write_synthetic_football_logos(tmp_path) / "football"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    return LogoSet("football", "dark", libs)


@pytest.mark.parametrize(("name", "share"), [("first", 1.0), ("second", 13.0)])
def test_each_page_snapshot(name, share, update_snapshots):
    check_snapshot(f"fb_stats_{name}", draw(share).render(), update_snapshots)


def test_pages_take_turns_for_as_long_as_the_stage_is_held():
    seconds = [0.0, 11.9, 12.0, 23.9, 24.0, 100.0]
    assert [fs.page_of(scene(s), 2) for s in seconds] == [0, 0, 1, 1, 0, 0]
    assert fs.page_of(Scene("fb_event", fb_seconds=0.0), 2) == 0


def test_the_leader_is_lit_in_team_colour_and_the_trailing_side_dims():
    # Page one: WSH ahead on every yardage row, tied on first downs (both stay lit).
    canvas = draw(1.0)
    away, home = team_color("WSH"), team_color("NYG")
    assert canvas.colors(fs.LEFT_X, 0, fs.LEFT_X + 20, 31) == {away}
    assert canvas.colors(fs.RIGHT_X - 20, 0, fs.RIGHT_X, 31) == {fs.TRAILING, home}
    # Page two: NYG is behind on the third-down rate, and WSH has fewer penalties.
    second = draw(13.0)
    assert fs.TRAILING in second.colors(fs.RIGHT_X - 20, 0, fs.RIGHT_X, 31)
    row = second.colors(fs.LEFT_X, 1, fs.LEFT_X + 20, 5)  # the 3rd-down row, WSH 4/5 vs NYG 1/5
    assert row == {away}


def test_the_second_page_marks_its_dot_and_shows_the_other_rows():
    first, second = draw(1.0), draw(13.0)
    assert first.render() != second.render()
    lit = lambda c, x: c.pixels.get((x, 28)) == fs.LIT_DOT  # noqa: E731
    assert lit(first, 6) and not lit(first, 10)
    assert lit(second, 10) and not lit(second, 6)


def test_everything_fits_and_the_text_stays_between_the_logos():
    box = draw(1.0).bbox(16, 0, 111, 31)
    assert box.x0 >= fs.LEFT_X and box.x1 <= fs.RIGHT_X


def test_logos_sit_at_the_edges_when_there_are_some(tmp_path):
    canvas = draw(1.0, logos=synthetic_logos(tmp_path))
    assert canvas.lit(0, 8, 15, 23) and canvas.lit(112, 8, 127, 23)
    assert not canvas.lit(0, 0, 15, 7)


def test_missing_stats_draw_nothing_rather_than_raise():
    assert draw(1.0, stats=None).lit() == {}


def test_pages_are_five_rows_so_they_fit_the_panel():
    assert all(len(page) <= len(fs.ROW_BASELINES) for page in PAGES)


# -- the mode --------------------------------------------------------------------------------


def test_the_mode_hands_the_director_stats_on_a_wide_panel_only():
    from scoreboard.football.mode import FootballMode

    wide = {"on": True}
    mode = FootballMode(client_factory=lambda: None, wide=lambda: wide["on"])
    mode._stats = {1: DEMO_STATS}
    assert mode._stats_for(1) is DEMO_STATS
    wide["on"] = False
    assert mode._stats_for(1) is None
    assert mode.director._stats == mode._stats_for


class StatsClient:
    def __init__(self):
        self.stats = {7: DEMO_STATS}

    def team_stats(self, game_id):
        return self.stats.get(game_id)


def test_the_worker_side_keeps_the_stats_and_a_failed_read_keeps_the_last_good():
    from scoreboard.football.mode import FootballMode

    mode = FootballMode(client_factory=lambda: None)
    client = StatsClient()
    mode._keep_stats(client, 7)
    assert mode._stats == {7: DEMO_STATS}
    before = mode._stats
    client.stats = {}
    mode._keep_stats(client, 7)
    assert mode._stats is before  # nothing new, nothing lost
    mode._keep_stats(object(), 7)  # a client with no stats method (a test fake)
    assert mode._stats is before
    mode.stop()
    assert mode._stats == {}


# -- held until play resumes ------------------------------------------------------------------


def on_stats(rig, limit=2000):
    """Advance until the stats are on screen; return the current stage."""
    for _ in range(limit):
        cur = rig.director.current(rig.game.id)
        if cur is not None and cur.stage.stage == dr.STATS:
            return cur
        rig.clock.advance(0.25)
    raise AssertionError("the stats never came up")


def test_the_stats_stay_up_across_pages_until_the_next_play_arrives():
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL)
    on_stats(rig)
    for _ in range(120):  # two minutes with no new play: still up
        rig.clock.advance(1.0)
        cur = rig.director.current(rig.game.id)
        assert cur is not None and cur.stage.stage == dr.STATS
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL, make_play(2, "rush", off="WSH"))
    rig.clock.advance(0.25)
    cur = rig.director.current(rig.game.id)
    assert cur is not None and cur.stage.stage == dr.PLAY  # the next play took the screen


def test_a_feed_that_never_delivers_the_next_play_does_not_hold_the_stats_forever():
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL)
    on_stats(rig)
    rig.clock.advance(dr.HOLD_CAP_SECONDS + 1)
    assert rig.director.current(rig.game.id) is None


def test_the_same_stoppage_listed_twice_is_shown_once():
    twin = make_play(2, "official_timeout", off="NYG")
    rig = rig_with(DEMO_STATS, make_play(0, "rush", off="WSH"))
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL, twin)
    on_stats(rig)
    rig.clock.advance(1.0)
    rig.poll(make_play(0, "rush", off="WSH"), OFFICIAL, twin, make_play(3, "rush", off="WSH"))
    seen = []
    for _ in range(200):
        cur = rig.director.current(rig.game.id)
        if cur is None:
            break
        if not seen or seen[-1] is not cur.stage:
            seen.append(cur.stage)
        rig.clock.advance(0.25)
    assert [s.stage for s in seen].count(dr.STATS) == 0  # no second stats screen for the twin


def test_sacks_allowed_replaced_total_plays_and_fewer_is_ahead():
    labels = [row.label for page in PAGES for row in page]
    assert "SACKS ALLOWED" in labels and "TOTAL PLAYS" not in labels
    row = next(r for page in PAGES for r in page if r.key == "sacksYardsLost")
    assert stats("sacksYardsLost", "0-0", "2-14").leader(row) == "away"
