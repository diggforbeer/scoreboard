"""The feed's FBS table is kept on disk, so a restart never waits on ESPN's two big requests.

Seen on a real board (2026-11-22, Georgia at South Carolina): after a restart mid-game the board
sat on the idle scroll. A college client has no team table until it has downloaded one (~1.9 MB),
and until then it answers no data, so the live game never reached the board.
"""

from __future__ import annotations

import json
import os
import time

from scoreboard.football import college_teams as ct
from scoreboard.football.api import LEAGUE_COLLEGE, FootballClient
from test_football_college import FIXTURES
from test_football_plays import FakeResponse, FakeSession


def table():
    standings = json.loads((FIXTURES / "college_standings_trimmed.json").read_text())
    teams = json.loads((FIXTURES / "college_teams_trimmed.json").read_text())
    return ct.table_from_payloads(standings, teams)


def responses():
    return (
        FakeResponse(json.loads((FIXTURES / "college_standings_trimmed.json").read_text())),
        FakeResponse(json.loads((FIXTURES / "college_teams_trimmed.json").read_text())),
    )


def client(*resp, keep=True):
    return FootballClient(league=LEAGUE_COLLEGE, session=FakeSession(*resp), keep_table=keep)


def test_a_table_survives_a_write_and_a_read(tmp_path):
    path = tmp_path / "t.json"
    original = table()
    ct.write_table(path, original, wall=1234.0)
    back, saved_at = ct.read_table(path)
    assert saved_at == 1234.0 and back == original
    assert back.by_abbrev("SC").espn_id == 2579


def test_a_missing_or_damaged_file_is_nothing_not_an_error(tmp_path):
    path = tmp_path / "t.json"
    assert ct.read_table(path) is None
    for text in ("", "not json", "[]", '{"saved_at": 1}', '{"saved_at": 1, "teams": []}'):
        path.write_text(text)
        assert ct.read_table(path) is None, text


def test_one_bad_team_makes_the_whole_file_untrusted(tmp_path):
    rows = ct.table_to_data(table())
    for mutate in (
        lambda r: r.update(espn_id="61"),
        lambda r: r.update(abbrev=""),
        lambda r: r.update(color=[1, 2]),
        lambda r: r.update(color=[1, 2, 999]),
        lambda r: r.update(secondary=None),
        lambda r: r.pop("conference"),
    ):
        bad = json.loads(json.dumps(rows))
        mutate(bad[3])
        assert ct.table_from_data(bad) is None
    assert ct.table_from_data(rows) is not None


def test_a_fetched_table_is_kept_and_the_next_client_needs_no_request(tmp_path):
    first = client(*responses())
    assert first._league_directory() is not None
    assert ct.table_file().is_file()
    second = client()  # no responses at all: any request would fail
    assert second._league_directory() is not None
    assert second.session.calls == [], "no request was made"
    assert second.directory.by_abbrev["SC"] is not None


def test_a_table_older_than_a_week_is_refreshed(tmp_path):
    ct.write_table(ct.table_file(), table(), wall=time.time() - ct.TABLE_MAX_AGE_SECONDS - 60)
    c = client(*responses())
    assert c._league_directory() is not None
    saved_at = ct.read_table(ct.table_file())[1]
    assert time.time() - saved_at < 60, "the fresh fetch was kept"


def test_a_stale_table_is_used_when_espn_cannot_be_reached(tmp_path):
    ct.write_table(ct.table_file(), table(), wall=time.time() - 30 * 24 * 3600)
    c = client(FakeResponse(None, status=500), FakeResponse(None, status=500))
    assert c._league_directory() is not None
    assert c.directory.by_abbrev["UGA"] is not None


def test_with_no_file_and_no_espn_there_is_no_directory(tmp_path):
    c = client(FakeResponse(None, status=500), FakeResponse(None, status=500))
    assert c._league_directory() is None


def test_a_client_that_does_not_keep_the_table_never_reads_or_writes_it(tmp_path):
    ct.write_table(ct.table_file(), table(), wall=time.time())
    before = os.stat(ct.table_file()).st_mtime_ns
    c = client(*responses(), keep=False)
    assert c._league_directory() is not None
    assert os.stat(ct.table_file()).st_mtime_ns == before
    assert len(c.session.calls) == 2, "it fetched, as an unkept client does"


def test_the_nfl_client_never_keeps_a_table():
    assert FootballClient(keep_table=True).keep_table is False


def test_the_running_boards_college_client_keeps_it():
    from scoreboard.config import ScoreboardConfig
    from scoreboard.football.mode import FootballMode

    mode = FootballMode(lambda: ScoreboardConfig(), league="college-football")
    assert mode._client_factory().keep_table is True
    assert (
        FootballMode(lambda: ScoreboardConfig(), league="nfl")._client_factory().keep_table is False
    )
