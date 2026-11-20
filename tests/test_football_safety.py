"""``fb_safety`` (#530): the favourite's safety, the touchdown's celebration with its own word.

Built the way the detector builds it (a real ``GenericScore`` from ``test_football_score``). It is
still the registered screen of a ``GenericScore``; ``draw_score`` hands the favourite's safety to
``football_touchdown.draw_safety``. A followed team's safety and every other generic score keep the
plain card.
"""

from __future__ import annotations

import dataclasses

import pytest

from scoreboard.display import football_field as ff
from scoreboard.display import football_plays as fp
from scoreboard.display import football_score as fsc
from scoreboard.display import football_touchdown as ftd
from scoreboard.football.teams import team_color
from test_football_scenes import check_snapshot
from test_football_score import QUICK, SAFETY, TWO, draw, generic

NYG = team_color("NYG")
AWAY = generic(
    "D.Jones sacked in End Zone for a SAFETY.", 2, off="NYG", favourite="WSH", home=False
)


def lit(canvas):
    return {p for p, c in canvas.pixels.items() if any(c)}


def word(age, width=128, event=SAFETY):
    """The letter pixels: bright team-coloured (or white-washed) ones away from the bottom name."""
    c = draw(event, age, width)
    zone = 14 if width >= 128 else 7
    return {
        p
        for p, col in c.pixels.items()
        if p[1] < 26 and zone <= p[0] < width - zone and col[2] > 150 and col != ff.BALL
    }


# -- who gets it ---------------------------------------------------------------------


def test_the_favourites_safety_goes_to_the_celebration_and_the_screen_is_still_draw_score():
    assert fp.EVENT_SCREENS[(type(SAFETY), "event")] is fsc.draw_score
    assert fsc.title(_scene(SAFETY)) == "SAFETY"
    assert draw(SAFETY, 0.3).pixels != draw(SAFETY, 2.5).pixels, "it moves"


def test_a_followed_teams_safety_and_other_generic_scores_keep_the_plain_card():
    quick = [draw(QUICK, t, seconds=4.0).pixels for t in (0.0, 1.0, 3.9)]
    assert quick[0] == quick[1] == quick[2], "static"
    assert draw(TWO, 1.0).pixels == draw(TWO, 3.0).pixels, "the favourite's two-point card is plain"


def _scene(event, age=1.0):
    from test_football_score import scene

    return scene(event, age)


# -- the timeline --------------------------------------------------------------------


def test_it_says_safety_one_letter_at_a_time_with_no_ball_and_no_touchdown():
    assert not word(0.9)
    first, later, all_in = word(1.3), word(1.75), word(3.2)
    assert first and max(x for x, _ in first) < 64, "S first"
    assert len(first) < len(later) < len(all_in)
    assert min(x for x, _ in all_in) >= 20 and max(x for x, _ in all_in) <= 108, (
        "centred, 6 letters"
    )
    for age in (0.5, 1.15, 1.5, 2.2, 3.2):
        assert not [p for p, c in draw(SAFETY, age).pixels.items() if c == ff.BALL], "no spike"


def test_it_opens_with_a_flash_and_pulsing_end_zones_then_strobes_like_the_touchdown():
    assert any(c[0] > 100 and c[1] > 100 and c[2] > 100 for c in draw(SAFETY, 0.02).pixels.values())
    zones = draw(SAFETY, 0.5)
    assert all(x < 14 or x >= 114 for x, _ in lit(zones)), "only the end zones are lit"
    frames = [len(lit(draw(SAFETY, 1.05 + 0.1 * i))) for i in range(6)]
    assert min(frames[0::2]) > 3000 and max(frames[1::2]) < 1500, "the whole panel strobes"


def test_the_team_name_fades_in_along_the_bottom_and_the_word_stays():
    assert not [p for p in draw(SAFETY, 3.2).pixels if p[1] >= 26]
    settled = draw(SAFETY, 5.0)
    assert [p for p, c in settled.pixels.items() if p[1] >= 26 and c[2] > 100]
    assert fsc.team_name("NYG") == "NY GIANTS"


def test_the_word_is_the_scoring_teams_colour_for_either_side():
    assert [p for p, c in draw(SAFETY, 5.0).pixels.items() if c == NYG]
    assert AWAY.team == "WSH"
    assert [p for p, c in draw(AWAY, 5.0).pixels.items() if c == team_color("WSH")]


def test_a_64px_panel_keeps_the_word_on_one_line():
    c = draw(SAFETY, 3.2, 64)
    rows = {y for (_, y), col in c.pixels.items() if col[2] > 150}
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    assert max(rows) - min(rows) < 14, "one line of normal-size letters"


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(SAFETY, team="AFC")
    for width in (128, 64):
        for age in (0.0, 0.5, 1.5, 2.5, 3.6, 5.0):
            assert draw(odd, age, width).pixels


@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("age", [0.0, 0.05, 0.12, 0.3, 1.0, 1.3, 2.0, 3.0, 3.6, 5.0, 6.0, 9.0])
def test_every_moment_draws_inside_the_panel(width, age):
    assert draw(SAFETY, age, width).pixels  # draw() also asserts nothing went off-panel


def test_touchdown_screen_is_unchanged_by_the_shared_code():
    assert ftd.WORD == "TOUCHDOWN" and ftd.SAFETY_WORD == "SAFETY"


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,age,width",
    [("flash", 0.06, 128), ("letters", 2.2, 128), ("strobe", 1.3, 128), ("settled", 4.2, 128),
     ("settled_64", 4.2, 64)],
)  # fmt: skip
def test_snapshot(name, age, width, update_snapshots):
    check_snapshot(f"safety_{name}", draw(SAFETY, age, width).render(), update_snapshots)
