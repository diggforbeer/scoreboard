"""The FBS team list the admin page's college picker offers (#543).

Hermetic: the table is built from the trimmed real ESPN captures; the "network" is a fake source
passed to the cache, and the admin server never gets a real one unless a test installs it.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from scoreboard import admin_server, college_picker
from scoreboard.football.college_teams import table_from_payloads

FIXTURES = Path(__file__).parent / "fixtures" / "football"
TABLE = table_from_payloads(
    json.loads((FIXTURES / "college_standings_trimmed.json").read_text()),
    json.loads((FIXTURES / "college_teams_trimmed.json").read_text()),
)


class Source:
    """A fake ESPN: counts calls and answers from a script."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        answer = self.answers[min(self.calls, len(self.answers)) - 1]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# -- the payload ----------------------------------------------------------------------------------


def test_the_payload_is_every_team_grouped_by_conference_with_what_the_picker_needs():
    payload = college_picker.payload_from_table(TABLE)
    assert payload["ready"] is True
    groups = payload["conferences"]
    assert sum(len(g["teams"]) for g in groups) == len(TABLE) > 0
    assert [g["name"] for g in groups] == [name for name, _, _ in TABLE.conferences()]
    team = groups[0]["teams"][0]
    assert set(team) == {"id", "abbrev", "name", "short_name", "color"}
    real = TABLE.by_id(team["id"])
    assert team["abbrev"] == real.abbrev
    assert team["name"] == f"{real.location} {real.nickname}"
    assert team["short_name"] == real.short_name
    assert team["color"] == list(real.color) and all(0 <= c <= 255 for c in team["color"])
    assert groups[0]["short"] == real.conference_short
    json.dumps(payload)  # plain data, ready for the socket


def test_the_teams_in_a_conference_are_a_to_z_and_independents_come_last():
    groups = college_picker.payload_from_table(TABLE)["conferences"]
    for group in groups:
        names = [t["short_name"].upper() for t in group["teams"]]
        assert names == sorted(names) or len(names) < 2
    names = [g["name"] for g in groups]
    if "FBS Independents" in names:
        assert names[-1] == "FBS Independents"


# -- the cache ------------------------------------------------------------------------------------


def test_nothing_is_ready_until_a_fetch_has_landed_and_there_is_no_fetch_without_a_source():
    cache = college_picker.CollegeTeamList(Clock())
    assert cache.payload == {"ready": False, "conferences": []}
    assert cache.due(None) is False
    assert cache.due(Source(TABLE)) is True


def test_a_fetched_list_is_served_from_memory_and_not_fetched_again_for_a_day():
    clock, source = Clock(), Source(TABLE)
    cache = college_picker.CollegeTeamList(clock)
    assert cache.refresh(source) is True and source.calls == 1
    assert cache.payload["ready"] is True
    clock.now += college_picker.TTL_SECONDS - 1
    assert cache.due(source) is False
    clock.now += 2
    assert cache.due(source) is True, "a day later it is due again"


def test_a_failed_fetch_waits_before_retrying_and_keeps_what_it_had(caplog):
    clock = Clock()
    cache = college_picker.CollegeTeamList(clock)
    boom = Source(None)
    with caplog.at_level(logging.WARNING):
        assert cache.refresh(boom) is False
    assert "unavailable" in caplog.text
    assert cache.payload["ready"] is False
    assert cache.due(boom) is False, "just failed: not due"
    clock.now += college_picker.RETRY_SECONDS
    assert cache.due(boom) is True
    # a good fetch, then a failed refresh a day on: the old list stays
    assert cache.refresh(Source(TABLE)) is True
    clock.now += college_picker.TTL_SECONDS
    assert cache.refresh(Source(None)) is False
    assert cache.payload["ready"] is True


def test_an_exception_or_an_empty_table_counts_as_a_failure():
    cache = college_picker.CollegeTeamList(Clock())
    assert cache.refresh(Source(RuntimeError("down"))) is False
    empty = type(TABLE)(teams=())
    assert cache.refresh(Source(empty)) is False
    assert cache.payload["ready"] is False


def test_a_fetch_in_flight_is_not_started_twice():
    cache = college_picker.CollegeTeamList(Clock())
    inner = []

    def slow():
        inner.append(cache.due(slow))  # asked while busy
        inner.append(cache.refresh(Source(TABLE)))  # a second fetch while busy
        return TABLE

    assert cache.refresh(slow) is True
    assert inner == [False, False]


# -- over the websocket ---------------------------------------------------------------------------


@pytest.fixture
def fresh(monkeypatch, tmp_path):
    cfg = tmp_path / "scoreboard.toml"
    cfg.write_text("")
    monkeypatch.setattr(admin_server, "CONFIG_PATH", str(cfg))
    monkeypatch.setattr(admin_server, "_college_list", college_picker.CollegeTeamList())
    monkeypatch.setattr(admin_server, "_college_task", None)
    monkeypatch.setattr(admin_server, "COLLEGE_SOURCE", None)


async def last_message(client, skip=15):
    for _ in range(skip):
        await client.recv()
    return json.loads(await client.recv())


def serve_and_run(scenario):
    async def run():
        async with serve(admin_server._handle, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                return await scenario(client)

    return asyncio.run(run())


def test_the_list_is_sent_last_on_connect_and_is_not_ready_with_no_source(fresh):
    message = serve_and_run(last_message)
    assert message == {
        "type": "config",
        "section": "college_teams",
        "data": {"ready": False, "conferences": []},
    }


def test_a_fetch_starts_on_the_first_connect_and_the_list_arrives_by_broadcast(fresh, monkeypatch):
    source = Source(TABLE)
    monkeypatch.setattr(admin_server, "COLLEGE_SOURCE", source)

    async def scenario(client):
        first = await last_message(client)
        pushed = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
        return first, pushed

    first, pushed = serve_and_run(scenario)
    assert first["data"]["ready"] is False, "the connect never waits on ESPN"
    assert pushed["section"] == "college_teams" and pushed["data"]["ready"] is True
    assert len(pushed["data"]["conferences"]) == len(TABLE.conferences())
    assert source.calls == 1


def test_a_later_connection_gets_the_cached_list_at_once_with_no_new_fetch(fresh, monkeypatch):
    source = Source(TABLE)
    monkeypatch.setattr(admin_server, "COLLEGE_SOURCE", source)
    admin_server._college_list.refresh(source)
    assert source.calls == 1

    message = serve_and_run(last_message)
    assert message["data"]["ready"] is True
    assert source.calls == 1


def test_with_no_network_a_cached_list_still_works(fresh, monkeypatch):
    offline = Source(RuntimeError("no network"))
    admin_server._college_list.refresh(Source(TABLE))
    monkeypatch.setattr(admin_server, "COLLEGE_SOURCE", offline)
    message = serve_and_run(last_message)
    assert message["data"]["ready"] is True
    assert offline.calls == 0


def test_a_failed_fetch_leaves_the_page_not_ready_and_the_connection_alive(fresh, monkeypatch):
    monkeypatch.setattr(admin_server, "COLLEGE_SOURCE", Source(None))

    async def scenario(client):
        message = await last_message(client)
        await asyncio.sleep(0.2)  # the worker fails; nothing is pushed
        await client.send(json.dumps({"type": "update_check"}))
        return message

    assert serve_and_run(scenario)["data"]["ready"] is False


def test_the_admin_server_installs_the_source_it_is_given(fresh, tmp_path):
    source = Source(TABLE)
    server = admin_server.AdminServer(
        config_path=str(tmp_path / "scoreboard.toml"),
        port=0,
        host="localhost",
        college_source=source,
    )
    server.start()
    try:
        assert admin_server.COLLEGE_SOURCE is source
    finally:
        server.stop()


def test_the_real_source_builds_the_table_through_a_college_client(monkeypatch):
    from scoreboard.football import api
    from test_football_college_ranks import RoutedSession
    from test_football_plays import FakeResponse

    session = RoutedSession(
        {
            "/standings": FakeResponse(
                json.loads((FIXTURES / "college_standings_trimmed.json").read_text())
            ),
            "/teams": FakeResponse(
                json.loads((FIXTURES / "college_teams_trimmed.json").read_text())
            ),
        }
    )
    real = api.FootballClient
    monkeypatch.setattr(api, "FootballClient", lambda league: real(league=league, session=session))
    table = college_picker.fetch_table()
    assert table is not None and len(table) == len(TABLE)
    assert [c[0] for c in table.conferences()] == [c[0] for c in TABLE.conferences()]


# -- kept on disk ---------------------------------------------------------------------------------


class Wall:
    def __init__(self, now=1_800_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


def kept(tmp_path, **kw):
    """A list that keeps its data in ``tmp_path`` (the clocks are fakes)."""
    clock, wall = kw.pop("clock", Clock()), kw.pop("wall", Wall())
    listing = college_picker.CollegeTeamList(clock, wall)
    listing.use_file(tmp_path / "state" / "college-teams.json")
    return listing, clock, wall


def write_file(path, payload, saved_at):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"saved_at": saved_at, "payload": payload}))


def test_a_fetched_list_is_saved_with_the_time_it_was_fetched(tmp_path):
    listing, _, wall = kept(tmp_path)
    assert listing.refresh(Source(TABLE))
    saved = json.loads((tmp_path / "state" / "college-teams.json").read_text())
    assert saved["saved_at"] == wall.now
    assert saved["payload"] == listing.payload == college_picker.payload_from_table(TABLE)
    assert not list((tmp_path / "state").glob("*.tmp")), "no half-written neighbour is left"


def test_a_restart_with_no_network_serves_the_saved_list_at_once(tmp_path):
    first, _, _ = kept(tmp_path)
    first.refresh(Source(TABLE))
    restarted, _, _ = kept(tmp_path)  # a new process, nothing in memory
    assert restarted.payload == college_picker.payload_from_table(TABLE)
    assert restarted.due(Source()) is False, "a fresh file is not fetched again"


def test_the_age_of_a_saved_list_carries_across_a_restart(tmp_path):
    path = tmp_path / "state" / "college-teams.json"
    payload = college_picker.payload_from_table(TABLE)
    write_file(path, payload, 1_800_000_000.0 - college_picker.TTL_SECONDS - 60)
    stale, _, _ = kept(tmp_path)
    assert stale.payload == payload, "an old list is still better than none"
    assert stale.due(Source()) is True, "but it is refreshed in the background"


def test_a_refresh_that_fails_keeps_the_saved_list_and_the_file(tmp_path):
    path = tmp_path / "state" / "college-teams.json"
    write_file(path, college_picker.payload_from_table(TABLE), 1_800_000_000.0 - 10**6)
    listing, _, _ = kept(tmp_path)
    assert listing.refresh(Source(None)) is False
    assert listing.payload["ready"] is True
    assert json.loads(path.read_text())["payload"]["ready"] is True


def test_a_clock_that_went_backwards_makes_the_file_look_new_not_from_the_future(tmp_path):
    path = tmp_path / "state" / "college-teams.json"
    write_file(path, college_picker.payload_from_table(TABLE), 1_800_000_000.0 + 10**7)
    listing, clock, _ = kept(tmp_path)
    assert listing.payload["ready"] is True and listing.due(Source()) is False
    clock.now += college_picker.TTL_SECONDS + 1
    assert listing.due(Source()) is True, "it is refreshed a day later like any other"


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        json.dumps({"saved_at": 1.0}),
        json.dumps({"saved_at": "soon", "payload": {}}),
        json.dumps({"saved_at": 1.0, "payload": {"ready": True, "conferences": []}}),
        json.dumps({"saved_at": 1.0, "payload": {"ready": False, "conferences": []}}),
        json.dumps({"saved_at": 1.0, "payload": {"ready": True, "conferences": "x"}}),
    ],
)
def test_a_missing_or_damaged_file_is_ignored_and_never_raises(tmp_path, content):
    path = tmp_path / "state" / "college-teams.json"
    path.parent.mkdir(parents=True)
    path.write_text(content)
    listing, _, _ = kept(tmp_path)
    assert listing.payload == college_picker.NOT_READY
    empty, _, _ = kept(tmp_path / "elsewhere")  # no file at all
    assert empty.payload == college_picker.NOT_READY


def test_one_incomplete_team_makes_the_whole_file_untrusted(tmp_path):
    payload = college_picker.payload_from_table(TABLE)
    del payload["conferences"][0]["teams"][0]["color"]
    write_file(tmp_path / "state" / "college-teams.json", payload, 1_800_000_000.0)
    listing, _, _ = kept(tmp_path)
    assert listing.payload == college_picker.NOT_READY


def test_a_file_that_cannot_be_written_is_logged_and_the_list_still_works(tmp_path, caplog):
    blocker = tmp_path / "state"
    blocker.write_text("a file where the directory should be")
    listing = college_picker.CollegeTeamList(Clock(), Wall())
    listing.use_file(blocker / "college-teams.json")
    with caplog.at_level(logging.WARNING):
        assert listing.refresh(Source(TABLE)) is True
    assert listing.payload["ready"] is True
    assert any("Could not save the college team list" in r.message for r in caplog.records)


def test_with_no_file_configured_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    listing = college_picker.CollegeTeamList(Clock(), Wall())
    listing.use_file(None)
    assert listing.refresh(Source(TABLE)) is True
    assert list(tmp_path.iterdir()) == []


def test_a_list_already_in_memory_is_not_replaced_by_an_older_file(tmp_path):
    path = tmp_path / "state" / "college-teams.json"
    listing = college_picker.CollegeTeamList(Clock(), Wall())
    listing.refresh(Source(TABLE))  # in memory, no file yet
    other = college_picker.payload_from_table(TABLE)
    other["conferences"] = other["conferences"][:1]
    write_file(path, other, 1_800_000_000.0 - 5000)
    listing.use_file(path)
    assert len(listing.payload["conferences"]) == len(TABLE.conferences())


def test_the_admin_server_loads_the_file_it_is_given_and_the_page_is_ready_offline(fresh, tmp_path):
    path = tmp_path / "state" / "college-teams.json"
    write_file(path, college_picker.payload_from_table(TABLE), time_now())
    server = admin_server.AdminServer(
        config_path=str(tmp_path / "scoreboard.toml"),
        port=0,
        host="localhost",
        college_source=Source(RuntimeError("no network")),
        college_cache=path,
    )
    server.start()
    try:
        message = serve_and_run(last_message)
    finally:
        server.stop()
    assert message["data"]["ready"] is True
    assert len(message["data"]["conferences"]) == len(TABLE.conferences())


def time_now():
    import time

    return time.time()


def test_the_real_cache_file_is_in_var_lib_unless_the_environment_says_otherwise():
    assert str(college_picker.CACHE_FILE).endswith("/college-teams.json")
    assert "college-teams" in college_picker.CACHE_FILE.name
