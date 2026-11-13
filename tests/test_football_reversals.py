"""The reversal detector (#357): a celebrated play the feed later changes.

The shapes are the real ones (``football_api.md``): ESPN rewrites a reversed play in place, so
a reversed touchdown comes back as an incompletion that no longer scores, with the review
sentence in its text. Plays reuse the helpers of ``test_football_events``.
"""

from __future__ import annotations

import logging

import pytest

from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football import reversals as rv
from nhl_scoreboard.football.events import EventDetector, Scope
from nhl_scoreboard.football.queue import PlayWatcher
from nhl_scoreboard.football.reversals import Reversal, ReversalDetector
from test_football_events import detector, make_game, make_play, one
from test_football_queue import Clock

REVIEW_UPHELD = (
    " The Replay Official reviewed the touchdown ruling, and the play was Upheld."
    " The ruling on the field stands."
)


def celebrate(play, *, favourite="NYG", follow=(), game=None, link=True):
    """Detect the events for ``play`` and start watching them, as the board will."""
    det, game, _cfg = detector(favourite, follow, game=game)
    events = det.on_plays(game, [play])
    watcher = ReversalDetector(det if link else None)
    return det, game, watcher, events


def td_by_home(n=1):
    return make_play(n, "rush_td_pat", score=(0, 7), off="NYG")


# -- the rules, one at a time --------------------------------------------------------------------


def test_the_score_going_down_is_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    assert watcher.remember_all(events) == []
    changed = make_play(1, "rush_td_pat", score=(0, 0), off="NYG")  # same type and flag, score gone
    reversal = one(watcher.on_poll(game, [changed]))
    assert reversal.rules == ("score_dropped",) and reversal.rule == "score_dropped"


def test_a_play_that_disappears_is_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    other = make_play(2, "rush", score=(0, 0), off="WSH")
    reversal = one(watcher.on_poll(game, [other]))
    assert reversal.rules == ("play_gone",) and reversal.current is None
    assert reversal.reason == rv.DEFAULT_REASON
    # The score returns to what it was before the touchdown.
    assert (reversal.away_score, reversal.home_score) == (0, 0)


def test_a_failed_fetch_is_not_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    assert watcher.on_poll(game, []) == [], "an empty poll is a failed fetch, not a disappearance"
    assert watcher.pending(game.id) == 1


def test_a_play_that_stops_scoring_is_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    cleared = make_play(1, "rush_td_pat", score=(0, 7), off="NYG", flags={"scoringPlay": False})
    assert one(watcher.on_poll(game, [cleared])).rules == ("flag_cleared",)


def test_a_changed_type_is_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    retyped = make_play(1, "rush_td_pat", score=(0, 7), off="NYG", ptype="Pass Incompletion")
    assert one(watcher.on_poll(game, [retyped])).rules == ("type_changed",)


def test_a_text_only_edit_is_not_a_reversal():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    edited = make_play(
        1,
        "rush_td_pat",
        score=(0, 7),
        off="NYG",
        text="J.Burrow left guard for 1 yard, TOUCHDOWN. Spelling fixed.",
    )
    assert watcher.on_poll(game, [edited]) == []
    assert watcher.pending(game.id) == 1, "still watched"


def test_a_play_that_keeps_scoring_emits_nothing_however_often_it_is_polled():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    same = td_by_home()
    for _ in range(5):
        assert watcher.on_poll(game, [same]) == []


# -- what a real reversal looks like -------------------------------------------------------------


def real_reversal():
    """A touchdown celebrated, then rewritten in place as an incompletion, as ESPN does."""
    celebrated = make_play(1, "pass_td_pat", score=(7, 0), off="WSH")
    det, game, watcher, events = celebrate(celebrated, favourite="WSH")
    assert watcher.remember_all(events) == []
    rewritten = make_play(1, "review_reversed_touchdown", score=(0, 0), off="WSH")
    return det, game, watcher, one(watcher.on_poll(game, [rewritten])), rewritten


def test_a_touchdown_rewritten_as_an_incompletion_is_reported_with_everything_a_screen_needs():
    _det, game, _watcher, reversal, rewritten = real_reversal()
    assert isinstance(reversal, Reversal) and isinstance(reversal, ev.Event)
    assert reversal.title == "TOUCHDOWN OVERTURNED" and reversal.original_kind == "touchdown"
    assert set(reversal.rules) == {"score_dropped", "flag_cleared", "type_changed"}
    assert reversal.rule == "score_dropped", "the first rule that fired leads"
    assert reversal.review is not None and reversal.review.reversed
    assert reversal.reason == "D.Prescott pass incomplete short right to C.Lamb."
    assert (reversal.away_score, reversal.home_score) == (0, 0)  # the restored score
    assert reversal.down_distance == rewritten.end.down_distance_text
    assert reversal.current is rewritten and reversal.original.play.id == rewritten.id
    assert reversal.team == "WSH" and reversal.scope == Scope.FULL and reversal.sound is False
    assert reversal.game_id == game.id


def test_the_reason_drops_formation_and_substitution_noise():
    assert rv._tidy("(Shotgun) M.Penix pass incomplete.") == "M.Penix pass incomplete."
    assert (
        rv._tidy("B.Jones reported in as eligible.  D.Prescott pass incomplete.")
        == "D.Prescott pass incomplete."
    )
    assert rv._tidy("C.Levin and K.Hinton reported in as eligible. X runs.") == "X runs."
    assert len(rv._tidy("word " * 100)) <= rv.MAX_REASON and rv._tidy("word " * 100).endswith("...")


# -- reviews that do not reverse the outcome -----------------------------------------------------


def test_an_upheld_review_is_not_a_reversal():
    celebrated = td_by_home()
    _det, game, watcher, events = celebrate(celebrated)
    watcher.remember_all(events)
    upheld = make_play(
        1, "rush_td_pat", score=(0, 7), off="NYG", text=celebrated.text + REVIEW_UPHELD
    )
    assert upheld.info.review is not None and not upheld.info.review.reversed
    assert watcher.on_poll(game, [upheld]) == []


def test_a_review_reversed_in_the_plays_favour_is_not_a_reversal():
    """An incompletion reversed into a touchdown is celebrated, and correctly: the review
    sentence alone must never be taken as a reversal."""
    text = (
        "D.Prescott pass incomplete short right to C.Lamb. The Replay Official reviewed the pass"
        " completion ruling, and the play was REVERSED. D.Prescott pass short right to C.Lamb for"
        " 11 yards, TOUCHDOWN."
    )
    final = make_play(1, "pass_td_pat", score=(0, 7), off="NYG", text=text)
    assert final.info.review is not None and final.info.review.reversed and final.is_touchdown
    _det, game, watcher, events = celebrate(final)
    assert one(events).team == "NYG"
    watcher.remember_all(events)
    assert watcher.on_poll(game, [final]) == []


# -- other ways a play is undone -----------------------------------------------------------------


def test_a_touchdown_wiped_out_by_a_penalty_gives_the_penalty_as_the_reason():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    flagged = make_play(1, "penalty_after_run", score=(0, 0), off="NYG")
    reversal = one(watcher.on_poll(game, [flagged]))
    assert "type_changed" in reversal.rules and reversal.review is None
    assert reversal.reason == "OFFENSIVE HOLDING ON ATL, NO PLAY"


def test_a_made_field_goal_negated():
    _det, game, watcher, events = celebrate(make_play(1, "fg_good", score=(0, 3), off="NYG"))
    assert one(events).scope == Scope.FULL
    watcher.remember_all(events)
    nullified = make_play(1, "penalty_pre_snap", score=(0, 0), off="NYG")
    reversal = one(watcher.on_poll(game, [nullified]))
    assert reversal.title == "FIELD GOAL NEGATED" and reversal.original_kind == "field_goal"


def test_a_generic_score_is_reversible():
    safety = make_play(1, "rush", score=(0, 2), off="WSH", ptype="Safety")
    _det, game, watcher, events = celebrate(safety)
    watcher.remember_all(events)
    reversal = one(watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="WSH")]))
    assert reversal.title == "SCORE OVERTURNED"


def test_a_turnover_whose_flag_is_cleared():
    pick = make_play(1, "interception_return", off="WSH", end="NYG")
    _det, game, watcher, events = celebrate(pick)
    assert one(events).reason == "interception"
    watcher.remember_all(events)
    back = make_play(1, "interception_return", off="WSH", end="NYG", flags={"isTurnover": False})
    reversal = one(watcher.on_poll(game, [back]))
    assert reversal.title == "TURNOVER OVERTURNED" and reversal.rules == ("flag_cleared",)


def test_a_turnover_on_downs_whose_possession_is_restored():
    failed = make_play(1, "rush", off="WSH", end="NYG", down=4)
    _det, game, watcher, events = celebrate(failed)
    assert one(events).reason == "on_downs"
    watcher.remember_all(events)
    converted = make_play(1, "rush", off="WSH", end="WSH", down=4)
    assert one(watcher.on_poll(game, [converted])).rules == ("possession_restored",)


# -- who and what is watched ---------------------------------------------------------------------


def test_an_opponents_score_is_never_watched_so_never_reversed():
    opp = make_play(1, "rush_td_pat", score=(7, 0), off="WSH")
    _det, game, watcher, events = celebrate(opp, favourite="NYG")
    assert events == [] and watcher.remember_all(events) == []
    assert watcher.pending(game.id) == 0
    assert watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="WSH")]) == []


def test_a_game_nobody_follows_is_silent():
    game = make_game("MIA", "IND")
    _det, _, watcher, events = celebrate(make_play(1, "rush_td_pat", score=(0, 7), off="IND"),
                                        favourite="DAL", game=game)  # fmt: skip
    assert events == [] and watcher.pending(game.id) == 0


def test_only_scores_and_turnovers_can_be_reversed():
    det, game, watcher, _ = celebrate(td_by_home())
    toss = det.on_plays(
        game, [make_play(2, "kickoff_return", score=(0, 7), off="WSH", end="NYG", clock="15:00")]
    )
    miss = det.on_plays(game, [make_play(3, "fg_miss_left", score=(0, 7), off="WSH")])
    assert toss and miss
    assert watcher.remember_all([*toss, *miss]) == [] and watcher.pending(game.id) == 0
    assert watcher.remember("not an event") is None  # type: ignore[arg-type]


def test_the_scope_of_the_celebration_carries_over_and_a_reversal_never_has_a_sound():
    # A made kick by a team nobody follows, in a followed game: shown plainly.
    _det, game, watcher, events = celebrate(make_play(1, "fg_good", score=(3, 0), off="WSH"))
    assert one(events).scope == Scope.PLAIN
    watcher.remember_all(events)
    reversal = one(
        watcher.on_poll(game, [make_play(1, "penalty_pre_snap", score=(0, 0), off="WSH")])
    )
    assert reversal.scope == Scope.PLAIN and reversal.sound is False
    # A followed team's touchdown: quick.
    _det, game, watcher, events = celebrate(make_play(1, "rush_td_pat", score=(7, 0), off="WSH"),
                                           favourite="DAL", follow=["WSH"])  # fmt: skip
    watcher.remember_all(events)
    assert (
        one(watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="WSH")])).scope
        == Scope.QUICK
    )


# -- once only, and the timing -------------------------------------------------------------------


def test_a_reversal_is_reported_once_and_a_later_change_is_a_new_play():
    det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    gone = [make_play(2, "rush", off="WSH")]
    assert len(watcher.on_poll(game, gone)) == 1
    assert watcher.on_poll(game, gone) == [], "reported once"
    assert watcher.pending(game.id) == 0
    # Celebrated again (say it was put back and re-detected): a fresh record, a fresh reversal.
    again = det.on_plays(game, [make_play(3, "rush_td_pat", score=(0, 14), off="NYG")])
    watcher.remember_all(again)
    assert len(watcher.on_poll(game, [make_play(4, "rush", off="WSH")])) == 1


def test_a_reversal_that_landed_while_the_celebration_waited_is_reported_at_once():
    """The poll with the rewritten play can be applied before the queue shows the touchdown."""
    celebrated = td_by_home()
    _det, game, watcher, events = celebrate(celebrated)
    rewritten = make_play(1, "rush_td_pat", score=(0, 0), off="NYG", flags={"scoringPlay": False})
    assert watcher.on_poll(game, [rewritten]) == []  # nothing celebrated yet
    reversal = one([r for r in [watcher.remember(events[0])] if r])
    assert "flag_cleared" in reversal.rules and watcher.pending(game.id) == 0


def test_the_hook_on_the_watcher_runs_on_the_same_delay_as_the_celebration():
    clock = Clock()
    det, game, _ = detector("NYG", seeded=False)
    reversals: list[Reversal] = []
    reverser = ReversalDetector(det)

    def on_applied(game_id, plays):
        reversals.extend(reverser.on_poll(game_id, list(plays)))

    watcher = PlayWatcher(clock, lambda: 30.0, clock.utc, on_applied=on_applied)
    td = td_by_home()
    watcher.on_fetch(game.id, [])  # the baseline applies at once
    det.seed(game.id, watcher.queue(game.id).baseline)
    watcher.on_fetch(game.id, [td])  # t=0: the touchdown arrives
    clock.advance(30)
    shown = watcher.next(game.id)
    assert shown is not None and reverser.remember_all(det.on_shown(game, shown)) == []
    clock.advance(10)  # the rewrite arrives 10s later...
    rewritten = make_play(1, "rush_td_pat", score=(0, 0), off="NYG", flags={"scoringPlay": False})
    watcher.on_fetch(game.id, [rewritten])
    watcher.tick()
    assert reversals == [], "...but the delay holds it back, as it held the touchdown"
    clock.advance(30)
    watcher.tick()
    assert len(reversals) == 1 and reversals[0].original_kind == "touchdown"


# -- keeping the score right after a reversal ----------------------------------------------------


def test_after_a_reversed_touchdown_the_next_real_touchdown_still_celebrates():
    """The running score would otherwise stay 7 too high and swallow the next touchdown."""
    det, game, watcher, events = celebrate(td_by_home(), link=True)
    watcher.remember_all(events)
    watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="NYG")])  # reversed: 0-0 again
    next_td = make_play(2, "rush_td_pat", score=(0, 7), off="NYG")  # 7 points on the restored 0-0
    assert one(det.on_plays(game, [next_td])).points == 7


def test_without_the_link_the_next_touchdown_is_swallowed():
    """The hazard the link exists for, shown so the test above means something."""
    det, game, watcher, events = celebrate(td_by_home(), link=False)
    watcher.remember_all(events)
    watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="NYG")])
    assert det.on_plays(game, [make_play(2, "rush_td_pat", score=(0, 7), off="NYG")]) == []


def test_only_the_reversed_points_come_off_so_later_scores_stay_valid():
    det, game, _ = detector("NYG")
    watcher = ReversalDetector(det)
    first = det.on_plays(game, [make_play(1, "rush_td_pat", score=(0, 7), off="NYG")])
    det.on_plays(game, [make_play(2, "rush_td_pat", score=(0, 14), off="NYG")])  # a second one
    watcher.remember_all(first)
    assert len(watcher.on_poll(game, [make_play(1, "rush", score=(0, 0), off="NYG")])) == 1
    third = det.on_plays(game, [make_play(3, "rush_td_pat", score=(0, 14), off="NYG")])
    assert one(third).points == 7, "14 minus the reversed 7 leaves 7 to build on"


def test_retract_never_goes_below_zero_and_ignores_unknown_games():
    det, game, _ = detector("NYG")
    det.retract(game.id, 50, 50)
    det.retract(999, 7, 7)
    assert (
        one(det.on_plays(game, [make_play(1, "rush_td_pat", score=(0, 7), off="NYG")])).points == 7
    )


# -- the log -------------------------------------------------------------------------------------


def test_every_match_is_logged_with_the_play_and_the_rules_that_fired(caplog):
    _det, game, watcher, events = celebrate(make_play(1, "pass_td_pat", score=(7, 0), off="WSH"),
                                           favourite="WSH")  # fmt: skip
    watcher.remember_all(events)
    with caplog.at_level(logging.INFO, logger="nhl_scoreboard.football.reversals"):
        watcher.on_poll(game, [make_play(1, "review_reversed_touchdown", score=(0, 0), off="WSH")])
    line = next(r.getMessage() for r in caplog.records if "reversal detected" in r.getMessage())
    assert "play=p0001" in line and "kind=touchdown" in line and "review=yes" in line
    for rule in ("score_dropped", "flag_cleared", "type_changed"):
        assert rule in line
    assert "D.Prescott pass incomplete" in line


def test_a_play_that_was_reviewed_but_stands_is_logged_quietly(caplog):
    celebrated = td_by_home()
    _det, game, watcher, events = celebrate(celebrated)
    watcher.remember_all(events)
    upheld = make_play(
        1, "rush_td_pat", score=(0, 7), off="NYG", text=celebrated.text + REVIEW_UPHELD
    )
    with caplog.at_level(logging.DEBUG, logger="nhl_scoreboard.football.reversals"):
        watcher.on_poll(game, [upheld])
    assert not [r for r in caplog.records if r.levelno >= logging.INFO]
    assert any("stands" in r.getMessage() for r in caplog.records)


# -- the reason ----------------------------------------------------------------------------------


def test_the_reason_falls_back_from_the_corrected_play_to_the_penalty_to_the_subject_to_a_default():
    reviewed = rv.Review(by="The Replay Official", subject="pass completion", reversed=True,
                         original_text="x", corrected_text="", timeout_cost=None)  # fmt: skip
    assert rv._reason(None, None) == rv.DEFAULT_REASON
    assert rv._reason(None, reviewed) == "PASS COMPLETION RULING REVERSED"
    plain = make_play(1, "rush", off="WSH")
    assert rv._reason(plain, None) == rv.DEFAULT_REASON
    flagged = make_play(1, "penalty_pre_snap", off="WSH")
    assert rv._reason(flagged, None) == "FALSE START ON ATL, NO PLAY"
    with_text = rv.Review(
        by="x",
        subject="y",
        reversed=True,
        original_text="a",
        corrected_text="(Shotgun) Real play text.",
        timeout_cost=None,
    )
    assert rv._reason(flagged, with_text) == "Real play text."


def test_a_declined_or_offsetting_penalty_is_not_given_as_the_reason():
    declined = make_play(1, "incomplete_penalty_declined", off="WSH")
    assert rv._reason(declined, None) == rv.DEFAULT_REASON


def test_junk_never_raises():
    _det, game, watcher, events = celebrate(td_by_home())
    watcher.remember_all(events)
    assert watcher.on_poll(game.id, []) == []
    watcher.forget(lambda g: False)
    assert watcher.pending(game.id) == 0
    assert watcher.on_poll(12345, [make_play(1, "rush")]) == []


def test_the_event_and_the_reversal_are_immutable():
    _det, _game, _watcher, reversal, _ = real_reversal()
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        reversal.reason = "x"  # type: ignore[misc]
    assert isinstance(_det, EventDetector)
