"""Shootout tension and polish (#259): elimination state, labels, animation, goal screen."""

from __future__ import annotations

import dataclasses

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display.renderer import ACCENT, FINAL, INTERMISSION, LIVE, LOSS, WHITE
from nhl_scoreboard.nhl.models import Shootout, ShootoutAttempt
from test_flow import FAV, PUCK_DROP, Clock, FlowClient, game, make_app, score, tick
from test_flow import fake_backend as fake_backend  # fixture, re-exported for this module
from test_render import H, W, canvas, check_snapshot, make_renderer, show
from test_shootout import rounds, so_game
from test_shootout import so_app as so_app  # fixture, re-exported for this module

# -- Shootout.state(): elimination tension ---------------------------------------------


def state_of(data: Shootout) -> tuple[str, str | None]:
    s = data.state("NSH", "OTT")
    return s.kind, s.team


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ([], ("open", None)),
        (["g-"], ("open", None)),
        (["gx", "xx"], ("open", None)),
        (["xg", "gx"], ("open", None)),
        # Away leads 1-0 after two rounds, then misses nothing: home shoots next.
        (["gx", "xx", "x-"], ("must_score", "OTT")),
        # Home leads 1-0 after two rounds; away shoots next.
        (["xg", "xx"], ("must_score", "NSH")),
        # 2-0 after two rounds: home's one remaining shot can't catch up.
        (["gx", "gx"], ("decided", "NSH")),
        (["gx", "xx", "g-"], ("decided", "NSH")),
        (["gx", "xx", "gx"], ("decided", "NSH")),
        (["xg", "xg", "xg"], ("decided", "OTT")),
        # Level after three rounds.
        (["gx", "xg", "gg"], ("sudden_death", None)),
        (["xx", "xx", "xx"], ("sudden_death", None)),
        # Sudden death: only one team has shot the round; level round; decided round.
        (["gx", "xg", "gg", "g-"], ("sudden_death", None)),
        (["gx", "xg", "gg", "xx"], ("sudden_death", None)),
        (["gx", "xg", "gg", "xx", "gg", "x-"], ("sudden_death", None)),
        (["gx", "xg", "gg", "xg"], ("decided", "OTT")),
        (["gx", "xg", "gg", "xx", "gx"], ("decided", "NSH")),
    ],
)
def test_state_table(spec, expected):
    assert state_of(rounds(spec)) == expected


def attempts_of(*shots: tuple[str, bool], first_sequence: int = 1, live=None) -> Shootout:
    attempts = tuple(
        ShootoutAttempt(first_sequence + i, team, scored) for i, (team, scored) in enumerate(shots)
    )
    away = sum(1 for team, scored in shots if scored and team == "NSH")
    home = sum(1 for team, scored in shots if scored and team == "OTT")
    return Shootout(attempts, *(live or (away, home)))


def with_sequences(data: Shootout, sequences: list[int]) -> Shootout:
    attempts = tuple(
        dataclasses.replace(a, sequence=s) for a, s in zip(data.attempts, sequences, strict=True)
    )
    return dataclasses.replace(data, attempts=attempts)


UNKNOWN_CASES = {
    "live score ahead of the events": attempts_of(("NSH", True), ("OTT", False), live=(2, 0)),
    "live score behind the events": attempts_of(("NSH", True), ("OTT", False), live=(0, 0)),
    "a shot missing from the feed": with_sequences(
        attempts_of(("NSH", True), ("OTT", False)), [1, 3]
    ),
    "teams not alternating": attempts_of(("NSH", True), ("NSH", False)),
    "a team that is neither side": attempts_of(("NSH", True), ("TBL", False)),
    "shooting on after it was decided": rounds(["gx", "gx", "gx", "g-"]),
}


@pytest.mark.parametrize("name", UNKNOWN_CASES)
def test_incomplete_or_inconsistent_data_is_unknown(name):
    assert UNKNOWN_CASES[name].state("NSH", "OTT").kind == "unknown"


# -- labels and the outline ---------------------------------------------------------------


def so_canvas(spec, *, state="LIVE", now=0.0, ages=None, data=None):
    c = canvas()
    if data is None:
        data = rounds(spec) if spec else None
    make_renderer().draw_shootout(c, so_game(state=state, shootout=data), now, ages)
    assert not c.out_of_bounds
    return c


def label_band(c) -> list[str]:
    return c.render().splitlines()[1 + 26 : -1]


def test_labels_follow_the_state():
    plain = so_canvas(["gx", "xg"])
    must = so_canvas(["gx", "gg", "x-"])
    sudden = so_canvas(["gx", "xg", "gg"])
    final = so_canvas(["xg", "gx", "xg"], state="OFF")
    assert len({tuple(label_band(c)) for c in (plain, must, sudden, final)}) == 4
    band = (0, 26, W - 1, H - 1)
    assert plain.colors(*band) == {LIVE}
    assert must.colors(*band) == {INTERMISSION}
    assert sudden.colors(*band) == {INTERMISSION}
    assert final.colors(*band) == {FINAL}


def test_unsure_data_falls_back_to_the_plain_label_and_no_outline():
    # Would be must_score(OTT) were liveScore not a poll ahead of the events.
    lagging = dataclasses.replace(rounds(["gx", "xx", "x-"]), away_goals=2)
    lagging_canvas = so_canvas(None, data=lagging)
    assert label_band(lagging_canvas) == label_band(so_canvas(["gx", "xg"]))
    assert lagging_canvas.colors(0, 26, W - 1, H - 1) == {LIVE}
    assert INTERMISSION not in lagging_canvas.colors(0, 0, W - 1, 25)


def test_must_score_outlines_only_the_next_cell_of_that_team_and_breathes():
    spec = ["gx", "gg", "x-"]  # home (OTT) shoots next and must score
    dim, bright = so_canvas(spec, now=2.25), so_canvas(spec, now=0.75)
    next_cell = (34 + 22 - 1, 15, 34 + 22 + 9, 25)  # OTT's third cell, ring included
    assert dim.colors(*next_cell) != bright.colors(*next_cell)
    for c in (dim, bright):
        assert any(rgb[0] > rgb[1] > rgb[2] == 0 for rgb in c.colors(*next_cell))
        assert INTERMISSION not in c.colors(0, 0, W - 1, 14)  # nothing on the away row
    assert {(rgb[0], rgb[1], rgb[2]) for rgb in bright.colors(*next_cell)} >= {INTERMISSION}
    quiet = so_canvas(["gx", "xg"])
    assert not any(rgb[2] == 0 and rgb[0] > rgb[1] > 0 for rgb in quiet.colors(*next_cell))


def test_sudden_death_does_not_outline_a_cell():
    c = so_canvas(["gx", "xg", "gg", "g-"])
    assert INTERMISSION not in c.colors(0, 0, W - 1, 25)


def test_winner_highlight_survives_the_final_label():
    c = so_canvas(["xg", "gx", "xg"], state="OFF")
    assert ACCENT in c.colors(24, 14, 28, 26)
    assert ACCENT not in c.colors(24, 2, 28, 12)
    assert c.colors(0, 26, W - 1, H - 1) == {FINAL}


# -- animation -------------------------------------------------------------------------------

AWAY_FIRST_CELL = (33, 3, 43, 13)
HOME_SECOND_CELL = (44, 15, 54, 25)


def test_newest_goal_grows_flashes_then_settles():
    static = so_canvas(["gx"])
    start, mid, flash, done = (so_canvas(["gx"], ages={1: age}) for age in (0.0, 0.45, 1.0, 1.5))
    size = [len(c.lit(*AWAY_FIRST_CELL)) for c in (start, mid, static)]
    assert size[0] < size[1] < size[2]
    assert WHITE in flash.colors(*AWAY_FIRST_CELL)
    assert WHITE not in static.colors(*AWAY_FIRST_CELL)
    assert done.render() == static.render()


def test_newest_miss_is_drawn_in_two_strokes():
    spec = ["gx", "xx"]

    def red(c) -> int:
        return sum(1 for rgb in c.lit(*HOME_SECOND_CELL).values() if rgb == LOSS)

    first, both = so_canvas(spec, ages={4: 0.3}), so_canvas(spec, ages={4: 0.9})
    static = so_canvas(spec)
    assert 0 < red(first) < red(both) < red(static)
    assert so_canvas(spec, ages={4: 1.5}).render() == static.render()


def test_only_the_aged_attempt_animates():
    static = so_canvas(["gx", "xg"]).pixels
    animated = so_canvas(["gx", "xg"], ages={4: 0.2}).pixels
    # The tally (x < 33) blinks too, by design; this is about the grid.
    changed = {
        p
        for p in static.keys() | animated.keys()
        if static.get(p) != animated.get(p) and p[0] >= 33
    }
    assert changed
    x0, y0, x1, y1 = 33 + 11, 14, 33 + 22, 26  # home's second cell, ring included
    assert all(x0 <= x <= x1 and y0 <= y <= y1 for x, y in changed)


def test_tally_blinks_while_that_teams_goal_is_new():
    tally = (24, 2, 29, 12)
    assert so_canvas(["gx"]).colors(*tally) == {WHITE}
    assert so_canvas(["gx"], ages={1: 0.1}).colors(*tally) == {ACCENT}
    assert so_canvas(["gx"], ages={1: 0.3}).colors(*tally) == {WHITE}
    assert so_canvas(["gx"], ages={1: 1.2}).colors(*tally) == {WHITE}


@pytest.mark.parametrize("age", [0.0, 0.2, 0.5, 0.9, 1.2, 1.45, 3.0])
@pytest.mark.parametrize(
    "spec", [["gx"], ["xg", "gx", "xg", "gg", "xx", "gx", "g-"], ["gx", "gg", "x-"]]
)
def test_nothing_is_off_panel_at_any_age(spec, age):
    last = len(rounds(spec).attempts)
    so_canvas(spec, ages={last: age, 1: age}, now=age)


@pytest.mark.parametrize(
    ("name", "spec", "ages"),
    [
        ("shootout_anim_goal_start", ["gx", "xg"], {4: 0.45}),
        ("shootout_anim_goal_flash", ["gx", "xg"], {4: 1.0}),
        ("shootout_anim_miss", ["gx", "xg", "x-"], {5: 0.9}),
    ],
)
def test_animation_snapshots(name, spec, ages, update_snapshots):
    c = so_canvas(spec, ages=ages)
    check_snapshot(name, show(name, c), update_snapshots)


# -- app: ages -------------------------------------------------------------------------------


def test_new_attempts_animate_but_a_restart_mid_shootout_does_not_replay(so_app):
    app, clock, client = so_app
    client.shootouts[1] = rounds(["gx", "xg"])
    app.refresh_shootouts()
    assert app.shootout_ages(1) == {}, "the first sighting is the baseline"

    clock.advance(seconds=5)
    client.shootouts[1] = rounds(["gx", "xg", "g-"])
    app.refresh_shootouts()
    clock.advance(seconds=1)
    assert app.shootout_ages(1) == pytest.approx({5: 1.0})
    clock.advance(seconds=1)
    assert app.shootout_ages(1) == {}, "window over: back to the static look"


def test_frame_loop_speeds_up_only_while_a_cell_is_animating(so_app):
    app, clock, client = so_app
    client.shootouts[1] = rounds(["gx"])
    app.refresh_shootouts()
    clock.advance(seconds=5)
    client.shootouts[1] = rounds(["gx", "x-"])
    app.refresh_shootouts()
    app.draw_scene(app.select_scene())
    assert app.frame_interval() < 0.5
    clock.advance(seconds=3)
    app.draw_scene(app.select_scene())
    assert app.frame_interval() == 0.5


def test_ages_are_pruned_when_the_game_leaves_the_slate(so_app):
    app, _, client = so_app
    client.shootouts[1] = rounds(["gx"])
    app.refresh_shootouts()
    assert 1 in app._shootout_seen
    app.games = []
    app.refresh_shootouts()
    assert app._shootout_seen == {}


# -- app: the goal screen stays off the shootout -----------------------------------------------


@pytest.fixture
def so_win(fake_backend):
    """The favourite (home) in a 2-2 shootout, seen once so the score has a baseline."""
    clock = Clock(PUCK_DROP)
    client = FlowClient()
    live = dataclasses.replace(so_game("TBL", FAV), id=1)
    client.today = [live]
    app = make_app(fake_backend, clock, client)
    app.refresh()
    return app, clock, client, live


def settle(app, clock, client, live, *, home=None, away=None, state="LIVE") -> None:
    client.today = [dataclasses.replace(score(live, home=home, away=away), state=state)]
    tick(app, clock, seconds=10)


def test_favourite_shootout_win_plays_the_horn_but_keeps_the_grid(so_win):
    app, clock, client, live = so_win
    settle(app, clock, client, live, home=3)
    assert app.horn.calls == [FAV]
    assert app.select_scene().kind == "game"


def test_the_grid_stays_when_the_game_is_already_final(so_win):
    app, clock, client, live = so_win
    settle(app, clock, client, live, home=3, state="OFF")
    assert app.horn.calls == [FAV]
    assert app.select_scene().kind == "game"


def test_goal_detail_is_suppressed_in_a_shootout(so_win):
    app, _, _, live = so_win
    app._goal_detail = (live.id, app.monotonic(), None)
    assert app._apply_goal_override(Scene("game", live)).kind == "game"


def test_muted_horn_stays_silent_but_the_grid_stays_too(so_win):
    app, clock, client, live = so_win
    app._horn_muted_until = app.monotonic() + 600
    settle(app, clock, client, live, home=3)
    assert app.horn.calls == []
    assert app.select_scene().kind == "game"


def test_favourite_shootout_loss_does_nothing(so_win):
    app, clock, client, live = so_win
    settle(app, clock, client, live, away=3)
    assert app.horn.calls == []
    assert app.select_scene().kind == "game"


def test_a_non_favourite_shootout_never_celebrates(fake_backend):
    clock = Clock(PUCK_DROP)
    client = FlowClient()
    other = dataclasses.replace(so_game("SEA", "CGY"), id=3)
    client.today = [other]
    app = make_app(fake_backend, clock, client)
    app.refresh()
    client.today = [score(other, home=3)]
    tick(app, clock, seconds=10)
    assert app.horn.calls == []
    assert app.last_goal is None


@pytest.mark.parametrize("period_type", ["REG", "OT"])
def test_regulation_and_overtime_goals_still_show_the_goal_scene(fake_backend, period_type):
    clock = Clock(PUCK_DROP)
    client = FlowClient()
    live = dataclasses.replace(
        game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=1), period_type=period_type
    )
    client.today = [live]
    app = make_app(fake_backend, clock, client)
    app.refresh()
    client.today = [score(live, home=1)]
    tick(app, clock, seconds=10)
    assert app.horn.calls == [FAV]
    assert app.select_scene().kind == "goal"
