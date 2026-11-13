"""``fb_reversal`` (#396): a celebrated play the feed has since changed. The reversals are the real
ones the detector builds (a celebration remembered, then a poll that changes the play), so the
titles, reasons and restored scores are the detector's own."""

from __future__ import annotations

import dataclasses

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_punt as punt
from nhl_scoreboard.display import football_reversal as frv
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football.director import REVERSAL
from nhl_scoreboard.football.reversals import Reversal
from test_football_events import make_game, make_play, one
from test_football_reversals import celebrate, td_by_home
from test_football_scenes import check_snapshot, renderer


def reversed_play(celebrated, changed, **kw):
    _det, game, watcher, events = celebrate(celebrated, **kw)
    watcher.remember_all(events)
    return one(watcher.on_poll(game, [changed]))


# NYG is the home team (left) and the favourite.
TD = reversed_play(td_by_home(), make_play(1, "penalty_after_run", score=(0, 0), off="NYG"))
FG = reversed_play(
    make_play(1, "fg_good", score=(0, 3), off="NYG"),
    make_play(1, "penalty_pre_snap", score=(0, 0), off="NYG"),
)
PICK = reversed_play(
    make_play(1, "interception_return", off="WSH", end="NYG"),
    make_play(1, "interception_return", off="WSH", end="NYG", flags={"isTurnover": False}),
)
SAFETY = reversed_play(
    make_play(1, "rush", score=(0, 2), off="WSH", ptype="Safety"),
    make_play(1, "rush", score=(0, 0), off="WSH"),
)
NO_TEXT = dataclasses.replace(TD, reason="PLAY CHANGED ON REVIEW", down_distance="")
LONG = dataclasses.replace(TD, reason="D.PRESCOTT PASS INCOMPLETE SHORT RIGHT TO C.LAMB, REVERSED")


def scene(reversal, share=0.4, seconds=5.0):
    return Scene("fb_event", fb_game=make_game(), fb_play=reversal.play, fb_event=reversal,
                 fb_stage=REVERSAL, fb_elapsed=share * seconds, fb_seconds=seconds,
                 animating=True)  # fmt: skip


def draw(reversal, share=0.4, width=128, art=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = art
    r.draw_fb_play_scene(canvas, scene(reversal, share))
    assert not canvas.out_of_bounds
    return canvas


def logos(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    return LogoSet("nfl", "dark", libs)


# -- the words -----------------------------------------------------------------------


def test_it_is_registered_for_reversals_and_the_detector_titles_are_what_it_shows():
    assert fp.EVENT_SCREENS[(Reversal, REVERSAL)] is frv.draw_reversal
    assert [r.title for r in (TD, FG, PICK, SAFETY)] == [
        "TOUCHDOWN OVERTURNED", "FIELD GOAL NEGATED", "TURNOVER OVERTURNED", "SCORE OVERTURNED",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "title,lines",
    [("TOUCHDOWN OVERTURNED", ("TOUCHDOWN", "OVERTURNED")),
     ("FIELD GOAL NEGATED", ("FIELD GOAL", "NEGATED")),
     ("SCORE OVERTURNED", ("SCORE", "OVERTURNED")), ("ODD", ("ODD", ""))],
)  # fmt: skip
def test_the_title_goes_over_two_lines_with_the_last_word_on_the_second(title, lines):
    assert frv.split_title(title) == lines


def test_a_reason_that_fits_is_shown_whole_and_a_long_one_is_held_then_scrolls_to_its_end():
    assert frv.reason_window("SHORT", 0.0, 21) == frv.reason_window("SHORT", 4.0, 21) == "SHORT"
    long = "OFFENSIVE PASS INTERFERENCE ON ATL-14"
    assert frv.reason_window(long, 0.0, 21) == long[:21]
    assert frv.reason_window(long, frv.HOLD, 21) == long[:21], "held for the first second"
    assert frv.reason_window(long, frv.HOLD + 0.5, 21) == long[5:26]
    assert frv.reason_window(long, 30.0, 21) == long[-21:], "and it ends on the end"
    steps = [frv.reason_window(long, 1.0 + 0.12 * i + 0.01, 21) for i in range(20)]
    assert steps[0] != steps[-1] and all(len(s) == 21 for s in steps)


def test_the_restored_score_has_the_home_team_first_and_the_new_down_is_tightened():
    s = scene(TD)
    assert frv.score_text(s) == "SCORE BACK TO NYG 0  WSH 0"
    assert frv.down_text(scene(dataclasses.replace(TD, down_distance="1st & 10"))) == "1ST&10"
    assert frv.down_text(scene(NO_TEXT)) == ""


# -- the screen ----------------------------------------------------------------------


def test_the_title_is_amber_neither_green_nor_red():
    c = draw(TD)
    assert fp.AMBER_CARD in c.pixels.values()
    assert fp.GAIN not in c.pixels.values() and fp.LOSS not in c.pixels.values()


def test_the_two_title_lines_then_the_reason_then_the_score_run_down_the_panel():
    c = draw(TD, 0.1)
    rows = {}
    for (x, y), col in c.pixels.items():
        if (
            frv.TEXT_LEFT <= x <= frv.TEXT_RIGHT or y >= 28
        ):  # the text column, and the full-width row
            rows.setdefault(y, set()).add(col)
    amber = sorted(y for y, cols in rows.items() if fp.AMBER_CARD in cols)
    white = sorted(y for y, cols in rows.items() if fp.WHITE in cols)
    dim = sorted(y for y, cols in rows.items() if fp.DIM in cols)
    assert max(amber) < min(white) and max(white) < min(dim)
    assert amber[0] < 8 and dim[-1] >= 28


def test_the_logo_is_the_team_whose_play_was_reversed_and_a_flag_stands_at_the_right(tmp_path):
    art = logos(tmp_path)
    from nhl_scoreboard.football.teams import team_color

    c = draw(TD, art=art)
    assert any(col == team_color("NYG") and x < 20 for (x, _), col in c.pixels.items())
    assert [p for p, col in c.pixels.items() if col == punt.FLAG and p[0] > 100]
    away = draw(PICK, art=art)  # WSH lost the interception... NYG gained: the original is NYG's
    assert any(col == team_color(PICK.original.team) for col in away.pixels.values())


def test_a_long_reason_scrolls_and_a_short_one_stays_still():
    assert draw(LONG, 0.1).pixels != draw(LONG, 0.6).pixels
    assert draw(LONG, 0.01).pixels == draw(LONG, 0.15).pixels, "held at first"
    short = dataclasses.replace(TD, reason="HOLDING ON NYG")
    assert draw(short, 0.1).pixels == draw(short, 0.9).pixels


def test_the_default_reason_reads_play_changed_on_review():
    assert NO_TEXT.reason == "PLAY CHANGED ON REVIEW" and draw(NO_TEXT).pixels


def test_the_last_row_adds_the_new_down_when_it_fits_shortening_score_back_to_first():
    font = renderer().fonts.tiny
    score = "SCORE BACK TO NYG 0  WSH 0"
    assert frv.last_row(score, "", 124, font) == score
    assert frv.last_row(score, "1ST&10", 124, font) == "BACK TO NYG 0  WSH 0  1ST&10"
    assert frv.last_row(score, "1ST&10", 140, font) == f"{score}  1ST&10"
    assert frv.last_row(score, "4TH&25 AT THE 49", 124, font) == score, "given up when too long"


def test_the_new_down_shows_on_the_score_row():
    with_down = dataclasses.replace(TD, down_distance="1st & 10")
    without = dataclasses.replace(TD, down_distance="")
    assert len(draw(with_down).pixels) > len(draw(without).pixels)
    huge = dataclasses.replace(TD, down_distance="4th & 25 at the opponent's 49 yard line")
    assert draw(huge).pixels == draw(without).pixels


def test_a_64px_panel_has_no_logo_or_flag_and_alternates_the_reason_and_the_score():
    first, later = draw(TD, 0.2, 64), draw(TD, 0.9, 64)
    assert first.pixels != later.pixels
    for c in (first, later):
        assert c.pixels and all(x < 64 for x, _ in c.pixels)
        assert not [p for p, col in c.pixels.items() if col == punt.FLAG]
    assert [p for p, col in first.pixels.items() if col == fp.WHITE], "the reason first"
    assert [p for p, col in later.pixels.items() if col == fp.DIM], "then the score"


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(TD, original=dataclasses.replace(TD.original, team="AFC"))
    for width in (128, 64):
        assert draw(odd, 0.5, width).pixels


@pytest.mark.parametrize("reversal", [TD, FG, PICK, SAFETY, NO_TEXT, LONG],
                         ids=["td", "fg", "pick", "safety", "no_text", "long"])  # fmt: skip
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.2, 0.4, 0.6, 0.8, 1.0, 2.0])
def test_every_moment_draws_inside_the_panel(reversal, width, share):
    assert draw(reversal, share, width).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,reversal,share,width",
    [("td", TD, 0.1, 128), ("field_goal", FG, 0.1, 128), ("scrolled", LONG, 0.6, 128),
     ("no_text", NO_TEXT, 0.1, 128), ("td_64_reason", TD, 0.2, 64), ("td_64_score", TD, 0.9, 64)],
)  # fmt: skip
def test_snapshot(name, reversal, share, width, update_snapshots):
    check_snapshot(f"reversal_{name}", draw(reversal, share, width).render(), update_snapshots)
