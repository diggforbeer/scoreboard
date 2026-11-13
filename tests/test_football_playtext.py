"""The play-text layout (#379): the field and the feed's own sentence, scrolling when long.

``football/textlayout.py`` is pure and tested on its own; the renderer tests then check what is
drawn at moments of the scroll, at 128px and 64px, with snapshots.
"""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import textlayout as tl
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

FITS = "D.Henry rush for 4 yards."
SHORT = "J.McCarthy pass short middle to I.Likely for 9 yards."
LONG = (
    "D.Prescott pass short right to C.Lamb for 11 yards, TOUCHDOWN. The Replay Official "
    "reviewed the pass completion ruling, and the play was Upheld. The ruling on the field "
    "stands. J.Doe extra point is GOOD."
)


# -- the timing, pure ---------------------------------------------------------------------------


def test_the_first_lines_are_held_then_it_scrolls_a_line_at_a_time_and_rests():
    assert [tl.first_line(t, 7, 3) for t in (0, 1.9, 2.0)] == [0, 0, 0]
    assert [tl.first_line(t, 7, 3) for t in (2.1, 3.0, 3.1, 4.2, 5.2)] == [1, 2, 2, 3, 4]
    assert tl.first_line(60, 7, 3) == 4, "rests on the last full window"


def test_text_that_fits_never_scrolls():
    assert [tl.first_line(t, 3, 3) for t in (0, 5, 50)] == [0, 0, 0]
    assert tl.first_line(10, 1, 3) == 0


def test_a_64px_panel_alternates_the_field_and_the_text():
    seq = [tl.narrow_view(t, 5, 3) for t in (0.0, 1.9, 2.0, 3.9, 5.5, 7.4, 7.6)]
    assert [v for v, _ in seq] == ["field", "field", "text", "text", "text", "text", "field"]
    assert seq[2][1] == 0.0 and seq[3][1] == pytest.approx(1.9)
    cycle = tl.FIELD_SECONDS + tl.text_seconds(5, 3)
    assert tl.narrow_view(cycle, 5, 3) == ("field", 0.0), "and it repeats"


def test_a_short_sentence_gets_the_five_second_minimum_and_a_long_one_longer_up_to_a_cap():
    assert tl.playtext_seconds("short", 5.0) >= 5.0
    assert tl.playtext_seconds(SHORT, 5.0) >= 5.0
    assert tl.playtext_seconds(LONG, 5.0) > tl.playtext_seconds(SHORT, 5.0)
    assert tl.playtext_seconds("x" * 5000, 5.0) == tl.MAX_SECONDS


# -- the screen ------------------------------------------------------------------------


def scene(text, elapsed=0.0, **kw):
    play = make_play(1, "pass_complete", off="WSH", text=text, **kw)
    return Scene("fb_playtext", fb_game=make_game(), fb_play=play, fb_stage="playtext",
                 fb_elapsed=elapsed, fb_seconds=8.0, animating=True)  # fmt: skip


def draw(text, elapsed=0.0, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(text, elapsed))
    assert not canvas.out_of_bounds
    return canvas


def text_pixels(canvas, width=128):
    """The pixels of the right half (the text and the down under it)."""
    return {p: c for p, c in canvas.pixels.items() if p[0] >= width // 2}


def test_a_short_sentence_is_shown_whole_and_does_not_move():
    assert text_pixels(draw(FITS, 0.0)) == text_pixels(draw(FITS, 6.0))


def test_a_long_sentence_scrolls_and_shows_its_end():
    first, later, last = draw(LONG, 0.0), draw(LONG, 3.5), draw(LONG, 30.0)
    assert text_pixels(first) != text_pixels(later) != text_pixels(last)
    assert text_pixels(last) == text_pixels(draw(LONG, 60.0)), "it rests on the end"


def test_the_down_and_distance_stays_put_under_the_scrolling_text():
    rows = lambda c: {p for p in c.pixels if p[1] >= 24 and p[0] >= 64}  # noqa: E731
    assert rows(draw(LONG, 0.0)) == rows(draw(LONG, 30.0)) != set()


def test_the_field_and_its_label_are_in_the_left_half_with_the_ball_where_the_play_ended():
    c = draw(SHORT)
    left = {p: col for p, col in c.pixels.items() if p[0] < 64}
    assert any(col == fp.ff.BALL for col in left.values())
    assert any(p[1] < 8 for p in left), "the label"


@pytest.mark.parametrize("text", ["", "A", SHORT, LONG, "WORD" * 40, "a" * 90])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("elapsed", [0.0, 2.5, 4.0, 9.0, 40.0])
def test_nothing_is_ever_drawn_off_the_panel(text, width, elapsed):
    c = draw(text, elapsed, width)
    assert c.pixels


def test_a_64px_panel_shows_the_field_first_then_the_text_and_never_both():
    field = draw(SHORT, 0.5, 64)
    texty = draw(SHORT, 3.0, 64)
    assert any(col == fp.ff.BALL for col in field.pixels.values())
    assert not any(col == fp.ff.BALL for col in texty.pixels.values())
    white_in_field = [p for p, col in field.pixels.items() if col == fp.WHITE]
    assert not white_in_field, "no sentence while the field has the panel"
    assert [p for p, col in texty.pixels.items() if col == fp.WHITE]


def test_a_64px_sentence_scrolls_too():
    assert draw(LONG, 2.5 + 0.1, 64).pixels != draw(LONG, 2.0 + 2.0 + 2.5, 64).pixels


@pytest.mark.parametrize(
    "name,text,elapsed,width",
    [
        ("short", SHORT, 0.0, 128),
        ("long_start", LONG, 0.0, 128),
        ("long_scrolled", LONG, 4.5, 128),
        ("long_end", LONG, 30.0, 128),
        ("short_64_field", SHORT, 0.5, 64),
        ("short_64_text", SHORT, 3.0, 64),
        ("long_64_scrolled", LONG, 8.0, 64),
    ],
)
def test_snapshot(name, text, elapsed, width, update_snapshots):
    check_snapshot(f"fb_playtext_{name}", draw(text, elapsed, width).render(), update_snapshots)
