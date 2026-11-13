"""``fb_touchdown`` (#390): the football goal light. A pure function of the seconds since the play,
so any frame is drawn on demand; the touchdown is built the way the detector builds it (a real
``Touchdown`` event from ``EventDetector``) and the quick version for a followed team is checked
alongside."""

from __future__ import annotations

import dataclasses

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_touchdown as ftd
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import EVENT
from nhl_scoreboard.football.teams import team_color
from test_football_events import detector, make_game, make_play
from test_football_scenes import check_snapshot, renderer

NYG = team_color("NYG")
WSH = team_color("WSH")


def real_touchdown(favourite="NYG", follow=(), off="NYG", score=(0, 7)):
    det, game, _ = detector(favourite, follow)
    play = make_play(1, "rush_td_pat", score=score, off=off)
    (event,) = det.on_plays(game, [play])
    assert isinstance(event, ev.Touchdown)
    return event


FULL = real_touchdown()  # NYG (home) scores, the favourite
QUICK = real_touchdown("DAL", ["NYG"])
AWAY = real_touchdown("WSH", off="WSH", score=(7, 0))


def scene(age, event=FULL):
    return Scene("fb_event", fb_game=make_game(), fb_play=event.play, fb_event=event,
                 fb_stage=EVENT, fb_elapsed=age, fb_seconds=6.0, animating=True)  # fmt: skip


def draw(age, width=128, event=FULL):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(age, event))
    assert not canvas.out_of_bounds
    return canvas


def lit(canvas):
    return {p for p, c in canvas.pixels.items() if any(c)}


def team_pixels(canvas, color=NYG, rows=range(0, 32)):
    return [p for p, c in canvas.pixels.items() if c == color and p[1] in rows]


# -- who and how big -----------------------------------------------------------------


def test_the_favourites_touchdown_is_the_full_animation_and_a_followed_teams_the_quick_card():
    assert FULL.scope == ev.Scope.FULL and QUICK.scope == ev.Scope.QUICK
    assert fp.EVENT_SCREENS[(ev.Touchdown, EVENT)] is ftd.draw_touchdown
    assert draw(0.3).pixels != draw(2.5).pixels, "the favourite's moves"
    quick = [draw(t, event=QUICK).pixels for t in (0.0, 1.0, 3.9)]
    assert quick[0] == quick[1] == quick[2], "the quick card is static"


def test_the_quick_card_names_the_team_and_shows_the_score():
    c = draw(1.0, event=QUICK)
    assert team_pixels(c) and [p for p, col in c.pixels.items() if col == fp.WHITE and p[1] > 26]
    assert (
        draw(1.0, event=QUICK).pixels
        != draw(1.0, event=real_touchdown("DAL", ["NYG"], score=(0, 14))).pixels
    )


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(FULL, team="AFC")
    for age in (0.0, 0.5, 1.5, 2.5, 3.6, 5.0):
        assert draw(age, event=odd).pixels
    assert ftd.city("AFC") == "AFC" and ftd.city("NYG") == "NY GIANTS"


# -- the timeline --------------------------------------------------------------------


def test_it_opens_with_a_white_flash_that_is_gone_by_a_fifth_of_a_second():
    flash = draw(0.02)
    assert any(c[0] > 100 and c[1] > 100 and c[2] > 100 for c in flash.pixels.values())
    after = draw(0.4)
    assert not any(c == (255, 255, 255) for c in after.pixels.values())


def test_both_end_zones_pulse_in_the_teams_colour_before_the_strobe():
    c = draw(0.5)
    columns = {x for x, _ in lit(c)}
    assert min(columns) == 0 and max(columns) == 127
    assert all(x < 14 or x >= 114 for x, _ in lit(c)), "only the end zones are lit"
    assert draw(0.5).pixels != draw(0.62).pixels, "and they pulse"


def test_the_whole_panel_strobes_between_one_second_and_three():
    frames = [len(lit(draw(1.0 + 0.05 + 0.1 * i))) for i in range(6)]
    on, off = frames[0::2], frames[1::2]
    assert min(on) > 3000, "the whole panel, not a strip"
    assert max(off) < 1000, "and dark in between"
    assert len(lit(draw(3.2))) < 2000, "the strobe stops at three seconds: just the word"


def test_the_ball_is_spiked_at_the_goal_line_the_scorer_attacked_and_then_rests_and_goes():
    def balls(age, event=FULL):
        return [p for p, col in draw(age, event=event).pixels.items() if col == ff.BALL]

    assert not balls(0.5)
    drop, bounce, rest = balls(1.15), balls(1.5), balls(2.2)
    assert drop and bounce and rest
    assert {x for x, _ in drop} <= set(range(112, 117)), "the right goal line: NYG is the home team"
    assert min(y for _, y in bounce) < max(y for _, y in rest), "it bounced"
    assert max(y for _, y in rest) >= ftd.BALL_GROUND
    assert {x for x, _ in balls(2.2, AWAY)} <= set(range(11, 16)), "the away team attacks left"
    assert not balls(3.2), "gone once the letters have landed"


def test_the_letters_drop_in_one_at_a_time_from_the_left_and_none_come_early():
    def word(age):
        """The letter pixels: bright team-coloured (or white-washed) ones on the field's middle."""
        c = draw(age)
        return {
            p for p, col in c.pixels.items() if 14 <= p[0] < 114 and col[2] > 150 and col != ff.BALL
        }

    assert not word(0.9)
    first, later, all_in = word(1.3), word(2.0), word(3.2)
    assert first and max(x for x, _ in first) < 70, "T first"
    assert len(first) < len(later) < len(all_in)
    assert max(x for x, _ in all_in) >= 100, "the last N"


def test_once_landed_the_word_does_not_change_until_the_shimmer_and_the_name():
    assert draw(3.2).pixels == draw(3.4).pixels


def test_the_teams_city_fades_in_along_the_bottom_from_three_and_a_half_seconds():
    def bottom(age):
        return [p for p, c in draw(age).pixels.items() if p[1] >= 27 and c != ff.BALL]

    assert not bottom(3.4)
    early, full = bottom(3.6), bottom(4.5)
    assert early and len(full) >= len(early) and full
    shade = {c for p, c in draw(4.5).pixels.items() if p[1] >= 28}
    assert NYG in shade


def test_a_white_shimmer_sweeps_the_letters_and_it_loops():
    base = draw(3.2).pixels
    sweep = draw(3.9).pixels
    whiter = [p for p in base if p in sweep and sum(sweep[p]) > sum(base[p]) + 60]
    assert whiter, "part of the word is lit white-ish as the band passes"
    assert draw(4.2).pixels == draw(5.7).pixels, "and it comes round again every 1.5s"


@pytest.mark.parametrize("event", [FULL, AWAY, QUICK], ids=["full", "away", "quick"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("age", [0.0, 0.05, 0.5, 1.0, 1.2, 1.8, 2.6, 3.4, 3.8, 4.5, 6.0, 9.0])
def test_every_moment_draws_inside_the_panel(event, width, age):
    assert draw(age, width, event).pixels


def test_a_64px_panel_wraps_the_word_to_two_lines_at_normal_size():
    c = draw(3.2, 64)
    rows = sorted({y for (x, y), col in c.pixels.items() if col != ff.BALL})
    top, bottom = [y for y in rows if y < 14], [y for y in rows if y >= 14]
    assert top and bottom and max(top) < 16 and max(rows) <= 31
    assert all(x < 64 for x, _ in c.pixels)
    assert max(x for x, _ in c.pixels) - min(x for x, _ in c.pixels) < 50, (
        "TOUCH is narrower than the panel"
    )


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,age,width,event",
    [
        ("flash", 0.04, 128, FULL),
        ("end_zones", 0.55, 128, FULL),
        ("strobe", 1.55, 128, FULL),
        ("letters", 2.2, 128, FULL),
        ("settled", 3.3, 128, FULL),
        ("shimmer", 4.7, 128, FULL),
        ("quick", 2.0, 128, QUICK),
        ("settled_64", 3.3, 64, FULL),
    ],
)
def test_snapshot(name, age, width, event, update_snapshots):
    check_snapshot(f"touchdown_{name}", draw(age, width, event).render(), update_snapshots)
