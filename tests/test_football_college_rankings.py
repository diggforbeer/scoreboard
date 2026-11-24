"""College polls from ESPN's /rankings, and which one decides "ranked" (#546).

Hermetic: ``college_rankings_trimmed.json`` is a trimmed real capture (2026-11-20, week 12).
"""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scoreboard.config import FootballConfig, Settings
from scoreboard.football import college_rankings as cr
from scoreboard.football.api import FootballClient
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
GEORGIA = 61
#: A moment in the week of the capture; the AP poll is dated 2026-11-16, the CFP's 11-17.
NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def payload():
    return json.loads((FIXTURES / "college_rankings_trimmed.json").read_text())


@pytest.fixture(scope="module")
def polls():
    return cr.polls_from_payload(payload())


def test_only_the_three_polls_the_board_reads_are_kept(polls):
    # The capture also holds the FCS poll, which is ignored.
    assert sorted(polls.polls) == ["ap", "cfp", "usa"]
    assert any(p["type"] == "fcs" for p in payload()["rankings"])


def test_each_poll_is_a_top_25_in_order(polls):
    for poll in polls.polls.values():
        assert [e.rank for e in poll.entries] == list(range(1, 26))
        assert len({e.team_id for e in poll.entries}) == 25


def test_an_entry_has_its_team_record_and_votes(polls):
    top = polls.get("ap").entries[0]
    assert (top.rank, top.team_id, top.abbrev) == (1, GEORGIA, "UGA")
    assert top.record == "9-1"
    # Only the committee's entries name a conference; the AP's leave it empty.
    assert top.conference == "" and polls.get("cfp").entries[0].conference == "SEC"
    assert top.points > 0 and top.first_place_votes > 0
    # The committee has no points or first-place votes.
    assert polls.get("cfp").entries[0].points == 0


def test_movement_is_places_gained_and_none_for_a_new_entry(polls):
    ap = polls.get("ap")
    for e in ap.entries:
        if e.previous is None:
            assert e.movement is None
        else:
            assert e.movement == e.previous - e.rank
    new = [e for e in ap.entries if e.previous is None]
    assert new, "the capture has teams that entered the poll this week"
    risers = [e for e in ap.entries if (e.movement or 0) > 0]
    fallers = [e for e in ap.entries if (e.movement or 0) < 0]
    assert risers and fallers


def test_movement_agrees_with_espns_own_trend_text(polls):
    raw = {x["team"]["id"]: x["trend"] for x in payload()["rankings"][1]["ranks"]}
    for e in polls.get("ap").entries:
        trend = raw[str(e.team_id)]
        if trend == "-":
            assert e.movement == 0 or e.previous is None
        elif e.movement is not None:
            assert int(trend) == e.movement


def test_rank_lookup_is_by_id_and_unranked_is_none(polls):
    ap = polls.get("ap")
    assert ap.rank_of(GEORGIA) == 1 and ap.rank_of(str(GEORGIA)) == 1
    assert ap.rank_of(999999) is None and ap.rank_of("x") is None and ap.rank_of(None) is None


def test_the_polls_carry_their_dates(polls):
    assert polls.get("ap").date == datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    assert polls.get("cfp").date == datetime(2026, 11, 17, 8, 0, tzinfo=UTC)
    assert polls.get("cfp").updated > polls.get("cfp").date


def test_a_current_poll_is_fresh_and_last_seasons_final_poll_is_not(polls):
    ap = polls.get("ap")
    assert ap.is_fresh(NOW)
    assert not ap.is_fresh(ap.updated + timedelta(days=cr.FRESH_DAYS + 1))
    assert polls.get("ap", NOW) is ap
    assert polls.get("ap", NOW + timedelta(days=200)) is None
    assert polls.get("ap") is ap, "no clock given: not filtered"


def test_the_committees_early_december_rankings_outlive_the_bowl_gap():
    # Published ~Dec 7; still the current CFP ranking on Jan 18, six weeks on.
    assert cr.FRESH_DAYS >= 42


def test_the_chosen_poll_decides_the_rank(polls):
    ranks = {c: polls.rank_of(GEORGIA, c, NOW) for c in ("ap", "usa", "cfp")}
    assert ranks["ap"] == 1 and all(isinstance(r, int) for r in ranks.values())
    # A team can sit at different numbers in different polls: that is why it is a setting.
    differing = [
        e.team_id for e in polls.get("ap").entries if polls.rank_of(e.team_id, "cfp", NOW) != e.rank
    ]
    assert differing, "the capture has teams the AP and the committee rank differently"
    team = differing[0]
    assert polls.rank_of(team, "ap", NOW) != polls.rank_of(team, "cfp", NOW)


def test_cfp_falls_back_to_the_ap_until_the_committee_publishes():
    data = payload()
    data["rankings"] = [p for p in data["rankings"] if p["type"] != "cfp"]
    polls = cr.polls_from_payload(data)
    assert polls.get("cfp") is None
    assert polls.chosen("cfp", NOW) is polls.get("ap")
    assert polls.rank_of(GEORGIA, "cfp", NOW) == 1


def test_a_stale_cfp_falls_back_to_a_fresh_ap_and_coaches_do_not_fall_back():
    data = payload()
    for p in data["rankings"]:
        if p["type"] == "cfp":
            p["date"] = p["lastUpdated"] = "2026-01-05T08:00Z"
    polls = cr.polls_from_payload(data)
    assert polls.chosen("cfp", NOW) is polls.get("ap")
    data["rankings"] = [p for p in data["rankings"] if p["type"] != "usa"]
    assert cr.polls_from_payload(data).chosen("usa", NOW) is None


def test_out_of_season_nobody_is_ranked():
    summer = NOW + timedelta(days=200)
    polls = cr.polls_from_payload(payload())
    assert polls.chosen("ap", summer) is None and polls.rank_of(GEORGIA, "cfp", summer) is None


def test_the_default_setting_is_the_ap_until_the_committee_publishes_then_the_committees():
    # Owner's call (2026-11-22): a board that never touched the setting follows the AP early in
    # the season and the committee from its first release on. South Carolina was the example:
    # #21 in the committee's rankings, unranked in the AP, in a game ESPN called #21.
    default = FootballConfig().college_poll
    data = payload()
    cfp_only = {p["type"]: p for p in data["rankings"]}["cfp"]
    team = next(
        e["team"]["id"]
        for e in cfp_only["ranks"]
        if cr.polls_from_payload(data).get("ap").rank_of(e["team"]["id"]) is None
    )
    before = dict(data, rankings=[p for p in data["rankings"] if p["type"] != "cfp"])
    early = cr.polls_from_payload(before)
    assert early.chosen(default, NOW) is early.get("ap"), "no committee rankings yet: the AP's"
    assert early.rank_of(team, default, NOW) is None
    later = cr.polls_from_payload(data)
    assert later.chosen(default, NOW) is later.get("cfp"), "the committee has published"
    assert later.rank_of(team, default, NOW) == later.get("cfp").rank_of(team) is not None


def test_an_unknown_choice_means_the_ap(polls):
    assert polls.chosen("bogus", NOW) is polls.get("ap")


def test_unreadable_entries_are_skipped_and_logged(caplog):
    data = payload()
    ap = next(p for p in data["rankings"] if p["type"] == "ap")
    ap["ranks"][3]["team"] = {}  # no id
    ap["ranks"][4]["current"] = 40  # off the chart
    ap["ranks"][5]["current"] = "x"
    with caplog.at_level("WARNING"):
        polls = cr.polls_from_payload(data)
    assert len(polls.get("ap").entries) == 22 and caplog.text.count("unreadable") == 3


def test_a_poll_with_no_usable_entries_is_absent():
    data = payload()
    next(p for p in data["rankings"] if p["type"] == "usa")["ranks"] = []
    assert cr.polls_from_payload(data).get("usa") is None


def test_a_bad_date_is_just_no_date():
    data = copy.deepcopy(payload())
    ap = next(p for p in data["rankings"] if p["type"] == "ap")
    ap["date"] = "soon"
    ap["lastUpdated"] = None
    poll = cr.polls_from_payload(data).get("ap")
    assert poll.date is None and poll.updated is None and not poll.is_fresh(NOW)


@pytest.mark.parametrize("bad", [None, [], "x", {}, {"rankings": "x"}])
def test_garbage_is_no_data(bad):
    assert cr.polls_from_payload(bad) is None


# -- the client ---------------------------------------------------------------------


def test_the_client_asks_for_rankings_once():
    c = FootballClient(league="college-football", session=FakeSession(FakeResponse(payload())))
    polls = c.college_rankings()
    url, params = c.session.calls[0]
    assert url == (
        "https://site.api.espn.com/apis/site/v2/sports/football/college-football/rankings"
    )
    assert params is None and len(c.session.calls) == 1
    assert polls.get("ap").rank_of(GEORGIA) == 1


def test_a_failed_request_is_none_and_an_nfl_client_refuses():
    bad = FootballClient(league="college-football", session=FakeSession(FakeResponse(status=500)))
    assert bad.college_rankings() is None
    with pytest.raises(ValueError, match="college-football client"):
        FootballClient(session=FakeSession()).college_rankings()


# -- the setting ---------------------------------------------------------------------


def test_the_poll_setting_defaults_to_the_committee_which_is_the_ap_until_it_publishes():
    # Owner's call (2026-11-22): AP until the CFP rankings come out, then the committee's.
    assert FootballConfig().college_poll == "cfp"
    assert Settings.from_dict({}).football.college_poll == "cfp"


@pytest.mark.parametrize("value", ["ap", "usa", "cfp"])
def test_each_poll_is_a_valid_setting(value):
    assert Settings.from_dict({"football": {"college_poll": value}}).football.college_poll == value


def test_the_setting_is_forgiving_about_case_and_falls_back_on_nonsense(caplog):
    assert FootballConfig(college_poll=" CFP ").college_poll == "cfp"
    with caplog.at_level("WARNING"):
        assert FootballConfig(college_poll="espn").college_poll == "cfp"
        assert FootballConfig(college_poll=7).college_poll == "cfp"
    assert "unknown football.college_poll" in caplog.text
