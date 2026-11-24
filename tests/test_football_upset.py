"""The upset alert's rules (#557), exactly as the owner set them (2026-11-20).

* From halftime on, never in the first half.
* A ranked team trailing a lower-ranked or unranked one (unranked is below every rank).
* Only when a team in the owner's list is one of the two, being upset or pulling it (#599).
* And an upset final: a ranked team that lost to a lower-ranked or unranked one.
"""

import dataclasses

import pytest

from scoreboard.football import upset as up
from scoreboard.football.upset import Upset, UpsetWatcher, upset_of
from test_football_scenes import game


def made(away=(None, 0), home=(None, 0), state="in", period=3, name="STATUS_IN_PROGRESS"):
    """A game with ``(rank, score)`` for each side (NFL teams: only the ranks matter here)."""
    g = game("NYG", "WSH", state, away[1], home[1], period=period, name=name)
    return dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, rank=away[0]),
        home=dataclasses.replace(g.home, rank=home[0]),
    )


def final(away, home):
    return made(away, home, state="post", period=4, name="STATUS_FINAL")


# -- when it can fire ---------------------------------------------------------------------------


@pytest.mark.parametrize("period", [1, 2])
def test_nothing_fires_in_the_first_half(period):
    assert upset_of(made(away=(5, 0), home=(None, 21), period=period)) is None


def test_it_starts_at_halftime():
    g = made(away=(5, 7), home=(None, 21), period=2, name="STATUS_HALFTIME")
    assert g.is_halftime
    assert upset_of(g) == Upset(g.away, g.home, False, 14)


@pytest.mark.parametrize("period", [3, 4, 5, 6])
def test_and_stays_through_the_second_half_and_overtime(period):
    assert upset_of(made(away=(5, 7), home=(None, 21), period=period)) is not None


def test_a_game_that_has_not_started_is_not_an_upset():
    assert upset_of(made(away=(5, 0), home=(None, 0), state="pre", period=0)) is None


# -- who is upset -------------------------------------------------------------------------------


def test_a_tie_is_not_an_upset():
    assert upset_of(made(away=(5, 14), home=(None, 14))) is None


def test_a_ranked_team_leading_an_unranked_one_is_not_an_upset():
    assert upset_of(made(away=(5, 21), home=(None, 7))) is None


def test_an_unranked_team_cannot_be_upset():
    assert upset_of(made(away=(None, 7), home=(None, 21))) is None
    assert upset_of(made(away=(None, 7), home=(5, 21))) is None, "it is the favourite that wins"


def test_a_ranked_team_trailing_an_unranked_one_is_an_upset_and_names_both():
    g = made(away=(None, 21), home=(3, 14))
    u = upset_of(g)
    assert (u.favourite, u.underdog, u.final, u.margin) == (g.home, g.away, False, 7)


def test_a_ranked_team_trailing_a_lower_ranked_one_is_an_upset():
    assert upset_of(made(away=(5, 7), home=(20, 21))) is not None


def test_a_ranked_team_trailing_a_higher_ranked_one_is_not():
    assert upset_of(made(away=(20, 7), home=(5, 21))) is None


def test_unranked_counts_as_below_the_25th():
    assert upset_of(made(away=(25, 7), home=(None, 21))) is not None


def test_the_minimum_gap_is_how_far_below_the_leader_must_be():
    g = made(away=(5, 7), home=(7, 21))
    assert upset_of(g, min_gap=1) is not None
    assert upset_of(g, min_gap=2) is not None
    assert upset_of(g, min_gap=3) is None
    assert upset_of(made(away=(5, 7), home=(None, 21)), min_gap=20) is not None
    assert upset_of(g, min_gap=0) is not None, "a gap below one is read as one"


# -- the final ----------------------------------------------------------------------------------


def test_a_ranked_team_that_lost_to_an_unranked_one_is_an_upset_final():
    g = final(away=(None, 24), home=(2, 21))
    u = upset_of(g)
    assert u.final and u.favourite is g.home and u.margin == 3


def test_a_ranked_team_that_won_is_no_upset_final():
    assert upset_of(final(away=(None, 10), home=(2, 21))) is None


def test_the_final_follows_the_same_rank_rule():
    assert upset_of(final(away=(20, 24), home=(5, 21))) is not None
    assert upset_of(final(away=(5, 24), home=(20, 21))) is None


# -- the watcher --------------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def ahead(gid=1, score=(7, 21), ranks=(5, None), **kw):
    g = made(away=(ranks[0], score[0]), home=(ranks[1], score[1]), **kw)
    return dataclasses.replace(g, id=gid)


def level(gid=1):
    return ahead(gid, score=(14, 14))


def watcher():
    clock = Clock()
    return UpsetWatcher(clock), clock


def test_a_game_already_in_an_upset_when_first_seen_does_not_alert():
    w, _ = watcher()
    w.observe([ahead()])
    assert w.waiting == 0 and w.current([ahead()], 8) is None


def test_a_game_already_in_an_upset_stays_silent_on_every_later_look_too():
    """Every frame looks at the slate: noting it at first sight must not fire on the second."""
    w, _ = watcher()
    for _ in range(5):
        w.observe([ahead()])
    assert w.waiting == 0
    w.observe([ahead(score=(14, 14))])
    w.observe([ahead()])
    assert w.waiting == 1, "leaving the upset and entering it again is a transition"


def test_entering_an_upset_alerts_once_and_shows_for_its_seconds():
    w, clock = watcher()
    w.observe([level()])
    w.observe([ahead()])
    assert w.waiting == 1
    _game, upset, elapsed = w.current([ahead()], 8)
    assert (upset.favourite.rank, upset.final, elapsed) == (5, False, 0.0)
    clock.t += 3
    assert w.current([ahead()], 8)[2] == 3.0
    clock.t += 5
    assert w.current([ahead()], 8) is None, "it has had its seconds"


def test_it_does_not_alert_again_when_the_lead_changes_back_and_forth():
    w, clock = watcher()
    w.observe([level()])
    w.observe([ahead()])
    w.current([ahead()], 8)
    clock.t += 9
    w.current([ahead()], 8)
    w.observe([level()])
    w.observe([ahead()])
    assert w.waiting == 0, "once per game"


def test_the_final_alerts_separately_from_the_live_alert():
    w, clock = watcher()
    w.observe([level()])
    w.observe([ahead()])
    w.current([ahead()], 8)
    clock.t += 9
    w.current([ahead()], 8)
    result = final(away=(5, 7), home=(None, 21))
    result = dataclasses.replace(result, id=1)
    w.observe([result])
    assert w.waiting == 1
    assert w.current([result], 8)[1].final is True


def test_a_game_that_is_final_when_first_seen_is_not_announced():
    w, _ = watcher()
    done = dataclasses.replace(final(away=(5, 7), home=(None, 21)), id=9)
    w.observe([done])
    assert w.waiting == 0


def test_an_upset_final_with_no_live_alert_still_fires():
    # The board was off or on another game: it saw the game level, then over.
    w, _ = watcher()
    w.observe([level()])
    done = dataclasses.replace(final(away=(5, 7), home=(None, 21)), id=1)
    w.observe([done])
    assert w.waiting == 1


def test_several_games_queue_and_show_one_after_another():
    w, clock = watcher()
    w.observe([level(1), level(2)])
    both = [ahead(1), ahead(2, ranks=(9, None))]
    w.observe(both)
    assert w.waiting == 2
    assert w.current(both, 8)[0].id == 1
    clock.t += 8
    assert w.current(both, 8)[0].id == 2


def test_an_alert_that_waited_too_long_is_dropped_as_old_news():
    w, clock = watcher()
    w.observe([level()])
    w.observe([ahead()])
    clock.t += up.STALE_AFTER + 1
    assert w.current([ahead()], 8) is None


def test_if_the_lead_changes_back_before_it_is_shown_there_is_nothing_to_announce():
    w, _ = watcher()
    w.observe([level()])
    w.observe([ahead()])
    assert w.current([level()], 8) is None


def test_a_game_that_leaves_the_slate_is_forgotten():
    w, _ = watcher()
    w.observe([level()])
    w.observe([ahead()])
    w.observe([])
    w.observe([level()])
    w.observe([ahead()])
    assert w.waiting == 2, "a game id that comes back is a new game"


def test_clear_forgets_everything():
    w, _ = watcher()
    w.observe([level()])
    w.observe([ahead()])
    w.clear()
    assert w.waiting == 0 and w.current([ahead()], 8) is None


def test_the_gap_setting_reaches_the_watcher():
    w, _ = watcher()
    close = lambda s: made(away=(5, s[0]), home=(6, s[1]))  # noqa: E731
    w.observe([close((14, 14))], min_gap=3)
    w.observe([close((7, 21))], min_gap=3)
    assert w.waiting == 0, "#6 is not three places below #5"


# -- only the ranked list's teams (#588) ----------------------------------------------------------


def test_one_of_the_two_teams_must_be_one_the_owner_follows():
    g = ahead()  # NYG (#5, away) trails WSH (unranked) 7-21
    assert upset_of(g, 1, ["NYG"]) is not None, "the team being upset is listed"
    assert upset_of(g, 1, ["nyg", "DAL"]) is not None, "case does not matter"
    assert upset_of(g, 1, ["WSH"]) is not None, "the team pulling the upset is listed (#599)"
    assert upset_of(g, 1, ["wsh"]).underdog.abbrev == "WSH"
    assert upset_of(g, 1, ["DAL"]) is None, "a game between two unlisted teams, however big"
    assert upset_of(g, 1, []) is None, "nobody listed, nothing alerts"
    assert upset_of(g, 1, None) is not None, "the pure default is any game"
    assert (
        upset_of(dataclasses.replace(g, away=dataclasses.replace(g.away, score=0)), 1, ["DAL"])
        is None
    )


def test_the_final_follows_the_same_list():
    lost = final((5, 21), (None, 24))
    assert upset_of(lost, 1, ["NYG"]).final
    assert upset_of(lost, 1, ["DAL"]) is None


def test_a_game_between_unlisted_teams_never_queues_an_alert():
    w, _ = watcher()
    w.observe([level()], teams=["DAL"])
    w.observe([ahead()], teams=["DAL"])
    assert w.waiting == 0 and w.current([ahead()], 8, teams=["DAL"]) is None


def test_a_listed_team_being_upset_alerts():
    w, _ = watcher()
    w.observe([level()], teams=["NYG"])
    w.observe([ahead()], teams=["NYG"])
    assert w.waiting == 1
    _game, u, seconds = w.current([ahead()], 8, teams=["NYG"])
    assert u.favourite.abbrev == "NYG" and seconds == 0.0


def test_a_listed_team_pulling_an_upset_alerts_live_and_at_the_final():
    """Both directions (#599): WSH (unranked, listed) beats NYG (#5)."""
    w, _ = watcher()
    w.observe([level()], teams=["WSH"])
    w.observe([ahead()], teams=["WSH"])
    assert w.waiting == 1
    _game, u, _s = w.current([ahead()], 8, teams=["WSH"])
    assert (u.favourite.abbrev, u.underdog.abbrev, u.final) == ("NYG", "WSH", False)
    w.observe([final((5, 21), (None, 24))], teams=["WSH"])
    assert w.waiting == 1, "and the final"
    assert w.current([final((5, 21), (None, 24))], 8, teams=["WSH"])[1].final


def test_a_listed_team_that_is_winning_without_an_upset_never_alerts():
    """WSH is listed and leads, but NYG (unranked) is not an upset victim: nothing to announce."""
    w, _ = watcher()
    quiet = made(away=(None, 7), home=(None, 21))
    w.observe([quiet], teams=["WSH"])
    w.observe([made(away=(None, 7), home=(None, 28))], teams=["WSH"])
    assert w.waiting == 0
    # a listed ranked team leading a lower-ranked one is the ordinary result, not an upset
    w.observe([made(away=(6, 7), home=(5, 21))], teams=["WSH"])
    w.observe([made(away=(6, 7), home=(5, 28))], teams=["WSH"])
    assert w.waiting == 0


def test_a_listed_team_pulling_an_upset_still_follows_the_gap_setting():
    w, _ = watcher()
    close = lambda s: made(away=(5, s[0]), home=(6, s[1]))  # noqa: E731
    w.observe([close((14, 14))], min_gap=3, teams=["WSH"])
    w.observe([close((7, 21))], min_gap=3, teams=["WSH"])
    assert w.waiting == 0, "#6 is not three places below #5, listed or not"


def test_a_newly_listed_team_already_in_an_upset_does_not_fire():
    w, _ = watcher()
    w.observe([level()], teams=["DAL"])
    w.observe([ahead()], teams=["DAL"])  # an upset, but nobody follows NYG
    w.observe([ahead()], teams=["DAL", "NYG"])  # NYG is added to the list now
    assert w.waiting == 0, "re-baselined: what was already happening is not announced"
    w.observe([ahead()], teams=["DAL", "NYG"])
    assert w.waiting == 0


def test_a_newly_listed_team_alerts_for_what_happens_after():
    w, _ = watcher()
    w.observe([ahead()], teams=["DAL"])
    w.observe([ahead()], teams=["DAL", "NYG"])
    w.observe([final((5, 21), (None, 24))], teams=["DAL", "NYG"])
    assert w.waiting == 1, "the final is a transition after the baseline"


def test_a_removed_team_drops_its_queued_alert():
    w, _ = watcher()
    w.observe([level()], teams=["NYG"])
    w.observe([ahead()], teams=["NYG"])
    assert w.waiting == 1
    assert w.current([ahead()], 8, teams=["DAL"]) is None, "no longer listed: nothing to announce"


def test_the_list_is_remembered_so_an_unchanged_list_does_not_rebaseline():
    w, _ = watcher()
    w.observe([level()], teams=["NYG"])
    w.observe([ahead()], teams=["NYG"])
    assert w.waiting == 1
    w.observe([ahead()], teams=["NYG"])
    assert w.waiting == 1, "the same list, the same state: no second alert"
