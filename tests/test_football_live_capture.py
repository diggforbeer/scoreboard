"""The live-game capture (#558): what it records, how often, and when it stops."""

import copy
import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from scoreboard.football import live_capture as lc

FIXTURES = Path(__file__).parent / "fixtures" / "football"
EVENT = "401856883"


def real_event():
    return json.loads((FIXTURES / "college_scoreboard.json").read_text())["events"][0]


def with_status(event, state, name, period, detail, away="0", home="0", situation=None):
    e = copy.deepcopy(event)
    comp = e["competitions"][0]
    comp["status"] = {
        "period": period,
        "displayClock": "3:12",
        "type": {"state": state, "name": name, "detail": detail, "shortDetail": detail},
    }
    for side in comp["competitors"]:
        side["score"] = away if side["homeAway"] == "away" else home
    if situation:
        comp["situation"] = situation
    return e


class Resp:
    def __init__(self, payload):
        self.payload = payload
        self.content = json.dumps(payload).encode()

    def json(self):
        return self.payload

    def raise_for_status(self):
        pass


class Session:
    """Answers by path; ``board`` and ``summary`` are what the next request returns."""

    def __init__(self):
        self.board = {"events": [real_event()]}
        self.summary = {"scoringPlays": [], "drives": {}}
        self.rankings = {"rankings": []}
        self.calls = []
        self.fail = set()

    def get(self, url, params=None, timeout=None):
        tail = url.rsplit("/", 1)[-1]
        self.calls.append(tail)
        if tail in self.fail:
            raise requests.ConnectionError("down")
        return Resp(
            {"scoreboard": self.board, "summary": self.summary, "rankings": self.rankings}[tail]
        )

    def count(self, tail):
        return self.calls.count(tail)


class Rig:
    def __init__(self, tmp_path, **kw):
        self.session = Session()
        self.t = 1000.0
        self.now = datetime(2026, 11, 21, 0, 0, tzinfo=UTC)
        self.capture = lc.Capture(
            EVENT,
            tmp_path / "cap",
            session=self.session,
            clock=lambda: self.now,
            monotonic=lambda: self.t,
            **kw,
        )

    def poll(self, advance=10.0):
        self.t += advance
        self.now += timedelta(seconds=advance)
        return self.capture.poll_once()

    def rows(self):
        path = self.capture.out / "observations.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def transitions(self):
        path = self.capture.out / "transitions.log"
        return path.read_text().splitlines() if path.exists() else []

    def raws(self, kind):
        return sorted((self.capture.out / "raw").glob(f"*-{kind}.json.gz"))


def test_a_poll_records_the_status_scores_ranks_and_how_long_the_fetch_took(tmp_path):
    rig = Rig(tmp_path)
    rig.session.board = {
        "events": [with_status(real_event(), "pre", "STATUS_SCHEDULED", 0, "7:30 PM")]
    }
    assert rig.poll()
    (row,) = rig.rows()
    assert (row["state"], row["status_name"], row["period"]) == ("pre", "STATUS_SCHEDULED", 0)
    assert row["sides"]["home"]["abbrev"] == "UGA" and row["sides"]["away"]["abbrev"] == "MIZ"
    assert row["sides"]["home"]["curatedRank"] == 1, (
        "the scoreboard's rank, to compare with the polls"
    )
    assert row["scoreboard_bytes"] > 100 and "scoreboard_seconds" in row


def test_the_live_situation_and_the_last_play_are_recorded(tmp_path):
    rig = Rig(tmp_path)
    sit = {
        "down": 2,
        "distance": 6,
        "yardLine": 62,
        "shortDownDistanceText": "2nd & 6",
        "possessionText": "UGA 38",
        "possession": "61",
        "isRedZone": False,
        "lastPlay": {"text": "J.Smith pass complete for 12 yards"},
    }
    rig.session.board = {
        "events": [
            with_status(real_event(), "in", "STATUS_IN_PROGRESS", 2, "3:12 - 2nd", "7", "14", sit)
        ]
    }
    rig.poll()
    s = rig.rows()[0]["situation"]
    assert s["shortDownDistanceText"] == "2nd & 6" and s["isRedZone"] is False
    assert s["lastPlay"].startswith("J.Smith")


def test_a_status_change_is_one_readable_line_and_a_repeat_is_not(tmp_path):
    rig = Rig(tmp_path)
    live = with_status(real_event(), "in", "STATUS_IN_PROGRESS", 2, "3:12 - 2nd", "7", "14")
    half = with_status(real_event(), "in", "STATUS_HALFTIME", 2, "Halftime", "7", "14")
    for board in (live, live, half, half, live):
        rig.session.board = {"events": [board]}
        rig.poll()
    lines = rig.transitions()
    assert [x.split()[1] for x in lines] == [
        "STATUS_IN_PROGRESS",
        "STATUS_HALFTIME",
        "STATUS_IN_PROGRESS",
    ]
    assert "Halftime" in lines[1] and "7-14" in lines[1]


def test_the_scoring_plays_and_their_types_come_from_the_summary(tmp_path):
    rig = Rig(tmp_path)
    rig.session.summary = {
        "scoringPlays": [
            {
                "type": {"text": "Rushing Touchdown"},
                "text": "A 4 Yd Run",
                "period": {"number": 1},
                "clock": {"displayValue": "13:59"},
                "awayScore": 0,
                "homeScore": 7,
            },
            {
                "type": {"text": "Field Goal Good"},
                "text": "B 40 Yd FG",
                "period": {"number": 2},
                "clock": {"displayValue": "2:10"},
                "awayScore": 0,
                "homeScore": 10,
            },
        ],
        "drives": {"previous": [{}, {}, {}], "current": {"id": 1}},
        "header": {"competitions": [{"status": {"type": {"name": "STATUS_IN_PROGRESS"}}}]},
    }
    rig.poll()
    row = rig.rows()[0]
    assert row["scoring_plays"] == 2 and row["last_scoring_play"]["type"] == "Field Goal Good"
    assert row["scoring_types"] == ["Field Goal Good", "Rushing Touchdown"]
    assert (row["drives_previous"], row["drive_current"]) == (3, True)
    assert row["summary_status"] == "STATUS_IN_PROGRESS"


def test_the_summary_is_fetched_on_its_own_slower_schedule(tmp_path):
    rig = Rig(tmp_path, summary_seconds=30.0)
    for _ in range(7):
        rig.poll(10.0)
    assert rig.session.count("scoreboard") == 7
    assert rig.session.count("summary") == 3, "once at the start, then every 30 s"


def test_the_rankings_are_fetched_at_the_start_and_then_rarely(tmp_path):
    rig = Rig(tmp_path, rankings_seconds=600.0)
    for _ in range(5):
        rig.poll(10.0)
    assert rig.session.count("rankings") == 1
    rig.poll(600.0)
    assert rig.session.count("rankings") == 2


def test_a_payload_is_kept_only_when_it_changes_and_the_file_is_readable(tmp_path):
    rig = Rig(tmp_path)
    rig.poll()
    rig.poll()
    assert len(rig.raws("event")) == 1, "unchanged: not stored twice"
    rig.session.board = {
        "events": [with_status(real_event(), "in", "STATUS_IN_PROGRESS", 1, "x", "7", "0")]
    }
    rig.poll()
    assert len(rig.raws("event")) == 2
    with gzip.open(rig.raws("event")[0], "rt") as handle:
        assert json.load(handle)["id"] == EVENT


def test_a_failed_request_is_recorded_and_the_capture_carries_on(tmp_path):
    rig = Rig(tmp_path)
    rig.session.fail.add("scoreboard")
    assert rig.poll() is True
    assert "error" in rig.rows()[0] and rig.capture.failures == 1
    rig.session.fail.clear()
    assert rig.poll() is True and rig.rows()[1]["state"]


def test_a_failed_summary_still_records_the_scoreboard_row(tmp_path):
    rig = Rig(tmp_path)
    rig.session.fail.add("summary")
    rig.poll()
    row = rig.rows()[0]
    assert "summary_error" in row and row["state"] and rig.capture.failures >= 1


def test_a_game_missing_from_the_scoreboard_is_noted_not_fatal(tmp_path):
    rig = Rig(tmp_path)
    rig.session.board = {"events": []}
    assert rig.poll() is True
    assert rig.rows()[0]["event"] == "not on the scoreboard"


def test_it_stops_ten_minutes_after_the_game_is_final(tmp_path):
    rig = Rig(tmp_path, grace_seconds=600.0)
    done = with_status(real_event(), "post", "STATUS_FINAL", 4, "Final", "24", "21")
    rig.session.board = {"events": [done]}
    assert rig.poll(10.0) is True, "just went final: stay for the grace period"
    assert rig.poll(300.0) is True
    assert rig.poll(301.0) is False


def test_the_pace_is_the_boards_while_live_and_slower_before_kickoff(tmp_path):
    rig = Rig(tmp_path, poll_seconds=10.0, idle_seconds=60.0)
    assert rig.capture.delay() == 60.0
    rig.session.board = {
        "events": [with_status(real_event(), "pre", "STATUS_SCHEDULED", 0, "7:30")]
    }
    rig.poll()
    assert rig.capture.delay() == 60.0
    rig.session.board = {"events": [with_status(real_event(), "in", "STATUS_IN_PROGRESS", 1, "x")]}
    rig.poll()
    assert rig.capture.delay() == 10.0


def test_run_polls_until_the_game_is_over_and_honours_a_time_limit(tmp_path):
    rig = Rig(tmp_path, grace_seconds=0.0)
    rig.session.board = {"events": [with_status(real_event(), "post", "STATUS_FINAL", 4, "Final")]}
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        assert len(slept) < 50, "the capture never stopped"
        rig.t += seconds
        rig.now += timedelta(seconds=seconds)

    rig.capture.run(sleep=sleep)
    assert rig.capture.polls == 2 and len(slept) == 1
    limited = Rig(tmp_path / "b")
    ticks = []

    def tick(seconds):
        ticks.append(seconds)
        assert len(ticks) < 50, "the time limit was ignored"
        limited.t += seconds

    limited.capture.run(sleep=tick, max_seconds=300)
    assert limited.capture.polls >= 2


def test_compact_tolerates_a_missing_event_and_summary():
    assert lc.compact(None, None) == {}
    bare = lc.compact({"id": "1", "competitions": [{}]}, {})
    assert bare["state"] is None and bare["situation"] is None and bare["sides"] == {}


@pytest.mark.parametrize("body", [{}, {"events": None}, {"events": [{"id": "9"}]}])
def test_find_event_handles_a_board_without_it(body):
    assert lc.find_event(body, EVENT) is None
