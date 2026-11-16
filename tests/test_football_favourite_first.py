"""Several teams at once: the favourite is the primary, followed teams break in.

* While the favourite's game holds the screen, a followed team's plays are not animated over it;
  its scores and turnovers still come through, quickly.
* The favourite's waiting play goes ahead of another game's stages, which are shown after it.
* A reversal in one game takes only that game's queued stages with it, and does not cut another
  game's celebration off.
* The favourite's countdown and final keep the screen when a followed team's game is live, and a
  followed team's score breaks in over them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hockey_scoreboard.config import FootballConfig
from hockey_scoreboard.football import director as dr
from hockey_scoreboard.football.director import Director
from hockey_scoreboard.football.mode import FootballMode
from hockey_scoreboard.football.teams import TEAMS
from hockey_scoreboard.football.worker import FeedSnapshot
from test_football_events import make_game, make_play
from test_football_idle_selection import (
    BASE,
    KICKOFF,
    IdleFeed,
    Utc,
    nyg_game,
    register,
    stand_ins,  # noqa: F401 - the autouse fixture that puts the idle screens back after each test
)
from test_football_queue import Clock
from test_football_scenes import game

TICK = 0.25
KC_ID = TEAMS["KC"].espn_id
FAV = make_game("WSH", "NYG", game_id=1)  # the favourite NYG's game
OTHER = make_game("PHI", "DAL", game_id=2)  # DAL, followed, elsewhere


class Rig:
    """A director over two games and a fake clock, polled the way the render loop does."""

    def __init__(self, hold=True, favourite="NYG", follow=("DAL",)):
        self.clock = Clock()
        self.cfg = FootballConfig(favourite_team=favourite, also_follow=list(follow))
        self.hold = hold
        self.director = Director(lambda: self.cfg, self.clock, lambda: 0.0, self.clock.utc)
        self.fav_plays: list = []
        self.other_plays: list = []

    def poll(self, fav=None, other=None):
        self.fav_plays = list(fav if fav is not None else self.fav_plays)
        self.other_plays = list(other if other is not None else self.other_plays)
        self.director.ingest(
            FeedSnapshot(
                games=(FAV, OTHER),
                plays={1: tuple(self.fav_plays), 2: tuple(self.other_plays)},
            )
        )

    def step(self):
        return self.director.current(1, hold=self.hold)

    def run(self, limit=800):
        """Every stage shown from now until the board rests: ``[Stage]``."""
        seen, last = [], None
        for _ in range(limit):
            current = self.step()
            if current is None:
                return seen
            if current.stage is not last:
                last = current.stage
                seen.append(last)
            self.clock.advance(TICK)
        raise AssertionError("the director never came to rest")

    def started(self):
        base_fav = [make_play(1, "rush", off="WSH")]
        base_other = [make_play(1, "rush", off="PHI")]
        self.poll(base_fav, base_other)
        assert self.run() == [], "the baseline is never animated"
        return self


def other_td(n=2):
    return make_play(n, "rush_td_pat", score=(0, 7), off="DAL")  # DAL is the home side


def fav_td(n=2):
    return make_play(n, "rush_td_pat", score=(0, 7), off="NYG")


def shape(stages):
    return [(s.game.id, s.stage) for s in stages]


# -- 1: the favourite holds the screen ----------------------------------------------------------


def test_a_followed_games_ordinary_play_is_not_animated_while_the_favourite_holds_the_screen():
    rig = Rig(hold=True).started()
    rig.poll(other=[*rig.other_plays, make_play(2, "pass_complete", off="PHI")])
    assert rig.run() == []


def test_without_a_favourite_holding_the_screen_a_followed_games_plays_still_animate():
    rig = Rig(hold=False).started()
    rig.poll(other=[*rig.other_plays, make_play(2, "pass_complete", off="PHI")])
    assert shape(rig.run()) == [(2, dr.PLAY), (2, dr.PLAYTEXT)]


def test_a_followed_teams_touchdown_comes_through_as_a_quick_screen_only():
    rig = Rig(hold=True).started()
    rig.poll(other=[*rig.other_plays, other_td()])
    stages = rig.run()
    assert shape(stages) == [(2, dr.EVENT)]
    assert stages[0].seconds == rig.director._timings().clamped().quick
    assert stages[0].event.team == "DAL"


def test_the_favourites_own_plays_are_animated_in_full_as_ever():
    rig = Rig(hold=True).started()
    rig.poll(fav=[*rig.fav_plays, make_play(2, "pass_complete", off="WSH")])
    assert shape(rig.run()) == [(1, dr.PLAY), (1, dr.PLAYTEXT)]


def test_the_followed_games_queue_does_not_back_up_while_it_is_not_shown():
    """Its plays are consumed (not left waiting to be replayed later), so nothing is shown late."""
    rig = Rig(hold=True).started()
    other = rig.other_plays
    for n in range(2, 10):
        other = [*other, make_play(n, "rush", off="PHI")]
        rig.poll(other=other)
        assert rig.run() == []
    assert rig.director.watcher.queue(2).depth == 0


# -- 3: the favourite goes first ------------------------------------------------------------------


def test_a_waiting_favourite_play_goes_ahead_of_a_followed_teams_screen_which_follows_it():
    rig = Rig(hold=True).started()
    rig.poll(other=[*rig.other_plays, other_td()])
    assert rig.step().stage.event.team == "DAL"  # the followed touchdown is up
    rig.poll(fav=[*rig.fav_plays, make_play(2, "pass_complete", off="WSH")])
    assert shape(rig.run()) == [(1, dr.PLAY), (1, dr.PLAYTEXT), (2, dr.EVENT)]


def test_a_favourite_touchdown_is_not_made_to_wait_behind_a_followed_one():
    rig = Rig(hold=True).started()
    rig.poll(other=[*rig.other_plays, other_td()])
    rig.step()
    rig.poll(fav=[*rig.fav_plays, fav_td()])
    names = shape(rig.run())
    assert names[:4] == [(1, dr.PLAY), (1, dr.EVENT), (1, dr.DETAIL), (1, dr.PLAYTEXT)]
    assert names[4:] == [(2, dr.EVENT)], "the followed touchdown is late, not lost"


# -- 2: a reversal only takes its own game's stages ----------------------------------------------


def reversed_in_other(rig):
    """The followed game's touchdown has been shown; the feed now rewrites it."""
    rig.poll(other=[*rig.other_plays, other_td()])
    assert shape(rig.run()) == [(2, dr.EVENT)]
    return make_play(2, "penalty_after_run", score=(0, 0), off="DAL")


def test_a_reversal_in_another_game_does_not_cut_off_the_favourites_celebration():
    rig = Rig(hold=True).started()
    rewritten = reversed_in_other(rig)
    rig.poll(fav=[*rig.fav_plays, fav_td()])
    assert rig.step().stage.stage == dr.PLAY  # the favourite's touchdown has begun
    rig.poll(other=[make_play(1, "rush", off="PHI"), rewritten])  # the review lands
    assert rig.step().stage.game.id == 1, "the favourite's stage is still on screen"
    names = shape(rig.run())
    # What was already on screen finishes, the rest of the chain follows, then the reversal.
    assert names == [
        (1, dr.PLAY),
        (1, dr.EVENT),
        (1, dr.DETAIL),
        (1, dr.PLAYTEXT),
        (2, dr.REVERSAL),
    ]


def test_a_reversal_clears_only_its_own_games_queued_stages():
    rig = Rig(hold=True).started()
    rewritten = reversed_in_other(rig)
    reversal = rig.director.reversals.on_poll(2, [rewritten])[0]
    director = rig.director

    def stage(game, name):
        return dr.Stage(name, 5.0, game, make_play(9, "rush", off="WSH"))

    director._active = None
    director._stages.extend(
        [
            stage(OTHER, dr.PLAYTEXT),
            stage(FAV, dr.EVENT),
            stage(OTHER, dr.DETAIL),
            stage(FAV, dr.DETAIL),
        ]
    )
    director._start_reversal(reversal, rig.clock())
    assert director._active.stage == dr.REVERSAL
    assert shape(director._stages) == [(1, dr.EVENT), (1, dr.DETAIL)]


def test_a_reversal_in_the_favourites_game_still_preempts_what_is_on_screen():
    rig = Rig(hold=True).started()
    rig.poll(fav=[*rig.fav_plays, fav_td()])
    rig.run()  # the touchdown is celebrated, so it is being watched
    rewritten = make_play(2, "penalty_after_run", score=(0, 0), off="NYG")
    rig.poll(fav=[make_play(1, "rush", off="WSH"), rewritten])
    assert rig.step().stage.stage == dr.REVERSAL


# -- 4: the favourite's countdown and final outrank a followed team's live game ------------------


def followed_live():
    """KC v LV, live, with KC followed (the favourite NYG is not playing yet)."""
    return game("LV", "KC", "in", 3, 0, game_id=9)


def test_the_favourites_countdown_keeps_the_screen_while_a_followed_team_is_live():
    register("fb_countdown", "fb_preview")
    utc = Utc(datetime(2026, 11, 22, 17, 5, tzinfo=UTC))  # 55 minutes before kickoff
    mode, _ = build_mode([nyg_game("pre"), followed_live()], follow=("KC",), utc=utc)
    scene = mode.scene()
    assert scene.kind == "fb_countdown" and scene.fb_game.id == 7


def test_the_favourites_final_keeps_the_screen_while_a_followed_team_is_live():
    register("fb_final", "fb_preview")
    mode, _ = build_mode([nyg_game("in"), followed_live()], follow=("KC",))
    mode.scene()  # the favourite's game is seen live
    mode._feed.games = [nyg_game("post"), followed_live()]
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_final"


def test_a_followed_live_game_still_takes_the_screen_when_the_favourite_has_nothing_up():
    register("fb_countdown", "fb_preview")
    mode, _ = build_mode(
        [nyg_game("pre"), followed_live()],
        follow=("KC",),
        utc=Utc(datetime(2026, 11, 22, 9, 0, tzinfo=UTC)),
    )  # kickoff is nine hours away: no countdown
    scene = mode.scene()
    assert scene.kind in ("fb_field", "fb_scores") and scene.fb_game.id == 9


def test_the_favourites_own_live_game_beats_the_countdown_of_nothing_else():
    register("fb_countdown", "fb_final", "fb_preview")
    mode, _ = build_mode([nyg_game("in"), followed_live()], follow=("KC",))
    assert mode.scene().fb_game.id == 7


def build_mode(games, follow=(), utc=None):
    clock = Clock(BASE)
    config = FootballConfig(favourite_team="NYG", also_follow=list(follow))
    feed = IdleFeed(games)
    mode = FootballMode(
        client_factory=lambda: feed,
        monotonic=clock,
        football=lambda: config,
        utc_now=utc or Utc(KICKOFF),
    )
    mode._feed = feed  # type: ignore[attr-defined]
    mode.worker.poll_once()
    return mode, clock


class PlaysFeed(IdleFeed):
    """The idle feed plus a play list for the followed game (id 9)."""

    def __init__(self, games):
        super().__init__(games)
        self.followed_plays: list = []

    def plays(self, game_id):
        return list(self.followed_plays) if game_id == 9 else []


def test_a_followed_teams_touchdown_breaks_in_over_the_favourites_countdown():
    register("fb_countdown", "fb_preview")
    utc = Utc(datetime(2026, 11, 22, 17, 5, tzinfo=UTC))
    clock = Clock(BASE)
    feed = PlaysFeed([nyg_game("pre"), followed_live()])
    feed.followed_plays = [make_play(1, "rush", off="LV")]
    config = FootballConfig(favourite_team="NYG", also_follow=["KC"])
    mode = FootballMode(
        client_factory=lambda: feed, monotonic=clock, football=lambda: config, utc_now=utc
    )
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_countdown"  # the baseline is taken: nothing on screen yet
    # KC (the home side) scores.
    feed.followed_plays = [
        make_play(1, "rush", off="LV"),
        make_play(2, "rush_td_pat", score=(0, 7), off="KC"),
    ]
    clock.t += 20
    mode.worker.poll_once()
    seen = set()
    for _ in range(80):
        clock.t += 0.25
        scene = mode.scene()
        seen.add((scene.kind, scene.fb_game.id if scene.fb_game else None))
    assert ("fb_event", 9) in seen, seen
    assert ("fb_play", 9) not in seen and ("fb_playtext", 9) not in seen, seen
    assert ("fb_countdown", 7) in seen, "and the countdown is back after the banner"


def test_a_red_zone_alert_shows_over_the_favourites_countdown_after_any_score_banner():
    from test_football_redzone import with_situation

    register("fb_countdown", "fb_preview")
    utc = Utc(datetime(2026, 11, 22, 17, 5, tzinfo=UTC))
    clock = Clock(BASE)
    out = with_situation(followed_live(), KC_ID, red=False)
    feed = PlaysFeed([nyg_game("pre"), out])
    feed.followed_plays = [make_play(1, "rush", off="LV")]
    config = FootballConfig(favourite_team="NYG", also_follow=["KC"])
    mode = FootballMode(
        client_factory=lambda: feed, monotonic=clock, football=lambda: config, utc_now=utc
    )
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_countdown"
    # KC drives into the red zone and scores on the same poll.
    feed.games = [nyg_game("pre"), with_situation(followed_live(), KC_ID, red=True)]
    feed.followed_plays = [
        make_play(1, "rush", off="LV"),
        make_play(2, "rush_td_pat", score=(0, 7), off="KC"),
    ]
    clock.t += 20
    mode.worker.poll_once()
    order = []
    for _ in range(120):
        clock.t += 0.25
        kind = mode.scene().kind
        if not order or order[-1] != kind:
            order.append(kind)
    assert order[:3] == ["fb_event", "fb_redzone", "fb_countdown"], order
