"""Team lookups are per league: the NFL's by default, the FBS's inside ``use_directory`` (#568).

The NFL and FBS share abbreviations (CIN, HOU, MIA) and ESPN ids (Auburn and the Bills are both
2), so a lookup is only meaningful inside one league.
"""

import copy
import json
import threading
from pathlib import Path

import pytest

from scoreboard.config import team_exists
from scoreboard.football import teams as nfl
from scoreboard.football.api import FootballClient
from scoreboard.football.college_teams import directory_from_table, table_from_payloads
from test_football_plays import FakeResponse, FakeSession

FIXTURES = Path(__file__).parent / "fixtures" / "football"
AUBURN_ID = BILLS_ID = 2


def load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(scope="module")
def fbs():
    return directory_from_table(
        table_from_payloads(
            load("college_standings_trimmed.json"), load("college_teams_trimmed.json")
        )
    )


# -- the directory ------------------------------------------------------------------------------


def test_the_nfl_is_the_default_and_nothing_about_it_changed():
    assert nfl.active_directory() is nfl.NFL_DIRECTORY
    assert len(nfl.NFL_DIRECTORY) == 32 and set(nfl.TEAMS) == set(nfl.NFL_DIRECTORY.by_abbrev)
    assert nfl.team_by_id(BILLS_ID).abbrev == "BUF"
    assert nfl.is_team("buf") and not nfl.is_team("UGA") and not nfl.is_team("")
    assert tuple(sorted(nfl.TEAMS)) == nfl.ABBREVIATIONS
    with pytest.raises(nfl.UnknownTeamError):
        nfl.team("UGA")
    with pytest.raises(nfl.UnknownTeamError):
        nfl.team_by_id(61)


def test_a_college_directory_has_every_fbs_team_as_a_football_team(fbs):
    assert len(fbs) == 138 and fbs.league == "college-football"
    uga = fbs.by_abbrev["UGA"]
    assert isinstance(uga, nfl.FootballTeam)
    assert (uga.espn_id, uga.city, uga.nickname, uga.name) == (61, "Georgia", "Bulldogs", "GEORGIA")
    assert fbs.by_id[61] is uga


def test_inside_a_block_the_same_functions_answer_for_the_college_league(fbs):
    assert nfl.team_by_id(AUBURN_ID).abbrev == "BUF"
    with nfl.use_directory(fbs):
        assert nfl.team_by_id(AUBURN_ID).abbrev == "AUB"
        assert nfl.is_team("UGA") and not nfl.is_team("BUF")
        assert nfl.team("uga").espn_id == 61
        assert nfl.team_color("UGA") == fbs.by_abbrev["UGA"].color
        assert nfl.team_secondary_color("UGA") == fbs.by_abbrev["UGA"].secondary
        assert nfl.team_name("UGA") == "GEORGIA"
    assert nfl.team_by_id(AUBURN_ID).abbrev == "BUF" and not nfl.is_team("UGA")


def test_a_shared_abbreviation_is_a_different_team_in_each_league(fbs):
    bengals = nfl.team("CIN")
    with nfl.use_directory(fbs):
        bearcats = nfl.team("CIN")
        assert bearcats is not bengals and bearcats.nickname == "Bearcats"
        assert bearcats.espn_id != bengals.espn_id
        assert nfl.team_color("CIN") != bengals.color
    assert nfl.team("CIN") is bengals and bengals.nickname == "Bengals"


def test_blocks_nest_and_always_restore_even_after_an_error(fbs):
    with nfl.use_directory(fbs):
        with nfl.use_directory(nfl.NFL_DIRECTORY):
            assert nfl.is_team("BUF")
        assert nfl.is_team("UGA")
        with pytest.raises(RuntimeError), nfl.use_directory(nfl.NFL_DIRECTORY):
            raise RuntimeError("boom")
        assert nfl.is_team("UGA"), "the failed inner block put the outer one back"
    assert nfl.active_directory() is nfl.NFL_DIRECTORY


def test_an_empty_directory_knows_no_team_rather_than_another_leagues(fbs):
    with nfl.use_directory(nfl.EMPTY_DIRECTORY):
        assert not nfl.is_team("CIN") and not nfl.is_team("BUF")
        with pytest.raises(nfl.UnknownTeamError):
            nfl.team_by_id(BILLS_ID)


def test_a_thread_does_not_inherit_the_block_so_a_worker_must_enter_its_own(fbs):
    seen = {}

    def work():
        seen["abbrev"] = nfl.team_by_id(AUBURN_ID).abbrev

    with nfl.use_directory(fbs):
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
    assert seen["abbrev"] == "BUF", "the worker saw the default league, not the caller's block"


def test_the_configs_nfl_check_never_depends_on_what_is_active(fbs):
    with nfl.use_directory(fbs):
        assert team_exists("football", "BUF") and not team_exists("football", "UGA")
        assert nfl.is_nfl_team("BUF") and not nfl.is_nfl_team("UGA")


def test_a_college_directory_is_drawn_by_the_football_screens_unchanged(fbs):
    # The renderers call these module functions with an abbreviation; nothing in them knows leagues.
    from scoreboard.display import football_score

    bengals = nfl.team("CIN").color
    with nfl.use_directory(fbs):
        assert football_score.team_name("UGA") == "GEORGIA"
        assert football_score.team_name("BUF") == "BUF", "not a college team: the abbreviation"
        assert nfl.team_color("CIN") != bengals


# -- the client ---------------------------------------------------------------------------------


def college_payload_with(away_id, away_abbrev, home_id, home_abbrev):
    payload = load("college_scoreboard.json")
    event = payload["events"][0]
    payload["events"] = [event]
    for side, (tid, abbrev) in zip(
        event["competitions"][0]["competitors"],
        ((home_id, home_abbrev), (away_id, away_abbrev)),
        strict=True,
    ):
        side["id"] = side["team"]["id"] = str(tid)
        side["team"]["abbreviation"] = abbrev
    return payload


def loaded_college_client(*responses):
    client = FootballClient(league="college-football", session=FakeSession(*responses))
    client._directory = directory_from_table(
        table_from_payloads(
            load("college_standings_trimmed.json"), load("college_teams_trimmed.json")
        )
    )
    return client


def test_a_college_client_reads_a_game_with_the_fbs_team_for_a_colliding_id():
    # Auburn (2) at Georgia (61): id 2 must come out as Auburn, not the Bills.
    payload = college_payload_with(AUBURN_ID, "AUB", 61, "UGA")
    (game,) = loaded_college_client(FakeResponse(payload)).scores()
    assert (game.away.abbrev, game.home.abbrev) == ("AUB", "UGA")
    assert game.away.is_football and game.home.is_football
    assert game.away.espn_id == AUBURN_ID


def test_the_same_payload_through_an_nfl_client_resolves_id_2_to_the_bills():
    # This is the bug the scoping prevents: it is what a shared table would have done.
    payload = college_payload_with(AUBURN_ID, "AUB", 61, "UGA")
    (game,) = FootballClient(session=FakeSession(FakeResponse(payload))).scores()
    assert game.away.abbrev == "BUF"


def test_a_shared_abbreviation_resolves_to_the_college_team_by_id():
    # Cincinnati's college id is not the Bengals' id.
    cincinnati = next(t for t in nfl.TEAMS.values() if t.abbrev == "CIN")
    college = loaded_college_client()._directory.by_abbrev["CIN"]
    assert college.espn_id != cincinnati.espn_id
    payload = college_payload_with(college.espn_id, "CIN", 61, "UGA")
    (game,) = loaded_college_client(FakeResponse(payload)).scores()
    assert game.away.abbrev == "CIN" and game.away.is_football


def test_a_team_outside_the_directory_is_drawn_as_unknown_not_as_an_nfl_team():
    # An FCS opponent of an FBS team: its id may equal an NFL team's id.
    payload = college_payload_with(5, "WHO", 61, "UGA")  # 5 is UAB in FBS, but not in this fake
    client = loaded_college_client(FakeResponse(payload))
    client._directory = nfl.Directory.of("college-football", [client._directory.by_abbrev["UGA"]])
    (game,) = client.scores()
    assert game.away.abbrev == "WHO" and not game.away.is_football, "not Cleveland (NFL id 5)"


def test_a_client_scopes_its_own_parsing_whatever_the_caller_has_active():
    payload = college_payload_with(AUBURN_ID, "AUB", 61, "UGA")
    with nfl.use_directory(nfl.EMPTY_DIRECTORY):
        (game,) = loaded_college_client(FakeResponse(payload)).scores()
        assert nfl.active_directory() is nfl.EMPTY_DIRECTORY, "the caller's block is put back"
    assert game.away.abbrev == "AUB"


def test_the_college_table_is_fetched_once_on_first_use_then_reused():
    scoreboard = college_payload_with(AUBURN_ID, "AUB", 61, "UGA")
    client = FootballClient(
        league="college-football",
        session=FakeSession(
            FakeResponse(load("college_standings_trimmed.json")),
            FakeResponse(load("college_teams_trimmed.json")),
            FakeResponse(scoreboard),
        ),
    )
    assert client.scores() is not None
    urls = [url.rsplit("/", 1)[-1] for url, _params in client.session.calls]
    assert urls == ["standings", "teams", "scoreboard"]
    assert client.scores() is not None and len(client.session.calls) == 4


def test_without_a_team_table_a_college_client_answers_no_data_and_asks_for_no_scoreboard():
    client = FootballClient(
        league="college-football", session=FakeSession(FakeResponse(status=500))
    )
    assert client.scores() is None and client.week(12) is None
    assert all("scoreboard" not in url for url, _ in client.session.calls)
    assert client.schedule(61) is None and client.roster(61) is None


def test_an_nfl_client_never_asks_for_a_college_table():
    payload = copy.deepcopy(load("college_scoreboard.json"))
    client = FootballClient(session=FakeSession(FakeResponse(payload)))
    client.scores()
    assert len(client.session.calls) == 1 and "college" not in client.session.calls[0][0]
