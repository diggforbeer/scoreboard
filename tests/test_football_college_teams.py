"""The FBS team table built from ESPN's standings and /teams payloads (#540).

Hermetic: both fixtures are trimmed real captures (2026-11-20, week 12).
"""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from scoreboard.football import college_teams as ct
from scoreboard.football.api import FootballClient
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
GEORGIA, OHIO_STATE, OHIO_STATE_NEWARK, ABILENE = 61, 194, 3161, 2000


def load(name):
    return json.loads((FIXTURES / name).read_text())


def standings():
    return load("college_standings_trimmed.json")


def teams():
    return load("college_teams_trimmed.json")


@pytest.fixture(scope="module")
def table():
    return ct.table_from_payloads(standings(), teams())


def test_every_fbs_team_is_in_the_table_and_only_fbs(table):
    assert len(table) == 138
    # /teams lists every division (the fixture keeps an FCS team and a branch campus as decoys).
    ids = {t["team"]["id"] for t in teams()["sports"][0]["leagues"][0]["teams"]}
    assert str(ABILENE) in ids and str(OHIO_STATE_NEWARK) in ids and len(ids) == 140
    assert table.by_id(ABILENE) is None and table.by_id(OHIO_STATE_NEWARK) is None


def test_the_nested_sun_belt_is_not_lost_and_is_one_conference(table):
    # Its node has two division children and no standings of its own: a loop over the root's
    # children alone drops all fourteen teams.
    sun_belt = [t for t in table.teams if t.conference == "Sun Belt Conference"]
    assert len(sun_belt) == 14
    assert {t.conference for t in table.teams}.isdisjoint({"Sun Belt - East", "Sun Belt - West"})


def test_conference_sizes_match_the_feed(table):
    sizes = Counter(t.conference_short for t in table.teams)
    assert sizes == {
        "Big Ten": 18,
        "ACC": 17,
        "Big 12": 16,
        "SEC": 16,
        "American": 14,
        "Sun Belt": 14,
        "MAC": 13,
        "CUSA": 10,
        "Mountain West": 10,
        "Pac-12": 8,
        "FBS Indep.": 2,
    }


def test_teams_are_keyed_by_id_and_osu_means_ohio_state(table):
    osu = table.by_id(OHIO_STATE)
    assert (osu.abbrev, osu.location, osu.conference_short) == ("OSU", "Ohio State", "Big Ten")
    assert table.by_abbrev("osu") is osu
    # The collision is real in the unfiltered list, which is why the id is the key.
    everyone = [t["team"] for t in teams()["sports"][0]["leagues"][0]["teams"]]
    assert Counter(t["abbreviation"] for t in everyone)["OSU"] == 2


def test_abbreviations_are_unique_within_fbs(table):
    assert max(Counter(t.abbrev for t in table.teams).values()) == 1


def test_a_team_carries_its_names_and_conference(table):
    uga = table.by_id(GEORGIA)
    assert (uga.abbrev, uga.location, uga.nickname) == ("UGA", "Georgia", "Bulldogs")
    assert (uga.name, uga.conference, uga.conference_short) == (
        "GEORGIA",
        "Southeastern Conference",
        "SEC",
    )
    assert table.by_id("61") is uga and table.by_id("nope") is None and table.by_id(None) is None


def test_conferences_are_a_to_z_with_the_independents_last_and_teams_a_to_z(table):
    groups = table.conferences()
    names = [name for name, _short, _teams in groups]
    assert names == [*sorted(names[:-1]), ct.INDEPENDENTS]
    for _name, _short, members in groups:
        assert [t.name for t in members] == sorted(t.name for t in members)
    assert sum(len(members) for *_rest, members in groups) == 138


def test_no_primary_colour_is_too_dark_for_the_panel(table):
    dark = [(t.abbrev, t.color) for t in table.teams if ct._luma(t.color) < ct.MIN_LUMA]
    assert dark == []
    assert all(len(t.color) == 3 and len(t.secondary) == 3 for t in table.teams)
    assert all(0 <= c <= 255 for t in table.teams for c in (*t.color, *t.secondary))


def test_a_bright_primary_is_kept_exactly():
    assert ct.led_colors("ffcb05", "00274c")[0] == (255, 203, 5)


def test_navy_is_lifted_to_a_lighter_shade_of_its_own_hue():
    primary, _ = ct.led_colors("00274c", "ffcb05")
    assert ct._luma(primary) >= ct.MIN_LUMA
    assert primary[2] > primary[0] and primary[2] > primary[1], "still a blue"


def test_a_pure_saturated_blue_is_washed_out_until_it_reads():
    primary, _ = ct.led_colors("0000e6", "ffffff")
    assert ct._luma(primary) >= ct.MIN_LUMA and primary[2] == max(primary)


def test_black_takes_the_alternate_if_it_reads_else_a_neutral_grey():
    assert ct.led_colors("000000", "c8102e")[0] == (200, 16, 46)
    assert ct.led_colors("000000", "000000")[0] == ct.NEUTRAL
    assert ct.led_colors("222222", None)[0] == ct.NEUTRAL


def test_missing_or_malformed_colours_fall_back_rather_than_fail():
    assert ct.led_colors(None, None) == (ct.NEUTRAL, ct.WHITE)
    assert ct.led_colors("zzzzzz", "12") == (ct.NEUTRAL, ct.WHITE)
    assert ct.led_colors("#ffcb05", "#00274c")[0] == (255, 203, 5)


def test_a_secondary_that_matches_the_primary_is_replaced():
    main, second = ct.led_colors("c8102e", "c8102e")
    assert main != second and second == ct.WHITE


def test_a_team_missing_from_the_teams_list_is_kept_in_neutral_colours(caplog):
    payload = teams()
    listed = payload["sports"][0]["leagues"][0]["teams"]
    payload["sports"][0]["leagues"][0]["teams"] = [
        t for t in listed if t["team"]["id"] != str(GEORGIA)
    ]
    with caplog.at_level("WARNING"):
        table = ct.table_from_payloads(standings(), payload)
    uga = table.by_id(GEORGIA)
    assert uga is not None and uga.color == ct.UNKNOWN_COLOR
    assert "not in /teams" in caplog.text and len(table) == 138


def test_a_bad_standings_entry_is_skipped_not_fatal(caplog):
    payload = copy.deepcopy(standings())
    entries = payload["children"][0]["standings"]["entries"]
    entries.append({"team": {"abbreviation": "XX"}})  # no id
    entries.append({"team": {"id": "9", "abbreviation": ""}})  # no abbreviation
    entries.append({"nonsense": True})
    with caplog.at_level("WARNING"):
        table = ct.table_from_payloads(payload, teams())
    assert len(table) == 138 and "no usable id" in caplog.text


def test_garbage_in_gives_none_not_a_crash():
    assert ct.table_from_payloads({}, {}) is None
    assert ct.table_from_payloads(None, None) is None
    assert ct.table_from_payloads({"children": "x"}, teams()) is None
    assert ct.table_from_payloads({"children": [{"name": "", "children": []}]}, teams()) is None


def test_teams_payload_in_the_wrong_shape_still_builds_with_neutral_colours():
    table = ct.table_from_payloads(standings(), {"sports": []})
    assert len(table) == 138 and all(t.color == ct.UNKNOWN_COLOR for t in table.teams)


# -- the client ---------------------------------------------------------------------


def college_client(*responses):
    return FootballClient(league="college-football", session=FakeSession(*responses))


def test_the_client_makes_the_two_requests_and_builds_the_table():
    c = college_client(FakeResponse(standings()), FakeResponse(teams()))
    table = c.college_teams()
    (surl, sparams), (turl, tparams) = c.session.calls
    assert surl == "https://site.api.espn.com/apis/v2/sports/football/college-football/standings"
    assert sparams == {"group": "80"}
    assert turl == "https://site.api.espn.com/apis/site/v2/sports/football/college-football/teams"
    assert tparams == {"limit": "1000"}
    assert len(table) == 138


def test_either_request_failing_gives_none_so_nothing_half_built_is_kept():
    assert college_client(FakeResponse(status=500)).college_teams() is None
    assert (
        college_client(FakeResponse(standings()), FakeResponse(status=500)).college_teams() is None
    )


def test_an_nfl_client_refuses_to_build_a_college_table():
    with pytest.raises(ValueError, match="college-football client"):
        FootballClient(session=FakeSession()).college_teams()
