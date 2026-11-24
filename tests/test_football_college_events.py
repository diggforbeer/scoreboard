"""College football shows scores and major events, not every play (#548).

The same real plays and the same detectors as the NFL's, through a scores-only director: only a
score's celebration and detail (and a reversal of one) reach the panel.
"""

from __future__ import annotations

from scoreboard.config import ScoreboardConfig
from scoreboard.football import director as dr
from scoreboard.football.director import Director
from scoreboard.football.mode import FootballMode
from scoreboard.football.worker import FeedSnapshot
from test_football_director import Rig, rewritten_td, started, td
from test_football_events import make_play


class ScoresRig(Rig):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.director = Director(
            lambda: self.cfg, self.clock, lambda: self.delay, self.clock.utc, scores_only=True
        )


def scores_started(*first, **kw):
    rig = ScoresRig(**kw)
    rig.poll(*first)
    assert rig.run() == []
    return rig


RUSH = make_play(1, "rush", off="WSH")


def test_a_followed_teams_touchdown_is_its_celebration_and_detail_and_nothing_else():
    rig = scores_started(RUSH)
    rig.poll(RUSH, td())
    assert rig.names() == [dr.EVENT, dr.DETAIL], "no play animation, no play text"


def test_the_same_touchdown_in_the_nfl_director_still_has_the_animation_and_the_text():
    nfl = started(RUSH)
    nfl.poll(RUSH, td())
    names = nfl.names()
    assert dr.PLAY in names and dr.PLAYTEXT in names and dr.EVENT in names


def test_an_ordinary_play_shows_nothing_at_all():
    rig = scores_started(RUSH)
    rig.poll(RUSH, make_play(2, "pass_complete", off="WSH"))
    assert rig.names() == []
    rig.poll(RUSH, make_play(3, "sack", off="WSH"))
    assert rig.names() == []


def test_a_made_field_goal_is_a_score_screen_for_a_followed_team():
    rig = scores_started(RUSH, favourite="WSH")
    rig.poll(RUSH, make_play(2, "fg_good", score=(3, 0), off="WSH"))
    assert rig.names() == [dr.EVENT, dr.DETAIL]


def test_a_missed_field_goal_has_no_screen():
    rig = scores_started(RUSH)
    rig.poll(RUSH, make_play(2, "fg_miss_left", off="WSH"))
    assert rig.names() == []


def test_turnovers_have_no_screen_only_the_score_change_they_cause():
    rig = scores_started(make_play(1, "rush", off="NYG"))
    rig.poll(
        make_play(1, "rush", off="NYG"), make_play(2, "interception_return", off="NYG", end="WSH")
    )
    assert rig.names() == []
    rig.poll(
        make_play(1, "rush", off="NYG"),
        make_play(2, "interception_return", off="NYG", end="WSH"),
        make_play(3, "fumble_own", off="NYG"),
    )
    assert rig.names() == []


def test_a_pick_six_is_a_touchdown_screen_not_a_turnover_screen():
    rig = scores_started(make_play(1, "rush", off="NYG"), favourite="NYG")
    rig.poll(
        make_play(1, "rush", off="NYG"),
        make_play(2, "interception_td", score=(0, 7), off="WSH", end="NYG"),
    )
    shown = rig.run()
    assert shown and {s.stage for s in shown} <= {dr.EVENT, dr.DETAIL}
    assert not any(isinstance(s.event, dr.Turnover) for s in shown)


def test_stoppages_the_half_and_the_coin_toss_have_no_play_screens():
    rig = scores_started(RUSH)
    rig.poll(RUSH, make_play(2, "official_timeout", off="WSH"))
    assert rig.names() == []
    rig.poll(RUSH, make_play(2, "official_timeout", off="WSH"), make_play(3, "end_half", off="WSH"))
    assert rig.names() == []


def test_an_overturned_touchdown_still_corrects_the_screen_that_was_shown():
    rig = scores_started(RUSH)
    rig.poll(RUSH, td())
    assert rig.names() == [dr.EVENT, dr.DETAIL]
    rig.poll(RUSH, rewritten_td())  # the same play id, now an incompletion
    assert rig.names() == [dr.REVERSAL]


def test_the_plays_are_still_read_so_the_score_is_known_whoever_scores():
    # An opponent's touchdown (a PLAIN scope) has no celebration, and now no animation either.
    rig = scores_started(RUSH, favourite="NYG")
    rig.poll(RUSH, make_play(2, "pass_td_pat", score=(7, 0), off="WSH"))
    assert rig.names() == []


# -- the mode picks the right director ----------------------------------------------------------


def mode(league):
    return FootballMode(lambda: ScoreboardConfig(), client_factory=lambda: None, league=league)


def test_a_college_mode_has_a_scores_only_director_and_the_nfl_mode_does_not():
    assert mode("college-football").director._scores_only is True
    assert mode("nfl").director._scores_only is False


def test_a_college_director_made_after_a_reset_is_still_scores_only():
    m = mode("college-football")
    m.reset_screens()
    assert m.director._scores_only is True


def test_snapshots_with_no_plays_are_harmless():
    rig = ScoresRig()
    rig.director.ingest(FeedSnapshot(games=(rig.game,), plays={}))
    assert rig.run() == []
