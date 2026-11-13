"""Jersey numbers: participants, rosters, the core feed and the fallbacks (#354).

Fixtures are trimmed real data (CIN @ ATL, 2026-11-08, event 401873038): eight plays from the core
feed (with the coin toss the site feed omits), the same plays as the site feed has them, and the
two rosters cut down to the athletes named. The expected numbers were read off the real rosters.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from pathlib import Path

import requests

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.football import api, people
from nhl_scoreboard.football.events import CoinToss, EventDetector, Scope
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.models import Participant, Play, PlayKind, normalise_ref, ref_id
from nhl_scoreboard.football.people import (
    CoreSync,
    RosterCache,
    RosterPlayer,
    find,
    merge_core,
    resolve_people,
    roster_from_payload,
)
from test_football_events import make_game
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
EVENT = 401873038


def load(name):
    return json.loads((FIXTURES / name).read_text())


CORE = load("core_plays_sample.json")
LABELS = load("core_plays_sample.labels.json")
BY_LABEL = {LABELS[i["id"]]: i["id"] for i in CORE["items"]}
SITE = load("site_plays_sample.json")


def core_plays() -> list[Play]:
    return [Play.from_api(i) for i in CORE["items"]]


def core_play(label: str) -> Play:
    return next(p for p in core_plays() if p.id == BY_LABEL[label])


def players() -> dict[int, RosterPlayer]:
    out = {}
    for team in ("ATL", "CIN"):
        out.update(roster_from_payload(load(f"roster_{team}.json")))
    return out


def client(*responses):
    return api.NflClient(session=FakeSession(*responses))


# -- ids from links ------------------------------------------------------------------------------


def test_the_id_is_read_out_of_the_link_with_nothing_fetched():
    athlete = (
        "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2026/athletes/"
        "4430807?lang=en&region=us"
    )
    team = "http://sports.core.api.espn.com/v2/sports/football/leagues/nfl/seasons/2026/teams/19?lang=en"
    assert ref_id(athlete) == 4430807 and ref_id(team) == 19
    assert ref_id("https://x/athletes/12") == 12
    for junk in (None, "", 5, "https://x/positions/9?lang=en", {}):
        assert ref_id(junk) is None


def test_the_broken_espn_pvt_host_is_rewritten_and_http_upgraded():
    assert (
        normalise_ref("http://sports.core.api.espn.pvt/v2/x")
        == "https://sports.core.api.espn.com/v2/x"
    )
    assert normalise_ref("https://a.espn.com/x") == "https://a.espn.com/x"


def test_an_espn_pvt_link_still_gives_its_id():
    assert ref_id("http://sports.core.api.espn.pvt/v2/seasons/2026/athletes/777?lang=en") == 777


# -- participants --------------------------------------------------------------------------------


def test_a_core_participant_has_a_role_and_an_athlete_id_from_its_link():
    part = Participant.from_api(
        {"type": "passer", "order": 2, "athlete": {"$ref": "https://x/athletes/4360423?lang=en"}}
    )
    assert part == Participant("passer", 4360423, 2)


def test_a_site_style_participant_carries_the_id_directly():
    assert Participant.from_api({"type": "rusher", "athlete": {"id": "55"}}).athlete_id == 55


def test_a_participant_with_neither_role_nor_athlete_is_dropped_but_a_partial_one_kept():
    assert Participant.from_api({}) is None and Participant.from_api("x") is None
    assert Participant.from_api({"type": "tackler"}) == Participant("tackler", None, 0)
    assert Participant.from_api({"athlete": {"$ref": "https://x/athletes/9"}}).athlete_id == 9


def test_a_core_play_names_its_participants_and_reads_team_ids_from_links():
    rush = core_play("rush")
    assert rush.kind == PlayKind.RUSH
    assert [(p.role, p.athlete_id) for p in rush.participants] == [
        ("rusher", 4430807),
        ("assistedBy", 4428985),
        ("assistedBy", 4431519),
    ]
    assert rush.start.team_id == 1 and rush.end.team_id == 1  # ATL, from the $ref


def test_a_site_play_without_participants_has_none():
    play = Play.from_api(SITE["drives"]["previous"][0]["plays"][0])
    assert play.participants == ()


# -- the core client -----------------------------------------------------------------------------


def test_one_request_covers_a_whole_game_and_the_ids_cost_nothing_more():
    session = FakeSession(FakeResponse(CORE))
    plays = api.NflClient(session=session).core_plays(EVENT)
    assert session.calls == [
        (f"{api.CORE_URL}/events/{EVENT}/competitions/{EVENT}/plays", {"limit": "300"})
    ], "one request: no athlete or team link was followed"
    assert len(plays) == 8
    assert [p.sequence for p in plays] == sorted(p.sequence for p in plays)


def test_the_coin_toss_is_in_the_core_feed_with_its_receiving_team():
    toss = core_plays()[0]
    assert toss.kind == PlayKind.COIN_TOSS and toss.sequence == 100
    assert (toss.start.team_id, toss.end.team_id) == (4, 1), "CIN kicks off, ATL receives"


def test_a_longer_game_follows_the_page_count():
    pages = []
    for n in (1, 2, 3):
        payload = copy.deepcopy(CORE)
        payload["pageCount"], payload["pageIndex"] = 3, n
        payload["items"] = CORE["items"][(n - 1) * 3 : n * 3]
        pages.append(FakeResponse(payload))
    session = FakeSession(*pages)
    plays = api.NflClient(session=session).core_plays(EVENT)
    assert [c[1] for c in session.calls] == [
        {"limit": "300"},
        {"limit": "300", "page": "2"},
        {"limit": "300", "page": "3"},
    ]
    assert len(plays) == 8


def test_a_failure_on_any_page_is_no_data():
    payload = copy.deepcopy(CORE)
    payload["pageCount"] = 2
    assert client(FakeResponse(payload), requests.ConnectionError("down")).core_plays(EVENT) is None
    assert client(requests.ConnectionError("down")).core_plays(EVENT) is None
    assert client(FakeResponse(status=500)).core_plays(EVENT) is None


def test_no_plays_yet_is_an_empty_list_and_junk_items_are_skipped(caplog):
    assert client(FakeResponse({"items": []})).core_plays(EVENT) == []
    assert client(FakeResponse({})).core_plays(EVENT) == []
    payload = copy.deepcopy(CORE)
    payload["items"] = [*payload["items"], {"type": {"text": "Rush"}}, "junk", None]
    assert len(client(FakeResponse(payload)).core_plays(EVENT)) == 8


def test_a_core_play_whose_links_use_espn_pvt_still_resolves():
    payload = copy.deepcopy(CORE)
    for item in payload["items"]:
        for part in item["participants"]:
            part["athlete"]["$ref"] = part["athlete"]["$ref"].replace("espn.com", "espn.pvt")
    plays = client(FakeResponse(payload)).core_plays(EVENT)
    assert next(p for p in plays if p.id == BY_LABEL["rush"]).participants[0].athlete_id == 4430807


# -- rosters -------------------------------------------------------------------------------------


def test_a_roster_gives_name_number_and_position_by_athlete_id():
    robinson = roster_from_payload(load("roster_ATL.json"))[4430807]
    assert (robinson.name, robinson.jersey, robinson.position) == ("B. Robinson", "7", "RB")
    assert robinson.full_name.endswith("Robinson") and robinson.last_name == "Robinson"


def test_the_roster_client_reads_the_team_endpoint():
    session = FakeSession(FakeResponse(load("roster_ATL.json")))
    roster = api.NflClient(session=session).roster(1)
    assert session.calls == [(f"{api.BASE_URL}/teams/1/roster", None)]
    assert 4430807 in roster
    assert client(requests.ConnectionError("x")).roster(1) is None


def test_roster_parsing_survives_junk_and_players_with_no_number():
    payload = {"athletes": [
        {"items": [{"id": "1", "fullName": "No Number", "shortName": "N. Number", "jersey": None},
                   {"id": "2", "fullName": "Empty", "jersey": ""},
                   {"fullName": "No id"}, "junk", None]},
        "junk",
        {"items": "not a list"},
    ]}  # fmt: skip
    roster = roster_from_payload(payload)
    assert set(roster) == {1, 2} and roster[1].jersey == "" and roster[2].jersey == ""
    assert roster_from_payload(None) == {} and roster_from_payload({"athletes": None}) == {}


# -- resolving who did it ------------------------------------------------------------------------


def test_a_rush_names_the_runner_with_his_number():
    rb = find(resolve_people(core_play("rush"), players()), "rusher")
    assert (rb.name, rb.jersey, rb.position, rb.label, rb.on_roster) == (
        "B. Robinson",
        "7",
        "RB",
        "7",
        True,
    )


def test_a_pass_names_the_passer_and_the_receiver():
    people_ = resolve_people(core_play("pass_complete"), players())
    assert find(people_, "passer").label == "9" and find(people_, "passer").position == "QB"
    assert (find(people_, "receiver").name, find(people_, "receiver").label) == ("J. Dotson", "4")


def test_a_touchdown_names_the_scorer_and_the_kicker_of_the_point_after():
    people_ = resolve_people(core_play("rush_td"), players())
    assert (find(people_, "scorer").name, find(people_, "scorer").jersey) == ("J. Burrow", "9")
    assert find(people_, "patScorer").jersey == "2" and find(people_, "patScorer").position == "PK"


def test_a_sack_names_the_defender_who_got_there():
    assert find(resolve_people(core_play("sack"), players()), "sackedBy").label == "94"


def test_a_takeaway_names_the_player_who_ended_up_with_the_ball():
    people_ = resolve_people(core_play("interception"), players())
    assert find(people_, "returner").name == "B. Carter" and find(people_, "returner").label == "49"


def test_find_takes_the_first_role_that_is_present_in_the_order_given():
    people_ = resolve_people(core_play("rush_td"), players())
    assert find(people_, "receiver", "scorer", "rusher").role == "scorer"
    assert find(people_, "receiver") is None and find([], "scorer") is None


# -- the fallbacks -------------------------------------------------------------------------------


def test_a_player_with_no_number_is_shown_by_last_name():
    brade = next(p for p in players().values() if p.name == "B. Brade")
    assert brade.jersey == ""
    play = dataclasses.replace(
        core_play("rush"), participants=(Participant("rusher", brade.athlete_id),)
    )
    person = resolve_people(play, players())[0]
    assert person.jersey == "" and person.on_roster and person.label == "BRADE"


def test_a_kicker_not_on_the_roster_is_named_from_the_play_text():
    """N.Folk is a real athlete the roster does not list: his name comes from the text."""
    kicker = find(resolve_people(core_play("fg_good"), players()), "kicker")
    assert (kicker.name, kicker.jersey, kicker.on_roster, kicker.label) == (
        "N.Folk",
        "",
        False,
        "FOLK",
    )
    assert find(resolve_people(core_play("kickoff_return"), players()), "kicker").label == "FOLK"


def test_an_athlete_with_no_roster_entry_and_no_name_in_the_text_gets_an_empty_label():
    tackler = find(resolve_people(core_play("interception"), players()), "tackler")
    assert (tackler.athlete_id, tackler.name, tackler.label, tackler.on_roster) == (
        4036444,
        "",
        "",
        False,
    )


def test_an_empty_roster_falls_back_to_text_names_for_everyone_the_text_names():
    people_ = resolve_people(core_play("pass_complete"), {})
    assert find(people_, "passer").name == "M.Penix" and find(people_, "passer").label == "PENIX"
    assert find(people_, "receiver").label == "DOTSON"
    assert not any(p.on_roster for p in people_)


def test_last_names_are_taken_sensibly():
    last = people._last_name
    assert (last("J.Burrow"), last("M. Penix Jr."), last("D.St. Brown"), last("K.Walker Jr.")) == (
        "Burrow", "Penix", "Brown", "Walker")  # fmt: skip
    assert last("Mi.Wilson") == "Wilson" and last("") == "" and last("Jr.") == ""


def test_resolving_never_raises_on_odd_participants():
    odd = (Participant("", None), Participant("passer", None, -3))
    play = dataclasses.replace(core_play("rush"), participants=odd)
    got = resolve_people(play, players())
    assert [(p.role, p.athlete_id, p.name, p.label, p.on_roster) for p in got] == [
        ("", None, "", "", False),
        ("passer", None, "", "", False),  # a rush's text names no passer
    ]
    assert resolve_people(dataclasses.replace(core_play("rush"), participants=()), players()) == ()


# -- joining the two feeds -----------------------------------------------------------------------


def site_plays():
    return [Play.from_api(p) for p in SITE["drives"]["previous"][0]["plays"]]


def test_participants_are_attached_to_the_site_plays_by_id():
    merged = merge_core(site_plays(), core_plays())
    rush = next(p for p in merged if p.id == BY_LABEL["rush"])
    assert [p.role for p in rush.participants] == ["rusher", "assistedBy", "assistedBy"]
    assert rush.text == next(p for p in site_plays() if p.id == rush.id).text, (
        "the site play is kept"
    )


def test_core_and_site_ids_match_so_every_site_play_gets_its_participants():
    site = site_plays()
    core_ids = {p.id for p in core_plays()}
    assert {p.id for p in site} <= core_ids, "core play ids are the site feed's ids"
    assert all(p.participants for p in merge_core(site, core_plays(), include_core_only=False))


def test_the_coin_toss_only_the_core_feed_has_is_included_and_can_be_left_out():
    merged = merge_core(site_plays(), core_plays())
    assert len(merged) == 8 and merged[0].kind == PlayKind.COIN_TOSS
    assert [p.sequence for p in merged] == sorted(p.sequence for p in merged)
    assert len(merge_core(site_plays(), core_plays(), include_core_only=False)) == 7


def test_a_site_play_the_core_feed_lacks_is_kept_and_nothing_is_mutated():
    site = site_plays()
    only_two = core_plays()[:2]  # the coin toss and the kickoff return
    merged = merge_core(site, only_two)
    assert len(merged) == 8, "the 7 site plays and the coin toss"
    with_people = [p for p in merged if p.participants]
    # (the coin toss has no participants of its own)
    assert {p.id for p in with_people} == {BY_LABEL["kickoff_return"]}
    assert any(p.kind == PlayKind.COIN_TOSS for p in merged)
    assert [p.id for p in merged if p.id in {s.id for s in site}] == [
        s.id for s in sorted(site, key=Play.sort_key)
    ], "every site play is kept, in order"
    assert site == site_plays(), "the inputs are untouched"
    assert merge_core([], []) == [] and merge_core(site, []) == sorted(site, key=Play.sort_key)


def test_the_core_coin_toss_gives_the_event_detector_its_receiver():
    game = make_game("CIN", "ATL")  # ATL is home (ESPN id 1), CIN away (4)
    cfg = FootballConfig(favourite_team="ATL")
    det = EventDetector(lambda: cfg)
    det.seed(game.id, None)
    toss = next(p for p in merge_core(site_plays(), core_plays()) if p.kind == PlayKind.COIN_TOSS)
    event = det.on_plays(game, [toss])[0]
    assert isinstance(event, CoinToss)
    assert (event.team, event.kicker, event.scope) == ("ATL", "CIN", Scope.FULL)


# -- when to fetch the core feed -----------------------------------------------------------------


def test_the_core_feed_is_fetched_on_first_sight_then_only_when_a_new_play_appears():
    sync = CoreSync()
    site = site_plays()
    assert sync.should_fetch(EVENT, site), "the first look at a game"
    sync.fetched(EVENT, site)
    assert not sync.should_fetch(EVENT, site) and not sync.should_fetch(EVENT, site[:3])
    newer = [*site, dataclasses.replace(site[0], id="a-new-play")]
    assert sync.should_fetch(EVENT, newer)
    sync.fetched(EVENT, newer)
    assert not sync.should_fetch(EVENT, newer)
    assert sync.should_fetch(99, site), "another game is its own first look"
    sync.forget(lambda g: False)
    assert sync.should_fetch(EVENT, site)


# -- the roster cache ----------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make_cache(responses, ttl=3600.0, retry=60.0):
    clock, calls = Clock(), []
    queue = list(responses)

    def fetch(team_id):
        calls.append(team_id)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    return RosterCache(fetch, clock, ttl, retry), clock, calls


A = {1: RosterPlayer(1, "A. One", "A One", "One", "10", "QB")}
B = {2: RosterPlayer(2, "B. Two", "B Two", "Two", "20", "RB")}


def test_a_roster_is_fetched_once_and_good_for_an_hour():
    cache, clock, calls = make_cache([A])
    assert cache.get(7) == A and cache.get(7) == A
    clock.t += 3599
    assert cache.get(7) == A and calls == [7]
    clock.t += 2
    cache.get(7)
    assert calls == [7, 7], "refetched after the hour"


def test_each_team_has_its_own_entry_and_both_merge_for_a_game():
    cache, _, calls = make_cache([A, B])
    assert cache.players_for([1, 2]) == {**A, **B}
    assert calls == [1, 2]
    assert cache.age(1) == 0.0 and cache.age(99) is None


def test_a_failed_fetch_returns_the_stale_roster_and_waits_before_trying_again():
    cache, clock, calls = make_cache([A, None, B], ttl=100.0, retry=60.0)
    assert cache.get(1) == A
    clock.t += 101
    assert cache.get(1) == A, "the fetch failed: the old roster is kept"
    clock.t += 30
    assert cache.get(1) == A and calls == [1, 1], "not retried for 60s"
    clock.t += 31
    assert cache.get(1) == B and calls == [1, 1, 1]


def test_a_roster_that_has_never_loaded_is_empty_not_an_error():
    cache, clock, calls = make_cache([None])
    assert cache.get(1) == {} and cache.get(1) == {} and calls == [1]
    clock.t += 61
    cache.get(1)
    assert calls == [1, 1]


def test_a_fetch_that_raises_is_caught(caplog):
    cache, _, _ = make_cache([RuntimeError("boom")])
    assert cache.get(1) == {}
    assert any("boom" in r.getMessage() for r in caplog.records)


def test_clear_forgets_everything():
    cache, _, calls = make_cache([A])
    cache.get(1)
    cache.clear()
    assert cache.age(1) is None
    cache.get(1)
    assert calls == [1, 1]


# -- dropped on a sport switch -------------------------------------------------------------------


class FakeNfl:
    def __init__(self):
        self.roster_calls = []
        self.closed = False
        self.last_error = ""

    def roster(self, team_id):
        self.roster_calls.append(team_id)
        return A

    def scores(self, date=None):
        return []

    def close(self):
        self.closed = True


def test_the_mode_owns_a_roster_cache_that_uses_its_own_client_and_is_dropped_on_stop():
    fake = FakeNfl()
    mode = NflMode(client_factory=lambda: fake)
    assert mode.rosters.get(5) == A and mode.rosters.get(5) == A
    assert fake.roster_calls == [5], "cached"
    mode.stop()
    assert fake.closed and mode.rosters.age(5) is None, "closed and emptied"


def test_a_fresh_mode_after_a_sport_switch_starts_with_no_rosters():
    first = NflMode(client_factory=FakeNfl)
    first.rosters.get(5)
    second = NflMode(client_factory=FakeNfl)
    assert second.rosters.age(5) is None and second.rosters is not first.rosters
