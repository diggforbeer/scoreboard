"""A live game, played out through the real app: kickoff, a return, two plays, a touchdown.

WSH kicks off to NYG (the favourite). NYG runs, passes, then scores a rushing touchdown with the
extra point. A fake ESPN client answers each poll the way the real feed would (the slate's score
and the growing play list); everything else is the real thing: the worker's collect, the
director's queue and detectors, the app's scene selection and the renderer. Each frame is drawn,
so a layout error anywhere in the game shows up as a pixel off the panel.
"""

from __future__ import annotations

from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import PLAY, PLAYTEXT
from test_football_events import make_play
from test_football_play_scenes import land, rig  # noqa: F401  (the real-app fixture)
from test_football_scenes import SIT, game

TICK = 0.25


def play_out(app, clock, limit=800):
    """Draw frames until the board rests on the field again.

    Returns ``[(kind, stage, seconds, scene)]``: each scene change with how long it stayed up
    (in the fake clock's seconds) and the last scene of that stretch.
    """
    shown: list[list] = []
    for _ in range(limit):
        scene = app.select_scene()
        key = (
            scene.kind,
            scene.fb_stage,
            scene.fb_event.__class__.__name__ if scene.fb_event else "",
        )
        if scene.kind == "fb_field":
            return [(k, s, secs, sc) for (k, s, _), secs, sc in shown]
        if not shown or shown[-1][0] != key:
            shown.append([key, 0.0, scene])
        shown[-1][1] += TICK
        shown[-1][2] = scene
        app.draw_scene(scene)
        assert not app.matrix.shown.out_of_bounds, f"{key} drew off the panel"
        assert app.matrix.shown.pixels, f"{key} drew nothing"
        clock.t += TICK
    raise AssertionError("the board never came back to the field")


def set_score(espn, away, home, yard=62):
    sit = dict(SIT, yardLine=yard)
    espn.slate = [game("WSH", "NYG", "in", away, home, situation=sit, game_id=1)]


def test_a_kickoff_a_return_two_plays_and_a_touchdown(rig):  # noqa: F811
    app, espn, clock = rig
    set_score(espn, 0, 0)

    # The game is on and nothing has been played: the board rests on the field, nothing animates.
    land(app, espn)
    assert app.select_scene().kind == "fb_field"
    assert play_out(app, clock) == []

    # -- WSH kicks off, NYG returns it: the coin toss first, then the kickoff, then its text.
    kickoff = make_play(1, "kickoff_return", off="WSH", end="NYG", clock="15:00")
    land(app, espn, kickoff)
    first = play_out(app, clock)
    assert [(k, s) for k, s, *_ in first] == [
        ("fb_event", "event"),
        ("fb_play", PLAY),
        ("fb_playtext", PLAYTEXT),
    ]
    toss = first[0][3].fb_event
    assert isinstance(toss, ev.CoinToss) and toss.team == "NYG"
    assert first[0][2] >= 6.0, "the coin toss holds its six seconds"
    assert first[1][3].fb_play.id == kickoff.id
    assert "kicks" in first[2][3].fb_play.text

    # -- NYG runs, then passes: each is its animation, then its text, then rest. No event cards.
    run = make_play(2, "rush", off="NYG", down=1, clock="14:40")
    land(app, espn, kickoff, run)
    second = play_out(app, clock)
    assert [(k, s) for k, s, *_ in second] == [("fb_play", PLAY), ("fb_playtext", PLAYTEXT)]
    assert second[0][3].fb_play.id == run.id

    pas = make_play(3, "pass_complete", off="NYG", down=2, clock="14:05")
    land(app, espn, kickoff, run, pas)
    third = play_out(app, clock)
    assert [(k, s) for k, s, *_ in third] == [("fb_play", PLAY), ("fb_playtext", PLAYTEXT)]
    assert third[0][3].fb_play.id == pas.id
    assert second[0][3].fb_play.id != third[0][3].fb_play.id

    # -- NYG scores: the animation, the favourite's celebration, its detail card, then the text.
    touchdown = make_play(4, "rush_td_pat", score=(0, 7), off="NYG", down=1, clock="13:30")
    set_score(espn, 0, 7, yard=75)
    land(app, espn, kickoff, run, pas, touchdown)
    scoring = play_out(app, clock)
    assert [(k, s) for k, s, *_ in scoring] == [
        ("fb_play", PLAY),
        ("fb_event", "event"),
        ("fb_event", "detail"),
        ("fb_playtext", PLAYTEXT),
    ]
    celebration, detail = scoring[1][3].fb_event, scoring[2][3].fb_event
    assert isinstance(celebration, ev.Touchdown) and celebration.scope == ev.Scope.FULL
    assert celebration is detail
    assert celebration.team == "NYG"
    assert scoring[1][3].fb_game.home.score == 7, "the celebration carries the new score"

    # Every stage held its length (to the frame), and the order never repeated anything.
    for kind, stage, seconds, scene in scoring:
        assert abs(seconds - scene.fb_seconds) <= TICK * 2, (kind, stage, seconds)

    # -- Back at rest on the field with the new score; nothing replays.
    rest = app.select_scene()
    assert rest.kind == "fb_field" and rest.fb_game.home.score == 7 and rest.fb_game.away.score == 0
    for _ in range(40):
        clock.t += TICK
        assert app.select_scene().kind == "fb_field"
    land(app, espn, kickoff, run, pas, touchdown)  # the same poll again: still nothing new
    assert app.select_scene().kind == "fb_field"
