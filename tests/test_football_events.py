"""Score, turnover, field goal and coin-toss events (#356).

Plays are real ones from ``play_cases.json`` with the scores, teams and downs set by the
test, so the scoping table and the score-delta attribution are pinned exactly. Nothing is
drawn and nothing is played: this is only the decision.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.events import EventDetector, Scope
from nhl_scoreboard.football.models import FbGame, Play, PlayKind
from nhl_scoreboard.football.queue import PlayQueue, Shown
from nhl_scoreboard.football.teams import TEAMS

FIXTURES = Path(__file__).parent / "fixtures" / "football"
BASE = datetime(2026, 11, 15, 18, 0, tzinfo=UTC)
K = PlayKind


def case(label: str) -> dict:
    data = json.loads((FIXTURES / "play_cases.json").read_text())
    return next(c["play"] for c in data["cases"] if c["label"] == label)


def tid(abbrev: str) -> dict:
    return {"id": str(TEAMS[abbrev].espn_id)}


def make_game(away="WSH", home="NYG", game_id=1) -> FbGame:
    def side(abbrev, home_away):
        return {"homeAway": home_away, "score": "0",
                "team": {"id": str(TEAMS[abbrev].espn_id), "abbreviation": abbrev}}  # fmt: skip

    comp = {"id": str(game_id), "status": {"type": {"state": "in", "name": "STATUS_IN_PROGRESS"}},
            "competitors": [side(home, "home"), side(away, "away")]}  # fmt: skip
    return FbGame.from_api({"id": str(game_id), "competitions": [comp]})


def make_play(n, label, score=(0, 0), off="WSH", end=None, down=None, period=1, clock=None,
              ptype=None, text=None, flags=None) -> Play:  # fmt: skip
    """The real ``label`` play as the ``n``-th of a game, with the given score after it."""
    raw = copy.deepcopy(case(label))
    raw["id"], raw["sequenceNumber"] = f"p{n:04d}", str(n * 100)
    raw["awayScore"], raw["homeScore"] = score
    raw["wallclock"] = (BASE + timedelta(seconds=n * 40)).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw["period"] = {"number": period}
    if clock is not None:
        raw["clock"] = {"displayValue": clock}
    raw["start"] = {**raw.get("start", {}), "team": tid(off)}
    raw["end"] = {**raw.get("end", {}), "team": tid(end or off)}
    if down is not None:
        raw["start"]["down"] = down
    if ptype is not None:
        raw["type"] = {"id": "0", "text": ptype}
    if text is not None:
        raw["text"] = text
    for key, value in (flags or {}).items():
        raw[key] = value
    return Play.from_api(raw)


def detector(favourite="NYG", follow=(), seeded=True, game=None):
    cfg = FootballConfig(favourite_team=favourite, also_follow=list(follow))
    det = EventDetector(lambda: cfg)
    game = game or make_game()
    if seeded:
        det.seed(game.id, None)
    return det, game, cfg


def run(det, game, *plays):
    return det.on_plays(game, list(plays))


def one(events):
    assert len(events) == 1, events
    return events[0]


# -- touchdowns: who scored comes from the score delta -------------------------------------------


def test_the_favourites_touchdown_is_full_and_carries_the_sound():
    det, game, _ = detector("NYG")
    td = one(run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG")))
    assert isinstance(td, ev.Touchdown)
    assert (td.team, td.scope, td.sound) == ("NYG", Scope.FULL, True)
    assert (td.points, td.away_before, td.home_before) == (7, 0, 0)
    assert (td.away_score, td.home_score) == (0, 7)
    assert td.via == "run" and td.extra_point == "good" and td.game_id == 1


def test_a_pass_touchdown_by_the_away_favourite():
    det, game, _ = detector("WSH")
    td = one(run(det, game, make_play(1, "pass_td_pat", score=(7, 0), off="WSH")))
    assert (td.team, td.via, td.scope, td.sound) == ("WSH", "pass", Scope.FULL, True)


def test_a_pick_six_counts_for_the_defence_not_the_team_with_the_ball():
    det, game, _ = detector("NYG")  # WSH threw it, NYG intercepted and scored
    pick_six = make_play(1, "interception_td", score=(0, 7), off="WSH", end="NYG")
    td = one(run(det, game, pick_six))
    assert td.team == "NYG" and td.via == "interception" and td.scope == Scope.FULL
    assert td.sound is True
    # No separate turnover event: the touchdown is the bigger event.
    assert not [e for e in run(det, game) if isinstance(e, ev.Turnover)]


def test_a_pick_six_against_the_favourite_is_an_opponents_score_and_emits_nothing():
    det, game, _ = detector("WSH")
    assert run(det, game, make_play(1, "interception_td", score=(0, 7), off="WSH", end="NYG")) == []


def test_a_safety_is_a_generic_score():
    det, game, _ = detector("NYG")
    safety = make_play(1, "rush", score=(0, 2), off="WSH", ptype="Safety", text="Safety.")
    generic = one(run(det, game, safety))
    assert isinstance(generic, ev.GenericScore)
    assert (generic.team, generic.points, generic.scope, generic.sound) == (
        "NYG",
        2,
        Scope.FULL,
        False,
    )


def test_an_unrecognised_touchdown_type_is_still_a_touchdown_by_the_delta():
    det, game, _ = detector("NYG")
    play = make_play(
        1, "rush_td_pat", score=(0, 6), off="WSH", end="NYG", ptype="Punt Return Touchdown"
    )
    td = one(run(det, game, play))
    assert (
        isinstance(td, ev.Touchdown) and td.team == "NYG" and td.via == "return" and td.points == 6
    )


def test_points_are_the_delta_so_a_two_point_conversion_is_counted():
    det, game, _ = detector("NYG")
    td = one(run(det, game, make_play(1, "rush_td_two_point_good", score=(0, 8), off="NYG")))
    assert td.points == 8 and td.two_point == "good"


def test_both_sides_scoring_on_one_play_gives_each_its_own_event():
    det, game, _ = detector("NYG", follow=["WSH"])
    both = make_play(
        1, "rush", score=(2, 6), off="NYG", ptype="Rushing Touchdown", text="TOUCHDOWN"
    )
    teams = {e.team for e in run(det, game, both)}
    assert teams <= {"NYG", "WSH"} and "NYG" in teams


# -- the scoping table ---------------------------------------------------------------------------


def test_scoping_for_touchdowns_pinned():
    td = lambda who, score, **kw: make_play(1, "rush_td_pat", score=score, off=who, **kw)  # noqa: E731
    # The favourite: full, with the sound.
    det, game, _ = detector("NYG", follow=["KC"])
    e = one(run(det, game, td("NYG", (0, 7))))
    assert (e.scope, e.sound) == (Scope.FULL, True)
    # An opponent: nothing, so no event and no sound flag.
    det, game, _ = detector("NYG", follow=["KC"])
    assert run(det, game, td("WSH", (7, 0))) == []
    # A followed team in a game the favourite is not in: quick, silent.
    det, game, _ = detector("NYG", follow=["KC"], game=make_game("KC", "DAL"))
    e = one(run(det, game, td("KC", (7, 0))))
    assert (e.team, e.scope, e.sound) == ("KC", Scope.QUICK, False)
    # A followed team scoring on the favourite: no screen (the NHL rule).
    det, game, _ = detector("NYG", follow=["WSH"])
    assert run(det, game, td("WSH", (7, 0))) == []
    # Two followed teams meeting: both count.
    det, game, _ = detector("DAL", follow=["KC", "PHI"], game=make_game("KC", "PHI"))
    away = one(run(det, game, td("KC", (7, 0))))
    home = one(run(det, game, make_play(2, "rush_td_pat", score=(7, 7), off="PHI")))
    assert (away.team, away.scope) == ("KC", Scope.QUICK) and (home.team, home.scope) == (
        "PHI",
        Scope.QUICK,
    )
    # A game nobody follows: nothing.
    det, game, _ = detector("DAL", follow=["KC"], game=make_game("MIA", "IND"))
    assert run(det, game, td("MIA", (7, 0))) == []


def test_with_no_favourite_set_followed_teams_still_get_the_quick_version():
    det, game, _ = detector("", follow=["NYG"])
    e = one(run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG")))
    assert (e.scope, e.sound) == (Scope.QUICK, False)


def test_the_sound_flag_is_only_for_the_favourites_touchdown_and_made_field_goal():
    det, game, _ = detector("NYG", follow=["WSH"])
    # Followed team's field goal in the favourite's game: quick, silent.
    kick = one(run(det, game, make_play(1, "fg_good", score=(3, 0), off="WSH")))
    assert (kick.scope, kick.sound) == (Scope.QUICK, False)
    td = one(run(det, game, make_play(2, "rush_td_pat", score=(3, 7), off="NYG")))
    fg = one(run(det, game, make_play(3, "fg_good", score=(3, 10), off="NYG")))
    assert td.sound is True and fg.sound is True
    safety = one(run(det, game, make_play(4, "rush", score=(3, 12), off="WSH", ptype="Safety")))
    assert safety.sound is False


# -- field goals: the outcome shows for either team in a followed game ---------------------------


def test_a_made_field_goal_for_each_kind_of_team():
    det, game, _ = detector("NYG")
    fg = one(run(det, game, make_play(1, "fg_good", score=(0, 3), off="NYG")))
    assert (fg.made, fg.team, fg.scope, fg.sound, fg.points) == (True, "NYG", Scope.FULL, True, 3)
    assert fg.yards == 31 and fg.miss == ""
    # The opponent's made kick in the favourite's game: shown plainly, no sound.
    opp = one(run(det, game, make_play(2, "fg_good", score=(3, 3), off="WSH")))
    assert (opp.team, opp.scope, opp.sound, opp.made) == ("WSH", Scope.PLAIN, False, True)


def test_a_made_field_goal_in_a_game_nobody_follows_is_not_shown():
    det, game, _ = detector("DAL", game=make_game("MIA", "IND"))
    assert run(det, game, make_play(1, "fg_good", score=(0, 3), off="IND")) == []


def test_a_followed_teams_made_field_goal_is_quick():
    det, game, _ = detector("DAL", follow=["KC"], game=make_game("KC", "ATL"))
    fg = one(run(det, game, make_play(1, "fg_good", score=(3, 0), off="KC")))
    assert (fg.scope, fg.sound) == (Scope.QUICK, False)


@pytest.mark.parametrize(
    ("label", "miss"), [("fg_miss_left", "Wide Left"), ("fg_miss_right", "Wide Right")]
)
def test_a_missed_field_goal_shows_for_either_team_with_its_side(label, miss):
    det, game, _ = detector("NYG")
    own = one(run(det, game, make_play(1, label, score=(0, 0), off="NYG")))
    assert (own.made, own.team, own.miss, own.points) == (False, "NYG", miss, 0)
    assert own.scope == Scope.QUICK and own.sound is False
    other = one(run(det, game, make_play(2, label, score=(0, 0), off="WSH")))
    assert (other.team, other.scope, other.sound) == ("WSH", Scope.PLAIN, False)
    assert other.yards is not None


def test_a_missed_field_goal_in_a_game_nobody_follows_is_not_shown():
    det, game, _ = detector("DAL", game=make_game("MIA", "IND"))
    assert run(det, game, make_play(1, "fg_miss_left", off="IND")) == []


# -- turnovers -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "reason"),
    [("interception_return", "interception"), ("fumble_opponent", "fumble"),
     ("sack_fumble", "sack_fumble"), ("muffed_punt", "muffed_punt")],
)  # fmt: skip
def test_each_kind_of_takeaway(label, reason):
    det, game, _ = detector("NYG")
    t = one(run(det, game, make_play(1, label, off="WSH", end="NYG")))
    assert isinstance(t, ev.Turnover)
    assert (t.reason, t.team, t.lost_by, t.scope, t.sound) == (
        reason,
        "NYG",
        "WSH",
        Scope.FULL,
        False,
    )


def test_a_giveaway_by_the_favourite_is_still_a_full_event_about_the_game():
    det, game, _ = detector("NYG")
    t = one(run(det, game, make_play(1, "interception_return", off="NYG", end="WSH")))
    assert (t.team, t.lost_by, t.scope) == ("WSH", "NYG", Scope.FULL)


def test_a_turnover_in_a_followed_game_is_quick_and_in_other_games_it_is_not_emitted():
    det, game, _ = detector("DAL", follow=["KC"], game=make_game("KC", "ATL"))
    t = one(run(det, game, make_play(1, "interception_return", off="KC", end="ATL")))
    assert t.scope == Scope.QUICK
    det, game, _ = detector("DAL", follow=["KC"], game=make_game("MIA", "IND"))
    assert run(det, game, make_play(1, "interception_return", off="MIA", end="IND")) == []


def test_a_turnover_on_downs_is_a_failed_fourth_down_that_changes_possession():
    det, game, _ = detector("NYG")
    failed = make_play(1, "rush", off="WSH", end="NYG", down=4)
    t = one(run(det, game, failed))
    assert (t.reason, t.team, t.lost_by) == ("on_downs", "NYG", "WSH")
    for label in ("pass_complete", "incomplete_target", "sack"):
        again = make_play(2, label, off="WSH", end="NYG", down=4)
        assert one(run(det, game, again)).reason == "on_downs"


def test_it_is_not_a_turnover_on_downs_when_the_drive_goes_on_or_it_was_not_fourth_down():
    det, game, _ = detector("NYG")
    assert run(det, game, make_play(1, "rush", off="WSH", end="WSH", down=4)) == []  # converted
    assert run(det, game, make_play(2, "rush", off="WSH", end="NYG", down=3)) == []  # not 4th
    assert (
        run(det, game, make_play(3, "punt_fair_catch", off="WSH", end="NYG", down=4)) == []
    )  # a punt
    assert run(det, game, make_play(4, "kickoff_return", off="WSH", end="NYG")) == []
    assert run(det, game, make_play(5, "penalty_no_play", off="WSH", end="NYG", down=4)) == []


def test_a_score_is_never_also_a_turnover():
    det, game, _ = detector("NYG")
    events = run(det, game, make_play(1, "fumble_opponent", score=(0, 6), off="WSH", end="NYG",
                                      flags={"scoringPlay": True}))  # fmt: skip
    assert [type(e) for e in events] == [ev.GenericScore]


# -- the coin toss -------------------------------------------------------------------------------


def test_the_opening_kickoff_names_the_receiver_once():
    det, game, _ = detector("NYG")
    kick = make_play(1, "kickoff_return", off="WSH", end="NYG", clock="15:00")
    toss = one(run(det, game, kick))
    assert isinstance(toss, ev.CoinToss)
    assert (toss.team, toss.kicker, toss.scope, toss.sound) == ("NYG", "WSH", Scope.FULL, False)
    again = make_play(2, "kickoff_return", off="WSH", end="NYG", clock="15:00")
    assert run(det, game, again) == [], "once per game"


def test_only_a_kickoff_at_the_start_of_the_game_is_the_toss():
    det, game, _ = detector("NYG")
    assert run(det, game, make_play(1, "kickoff_return", off="WSH", end="NYG", clock="9:41")) == []
    assert run(det, game, make_play(2, "kickoff_return", off="WSH", end="NYG", clock="15:00",
                                    period=3)) == []  # fmt: skip
    assert run(det, game, make_play(3, "rush", off="WSH", clock="15:00")) == []


def test_an_actual_coin_toss_play_works_too():
    det, game, _ = detector("NYG")
    play = make_play(1, "kickoff_return", off="WSH", end="NYG", ptype="Coin Toss", text="GAME")
    toss = one(run(det, game, play))
    assert toss.team == "NYG" and toss.kicker == "WSH"


def test_the_toss_is_full_in_the_favourites_game_quick_in_a_followed_one_and_otherwise_absent():
    kick = lambda: make_play(1, "kickoff_return", off="KC", end="ATL", clock="15:00")  # noqa: E731
    det, game, _ = detector("DAL", follow=["KC"], game=make_game("KC", "ATL"))
    assert one(run(det, game, kick())).scope == Scope.QUICK
    det, game, _ = detector("DAL", follow=[], game=make_game("KC", "ATL"))
    assert run(det, game, kick()) == []


def test_a_board_that_joins_mid_game_never_celebrates_the_toss():
    """The opening kickoff is in the queue's baseline, so it is never shown."""
    det, game, _ = detector("NYG", seeded=False)
    queue = PlayQueue()
    history = [make_play(1, "kickoff_return", score=(0, 0), off="WSH", end="NYG", clock="15:00"),
               make_play(2, "rush", score=(0, 0), off="NYG")]  # fmt: skip
    queue.offer(history)  # the baseline: nothing is shown
    det.seed(game.id, queue.baseline)
    assert queue.next() is None and run(det, game) == []


# -- no event for the score the board started with -----------------------------------------------


def test_nothing_fires_for_the_score_at_startup_but_the_next_score_does():
    det, game, _ = detector("NYG", seeded=False)
    queue = PlayQueue()
    history = [make_play(1, "rush_td_pat", score=(0, 7), off="NYG"),
               make_play(2, "pass_td_pat", score=(7, 7), off="WSH")]  # fmt: skip
    queue.offer(history)
    det.seed(game.id, queue.baseline)
    assert det.seeded(game.id)
    # A play after the baseline that does not change the score: nothing.
    queue.offer([*history, make_play(3, "rush", score=(7, 7), off="NYG")])
    shown = queue.next()
    assert det.on_shown(game, shown) == []
    # A real touchdown afterwards does fire, with the right before and after.
    queue.offer([*history, shown.play, make_play(4, "rush_td_pat", score=(7, 14), off="NYG")])
    td = one(det.on_shown(game, queue.next()))
    assert (td.team, td.points, td.home_before, td.home_score) == ("NYG", 7, 7, 14)


def test_a_game_watched_from_before_kickoff_seeds_at_nil_nil_and_celebrates_the_first_score():
    det, game, _ = detector("NYG", seeded=False)
    queue = PlayQueue()
    queue.offer([])  # pre-game
    det.seed(game.id, queue.baseline)
    td = make_play(1, "rush_td_pat", score=(0, 7), off="NYG")
    queue.offer([td])
    assert one(det.on_shown(game, queue.next())).points == 7


def test_an_unseeded_game_treats_its_first_play_as_the_baseline(caplog):
    det, game, _ = detector("NYG", seeded=False)
    with caplog.at_level(logging.INFO, logger="nhl_scoreboard.football.events"):
        assert run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG")) == []
    assert any("unseeded" in r.getMessage() for r in caplog.records)
    assert one(run(det, game, make_play(2, "rush_td_pat", score=(0, 14), off="NYG"))).points == 7


def test_a_fresh_detector_after_a_sport_switch_remembers_nothing():
    det, game, cfg = detector("NYG")
    run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG"))
    assert det.seeded(game.id)
    fresh = EventDetector(lambda: cfg)
    assert not fresh.seeded(game.id)
    assert run(fresh, game, make_play(2, "rush_td_pat", score=(0, 14), off="NYG")) == []


def test_forgetting_a_game_drops_its_score():
    det, game, _ = detector("NYG")
    det.forget(lambda g: g != game.id)
    assert not det.seeded(game.id)


# -- the queue hand-off: skipped plays still count -----------------------------------------------


def test_a_touchdown_skipped_by_the_queue_still_celebrates_in_order():
    det, game, _ = detector("NYG")
    td = make_play(2, "rush_td_pat", score=(0, 7), off="NYG")
    skipped_other = make_play(1, "rush", score=(0, 0), off="NYG")
    shown_play = make_play(3, "pass_complete", score=(0, 7), off="WSH")
    shown = Shown(shown_play, 1000.0, 2.0, 5, (td, skipped_other), None)  # skipped out of order
    events = det.on_shown(game, shown)
    assert [type(e) for e in events] == [ev.Touchdown] and events[0].play is td


def test_events_come_out_in_play_order():
    det, game, _ = detector("NYG")
    fg = make_play(1, "fg_good", score=(0, 3), off="NYG")
    td = make_play(2, "rush_td_pat", score=(0, 10), off="NYG")
    shown = Shown(td, 1000.0, 2.0, 3, (fg,), None)
    assert [type(e).__name__ for e in det.on_shown(game, shown)] == ["FieldGoal", "Touchdown"]


# -- the live config -----------------------------------------------------------------------------


def test_changing_the_followed_teams_applies_to_the_very_next_play():
    cfg = FootballConfig(favourite_team="NYG")
    det = EventDetector(lambda: cfg)
    game = make_game("KC", "DAL")
    det.seed(game.id, None)
    assert run(det, game, make_play(1, "rush_td_pat", score=(7, 0), off="KC")) == []
    cfg.also_follow = ["KC"]  # the owner starts following Kansas City
    assert (
        run(det, game, make_play(2, "rush_td_pat", score=(14, 0), off="KC"))[0].scope == Scope.QUICK
    )


def test_a_score_going_down_after_a_review_emits_nothing_and_resets_the_baseline():
    det, game, _ = detector("NYG")
    run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG"))
    assert run(det, game, make_play(2, "rush", score=(0, 0), off="NYG")) == [], "reversals are #357"
    assert one(run(det, game, make_play(3, "rush_td_pat", score=(0, 7), off="NYG"))).points == 7


# -- the events themselves -----------------------------------------------------------------------


def test_events_are_immutable_and_hashable():
    det, game, _ = detector("NYG")
    td = one(run(det, game, make_play(1, "rush_td_pat", score=(0, 7), off="NYG")))
    with pytest.raises(dataclasses.FrozenInstanceError):
        td.points = 99  # type: ignore[misc]
    assert hash(td) == hash(td) and {td: 1}[td] == 1


def test_the_queue_remembers_its_baseline_play():
    queue = PlayQueue()
    assert queue.baseline is None
    queue.offer([])
    assert queue.baseline is None
    queue = PlayQueue()
    plays = [make_play(1, "rush", score=(3, 0)), make_play(2, "rush", score=(3, 7))]
    queue.offer(plays)
    assert queue.baseline is plays[-1] and queue.baseline.home_score == 7
