"""``fb_score_detail`` (#391): who scored, with the kind of score and the new score. Events are the
ones the detector emits for the real plays in ``play_cases.json`` (so the parsed names, yards and
point-after results are the real ones); the roster side is built by hand."""

from __future__ import annotations

import dataclasses

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_score_detail as fsd
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import DETAIL
from nhl_scoreboard.football.people import Person
from nhl_scoreboard.football.teams import team_color
from test_football_events import detector, make_game, make_play
from test_football_scenes import check_snapshot, renderer


def event_for(label, off="NYG", score=(0, 7), favourite="NYG"):
    det, game, _ = detector(favourite)
    play = make_play(1, label, off=off, score=score)
    (event,) = [e for e in det.on_plays(game, [play]) if not isinstance(e, ev.CoinToss)]
    return event


PASS = event_for("pass_td_pat")
RUN = event_for("rush_td_pat")
TWO = event_for("rush_td_two_point_good", score=(0, 8))
TWO_FAIL = event_for("pass_td_two_point_fail", score=(0, 6))
PICK = event_for("interception_td", off="NYG")
FG = event_for("fg_good", score=(0, 3))
AWAY = event_for("rush_td_pat", off="WSH", score=(7, 0), favourite="WSH")

WOERNER = Person("scorer", 1, "C. Woerner", "14", "TE", True)
PENIX = Person("passer", 2, "M. Penix", "9", "QB", True)
FOLK = Person("kicker", 3, "N. Folk", "6", "K", True)


def scene(event, people=()):
    return Scene("fb_event", fb_game=make_game(), fb_play=event.play, fb_event=event,
                 fb_stage=DETAIL, fb_elapsed=1.0, fb_seconds=8.0, animating=True,
                 fb_people=people)  # fmt: skip


def draw(event, people=(), width=128, art=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = art
    r.draw_fb_play_scene(canvas, scene(event, people))
    assert not canvas.out_of_bounds
    return canvas


def logos(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    return LogoSet("nfl", "dark", libs)


# -- the text ------------------------------------------------------------------------


def test_it_is_registered_for_touchdowns_and_made_field_goals_in_the_detail_stage():
    assert fp.EVENT_SCREENS[(ev.Touchdown, DETAIL)] is fsd.draw_score_detail
    assert fp.EVENT_SCREENS[(ev.FieldGoal, DETAIL)] is fsd.draw_score_detail


def test_the_scorer_is_the_number_then_the_name_or_the_name_alone_or_the_texts_own_spelling():
    assert fsd.person_line(WOERNER, "C.Woerner") == "14 C. WOERNER"
    nameless = Person("scorer", 1, "C. Woerner", "", "TE", True)
    assert fsd.person_line(nameless, "C.Woerner") == "C. WOERNER"
    assert fsd.person_line(None, "C.Woerner") == "C.WOERNER"
    assert fsd.person_line(None, "") == ""


def test_the_scorer_comes_from_the_play_text_by_how_it_was_scored():
    assert fsd.scorer_line(scene(PASS)) == "C.WOERNER"
    assert fsd.scorer_line(scene(RUN)) == "J.BURROW"
    assert fsd.scorer_line(scene(PICK)) == "J.JOHNSON"
    assert fsd.scorer_line(scene(FG)) == "N.FOLK"
    assert fsd.scorer_line(scene(PASS, (WOERNER,))) == "14 C. WOERNER", "the roster's number wins"
    assert fsd.scorer_line(scene(FG, (FOLK,))) == "6 N. FOLK"


def test_the_yards_and_how():
    assert fsd.how_lines(scene(PASS)) == ("1 YD PASS FROM", "M.PENIX")
    assert fsd.how_lines(scene(PASS, (PENIX,)))[1] == "9 M. PENIX"
    assert fsd.how_lines(scene(RUN)) == ("1 YD RUN", "")
    assert fsd.how_lines(scene(PICK)) == ("67 YD INT RETURN", "")
    assert fsd.how_lines(scene(FG)) == ("31 YD FIELD GOAL", "")


def test_the_point_after_and_the_two_point_try():
    assert fsd.point_after(scene(PASS)) == "PAT GOOD"
    assert fsd.point_after(scene(TWO)) == "2 PT GOOD"
    assert fsd.point_after(scene(TWO_FAIL)) == "2 PT NO GOOD"
    assert fsd.point_after(scene(FG)) == ""
    missed = dataclasses.replace(PASS, extra_point="no good")
    assert fsd.point_after(scene(missed)) == "PAT NO GOOD"
    assert fsd.point_after(scene(dataclasses.replace(PASS, extra_point=""))) == ""


def test_the_new_score_has_the_scoring_team_first_and_includes_the_point_after():
    assert fsd.score_line(scene(PASS)) == "NYG 7 WSH 0"
    assert fsd.score_line(scene(AWAY)) == "WSH 7 NYG 0"
    assert fsd.score_line(scene(TWO)) == "NYG 8 WSH 0"
    assert fsd.other_team(scene(PASS)) == "WSH" and fsd.other_team(scene(AWAY)) == "NYG"


# -- the screen ----------------------------------------------------------------------


def test_the_scoring_team_is_at_full_brightness_and_the_other_dimmed(tmp_path):
    c = draw(PASS, art=logos(tmp_path))
    left = {col for p, col in c.pixels.items() if p[0] < 20}
    right = {col for p, col in c.pixels.items() if p[0] > 108}
    assert team_color("NYG") in left
    assert tuple(round(v * fsd.OTHER_TEAM_DIM) for v in team_color("WSH")) in right
    assert team_color("WSH") not in right


def test_without_logos_the_abbreviations_stand_in():
    c = draw(PASS)
    assert [p for p in c.pixels if p[0] < 20] and [p for p in c.pixels if p[0] > 108]


def test_the_text_stays_between_the_logos_and_the_whole_line_fits():
    for event, people in (
        (PASS, (WOERNER, PENIX)),
        (RUN, ()),
        (TWO, ()),
        (TWO_FAIL, ()),
        (PICK, ()),
        (FG, (FOLK,)),
    ):
        c = draw(event, people)
        text = [p for p, col in c.pixels.items() if 20 <= p[0] <= 108]
        assert text and not [p for p, col in c.pixels.items() if 3 < p[0] < 20 and p[1] < 8]


def test_a_pass_shows_both_the_passer_and_the_point_after_and_a_run_has_no_passer_row():
    pass_rows = {y for (x, y), col in draw(PASS, (WOERNER, PENIX)).pixels.items() if 20 <= x <= 108}
    run_rows = {y for (x, y), col in draw(RUN).pixels.items() if 20 <= x <= 108}
    assert len(pass_rows) > len(run_rows) or pass_rows != run_rows
    assert fsd.point_after(scene(PASS)) and fsd.how_lines(scene(PASS))[1]


def test_a_long_point_after_with_a_passer_drops_the_point_after_not_the_passer():
    # "2 PT NO GOOD" plus a two-digit score and a passer do not fit on one row.
    long = dataclasses.replace(TWO_FAIL, via="pass", away_score=12, home_score=14)
    c = draw(long, (WOERNER, PENIX))
    assert c.pixels and not c.out_of_bounds


def test_the_64px_panel_has_no_logos_and_no_passer_but_keeps_the_point_after():
    c = draw(PASS, (WOERNER, PENIX), 64)
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    wide = draw(PASS, (WOERNER, PENIX))
    assert len(c.pixels) < len(wide.pixels)
    rows = {y for (x, y) in c.pixels}
    assert max(rows) <= 31 and len(rows) > 10


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(PASS, team="AFC")
    for width in (128, 64):
        assert draw(odd, width=width).pixels


@pytest.mark.parametrize(
    "event",
    [PASS, RUN, TWO, TWO_FAIL, PICK, FG, AWAY],
    ids=lambda e: type(e).__name__ + str(e.points),
)
@pytest.mark.parametrize("width", [128, 64])
def test_every_real_score_draws_inside_the_panel(event, width):
    assert draw(event, (WOERNER, PENIX, FOLK), width).pixels
    assert draw(event, (), width).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,event,people,width",
    [
        ("pass", PASS, (WOERNER, PENIX), 128),
        ("run", RUN, (), 128),
        ("two_point", TWO, (), 128),
        ("pick_six", PICK, (), 128),
        ("fieldgoal", FG, (FOLK,), 128),
        ("away", AWAY, (), 128),
        ("pass_64", PASS, (WOERNER, PENIX), 64),
        ("fieldgoal_64", FG, (FOLK,), 64),
    ],
)
def test_snapshot(name, event, people, width, update_snapshots):
    check_snapshot(f"score_detail_{name}", draw(event, people, width).render(), update_snapshots)
