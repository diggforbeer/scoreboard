"""The ESPN scoreboard client, models and ``--dump --sport nfl`` (#350).

Hermetic: a fake session stands in for ``requests``, fed by trimmed real
payloads in ``tests/fixtures/football/``.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests

from nhl_scoreboard import __main__ as cli
from nhl_scoreboard.football import api
from nhl_scoreboard.football.models import FbGame, FbSituation, FbTeam

FIXTURES = Path(__file__).parent / "fixtures" / "football"
CENTRAL = ZoneInfo("America/Chicago")


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, body=None, status=200, text=None):
        self._body, self.status_code, self._text = body, status, text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        if self._text is not None:
            return json.loads(self._text)
        return self._body


class FakeSession:
    """Plays back a list of responses (or exceptions) and records each call."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict | None]] = []
        self.closed = False

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def client(*responses) -> api.NflClient:
    return api.NflClient(session=FakeSession(*responses))


# -- parsing real payloads ------------------------------------------------------


def test_live_fixture_parses_the_game_and_its_situation():
    games = client(FakeResponse(load("scoreboard_live.json"))).scores()
    live = games[0]  # live games sort first
    assert (live.id, live.away.abbrev, live.home.abbrev) == (401873052, "WSH", "NYG")
    assert live.is_live and not live.is_final and not live.is_pregame
    assert (live.away.score, live.home.score) == (10, 7)
    assert live.home.linescores == (0, 7, 0) and live.away.linescores == (0, 10, 0)
    assert live.home.record == "5-2-1" and live.home.home_record == "3-1"
    assert live.period == 3 and live.display_clock == "12:24"
    assert live.short_detail == "12:24 - 3rd" and not live.completed
    assert live.venue == "MetLife Stadium" and live.week == 10 and not live.neutral_site
    assert live.start_utc.isoformat() == "2026-11-13T01:15:00+00:00"

    sit = live.situation
    assert (sit.down, sit.distance, sit.yard_line) == (1, 10, 70)
    assert sit.short_down_distance_text == "1st & 10"
    assert sit.down_distance_text == "1st & 10 at WSH 30"
    assert sit.possession_text == "WSH 30" and sit.possession_team_id == 19  # NYG has the ball
    assert not sit.is_red_zone and (sit.home_timeouts, sit.away_timeouts) == (3, 3)
    lp = sit.last_play
    assert lp.type == "Pass Reception" and lp.stat_yardage == 25 and lp.score_value == 0
    assert lp.team_id == 19 and (lp.start_yard_line, lp.end_yard_line) == (45, 70)
    assert "McCarthy pass deep left to M.Fields" in lp.text


def test_yard_line_is_kept_exactly_as_sent_not_flipped():
    # NYG (home) has the ball at WSH 30: the feed says 70, from the HOME goal line.
    live = client(FakeResponse(load("scoreboard_live.json"))).scores()[0]
    assert live.situation.yard_line == 70


def test_pre_and_neutral_site_games_parse_and_sort_after_live():
    games = client(FakeResponse(load("scoreboard_live.json"))).scores()
    assert [g.state for g in games] == ["in", "pre", "pre"]
    ne_det = next(g for g in games if g.involves("NE"))
    assert ne_det.neutral_site and ne_det.is_pregame and ne_det.situation is None
    assert (ne_det.away.score, ne_det.home.score) == (0, 0) and ne_det.period == 0
    assert ne_det.away.winner is None
    assert games[1].start_utc <= games[2].start_utc


def test_final_fixture_parses_with_winner_and_linescores():
    games = client(FakeResponse(load("scoreboard_final.json"))).scores()
    assert all(g.is_final and g.completed and g.situation is None for g in games)
    g = next(g for g in games if g.id == 401873038)
    assert (g.home.abbrev, g.away.abbrev) == ("ATL", "CIN")
    assert (g.home.score, g.away.score) == (17, 34)
    assert g.away.winner is True and g.home.winner is False
    assert g.away.linescores == (7, 17, 7, 3)
    assert g.short_detail == "Final" and g.period == 4


def test_bye_week_is_an_empty_list_not_no_data():
    c = client(FakeResponse(load("scoreboard_bye.json")))
    assert c.scores() == []
    assert c.last_error == ""


def test_status_label_for_each_state():
    live, pre_a, _pre_b = client(FakeResponse(load("scoreboard_live.json"))).scores()
    assert live.status_label(CENTRAL) == "12:24 - 3rd"
    assert pre_a.status_label(CENTRAL) == "Sun 11/15 8:30 AM"  # 9:30 AM EST = 8:30 AM CST
    final = client(FakeResponse(load("scoreboard_final.json"))).scores()[0]
    assert final.status_label(CENTRAL) == "Final"


def test_teams_map_through_the_nfl_table():
    live = client(FakeResponse(load("scoreboard_live.json"))).scores()[0]
    assert live.home.is_nfl and live.home.espn_id == 19
    assert live.team("nyg") is live.home and live.team("XYZ") is None
    assert live.involves("wsh") and not live.involves("NSH")


# -- defensive parsing ----------------------------------------------------------


def test_unknown_team_keeps_the_feeds_abbreviation_and_is_not_nfl():
    event = copy.deepcopy(load("scoreboard_live.json")["events"][0])
    comp = event["competitions"][0]["competitors"][0]["team"]
    comp.update(id="9999", abbreviation="afc")  # the home side, e.g. a Pro Bowl team
    game = FbGame.from_api(event)
    assert game.home.abbrev == "AFC" and not game.home.is_nfl and game.home.espn_id == 9999
    assert game.away.abbrev == "WSH" and game.away.is_nfl


def test_removing_fields_never_raises():
    """The API is undocumented: whatever goes missing, parsing degrades to defaults."""
    event = load("scoreboard_live.json")["events"][0]
    for path in (
        ["status"],
        ["situation"],
        ["venue"],
        ["startDate"],
        ["neutralSite"],
        ["status", "type"],
        ["status", "clock"],
        ["situation", "lastPlay"],
        ["situation", "down"],
        ["situation", "possession"],
        ["competitors", 0, "records"],
        ["competitors", 0, "linescores"],
        ["competitors", 0, "score"],
    ):
        broken = copy.deepcopy(event)
        node = broken["competitions"][0]
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
        game = FbGame.from_api(broken)  # must not raise
        assert game.id == 401873052


def test_wrong_types_degrade_to_defaults():
    event = copy.deepcopy(load("scoreboard_live.json")["events"][0])
    c = event["competitions"][0]
    c["status"]["period"] = "three"
    c["status"]["clock"] = "soon"
    c["situation"]["down"] = None
    c["situation"]["distance"] = "ten"
    c["situation"]["isRedZone"] = "yes"
    c["competitors"][0]["score"] = "n/a"
    c["startDate"] = "not a date"
    game = FbGame.from_api(event)
    assert game.period == 0 and game.clock_seconds == 0.0 and game.start_utc is None
    assert game.situation.down is None and game.situation.distance is None
    assert game.situation.is_red_zone is False
    assert game.home.score == 0 and game.away.score == 10  # only the junk score is lost


def test_an_event_with_no_id_or_without_two_teams_is_refused():
    event = load("scoreboard_live.json")["events"][0]
    no_id = {k: v for k, v in event.items() if k != "id"}
    with pytest.raises(ValueError, match="no game id"):
        FbGame.from_api(no_id)
    one_team = copy.deepcopy(event)
    del one_team["competitions"][0]["competitors"][1]
    with pytest.raises(ValueError, match="away and a home"):
        FbGame.from_api(one_team)
    for junk in (None, [], "x", 3):
        with pytest.raises(ValueError):
            FbGame.from_api(junk)


def test_one_bad_event_is_skipped_and_the_rest_survive(caplog):
    payload = copy.deepcopy(load("scoreboard_live.json"))
    payload["events"].insert(1, {"id": "1", "competitions": []})
    payload["events"].append("not an event")
    with caplog.at_level(logging.WARNING):
        games = client(FakeResponse(payload)).scores()
    assert len(games) == 3
    assert sum("Skipping unusable event" in r.message for r in caplog.records) == 2


def test_situation_and_team_parsers_accept_junk():
    assert FbSituation.from_api(None) is None and FbSituation.from_api("x") is None
    assert FbSituation.from_api({}) is None
    with pytest.raises(ValueError):
        FbTeam.from_api({})


# -- failure handling -----------------------------------------------------------


def test_a_network_failure_is_no_data_and_logs_once_per_outage(caplog):
    fail = requests.ConnectionError("boom")
    c = client(fail)
    with caplog.at_level(logging.DEBUG):
        assert c.scores() is None and c.scores() is None and c.scores() is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "boom" in warnings[0].message
    assert "boom" in c.last_error


def test_recovery_is_logged_and_clears_the_error(caplog):
    c = client(requests.Timeout("slow"), FakeResponse(load("scoreboard_final.json")))
    assert c.scores() is None and c.last_error
    with caplog.at_level(logging.INFO):
        assert len(c.scores()) == 3
    assert c.last_error == ""
    assert any("reachable again" in r.message for r in caplog.records)


def test_a_new_outage_after_recovery_warns_again(caplog):
    c = client(
        requests.ConnectionError("one"),
        FakeResponse({"events": []}),
        requests.ConnectionError("two"),
    )
    with caplog.at_level(logging.WARNING):
        c.scores()
        c.scores()
        c.scores()
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 2


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(status=500),
        FakeResponse(status=404),
        FakeResponse(text="<html>not json</html>"),
        FakeResponse(body=["not", "an", "object"]),
        FakeResponse(body="a string"),
    ],
)
def test_bad_responses_are_no_data(response):
    c = client(response)
    assert c.scores() is None
    assert c.last_error


def test_a_payload_without_events_is_an_empty_slate():
    assert client(FakeResponse({"leagues": []})).scores() == []
    assert client(FakeResponse({"events": "junk"})).scores() == []


def test_the_request_is_the_scoreboard_with_an_optional_date():
    session = FakeSession(FakeResponse({"events": []}))
    c = api.NflClient(session=session)
    c.scores()
    c.scores("20261108")
    assert session.calls == [
        (f"{api.BASE_URL}/scoreboard", None),
        (f"{api.BASE_URL}/scoreboard", {"dates": "20261108"}),
    ]


def test_client_is_a_context_manager_that_closes_its_session():
    session = FakeSession(FakeResponse({"events": []}))
    with api.NflClient(session=session) as c:
        assert c.base_url == api.BASE_URL
    assert session.closed


def test_polling_floor_respects_the_feeds_cache_header():
    assert api.MIN_POLL_SECONDS >= 9  # the feed answers max-age=7..9


def test_default_session_retries_and_identifies_itself():
    session = api._build_session()
    assert "nhl-scoreboard" in session.headers["User-Agent"]
    assert session.adapters["https://"].max_retries.total == 3
    session.close()


# -- --dump --sport nfl ---------------------------------------------------------


def test_dump_prints_todays_games_from_a_fixture(monkeypatch, capsys, tmp_path):
    cfg = tmp_path / "scoreboard.toml"
    cfg.write_text('[scoreboard]\ntimezone = "America/Chicago"\n')
    monkeypatch.setattr(
        api, "_build_session", lambda: FakeSession(FakeResponse(load("scoreboard_live.json")))
    )
    assert cli.main(["--dump", "--sport", "nfl", "-c", str(cfg)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "WSH 10 @ NYG  7  12:24 - 3rd  | 1st & 10 at WSH 30"
    assert out[1].startswith(" NE  0 @ DET  0  Sun 11/15")
    assert len(out) == 3


def test_dump_says_when_there_are_no_games(monkeypatch, capsys):
    monkeypatch.setattr(api, "_build_session", lambda: FakeSession(FakeResponse({"events": []})))
    assert cli.main(["--dump", "--sport", "nfl"]) == 0
    assert capsys.readouterr().out.strip() == "No games today."


def test_dump_reports_an_unreachable_feed_and_exits_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(
        api, "_build_session", lambda: FakeSession(requests.ConnectionError("no route"))
    )
    assert cli.main(["--dump", "--sport", "nfl"]) == 1
    assert "no route" in capsys.readouterr().err


def test_dump_follows_the_configured_sport_when_not_told(monkeypatch, capsys, tmp_path):
    cfg = tmp_path / "scoreboard.toml"
    cfg.write_text('[scoreboard]\nsport = "nfl"\n')
    monkeypatch.setattr(api, "_build_session", lambda: FakeSession(FakeResponse({"events": []})))
    assert cli.main(["--dump", "-c", str(cfg)]) == 0
    assert "No games today." in capsys.readouterr().out
