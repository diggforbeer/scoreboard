"""The conference standings idle screen (#553): the parser, the view, the drawing, the fetch.

Hermetic: ``college_conference_standings_trimmed.json`` is a real ``group=80`` capture (2026-11-20)
cut to the American, the FBS Independents, the Pac-12 and the nested Sun Belt, with the stats that
matter and the ones that make parsing by name wrong (the repeated ``wins``).
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scoreboard.display import college_idle as ci
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_scenes import LIVE, RANK_COLOR, RED_ZONE, WHITE
from scoreboard.football import scroll
from scoreboard.football.api import FootballClient
from scoreboard.football.college_standings import (
    college_standings_from_payload,
    short_conference,
)
from scoreboard.football.college_views import build_conference
from scoreboard.football.idle import STANDINGS_TTL, Cached, IdleSnapshot
from scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from scoreboard.football.teams import use_directory
from teamcfg import fcfg
from test_football_college import _fbs_directory
from test_football_college_ap import college_mode
from test_football_plays import FakeResponse
from test_football_scenes import H, check_snapshot, renderer

PAYLOAD = json.loads(
    (
        Path(__file__).parent
        / "fixtures"
        / "football"
        / "college_conference_standings_trimmed.json"
    ).read_text()
)
TABLES = college_standings_from_payload(PAYLOAD)
FBS = _fbs_directory()
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def table(abbrev):
    return TABLES.conference_of(abbrev)


def ctx(favourite="UTSA", standings=TABLES, age=0.0, **cfg):
    snap = IdleSnapshot(
        college_standings_cached=Cached(standings, 0.0) if standings is not None else None
    )
    return IdleContext(age, NOW, [], snap, fcfg(favourite_team=favourite, **cfg))


def draw(view, px=0):
    c = AsciiCanvas(128, H)
    with use_directory(FBS):
        ci.draw_cfb_conference(renderer(), c, view, px)
    return c


# -- the parser ---------------------------------------------------------------------------------


def test_each_conference_is_a_table_and_the_sun_belt_is_merged_from_its_divisions():
    names = [t.short for t in TABLES.conferences]
    assert names == ["AAC", "IND", "PAC", "SBC"]
    assert [len(t.rows) for t in TABLES.conferences] == [14, 2, 8, 14]
    sun = table("GASO")
    assert {r.abbrev for r in sun.rows} >= {"LT", "GASO", "JMU", "ODU"}, "East and West together"
    assert [r.seed for r in sun.rows] == list(range(1, 15)), "the seeds run across both divisions"


def test_the_table_is_in_seed_order_not_in_the_order_the_feed_lists_it():
    listed = [e["team"]["abbreviation"] for e in PAYLOAD["children"][0]["standings"]["entries"]]
    ordered = [r.abbrev for r in table("UTSA").rows]
    assert listed != ordered
    assert ordered[:7] == ["UTSA", "MEM", "UNT", "UAB", "ECU", "ARMY", "TLSA"]
    assert listed.index("ARMY") > listed.index("TLSA"), "listed later, seeded earlier"


def test_records_are_read_by_type_never_by_the_name_that_repeats():
    utsa = next(r for r in table("UTSA").rows if r.abbrev == "UTSA")
    assert (utsa.overall, utsa.conf, utsa.seed, utsa.streak) == ("8-2", "5-1", 1, "W1")
    entry = PAYLOAD["children"][0]["standings"]["entries"][0]
    wins = [s for s in entry["stats"] if s["name"] == "wins"]
    assert len(wins) > 1 and len({s["displayValue"] for s in wins}) > 1, "the trap is in the data"


def test_a_team_with_no_conference_schedule_has_no_conference_record():
    assert [(r.abbrev, r.overall, r.conf) for r in table("ND").rows] == [
        ("ND", "9-1", ""),
        ("CONN", "5-5", ""),
    ]


def test_conference_names_are_short():
    assert short_conference("Big Ten") == "B1G" and short_conference("FBS Indep.") == "IND"
    assert TABLES.conferences[0].name == "American Conference"


def test_a_payload_that_is_not_standings_gives_none_and_a_bad_entry_is_skipped():
    for bad in (None, {}, {"children": []}, {"children": ["x"]}, [], {"children": [{"name": "A"}]}):
        assert college_standings_from_payload(bad) is None, bad
    broken = copy.deepcopy(PAYLOAD)
    broken["children"][0]["standings"]["entries"].insert(0, {"team": {"id": "x"}})
    assert len(college_standings_from_payload(broken).conferences[0].rows) == 14


def test_a_missing_seed_goes_last_and_a_missing_stat_is_an_empty_string():
    odd = copy.deepcopy(PAYLOAD)
    entries = odd["children"][0]["standings"]["entries"]
    entries[0]["stats"] = [s for s in entries[0]["stats"] if s["type"] != "playoffseed"]
    entries[1]["stats"] = []
    rows = college_standings_from_payload(odd).conferences[0].rows
    assert rows[-1].abbrev in ("UTSA", "MEM") and rows[-2].abbrev in ("UTSA", "MEM")
    memphis = next(r for r in rows if r.abbrev == "MEM")
    assert (memphis.overall, memphis.conf, memphis.seed, memphis.streak) == ("", "", None, "")


# -- the view -----------------------------------------------------------------------------------


def test_the_view_is_the_lead_teams_conference():
    view = build_conference(ctx("UTSA"))
    assert view.short == "AAC" and view.team == "UTSA" and view.scroll_rows == 14
    assert build_conference(ctx("GASO")).short == "SBC"
    assert IDLE_SCREENS["cfb_conference"](ctx("ND")) is not None


@pytest.mark.parametrize("favourite", ["", "UGA", "ZZZZ"])
def test_no_view_for_a_team_not_in_the_tables(favourite):
    assert build_conference(ctx(favourite)) is None, "skipped, never blank"


def test_no_view_before_the_standings_arrive_or_once_they_are_stale():
    assert build_conference(ctx(standings=None)) is None
    assert build_conference(ctx(age=STANDINGS_TTL)) is not None, "an hour old is still current"
    assert build_conference(ctx(age=STANDINGS_TTL * 2 + 1)) is None, "past twice the TTL: stale"


def test_no_view_before_a_game_has_been_played():
    fresh = copy.deepcopy(PAYLOAD)
    for node in fresh["children"]:
        nodes = node.get("children") or [node]
        for n in nodes:
            for entry in n["standings"]["entries"]:
                for stat in entry["stats"]:
                    if stat["type"] in ("total", "vsconf"):
                        stat["summary"] = stat["displayValue"] = "0-0"
    assert build_conference(ctx("UTSA", standings=college_standings_from_payload(fresh))) is None


# -- the drawing --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "team", "px"),
    [
        ("cfb_conf_american_top", "UTSA", 0),
        ("cfb_conf_american_mid", "MEM", 40),
        ("cfb_conf_independents", "ND", 0),
        ("cfb_conf_sun_belt", "GASO", 0),
    ],
)
def test_snapshots(name, team, px, update_snapshots):
    c = draw(build_conference(ctx(team)), px)
    check_snapshot(name, c.render(), update_snapshots)
    assert all(0 <= x < 128 for x, _ in c.out_of_bounds)


def test_the_lead_team_is_white_with_a_bar_and_the_others_are_grey():
    c = draw(build_conference(ctx("UTSA")))
    assert WHITE in c.colors(0, 0, 127, 5) and RANK_COLOR in c.colors(0, 0, 127, 5)
    assert c.lit(ci.LABEL_WIDTH - 1, 0, ci.LABEL_WIDTH - 1, 5), "the bar"
    assert WHITE not in c.colors(0, 7, 127, 24), "only the lead team's row is white"
    nobody = draw(build_conference(ctx("ND")), 0)
    assert not nobody.lit(ci.LABEL_WIDTH - 1, 7, ci.LABEL_WIDTH - 1, 24), "no bar on the others"


def test_streaks_are_green_for_a_win_and_red_for_a_loss():
    c = draw(build_conference(ctx("UTSA")))
    right = (96, 0, 127, 24)
    assert LIVE in c.colors(*right) and RED_ZONE in c.colors(*right), "W1 W2 L1 W2 W3"
    assert RED_ZONE not in c.colors(ci.LABEL_WIDTH, 0, 95, 24), "red only on a losing streak"


def test_a_team_with_no_conference_record_shows_a_dash_and_its_overall_record():
    ind = draw(build_conference(ctx("ND")))
    american = draw(build_conference(ctx("UTSA")))
    area = (ci.LABEL_WIDTH + 2 + ci.CONF_RECORD_X, 0, ci.LABEL_WIDTH + 2 + ci.CONF_OVERALL_X - 2, 5)
    assert len(ind.lit(*area)) < len(american.lit(*area)), "a dash, not a record"
    assert ind.lit(ci.LABEL_WIDTH + 2 + ci.CONF_OVERALL_X, 0, 127, 5), "the overall record"


def test_the_label_names_the_conference_and_stays_while_the_rows_scroll():
    view = build_conference(ctx("UTSA"))
    a, b = draw(view, 0), draw(view, 40)
    label = (0, 0, ci.LABEL_WIDTH - 2, 31)
    assert a.lit(*label) == b.lit(*label)
    assert draw(build_conference(ctx("GASO")), 0).lit(*label) != a.lit(*label)


def test_only_rows_part_way_off_the_panel_are_clipped():
    view = build_conference(ctx("UTSA"))
    for px in (0, 11, scroll.scroll_range(14)):
        for x, y in draw(view, px).out_of_bounds:
            assert 0 <= x < 128 and (y < 0 or y >= 32), (px, x, y)


# -- the fetch ----------------------------------------------------------------------------------


def client_with(routes):
    from test_football_college_ranks import Feed, scoreboard

    feed = Feed(scoreboard(), None)
    feed.session.routes.update(routes)
    return feed


def test_the_client_reads_the_group_80_table_and_only_a_college_client_may():
    feed = client_with({"/standings": FakeResponse(PAYLOAD)})
    got = feed.college_standings()
    assert [t.short for t in got.conferences] == ["AAC", "IND", "PAC", "SBC"]
    assert feed.session.calls[-1][1] == {"group": "80"}
    with pytest.raises(ValueError):
        FootballClient().college_standings()
    assert FootballClient(league="college-football").standings() is None, "the NFL's is not it"


def test_a_failed_fetch_is_no_data_not_a_crash(caplog):
    feed = client_with({"/standings": FakeResponse(status=500)})
    with caplog.at_level(logging.WARNING):
        assert feed.college_standings() is None


def test_the_mode_fetches_the_tables_only_when_the_screen_is_listed_and_hourly():
    mode, _ = college_mode(favourite="UTSA", rows=(("cfb_conference", 8.0),), standings=PAYLOAD)
    client = mode.worker._client
    first = mode.snapshot.idle.college_standings_cached
    assert first is not None and first.value.conference_of("UTSA") is not None

    def table_requests():
        return sum(1 for _, params in client.session.calls if params == {"group": "80"})

    seen = table_requests()
    mode.worker.poll_once()
    assert table_requests() == seen, "not again inside the hour"
    unlisted, _ = college_mode(favourite="UTSA", rows=(("cfb_ap", 8.0),), standings=PAYLOAD)
    assert unlisted.snapshot.idle.college_standings_cached is None, "not listed, not fetched"


def test_the_slot_scrolls_the_table_and_is_skipped_when_the_team_is_in_none():
    mode, clock = college_mode(favourite="UTSA", rows=(("cfb_conference", 8.0),), standings=PAYLOAD)
    total = scroll.scroll_seconds(14, 8.0)
    clock["mono"] = 1000.0 + total / 2
    scene = mode.scene()
    assert scene.kind == "cfb_conference" and scene.scrolling and scene.scroll_px > 0
    clock["mono"] = 1000.0 + total - 0.5  # in the rest at the bottom, before the wrap
    assert mode.scene().scroll_px == scroll.scroll_range(14)
    other, _ = college_mode(favourite="UGA", rows=(("cfb_conference", 8.0),), standings=PAYLOAD)
    assert other.scene().kind != "cfb_conference"
