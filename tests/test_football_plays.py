"""The play feed client, the ``Play`` model and the play-text parser (#353).

``tests/fixtures/football/play_cases.json`` holds one real play per case, picked
from 2,441 plays across 13 finished games (2026-11-08). The expected values below
were read off those plays by eye, not generated from the parser.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path

import pytest
import requests

from nhl_scoreboard import __main__ as cli
from nhl_scoreboard.football import api
from nhl_scoreboard.football.models import FieldPos, Play, PlayKind, classify
from nhl_scoreboard.football.playtext import parse_text

FIXTURES = Path(__file__).parent / "fixtures" / "football"
K = PlayKind


def cases() -> dict[str, dict]:
    data = json.loads((FIXTURES / "play_cases.json").read_text())
    return {c["label"]: c["play"] for c in data["cases"]}


CASES = cases()


class FakeResponse:
    def __init__(self, body=None, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def client(*responses):
    return api.NflClient(session=FakeSession(*responses))


# What each real play should parse to: (kind, {PlayText field: value}).
EXPECTED: dict[str, tuple[K, dict]] = {
    "kickoff_return": (
        K.KICKOFF,
        dict(
            kicker="N.Folk",
            kick_yards=60,
            kick_from="ATL 35",
            landing="CIN 5",
            returner="D.Meyers",
            return_yards=20,
            return_spot="CIN 25",
            touchback=False,
            onside=False,
        ),
    ),
    "kickoff_touchback": (
        K.KICKOFF,
        dict(
            kick_yards=65,
            kick_from="CLV 35",
            landing="end zone",
            touchback=True,
            touchback_spot="NO 35",
            returner="",
            return_yards=None,
        ),
    ),
    "kickoff_onside": (
        K.KICKOFF,
        dict(onside=True, kick_yards=19, landing="NYG 46", returner="M.Nabers", return_yards=0),
    ),
    "kickoff_penalty": (K.KICKOFF, dict(returner="K.Herbert", return_yards=24, no_play=False)),
    "kickoff_lateral": (
        K.KICKOFF,
        dict(landing="LV 0", returner="D.Laube", return_yards=16, lateral=True),
    ),
    "punt_fair_catch": (
        K.PUNT,
        dict(
            kicker="J.Bailey",
            kick_yards=53,
            landing="CIN 12",
            fair_catch=True,
            returner="D.Meyers",
            return_yards=None,
        ),
    ),
    "punt_out_of_bounds": (
        K.PUNT,
        dict(
            kick_yards=37, landing="CIN 17", out_of_bounds=True, fair_catch=False, return_yards=None
        ),
    ),
    "punt_return": (
        K.PUNT,
        dict(
            kick_yards=51,
            landing="ATL 27",
            returner="O.Zaccheaus",
            return_yards=-3,
            return_spot="ATL 24",
            out_of_bounds=False,
        ),
    ),
    "punt_downed": (K.PUNT, dict(kick_yards=58, landing="WAS 18", downed=True, returner="")),
    "punt_touchback": (K.PUNT, dict(landing="end zone", touchback=True, touchback_spot="")),
    "punt_penalty": (K.PUNT, dict(returner="O.Zaccheaus", return_yards=9)),
    "rush": (K.RUSH, dict(rusher="B.Robinson", run_gap="left guard", kneel=False, scramble=False)),
    "rush_up_the_middle": (K.RUSH, dict(rusher="B.Robinson", run_gap="up the middle")),
    "rush_no_gain": (K.RUSH, dict(run_gap="right tackle")),
    "rush_kneel": (K.RUSH, dict(kneel=True, rusher="J.Burrow", run_gap="")),
    "rush_scramble": (K.RUSH, dict(scramble=True, rusher="M.Penix", run_gap="left tackle")),
    "rush_td_pat": (
        K.RUSHING_TOUCHDOWN,
        dict(
            touchdown=True,
            extra_point="good",
            two_point="",
            rusher="J.Burrow",
            run_gap="left guard",
        ),
    ),
    "rush_td_two_point_good": (
        K.RUSHING_TOUCHDOWN,
        dict(touchdown=True, two_point="good", rusher="S.Barkley"),
    ),
    "rush_td_two_point_fail": (
        K.RUSHING_TOUCHDOWN,
        dict(touchdown=True, two_point="failed", rusher="J.Coleman", passer="", target=""),
    ),  # the attempt's own pass is not this play's
    "pass_complete": (
        K.PASS_COMPLETE,
        dict(
            passer="M.Penix",
            target="J.Dotson",
            pass_depth="short",
            pass_direction="right",
            incomplete=False,
        ),
    ),
    "pass_complete_deep_ob": (
        K.PASS_COMPLETE,
        dict(target="B.Robinson", pass_depth="deep", pass_direction="left"),
    ),
    "pass_complete_lateral": (K.PASS_COMPLETE, dict(lateral=True, target="E.Chism")),
    "pass_td_pat": (
        K.PASSING_TOUCHDOWN,
        dict(
            touchdown=True,
            extra_point="good",
            passer="M.Penix",
            target="C.Woerner",
            pass_depth="short",
            pass_direction="right",
        ),
    ),
    "pass_td_two_point_fail": (
        K.PASSING_TOUCHDOWN,
        dict(touchdown=True, two_point="failed", passer="S.Sanders", target="H.Fannin"),
    ),
    "incomplete_target": (
        K.PASS_INCOMPLETE,
        dict(incomplete=True, target="K.Pitts", pass_depth="short", pass_direction="left"),
    ),
    "incomplete_no_target": (
        K.PASS_INCOMPLETE,
        dict(incomplete=True, target="", pass_depth="deep", pass_direction="left"),
    ),
    "incomplete_deflected": (
        K.PASS_INCOMPLETE,
        dict(incomplete=True, target="", passer="J.Burrow"),
    ),
    "incomplete_spike": (
        K.PASS_INCOMPLETE,
        dict(spike=True, incomplete=True, passer="S.Sanders", pass_direction=""),
    ),
    "incomplete_grounding": (K.PASS_INCOMPLETE, dict(incomplete=True, spike=False)),
    "incomplete_penalty_declined": (K.PASS_INCOMPLETE, dict(incomplete=True, no_play=False)),
    "sack": (
        K.SACK,
        dict(
            sack=True,
            passer="J.Burrow",
            sack_spot="CIN 31",
            sack_yards=-6,
            sackers=("L.London",),
            fumble=False,
        ),
    ),
    "sack_zero": (K.SACK, dict(sack_yards=0, sack_spot="ATL 30", sackers=("Z.Harrison",))),
    "sack_fumble": (
        K.SACK_FUMBLE,
        dict(
            sack=True, fumble=True, recovered_by_team="IND", recovered_by="C.Curry", sack_yards=-5
        ),
    ),
    "penalty_no_play": (K.PENALTY, dict(no_play=True, incomplete=True, target="D.London")),
    "penalty_after_run": (K.PENALTY, dict(no_play=True, scramble=True, rusher="M.Penix")),
    "penalty_pre_snap": (K.PENALTY, dict(no_play=True, passer="", rusher="")),
    "penalty_accepted_and_declined": (K.PENALTY, dict(no_play=True, incomplete=True)),
    "penalty_offsetting_play": (K.PASS_INCOMPLETE, dict(no_play=True, incomplete=True)),
    "penalty_kickoff_placed": (K.KICKOFF, dict(kick_yards=57, landing="KC 8", out_of_bounds=True)),
    "penalty_team_only": (K.PENALTY, dict(no_play=True, passer="", rusher="")),
    "pass_complete_two_letter_initial": (
        K.PASS_COMPLETE,
        dict(passer="G.Minshew", target="Mi.Wilson", pass_depth="deep", pass_direction="right"),
    ),
    "sack_at_midfield": (
        K.SACK,
        dict(sack=True, passer="J.Daniels", sack_spot="50", sack_yards=-12, sackers=("M.Garrett",)),
    ),
    "fg_good": (K.FIELD_GOAL_GOOD, dict(kicker="N.Folk", fg_yards=31, fg_miss="")),
    "fg_miss_left": (K.FIELD_GOAL_MISSED, dict(kicker="N.Folk", fg_yards=38, fg_miss="Wide Left")),
    "fg_miss_right": (
        K.FIELD_GOAL_MISSED,
        dict(kicker="C.Smyth", fg_yards=52, fg_miss="Wide Right"),
    ),
    "timeout": (K.TIMEOUT, dict(timeout_team="CIN", timeout_number=1, timeout_clock="01:10")),
    "official_timeout": (K.OFFICIAL_TIMEOUT, dict(timeout_clock="11:12", timeout_team="")),
    "two_minute_warning": (K.TWO_MINUTE_WARNING, {}),
    "end_period": (K.END_PERIOD, {}),
    "end_half": (K.END_HALF, {}),
    "end_game": (K.END_GAME, {}),
    "end_regulation": (K.END_REGULATION, {}),
    "interception_return": (
        K.INTERCEPTION_RETURN,
        dict(
            passer="M.Penix", target="B.Robinson", interceptor="B.Carter", intercept_spot="ATL 43"
        ),
    ),
    "interception_td": (
        K.INTERCEPTION_TOUCHDOWN,
        dict(touchdown=True, extra_point="good", interceptor="J.Johnson", intercept_spot="CHI 33"),
    ),
    "fumble_own": (
        K.FUMBLE_RECOVERY_OWN,
        dict(fumble=True, recovered_by_team="NO", recovered_by="A.Kamara"),
    ),
    "fumble_opponent": (
        K.FUMBLE_RECOVERY_OPPONENT,
        dict(fumble=True, recovered_by_team="CLV", recovered_by="T.Campbell"),
    ),
    "muffed_punt": (K.MUFFED_PUNT, dict(muffed=True, recovered_by_team="PHI", kick_yards=44)),
    "review_challenge_upheld": (K.PASS_COMPLETE, dict(target="J.Chase")),
    "review_replay_upheld": (K.PASS_COMPLETE, dict(fumble=True)),
    "review_reversed_touchdown": (
        K.PASS_INCOMPLETE,
        dict(incomplete=True, target="C.Lamb", touchdown=False),
    ),
    "review_reversed_challenge": (
        K.FUMBLE_RECOVERY_OPPONENT,
        dict(fumble=True, recovered_by_team="IND"),
    ),
    "review_reversed_replay_fumble": (
        K.PASS_INCOMPLETE,
        dict(incomplete=True, sack=False, target="I.TeSlaa", touchdown=False),
    ),
}


def test_every_case_in_the_fixture_has_an_expectation():
    assert set(EXPECTED) == set(CASES)


@pytest.mark.parametrize("label", sorted(EXPECTED))
def test_each_real_play_parses_as_expected(label):
    play = Play.from_api(CASES[label])
    kind, fields = EXPECTED[label]
    assert play.kind == kind, f"{label}: type {play.type!r}"
    for name, want in fields.items():
        assert getattr(play.info, name) == want, f"{label}: {name}"


def test_every_play_type_in_the_sample_is_classified_not_unknown():
    kinds = {Play.from_api(p).kind for p in CASES.values()}
    assert K.UNKNOWN not in kinds
    assert kinds >= {
        K.RUSH, K.PASS_COMPLETE, K.PASS_INCOMPLETE, K.SACK, K.KICKOFF, K.PUNT,
        K.FIELD_GOAL_GOOD, K.FIELD_GOAL_MISSED, K.PENALTY, K.TIMEOUT, K.OFFICIAL_TIMEOUT,
        K.TWO_MINUTE_WARNING, K.END_PERIOD, K.END_HALF, K.END_REGULATION, K.END_GAME,
        K.RUSHING_TOUCHDOWN, K.PASSING_TOUCHDOWN, K.INTERCEPTION_RETURN,
        K.INTERCEPTION_TOUCHDOWN, K.FUMBLE_RECOVERY_OWN, K.FUMBLE_RECOVERY_OPPONENT,
        K.SACK_FUMBLE, K.MUFFED_PUNT,
    }  # fmt: skip


# -- the play model -------------------------------------------------------------


def test_the_structured_fields_come_through_exactly():
    play = Play.from_api(CASES["sack"])
    assert play.id and play.sequence == 339200 and play.period >= 1
    assert play.stat_yardage == -6 and play.kind == K.SACK and play.type == "Sack"
    assert not play.scoring_play and not play.is_turnover
    assert play.wallclock is not None and play.wallclock.tzinfo is not None
    assert isinstance(play.start, FieldPos) and isinstance(play.end, FieldPos)
    assert (
        play.start.yard_line == 63 and play.end.yard_line == 69
    )  # away team lost 6 toward its own goal


def test_flags_and_scores_on_a_touchdown():
    play = Play.from_api(CASES["pass_td_pat"])
    assert play.scoring_play and play.is_touchdown and not play.is_turnover
    assert (play.away_score, play.home_score) == (0, 7)
    assert play.start.yards_to_endzone == 1 and play.end.yard_line == 100


def test_yards_after_catch_only_when_sent():
    assert Play.from_api(CASES["pass_complete"]).yards_after_catch is not None
    assert Play.from_api(CASES["rush"]).yards_after_catch is None


def test_a_turnover_flag_comes_from_the_feed_not_the_text():
    assert Play.from_api(CASES["interception_return"]).is_turnover
    assert Play.from_api(CASES["fumble_opponent"]).is_turnover
    assert not Play.from_api(CASES["fumble_own"]).is_turnover


def test_classification_is_forgiving_and_never_raises():
    assert classify("  Pass   Reception ") == K.PASS_COMPLETE
    assert classify("Punt Return Touchdown") == K.OTHER_TOUCHDOWN
    assert classify("Kickoff Return Touchdown") == K.OTHER_TOUCHDOWN
    assert classify("Coin Toss") == K.COIN_TOSS
    for junk in ("", None, "Brand New Type", 7):
        assert classify(junk) == K.UNKNOWN


def test_an_unknown_type_keeps_its_raw_type_and_text():
    raw = copy.deepcopy(CASES["rush"])
    raw["type"] = {"id": "999", "text": "Free Kick Safety"}
    play = Play.from_api(raw)
    assert play.kind == K.UNKNOWN and play.type == "Free Kick Safety"
    assert play.text == CASES["rush"]["text"] and not play.is_touchdown


def test_other_touchdown_types_still_count_as_touchdowns():
    raw = copy.deepcopy(CASES["rush_td_pat"])
    raw["type"]["text"] = "Punt Return Touchdown"
    assert Play.from_api(raw).is_touchdown


def test_a_play_without_an_id_is_refused_but_a_sparse_one_is_not():
    with pytest.raises(ValueError, match="no id"):
        Play.from_api({"type": {"text": "Rush"}})
    with pytest.raises(ValueError):
        Play.from_api("nope")
    bare = Play.from_api({"id": "5"})
    assert bare.kind == K.UNKNOWN and bare.sequence == 0 and bare.start is None
    assert bare.info.underlying_text == ""


def test_missing_and_mistyped_fields_degrade_to_defaults():
    raw = copy.deepcopy(CASES["rush"])
    raw.update(
        sequenceNumber="x",
        statYardage="n/a",
        scoringPlay="yes",
        awayScore=None,
        wallclock="soon",
        period="1st",
        clock=None,
    )
    raw["start"] = "nowhere"
    play = Play.from_api(raw)
    assert play.sequence == 0 and play.stat_yardage == 0 and not play.scoring_play
    assert play.away_score == 0 and play.wallclock is None and play.period == 0
    assert play.clock == "" and play.start is None


# -- reading the text -----------------------------------------------------------


def test_a_penalty_on_a_run_keeps_the_run_so_a_nullified_play_can_be_shown():
    info = Play.from_api(CASES["penalty_after_run"]).info
    assert info.underlying_text.startswith("(Shotgun) M.Penix scrambles up the middle to CIN 1")
    assert "PENALTY" not in info.underlying_text
    assert info.has_penalty and info.accepted_penalty and info.no_play
    pen = info.penalties[0]
    assert (pen.team, pen.player, pen.name, pen.yards) == (
        "ATL",
        "M.Bergeron",
        "Offensive Holding",
        10,
    )
    assert pen.spot == "CIN 7" and not pen.declined


def test_a_declined_penalty_is_told_apart_from_an_accepted_one():
    declined = Play.from_api(CASES["incomplete_penalty_declined"]).info
    assert declined.has_penalty and not declined.accepted_penalty and not declined.no_play
    assert declined.penalties[0].declined and declined.penalties[0].yards is None
    accepted = Play.from_api(CASES["incomplete_grounding"]).info
    assert accepted.accepted_penalty and accepted.penalties[0].name == "Intentional Grounding"
    # The type stays Pass Incompletion: the grounding is only in the text.
    assert Play.from_api(CASES["incomplete_grounding"]).kind == K.PASS_INCOMPLETE


def test_offsetting_penalties_are_neither_accepted_nor_declined():
    info = Play.from_api(CASES["penalty_offsetting_play"]).info
    assert len(info.penalties) == 2 and all(p.offsetting for p in info.penalties)
    assert not info.accepted_penalty and info.no_play


def test_two_penalties_on_one_play_are_both_kept():
    info = Play.from_api(CASES["penalty_accepted_and_declined"]).info
    assert [p.declined for p in info.penalties] == [False, True]
    assert info.accepted_penalty


def test_a_penalty_on_a_whole_team_has_no_player():
    pen = Play.from_api(CASES["penalty_team_only"]).info.penalties[0]
    assert (pen.team, pen.player, pen.name, pen.yards) == ("ATL", "", "Delay of Game", 5)
    assert pen.spot == "ATL 32"


def test_a_kickoff_penalty_is_placed_not_yardage():
    play = Play.from_api(CASES["penalty_kickoff_placed"])
    pen = play.info.penalties[0]
    assert (pen.team, pen.player, pen.name) == ("NYJ", "A.Beck", "Kickoff Out of Bounds")
    assert pen.yards is None and pen.spot == "KC 40" and not pen.declined
    assert play.kind == K.KICKOFF and play.info.kick_yards == 57  # the kick is still there


def test_midfield_is_written_as_a_bare_50():
    assert Play.from_api(CASES["sack_at_midfield"]).info.sack_spot == "50"
    info = parse_text("Punt", "A.Bee punts 45 yards to 50, Center-X.Yee, fair catch by Z.Zed.")
    assert info.landing == "50" and info.fair_catch


def test_a_player_with_a_two_letter_initial_is_read():
    info = parse_text(
        "Pass Reception",
        "(Shotgun) G.Minshew pass short left to Mi.Wilson ran ob at SEA 39 for 23 yards (J.Love).",
    )
    assert info.target == "Mi.Wilson"


def test_a_play_with_no_penalty_has_none():
    info = Play.from_api(CASES["rush"]).info
    assert not info.has_penalty and info.penalties == () and not info.accepted_penalty
    assert info.underlying_text == CASES["rush"]["text"]


def test_a_reversed_review_keeps_the_original_call_and_the_corrected_play():
    play = Play.from_api(CASES["review_reversed_touchdown"])
    rv = play.info.review
    assert rv.reversed and rv.by == "The Replay Official" and rv.subject == "pass completion"
    assert "TOUCHDOWN" in rv.original_text and "TOUCHDOWN" not in rv.corrected_text
    assert rv.corrected_text.endswith("pass incomplete short right to C.Lamb.")
    # The feed rewrote the play in place: its type and flags are the final ruling,
    # so it looks like an ordinary incompletion with no score.
    assert play.kind == K.PASS_INCOMPLETE and not play.scoring_play
    # ...and the play's own details come from the corrected text, not the original touchdown.
    assert play.info.incomplete and not play.info.touchdown


def test_a_challenge_records_who_challenged_and_what_it_cost():
    rv = Play.from_api(CASES["review_challenge_upheld"]).info.review
    assert rv.by == "Atlanta" and not rv.reversed and rv.timeout_cost == 1
    assert rv.corrected_text == "" and rv.subject == "pass completion"
    ch = Play.from_api(CASES["review_reversed_challenge"]).info.review
    assert ch.by == "Indianapolis" and ch.reversed and ch.subject == "runner was down by contact"
    assert "RECOVERED by IND-K.Harris" in ch.corrected_text


def test_a_review_that_was_upheld_leaves_the_play_as_it_was():
    play = Play.from_api(CASES["review_replay_upheld"])
    assert play.info.review.by == "The Replay Official" and not play.info.review.reversed
    assert play.info.fumble and play.kind == K.PASS_COMPLETE


def test_a_play_without_a_review_has_none():
    assert Play.from_api(CASES["rush"]).info.review is None


# -- the parser never raises ------------------------------------------------------


def test_every_case_survives_being_cut_off_anywhere():
    """The text is a sentence from an undocumented feed: truncate it at every position."""
    for label, raw in CASES.items():
        text = raw["text"]
        for cut in range(len(text) + 1):
            parse_text(raw["type"]["text"], text[:cut])  # must not raise
            parse_text(raw["type"]["text"], text[cut:])
        assert label


@pytest.mark.parametrize(
    "junk", [None, "", "   ", "\n\t", "((((", "PENALTY on ", "Timeout #", 12, [], {}]
)
def test_junk_text_never_raises(junk):
    info = parse_text("Rush", junk)  # type: ignore[arg-type]
    assert info.penalties == () and info.review is None


def test_whitespace_in_the_text_is_collapsed():
    info = parse_text("Timeout", "Timeout   #2\n by  NYG at 00:45.")
    assert (info.timeout_team, info.timeout_number) == ("NYG", 2)


# -- the client -------------------------------------------------------------------


def feed():
    return json.loads((FIXTURES / "summary_drives.json").read_text())


def test_plays_come_back_in_play_order_whatever_order_the_drives_are_in():
    plays = client(FakeResponse(feed())).plays(401873038)
    assert [p.sequence for p in plays] == sorted(p.sequence for p in plays)
    assert len(plays) == 12 and len({p.id for p in plays}) == 12
    assert plays[0].sequence == min(p.sequence for p in map(Play.from_api, _all_plays()))
    assert plays[-1].sequence == max(p.sequence for p in map(Play.from_api, _all_plays()))


def test_the_current_drive_is_included():
    payload = feed()
    current_ids = {p["id"] for p in payload["drives"]["current"]["plays"]}
    plays = client(FakeResponse(payload)).plays(1)
    assert current_ids <= {p.id for p in plays} and current_ids


def test_a_play_listed_twice_is_kept_once_and_the_later_copy_wins():
    payload = feed()
    first = payload["drives"]["previous"][0]["plays"][0]
    dup = copy.deepcopy(first)
    dup["text"] = "changed after review"
    payload["drives"]["current"]["plays"].append(dup)
    plays = client(FakeResponse(payload)).plays(1)
    same = [p for p in plays if p.id == first["id"]]
    assert len(same) == 1 and same[0].text == "changed after review"


def test_a_game_with_no_plays_yet_is_an_empty_list_not_no_data():
    assert client(FakeResponse({"drives": {}})).plays(1) == []
    assert client(FakeResponse({})).plays(1) == []
    assert client(FakeResponse({"drives": {"previous": [], "current": {}}})).plays(1) == []
    assert client(FakeResponse({"drives": "junk"})).plays(1) == []


def test_unusable_plays_are_skipped_and_the_rest_survive(caplog):
    payload = feed()
    payload["drives"]["current"]["plays"] += [{"type": {"text": "Rush"}}, "junk", None]
    with caplog.at_level(logging.WARNING):
        plays = client(FakeResponse(payload)).plays(1)
    assert len(plays) == 12
    assert sum("Skipping unusable play" in r.message for r in caplog.records) == 3


def test_a_failure_is_no_data_not_an_exception():
    c = client(requests.ConnectionError("down"))
    assert c.plays(1) is None and "down" in c.last_error
    assert client(FakeResponse(status=500)).plays(1) is None
    assert client(FakeResponse(body=["x"])).plays(1) is None


def test_the_request_is_the_summary_for_that_event():
    session = FakeSession(FakeResponse({"drives": {}}))
    api.NflClient(session=session).plays(401873052)
    assert session.calls == [(f"{api.BASE_URL}/summary", {"event": "401873052"})]


# -- --dump-plays ----------------------------------------------------------------


def test_dump_plays_prints_a_fixture_game_in_order(monkeypatch, capsys):
    monkeypatch.setattr(api, "_build_session", lambda: FakeSession(FakeResponse(feed())))
    assert cli.main(["--dump-plays", "401873038"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 12
    assert out[0].split()[0] == str(min(p.sequence for p in map(Play.from_api, _all_plays())))
    sequences = [int(line.split()[0]) for line in out]
    assert sequences == sorted(sequences)
    assert any("kickoff" in line for line in out) and any("end_half" in line for line in out)
    assert all("Q" in line for line in out)


def _all_plays():
    f = feed()["drives"]
    for d in [*f["previous"], f["current"]]:
        yield from d["plays"]


def test_dump_plays_with_no_plays_and_with_a_dead_feed(monkeypatch, capsys):
    monkeypatch.setattr(api, "_build_session", lambda: FakeSession(FakeResponse({"drives": {}})))
    assert cli.main(["--dump-plays", "1"]) == 0
    assert capsys.readouterr().out.strip() == "No plays yet."
    monkeypatch.setattr(
        api, "_build_session", lambda: FakeSession(requests.ConnectionError("no route"))
    )
    assert cli.main(["--dump-plays", "1"]) == 1
    assert "no route" in capsys.readouterr().err
