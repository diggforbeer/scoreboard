"""The director (#377): what is on the NFL panel, play by play.

Plays come from the real fixtures (``tests/fixtures/football/play_cases.json``) through the
real queue and detectors; only the clock is fake.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.football import director as dr
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import Director, Timings
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.reversals import Reversal
from nhl_scoreboard.football.worker import FeedSnapshot
from test_football_events import make_game, make_play
from test_football_queue import Clock

TICK = 0.25


class Rig:
    """A director over a fake clock, polled the way the render loop does."""

    def __init__(self, favourite="NYG", follow=(), delay=0.0, game: FbGame | None = None):
        self.clock = Clock()
        self.cfg = FootballConfig(favourite_team=favourite, also_follow=list(follow))
        self.delay = delay
        self.game = game or make_game()
        self.director = Director(lambda: self.cfg, self.clock, lambda: self.delay, self.clock.utc)

    def poll(self, *plays, game=None):
        game = game or self.game
        self.director.ingest(FeedSnapshot(games=(game,), plays={game.id: tuple(plays)}))

    def run(self, limit=400):
        """Everything shown from now until the board rests: ``[(stage name, event or None)]``."""
        seen, last = [], None
        for _ in range(limit):
            current = self.director.current(self.game.id)
            if current is None:
                return seen
            if current.stage is not last:
                last = current.stage
                seen.append(last)
            self.clock.advance(TICK)
        raise AssertionError("the director never came to rest")

    def names(self):
        return [s.stage for s in self.run()]


def started(*first_plays, **kw):
    """A rig that has baselined on ``first_plays`` (the plays already played at startup)."""
    rig = Rig(**kw)
    rig.poll(*first_plays)
    assert rig.run() == [], "the baseline is never animated"
    return rig


def td(n=2):
    return make_play(n, "rush_td_pat", score=(0, 7), off="NYG")


# -- the shape of a play ---------------------------------------------------------------------


def test_a_game_joined_mid_play_animates_nothing_from_before_startup():
    rig = Rig()
    rig.poll(make_play(1, "rush", off="WSH"), td(2))
    assert rig.run() == []


def test_an_ordinary_play_is_its_animation_then_its_text_then_rest():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), make_play(2, "pass_complete", off="WSH"))
    assert rig.names() == [dr.PLAY, dr.PLAYTEXT]
    assert rig.director.current(1) is None


def test_stage_lengths_are_the_proposed_timings():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), td(2))
    stages = rig.run()
    assert [(s.stage, s.seconds) for s in stages] == [
        (dr.PLAY, 3.0), (dr.EVENT, 6.0), (dr.DETAIL, 8.0), (dr.PLAYTEXT, 5.0),
    ]  # fmt: skip


def test_the_stage_is_on_screen_for_its_length_and_its_clock_starts_when_shown():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), make_play(2, "rush", off="WSH"))
    first = rig.director.current(1)
    assert first.stage.stage == dr.PLAY and first.elapsed == 0.0
    rig.clock.advance(1.5)
    assert rig.director.current(1).elapsed == pytest.approx(1.5)
    rig.clock.advance(1.6)  # 3.1s in: the animation is over
    assert rig.director.current(1).stage.stage == dr.PLAYTEXT
    assert rig.director.current(1).elapsed == pytest.approx(0.0)


# -- celebrations by scope ------------------------------------------------------------------------


def test_the_favourites_touchdown_is_animation_celebration_detail_text():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), td())
    stages = rig.run()
    assert [s.stage for s in stages] == [dr.PLAY, dr.EVENT, dr.DETAIL, dr.PLAYTEXT]
    assert isinstance(stages[1].event, ev.Touchdown) and stages[1].event.scope == ev.Scope.FULL
    assert stages[1].event is stages[2].event


def test_a_followed_teams_touchdown_is_the_quick_version_without_detail():
    rig = started(make_play(1, "rush", off="WSH"), favourite="DAL", follow=["NYG"])
    rig.poll(make_play(1, "rush", off="WSH"), td())
    stages = rig.run()
    assert [(s.stage, s.seconds) for s in stages] == [
        (dr.PLAY, 3.0), (dr.EVENT, 4.0), (dr.PLAYTEXT, 5.0),
    ]  # fmt: skip
    assert stages[1].event.scope == ev.Scope.QUICK


def test_an_opponents_made_field_goal_gets_only_the_plays_animation():
    rig = started(make_play(1, "rush", off="NYG"))
    kick = make_play(2, "fg_good", score=(3, 0), off="WSH")
    rig.poll(make_play(1, "rush", off="NYG"), kick)
    assert rig.names() == [dr.PLAY, dr.PLAYTEXT]


def test_a_missed_field_goal_is_a_short_card_for_either_team():
    rig = started(make_play(1, "rush", off="NYG"))
    rig.poll(make_play(1, "rush", off="NYG"), make_play(2, "fg_miss_left", off="WSH"))
    stages = rig.run()
    assert [s.stage for s in stages] == [dr.PLAY, dr.EVENT, dr.PLAYTEXT]
    assert isinstance(stages[1].event, ev.FieldGoal) and stages[1].seconds == 3.0


def test_a_turnover_is_an_alert_after_the_animation():
    rig = started(make_play(1, "rush", off="NYG"))
    rig.poll(
        make_play(1, "rush", off="NYG"), make_play(2, "interception_return", off="NYG", end="WSH")
    )
    stages = rig.run()
    assert [s.stage for s in stages] == [dr.PLAY, dr.EVENT, dr.PLAYTEXT]
    assert isinstance(stages[1].event, ev.Turnover) and stages[1].seconds == 4.0


def test_the_coin_toss_comes_before_the_opening_kickoffs_animation():
    rig = Rig()
    rig.poll()  # the game has not started: an empty baseline
    assert rig.run() == []
    rig.poll(make_play(1, "kickoff_return", off="WSH", end="NYG", clock="15:00"))
    stages = rig.run()
    assert [s.stage for s in stages] == [dr.EVENT, dr.PLAY, dr.PLAYTEXT]
    assert isinstance(stages[0].event, ev.CoinToss) and stages[0].event.team == "NYG"
    assert stages[0].seconds == 6.0


def test_a_play_nobody_has_drawn_never_raises():
    rig = started(make_play(1, "rush", off="WSH"))
    odd = make_play(2, "rush", off="WSH", ptype="Blocked Punt (never seen)")
    rig.poll(make_play(1, "rush", off="WSH"), odd)
    assert rig.names() == [dr.PLAY, dr.PLAYTEXT]


# -- preemption, catch-up, delay ---------------------------------------------------------


def rewritten_td():
    """The real shape of a reversal: the same play id, now an incompletion that does not score."""
    return make_play(
        2, "incomplete_target", score=(0, 0), off="NYG",
        text="Pass incomplete. The Replay Official reviewed the pass completion ruling, "
        "and the play was REVERSED.",
    )  # fmt: skip


def test_a_reversal_replaces_the_celebration_at_once_and_skips_the_detail():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), td())
    while rig.director.current(1).stage.stage != dr.EVENT:
        rig.clock.advance(TICK)
    rig.clock.advance(1.0)
    rig.poll(make_play(1, "rush", off="WSH"), rewritten_td())
    rev = rig.director.current(1)
    assert rev.stage.stage == dr.REVERSAL and isinstance(rev.stage.event, Reversal)
    rest = [s.stage for s in rig.run()]
    assert dr.DETAIL not in rest and dr.EVENT not in rest, rest
    assert rev.stage.event.title == "TOUCHDOWN OVERTURNED"


def test_a_reversal_is_shown_once():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.poll(make_play(1, "rush", off="WSH"), td())
    rig.run()
    rig.poll(make_play(1, "rush", off="WSH"), rewritten_td())
    assert dr.REVERSAL in rig.names()
    rig.poll(make_play(1, "rush", off="WSH"), rewritten_td())
    assert rig.run() == []


def test_a_backlog_is_caught_up_at_double_speed_and_the_skipped_touchdown_still_celebrates():
    rig = started(make_play(1, "rush", off="WSH"))
    plays = [make_play(1, "rush", off="WSH"), td(2)] + [
        make_play(n, "rush", score=(0, 7), off="WSH") for n in range(3, 7)
    ]
    rig.poll(*plays)
    stages = rig.run()
    assert any(isinstance(s.event, ev.Touchdown) for s in stages), (
        "a skipped touchdown still counts"
    )
    assert any(s.speed == 2.0 for s in stages)
    fast = next(s for s in stages if s.speed == 2.0)
    assert fast.duration == fast.seconds / 2


def test_the_broadcast_delay_holds_back_every_stage_together():
    rig = started(make_play(1, "rush", off="WSH"), delay=10.0)
    rig.poll(make_play(1, "rush", off="WSH"), td())
    assert rig.director.current(1) is None
    rig.clock.advance(9.0)
    assert rig.director.current(1) is None
    rig.clock.advance(1.5)
    assert rig.director.current(1).stage.stage == dr.PLAY


def test_another_watched_games_plays_get_their_turn():
    other = make_game("DAL", "PHI", game_id=2)
    rig = Rig(game=make_game())
    rig.game_two = other
    games = (rig.game, other)
    rig.director.ingest(FeedSnapshot(games=games, plays={1: (), 2: ()}))
    rig.director.current(1)
    rig.director.ingest(
        FeedSnapshot(games=games, plays={1: (), 2: (make_play(1, "rush", off="DAL"),)})
    )
    current = rig.director.current(1)  # game 1 is on screen, but game 2 has a play waiting
    assert current is not None and current.stage.game.id == 2


def test_a_game_that_leaves_the_slate_is_forgotten():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.director.ingest(FeedSnapshot(games=(), plays={}))
    assert rig.director.watcher._queues == {}


def test_timings_are_held_to_sane_ranges():
    t = Timings(score=1.0, reversal=100.0, play=0.0).clamped()
    assert (t.score, t.reversal, t.play) == (4.0, 15.0, 1.0)
