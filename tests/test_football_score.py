"""``fb_score`` (#395): the generic score screen for a safety, a two-point conversion, or any
scoring play with a type nothing else recognises. Events come from the real ``EventDetector``
(an unrecognised scoring type is how a ``GenericScore`` is made)."""

from __future__ import annotations

import dataclasses

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_score as fsc
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import EVENT
from nhl_scoreboard.football.teams import team_color
from test_football_director import started
from test_football_events import detector, make_game, make_play
from test_football_scenes import check_snapshot, renderer

NYG = team_color("NYG")
SAFETY_TEXT = "(Shotgun) D.Jones sacked in End Zone for a SAFETY. The ball is free kicked to WSH."
TWO_TEXT = "TWO-POINT CONVERSION ATTEMPT. D.Jones pass to K.Pitts is complete. ATTEMPT SUCCEEDS."


def generic(text, points=2, off="WSH", favourite="NYG", follow=(), home=True):
    det, game, _ = detector(favourite, follow)
    score = (0, points) if home else (points, 0)
    play = make_play(
        1,
        "rush",
        off=off,
        end="NYG",
        score=score,
        ptype="Odd Score",
        text=text,
        flags={"scoringPlay": True},
    )
    (event,) = [e for e in det.on_plays(game, [play]) if isinstance(e, ev.GenericScore)]
    return event


SAFETY = generic(SAFETY_TEXT)
TWO = generic(TWO_TEXT)
ONE = generic("Something worth one point.", 1)
QUICK = generic(SAFETY_TEXT, favourite="DAL", follow=["NYG"])


def scene(event, age=1.0, seconds=6.0):
    return Scene("fb_event", fb_game=make_game(), fb_play=event.play, fb_event=event,
                 fb_stage=EVENT, fb_elapsed=age, fb_seconds=seconds, animating=True)  # fmt: skip


def draw(event, age=1.0, width=128, seconds=6.0):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(event, age, seconds))
    assert not canvas.out_of_bounds
    return canvas


# -- the words -----------------------------------------------------------------------


def test_it_is_registered_for_generic_scores_and_the_detector_makes_them_for_odd_types():
    assert fp.EVENT_SCREENS[(ev.GenericScore, EVENT)] is fsc.draw_score
    assert SAFETY.scope == ev.Scope.FULL and QUICK.scope == ev.Scope.QUICK
    assert (SAFETY.points, SAFETY.team) == (2, "NYG")


def test_the_headline_is_safety_two_point_conversion_or_the_points():
    assert fsc.title(scene(SAFETY)) == "SAFETY"
    assert fsc.title(scene(TWO)) == "2-POINT CONVERSION"
    assert fsc.title(scene(ONE)) == "1 POINT"
    assert fsc.title(scene(generic("A return of some new kind.", 6))) == "6 POINTS"


def test_the_score_has_the_scoring_team_first_for_either_side():
    assert fsc.score_line(scene(SAFETY)) == "NYG 2  WSH 0"
    away = generic("Odd score.", 2, off="WSH", favourite="WSH", home=False)
    assert away.team == "WSH" and fsc.score_line(scene(away)) == "WSH 2  NYG 0"


def test_the_first_line_is_the_first_sentence_without_the_formation_tag():
    assert fsc.first_line(scene(SAFETY)) == "D.JONES SACKED IN END ZONE FOR A SAFETY"
    assert fsc.first_line(scene(TWO)) == "TWO-POINT CONVERSION ATTEMPT"
    bare = generic("No sentence stop here", 2)
    assert fsc.first_line(scene(bare)) == "NO SENTENCE STOP HERE"
    assert fsc.first_line(scene(generic("(Shotgun) (No Huddle) Odd.", 2))) == "ODD"


def test_the_team_name_is_the_short_name_or_the_code():
    assert fsc.team_name("NYG") == "NY GIANTS" and fsc.team_name("AFC") == "AFC"


# -- the screen ----------------------------------------------------------------------


def test_it_shows_the_points_the_team_the_score_and_the_play_text_in_that_order():
    c = draw(SAFETY, 1.0)
    rows = {}
    for (_, y), col in c.pixels.items():
        rows.setdefault(y, set()).add(col)
    headline = [y for y, cols in rows.items() if NYG in cols and y < 14]
    name = [y for y, cols in rows.items() if NYG in cols and 14 <= y < 22]
    score = [y for y, cols in rows.items() if fp.WHITE in cols and 20 <= y < 27]
    text = [y for y, cols in rows.items() if fp.DIM in cols and y >= 27]
    assert headline and name and score and text
    assert max(headline) < min(name) <= max(name) < min(text)


def test_it_is_plainer_than_the_touchdown_no_strobe_and_nothing_dropping_in():
    sizes = {len(draw(SAFETY, age).pixels) for age in (0.5, 1.0, 2.0, 4.0)}
    assert len(sizes) == 1 or max(sizes) < 1500, "static after the opening"
    assert max(len(draw(SAFETY, age).pixels) for age in (0.3, 0.5, 0.7, 0.9)) < 1500


def test_the_favourites_opens_with_a_short_white_flash_and_a_followed_teams_is_static():
    assert any(c[0] > 80 and c[1] > 80 and c[2] > 80 and c != fp.WHITE
               for c in draw(SAFETY, 0.02).pixels.values())  # fmt: skip
    assert not any(sum(c) > 700 and c[0] < 255 for c in draw(SAFETY, 0.5).pixels.values())
    quick = [draw(QUICK, age, seconds=4.0).pixels for age in (0.0, 0.5, 2.0)]
    assert quick[0] == quick[1] == quick[2]


def test_the_headline_fades_in_for_the_favourite():
    assert draw(SAFETY, 0.05).pixels != draw(SAFETY, 1.0).pixels
    assert draw(SAFETY, 1.0).pixels == draw(SAFETY, 3.0).pixels


def test_a_64px_panel_has_smaller_type_and_no_team_name_line():
    c = draw(SAFETY, 1.0, 64)
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    assert len(c.pixels) < len(draw(SAFETY, 1.0).pixels)


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(SAFETY, team="AFC")
    for width in (128, 64):
        assert draw(odd, 1.0, width).pixels


@pytest.mark.parametrize("event", [SAFETY, TWO, ONE, QUICK], ids=["safety", "two", "one", "quick"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("age", [0.0, 0.05, 0.12, 0.3, 1.0, 3.0, 6.0, 9.0])
def test_every_moment_draws_inside_the_panel(event, width, age):
    assert draw(event, age, width).pixels


# -- the director --------------------------------------------------------------------


def staged(favourite, follow=()):
    rig = started(make_play(1, "rush", off="NYG"), favourite=favourite, follow=follow)
    odd = make_play(
        2,
        "rush",
        off="WSH",
        end="NYG",
        score=(0, 2),
        ptype="Odd Score",
        text=SAFETY_TEXT,
        flags={"scoringPlay": True},
    )
    rig.poll(make_play(1, "rush", off="NYG"), odd)
    return rig.run()


def test_the_favourites_generic_score_is_one_screen_with_no_detail_after_it():
    stages = staged("NYG")
    assert [s.stage for s in stages] == ["play", "event", "playtext"]
    assert stages[1].seconds == 6.0 and isinstance(stages[1].event, ev.GenericScore)


def test_a_followed_teams_is_the_quick_four_seconds():
    stages = staged("DAL", ["NYG"])
    assert [s.stage for s in stages] == ["play", "event", "playtext"] and stages[1].seconds == 4.0


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,event,age,width,seconds",
    [("safety", SAFETY, 1.0, 128, 6.0), ("two_point", TWO, 1.0, 128, 6.0),
     ("quick", QUICK, 1.0, 128, 4.0), ("safety_64", SAFETY, 1.0, 64, 6.0)],
)  # fmt: skip
def test_snapshot(name, event, age, width, seconds, update_snapshots):
    check_snapshot(f"fb_score_{name}", draw(event, age, width, seconds).render(), update_snapshots)
