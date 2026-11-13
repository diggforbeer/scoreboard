"""NFL play scenes end to end (#377): the feed worker's plays, the director and the renderer.

A fake ESPN client answers; everything else is the real thing: the worker thread's ``collect``
(driven by ``poll_once``), the app's scene selection, the generic renderer, the animation
flags. Panels are checked for pixels off the edge.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from RGBMatrixEmulator import graphics

from nhl_scoreboard.app import ANIMATION_FRAME_INTERVAL, FRAME_INTERVAL, Scene, ScoreboardApp
from nhl_scoreboard.config import FootballConfig, Settings
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.football.models import Participant
from nhl_scoreboard.football.people import RosterPlayer
from nhl_scoreboard.football.teams import TEAMS
from test_app import FakeOptions
from test_football_events import make_game, make_play
from test_football_scenes import SIT, _Nhl, game, renderer
from test_mirror import AsciiMatrix


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class Espn:
    """A fake ESPN client: a slate, a game's plays, the core feed and the rosters."""

    def __init__(self):
        self.slate = []
        self.site = []
        self.core = []
        self.rosters = {}
        self.calls = []
        self.last_error = ""
        self.fail_plays = False
        self.fail_core = False

    def scores(self, date=None):
        return list(self.slate)

    def plays(self, game_id):
        self.calls.append(("plays", game_id))
        return None if self.fail_plays else list(self.site)

    def core_plays(self, game_id):
        self.calls.append(("core", game_id))
        return None if self.fail_core else list(self.core)

    def roster(self, team_id):
        self.calls.append(("roster", team_id))
        return self.rosters.get(team_id)

    def close(self):
        pass


@pytest.fixture
def rig(tmp_path):
    espn = Espn()
    clock = Clock()
    settings = Settings()
    settings.status.enabled = False
    settings.scoreboard.sport = "nfl"
    settings.football = FootballConfig(favourite_team="NYG")
    app = ScoreboardApp(
        settings,
        client=_Nhl(),
        backend=Backend("ascii", AsciiMatrix, FakeOptions, graphics),
        clock=lambda: datetime(2026, 11, 15, 19, 0, tzinfo=UTC),
        monotonic=clock,
        ap_setup_state_path=tmp_path / "no-ap",
        hw_mapping_trial_path=tmp_path / "no-trial",
        nfl_client_factory=lambda: espn,
    )
    espn.slate = [game("WSH", "NYG", "in", 0, 0, situation=SIT, game_id=1)]
    return app, espn, clock


def land(app, espn, *plays):
    """A poll lands and the render loop sees it (the director takes its snapshot each frame)."""
    espn.site = list(plays)
    app._nfl.worker.poll_once()
    app._nfl.director.ingest(app._nfl.snapshot)


def kinds_until_rest(app, clock, limit=400):
    """``[(kind, stage)]`` each time the scene changes, until the board is back on the scores."""
    seen = []
    for _ in range(limit):
        scene = app.select_scene()
        if not seen or seen[-1] != (scene.kind, scene.fb_stage):
            seen.append((scene.kind, scene.fb_stage))
        if scene.kind == "fb_field":
            return seen
        app.draw_scene(scene)
        assert not app.matrix.shown.out_of_bounds, f"{scene.kind}/{scene.fb_stage} drew off-panel"
        clock.t += 0.25
    raise AssertionError("never came to rest")


def rush(n, off="WSH", **kw):
    return make_play(n, "rush", off=off, **kw)


def test_the_plays_of_a_watched_game_reach_the_snapshot_with_jersey_numbers(rig):
    app, espn, _ = rig
    henry = RosterPlayer(99, "D. Henry", "Derrick Henry", "Henry", "22", "RB")
    espn.rosters = {TEAMS["NYG"].espn_id: {99: henry}, TEAMS["WSH"].espn_id: {}}
    play = rush(1)
    espn.core = [dataclasses.replace(play, participants=(Participant("rusher", 99),))]
    land(app, espn, play)
    snap = app._nfl.snapshot
    assert [p.id for p in snap.plays[1]] == [play.id]
    assert snap.plays[1][0].participants[0].athlete_id == 99
    assert snap.players[1][99].jersey == "22"


def test_only_watched_games_have_their_plays_fetched(rig):
    app, espn, _ = rig
    espn.slate = [
        game("WSH", "NYG", "in", 0, 0, situation=SIT, game_id=1),
        game("DAL", "PHI", "in", 0, 0, game_id=2),
        game("KC", "BUF", "post", 20, 17, game_id=3, short="Final", name="STATUS_FINAL"),
    ]
    land(app, espn)
    assert {c[1] for c in espn.calls if c[0] in ("plays", "core")} == {1}


def test_with_nobody_in_play_the_first_live_game_is_watched(rig):
    app, espn, _ = rig
    app.settings.football.favourite_team = "SEA"
    espn.slate = [
        game("DAL", "PHI", "in", 0, 0, game_id=2),
        game("KC", "BUF", "in", 0, 0, game_id=3),
    ]
    land(app, espn)
    assert {c[1] for c in espn.calls if c[0] == "plays"} == {2}


def test_a_game_about_to_kick_off_is_watched_so_the_opening_kickoff_is_not_missed(rig):
    app, espn, _ = rig
    espn.slate = [
        game("WSH", "NYG", "pre", start="2026-11-15T19:10Z", name="STATUS_SCHEDULED", game_id=1)
    ]
    land(app, espn)
    assert ("plays", 1) in espn.calls
    espn.calls.clear()
    espn.slate = [
        game("WSH", "NYG", "pre", start="2026-11-15T21:00Z", name="STATUS_SCHEDULED", game_id=1)
    ]
    land(app, espn)
    assert espn.calls == [], "two hours out: nothing to fetch yet"


def test_the_core_feed_is_only_fetched_when_the_site_feed_shows_a_new_play(rig):
    app, espn, _ = rig
    land(app, espn, rush(1))
    land(app, espn, rush(1))
    land(app, espn, rush(1), rush(2))
    assert [c for c in espn.calls if c[0] == "core"] == [("core", 1), ("core", 1)]


def test_a_failed_play_fetch_keeps_the_last_plays_and_the_scores_still_publish(rig):
    app, espn, _ = rig
    play = rush(1)
    espn.core = [dataclasses.replace(play, participants=(Participant("rusher", 99),))]
    land(app, espn, play)
    espn.fail_plays = True
    espn.slate = [game("WSH", "NYG", "in", 7, 0, situation=SIT, game_id=1)]
    land(app, espn)
    snap = app._nfl.snapshot
    assert snap.games[0].away.score == 7 and [p.id for p in snap.plays[1]] == [play.id]


def test_a_failed_core_fetch_does_not_lose_numbers_already_known(rig):
    app, espn, _ = rig
    play = rush(1)
    espn.core = [dataclasses.replace(play, participants=(Participant("rusher", 99),))]
    land(app, espn, play)
    espn.fail_core = True
    land(app, espn, play, rush(2))
    plays = {p.id: p for p in app._nfl.snapshot.plays[1]}
    assert plays[play.id].participants, "the earlier numbers survive a failed core fetch"


def test_a_failure_in_collecting_plays_never_blanks_the_scores(rig):
    app, espn, _ = rig

    def boom(game_id):
        raise RuntimeError("feed exploded")

    espn.plays = boom
    app._nfl.worker.poll_once()
    assert app._nfl.snapshot.games is not None and app.select_scene().kind == "fb_field"


# -- a play through the real app ----------------------------------------------------------------


def test_an_ordinary_play_runs_animation_then_text_then_returns_to_the_field(rig):
    app, espn, clock = rig
    land(app, espn, rush(1))
    assert app.select_scene().kind == "fb_field", "the first poll is the baseline"
    land(app, espn, rush(1), rush(2))
    scene = app.select_scene()
    assert (scene.kind, scene.fb_stage, scene.animating) == ("fb_play", "play", True)
    assert scene.fb_game.id == 1 and scene.fb_play.id == rush(2).id
    app.draw_scene(scene)
    assert app.frame_interval() == ANIMATION_FRAME_INTERVAL
    assert kinds_until_rest(app, clock) == [
        ("fb_play", "play"),
        ("fb_playtext", "playtext"),
        ("fb_field", ""),
    ]
    app.draw_scene(app.select_scene())
    assert app.frame_interval() == FRAME_INTERVAL, "back to the slow loop at rest"


def test_a_favourite_touchdown_runs_the_whole_celebration(rig):
    app, espn, clock = rig
    land(app, espn, rush(1))
    land(app, espn, rush(1), make_play(2, "rush_td_pat", score=(0, 7), off="NYG"))
    assert kinds_until_rest(app, clock) == [
        ("fb_play", "play"), ("fb_event", "event"), ("fb_event", "detail"),
        ("fb_playtext", "playtext"), ("fb_field", ""),
    ]  # fmt: skip


def test_a_reversal_preempts_the_celebration(rig):
    app, espn, clock = rig
    land(app, espn, rush(1))
    land(app, espn, rush(1), make_play(2, "rush_td_pat", score=(0, 7), off="NYG"))
    while app.select_scene().fb_stage != "event":
        clock.t += 0.25
    reversed_td = make_play(
        2, "incomplete_target", score=(0, 0), off="NYG", text="Pass incomplete."
    )
    land(app, espn, rush(1), reversed_td)
    scene = app.select_scene()
    assert (scene.kind, scene.fb_stage) == ("fb_event", "reversal")
    app.draw_scene(scene)
    assert not app.matrix.shown.out_of_bounds
    assert "detail" not in [s for _, s in kinds_until_rest(app, clock)]


def test_the_scene_carries_the_latest_score_not_the_one_from_when_the_play_began(rig):
    app, espn, _ = rig
    land(app, espn, rush(1))
    land(app, espn, rush(1), rush(2))
    assert app.select_scene().fb_game.away.score == 0
    espn.slate = [game("WSH", "NYG", "in", 7, 0, situation=SIT, game_id=1)]
    land(app, espn, rush(1), rush(2))
    assert app.select_scene().fb_game.away.score == 7


def test_the_live_view_waits_for_an_animation_to_finish(rig):
    app, espn, _ = rig
    land(app, espn, rush(1))
    land(app, espn, rush(1), rush(2))
    app.mirror.requested = True
    app.draw_scene(app.select_scene())
    assert app.mirror.requested, "a frame mid-animation is held back, not frozen half-drawn"


def test_elapsed_time_is_not_part_of_the_scenes_identity():
    a = Scene("fb_play", fb_elapsed=0.5)
    b = Scene("fb_play", fb_elapsed=1.5)
    assert a == b and Scene("fb_play", fb_stage="detail") != a


# -- the renderer ------------------------------------------------------------------------------


def scene_for(kind, stage, play, event=None, elapsed=1.0, seconds=3.0):
    return Scene(
        kind, fb_game=make_game(), fb_play=play, fb_event=event, fb_stage=stage,
        fb_elapsed=elapsed, fb_seconds=seconds, animating=True,
    )  # fmt: skip


def draw_scene(scene, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene)
    return canvas


@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize(
    "label",
    ["rush", "pass_complete", "punt_return", "kickoff_return", "penalty_after_run", "sack",
     "timeout", "end_half", "fg_good", "interception_return", "incomplete_target"],
)  # fmt: skip
def test_every_play_kind_draws_something_inside_the_panel(label, width):
    canvas = draw_scene(scene_for("fb_play", "play", make_play(1, label, off="WSH")), width)
    assert canvas.pixels and not canvas.out_of_bounds


@pytest.mark.parametrize("width", [128, 64])
def test_the_play_text_fits_the_panel_even_when_it_is_long(width):
    long = make_play(1, "penalty_after_run", off="WSH")
    canvas = draw_scene(scene_for("fb_playtext", "playtext", long), width)
    assert canvas.pixels and not canvas.out_of_bounds


def test_the_generic_ball_moves_from_the_start_spot_to_the_end_spot():
    play = make_play(1, "rush", off="WSH")
    first = draw_scene(scene_for("fb_play", "play", play, elapsed=0.0))
    last = draw_scene(scene_for("fb_play", "play", play, elapsed=3.0))
    assert first.pixels != last.pixels


def test_an_unknown_play_kind_draws_the_generic_animation():
    odd = make_play(1, "rush", off="WSH", ptype="Something New")
    canvas = draw_scene(scene_for("fb_play", "play", odd))
    assert canvas.pixels and not canvas.out_of_bounds


def test_a_registered_screen_replaces_the_generic_one_and_only_for_its_kind():
    from nhl_scoreboard.display import football_plays as fp
    from nhl_scoreboard.football.models import PlayKind

    calls = []

    @fp.play_screen(PlayKind.RUSH)
    def draw_rush(r, canvas, scene):
        calls.append(scene.fb_play.kind)
        canvas.Clear()

    try:
        draw_scene(scene_for("fb_play", "play", make_play(1, "rush", off="WSH")))
        draw_scene(scene_for("fb_play", "play", make_play(2, "sack", off="WSH")))
    finally:
        del fp.PLAY_SCREENS[PlayKind.RUSH]
    assert calls == [PlayKind.RUSH]


@pytest.mark.parametrize("width", [128, 64])
def test_every_event_draws_a_card_inside_the_panel(width):
    from nhl_scoreboard.config import FootballConfig
    from nhl_scoreboard.football import events as ev
    from nhl_scoreboard.football.events import EventDetector
    from nhl_scoreboard.football.reversals import ReversalDetector

    cfg = FootballConfig(favourite_team="NYG")
    det, g = EventDetector(lambda: cfg), make_game()
    det.seed(g.id, None)
    cases = [
        make_play(1, "rush_td_pat", score=(0, 7), off="NYG"),
        make_play(2, "fg_good", score=(0, 10), off="NYG"),
        make_play(3, "fg_miss_left", score=(0, 10), off="WSH"),
        make_play(4, "interception_return", score=(0, 10), off="NYG", end="WSH"),
    ]
    events = [e for p in cases for e in det.on_plays(g, [p])]
    assert {type(e) for e in events} >= {ev.Touchdown, ev.FieldGoal, ev.Turnover}
    toss = ev.CoinToss(play=cases[0], game_id=1, team="NYG", scope=ev.Scope.FULL, kicker="WSH")
    changed = make_play(1, "incomplete_target", score=(0, 0), off="NYG", text="Pass incomplete.")
    rd = ReversalDetector(det)
    rd.remember_all(events[:1])
    reversals = rd.on_poll(g, [changed])
    assert reversals
    for event in [*events, toss, *reversals]:
        for stage in ("event", "detail", "reversal"):
            canvas = draw_scene(scene_for("fb_event", stage, event.play, event), width)
            assert canvas.pixels and not canvas.out_of_bounds, (type(event).__name__, stage)
