"""``fb_cointoss`` (#389): the coin flips, lands on the receiving team's logo, and says who
receives. The event is built the way the detector builds it (``CoinToss`` from the opening
kickoff); the director's own staging of it is tested in ``test_football_director.py``."""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_cointoss as fct
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import EVENT
from nhl_scoreboard.football.teams import team_color
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

KICKOFF = make_play(1, "kickoff_return", off="WSH", end="NYG", clock="15:00")
TOSS = ev.CoinToss(play=KICKOFF, game_id=1, team="NYG", scope=ev.Scope.FULL, kicker="WSH")
BLUE = team_color("NYG")


def scene(share, event=TOSS):
    return Scene(
        "fb_event",
        fb_game=make_game(),
        fb_play=event.play,
        fb_event=event,
        fb_stage=EVENT,
        fb_elapsed=share * 6.0,
        fb_seconds=6.0,
        animating=True,
    )


def logos(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    return LogoSet("nfl", "dark", libs)


def draw(share, width=128, event=TOSS, art=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = art
    r.draw_fb_play_scene(canvas, scene(share, event))
    assert not canvas.out_of_bounds
    return canvas


def colored(canvas, color):
    return [p for p, c in canvas.pixels.items() if c == color]


# -- the coin ------------------------------------------------------------------------


def test_it_is_registered_for_the_coin_toss_event_and_says_who_the_event_names():
    assert fp.EVENT_SCREENS[(ev.CoinToss, EVENT)] is fct.draw_cointoss
    assert TOSS.sound is False, "silent"
    assert (TOSS.team, TOSS.kicker) == ("NYG", "WSH")


def test_the_title_is_coin_toss_or_ot_coin_toss_in_overtime():
    assert fct.title(scene(0)) == "COIN TOSS"
    ot = dataclasses.replace(TOSS, play=dataclasses.replace(KICKOFF, period=5))
    assert fct.title(scene(0, ot)) == "OT COIN TOSS"


def test_the_coin_appears_growing_then_squeezes_to_a_line_and_back_many_times():
    sizes = [fct.coin_state(s / 100)[0] for s in range(0, 9)]
    assert sizes == sorted(sizes) and sizes[-1] > 7
    widths = [fct.coin_state(s / 200)[0] for s in range(17, 100)]
    assert max(widths) <= fct.RADIUS + 1e-9 and min(widths) < 1.0, "edge-on"
    edges = sum(1 for a, b in pairwise(widths) if a > 2 >= b)
    assert edges >= 3, "it turns over several times"


def test_the_spin_slows_down_so_the_last_turns_take_longer_than_the_first():
    steps = 2000
    widths = [fct.coin_state(fct.APPEAR_END + (fct.FLIP_END - fct.APPEAR_END) * i / steps)[0]
              for i in range(steps + 1)]  # fmt: skip
    edge_on, clusters = [i for i, w in enumerate(widths) if w < 1.0], []
    for i in edge_on:
        if clusters and i - clusters[-1][-1] <= 3:
            clusters[-1].append(i)
        else:
            clusters.append([i])
    mids = [sum(c) / len(c) for c in clusters]
    gaps = [b - a for a, b in pairwise(mids)]
    assert len(gaps) >= 3 and gaps[-1] > gaps[0]


def test_it_rises_and_falls_and_lands_face_up_at_full_size():
    rises = [fct.coin_state(s / 200)[1] for s in range(17, 100)]
    assert rises[0] < max(rises) > rises[-1] and max(rises) <= fct.RISE
    rx, rise, face = fct.coin_state(fct.FLIP_END)
    assert face == 1 and rx == pytest.approx(fct.RADIUS) and rise == pytest.approx(0, abs=1e-6)


def test_both_faces_are_drawn_during_the_flip():
    seen = set()
    for s in range(9, 50):
        c = draw(s / 100)
        seen |= {col for col in c.pixels.values() if col in (fct.FRONT, fct.BACK)}
    assert seen == {fct.FRONT, fct.BACK}


# -- the result ----------------------------------------------------------------------


def test_nothing_says_who_receives_until_it_has_landed():
    for share in (0.0, 0.05, 0.3, 0.5):
        assert not colored(draw(share), BLUE), share


def test_the_receive_line_fades_in_after_the_landing_in_the_teams_colour():
    at_landing = len(colored(draw(fct.LAND_END + 0.001), BLUE))
    full = colored(draw(0.8), BLUE)
    assert full and len(full) > at_landing
    assert draw(0.8).pixels == draw(1.0).pixels, "held once faded in"
    low = {c for c in draw(0.62).pixels.values() if c[2] > 0 and c != BLUE and c[2] > c[0]}
    assert low, "a dimmer shade while it fades in"


def test_the_coins_face_is_the_receiving_teams_logo_and_falls_back_to_its_abbreviation(tmp_path):
    with_art = draw(0.8, art=logos(tmp_path))
    plain = draw(0.8)
    centre = lambda c: [p for p in c.pixels if 52 <= p[0] <= 76 and p[1] < 24]  # noqa: E731
    assert len(centre(with_art)) > 100, "a 16px logo"
    assert 0 < len(centre(plain)) < len(centre(with_art)), "just the abbreviation"


def test_the_kicking_team_is_small_and_dim_at_the_far_edge_with_kick_on_a_wide_panel(tmp_path):
    c = draw(0.9, art=logos(tmp_path))
    dim_blue = [
        p
        for p in colored(c, tuple(round(v * fct.KICKER_DIM) for v in team_color("WSH")))
        if p[0] > 104
    ]
    assert dim_blue, "WSH's logo, dimmed, at the right edge"
    assert [p for p in c.pixels if p[0] > 104 and p[1] >= 28], "the KICK caption"


def test_a_64px_panel_has_only_the_logo_and_the_receive_line():
    c = draw(0.9, 64)
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    wide = draw(0.9)
    assert len(c.pixels) < len(wide.pixels)
    assert not [p for p in c.pixels if p[0] > 50 and p[1] >= 28 and c.pixels[p] != BLUE]


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(TOSS, team="AFC", kicker="NFC")
    for share in (0.0, 0.3, 0.6, 0.9, 1.0):
        assert draw(share, event=odd).pixels


@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [i / 20 for i in range(21)] + [2.0])
def test_every_moment_draws_inside_the_panel(width, share):
    assert draw(share, width).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,share,width",
    [("appear", 0.04, 128), ("flip", 0.18, 128), ("landed", 0.55, 128),
     ("fading", 0.63, 128), ("result", 0.9, 128), ("result_64", 0.9, 64)],
)  # fmt: skip
def test_snapshot(name, share, width, update_snapshots):
    check_snapshot(f"cointoss_{name}", draw(share, width).render(), update_snapshots)
