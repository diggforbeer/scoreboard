"""The end of a quarter, the half and the game (#388): the wipe card, and the halftime card the
board rests on afterwards. Plays are the real fixtures; the rest uses ``football.demo._play``."""

from __future__ import annotations

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_period as fper
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_scenes as fsc
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.mode import FB_SCENE_KINDS, resting_kind
from nhl_scoreboard.football.models import PlayKind
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, game, renderer

END_Q = make_play(1, "end_period", off="NYG")  # END QUARTER 1
END_HALF = make_play(1, "end_half", off="NYG")  # END QUARTER 2
END_GAME = make_play(1, "end_game", off="NYG")
END_REG = make_play(1, "end_regulation", off="NYG")  # END QUARTER 4


def scene(play, share):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_stage="play",
                 fb_elapsed=share * 3.0, fb_seconds=3.0, animating=True)  # fmt: skip


def draw(play, share, width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share))
    assert not canvas.out_of_bounds
    return canvas


def colored(canvas, color, rows=range(9, 30)):
    return [p for p, c in canvas.pixels.items() if c == color and p[1] in rows]


# -- the card ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "play,text,color",
    [(END_Q, "END Q1", fp.AMBER_CARD), (END_HALF, "END Q2", fp.AMBER_CARD),
     (END_REG, "END Q4", fp.AMBER_CARD), (END_GAME, "FINAL", fp.WHITE)],
)  # fmt: skip
def test_the_headline_comes_from_the_text(play, text, color):
    assert fper.headline(scene(play, 0)) == (text, color)


def test_the_quarter_falls_back_to_the_period_and_overtime_is_ot():
    bare = _play("End Period", "End of the quarter", 46, 46, "NYG", 0)
    assert fper.headline(scene(bare, 0))[0] == "END Q3", "the demo play's period"
    ot = _play("End Period", "END QUARTER 5", 46, 46, "NYG", 0)
    assert fper.headline(scene(ot, 0))[0] == "END OT"


def test_the_four_stoppage_kinds_are_registered_for_the_card_and_take_three_seconds():
    for kind in (
        PlayKind.END_PERIOD,
        PlayKind.END_HALF,
        PlayKind.END_REGULATION,
        PlayKind.END_GAME,
    ):
        assert fp.PLAY_SCREENS[kind] is fper.draw_period_card
        assert pacing.animation_seconds(make_play(1, "end_period", off="NYG"), 3.0) == 3.0
    assert fp.PLAY_SCREENS.get(PlayKind.TIMEOUT) is not fper.draw_period_card


def card_columns(canvas):
    """The columns of the black card on the middle row of the field."""
    row = 27  # below the headline's glyphs
    return [x for x in range(128) if canvas.pixels.get((x, row)) is None]


def test_the_card_wipes_out_from_the_middle_and_then_holds():
    widths = []
    for s in range(0, 60, 5):
        cols = [x for x in card_columns(draw(END_Q, s / 100)) if 20 <= x <= 108]
        widths.append(len(cols))
    assert widths[0] == 0 or widths[0] < widths[3]
    assert widths == sorted(widths), "only ever widening"
    assert widths[-1] == widths[-2] and widths[-1] >= 80, "full width and held"


def test_the_headline_shows_once_the_card_is_wide_enough_and_never_before():
    assert not colored(draw(END_Q, 0.0), fp.AMBER_CARD)
    assert not colored(draw(END_Q, 0.05), fp.AMBER_CARD)
    assert colored(draw(END_Q, 0.6), fp.AMBER_CARD)
    assert colored(draw(END_GAME, 0.6), fp.WHITE)
    assert draw(END_Q, 0.6).pixels == draw(END_Q, 1.0).pixels, "held"


def test_the_field_and_the_ball_are_underneath_and_the_card_inset_on_a_narrow_panel():
    narrow = draw(END_Q, 1.0, 64)
    assert narrow.pixels and all(x < 64 for x, _ in narrow.pixels)
    assert colored(narrow, fp.AMBER_CARD)


@pytest.mark.parametrize("label", ["end_period", "end_half", "end_game", "end_regulation"])
@pytest.mark.parametrize("off", ["NYG", "WSH"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.1, 0.3, 0.4, 0.7, 1.0, 2.0])
def test_every_real_period_play_draws_inside_the_panel_at_every_moment(label, off, width, share):
    play = make_play(1, label, off=off)
    assert draw(play, share, width).pixels


# -- the halftime card the board rests on --------------------------------------------


def half_game(away=10, home=17):
    return game("WSH", "NYG", "in", away, home, short="Halftime", name="STATUS_HALFTIME")


def halftime(g=None, width=128, logos=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = logos
    r.draw_fb_halftime(canvas, g or half_game())
    assert not canvas.out_of_bounds
    return canvas


def test_only_a_game_at_the_half_rests_on_the_halftime_card():
    assert resting_kind(half_game()) == "fb_halftime"
    assert resting_kind(game("WSH", "NYG", "in", 0, 0)) == "fb_field"
    assert (
        resting_kind(game("WSH", "NYG", "post", 3, 0, short="Final", name="STATUS_FINAL"))
        == "fb_scores"
    )
    assert (
        resting_kind(game("WSH", "NYG", "pre", short="x", name="STATUS_SCHEDULED")) == "fb_scores"
    )
    assert "fb_halftime" in FB_SCENE_KINDS


def test_the_card_says_halftime_with_both_teams_and_the_score():
    c = halftime()
    assert [p for p, col in c.pixels.items() if col == fp.WHITE and p[1] < 20], "HALFTIME"
    teams = {col for col in c.pixels.values()}
    assert fsc.side_color(make_game().home) in teams and fsc.side_color(make_game().away) in teams
    assert halftime(half_game(3, 24)).pixels != halftime().pixels, "the score is shown"


def test_the_logos_are_at_the_edges_on_a_wide_panel_and_dropped_on_a_narrow_one(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    logos = LogoSet("nfl", "dark", libs)
    plain, with_logos = halftime(), halftime(logos=logos)
    assert len(with_logos.pixels) > len(plain.pixels)
    assert [p for p in with_logos.pixels if p[0] < 24] and [
        p for p in with_logos.pixels if p[0] > 104
    ]
    narrow = halftime(width=64, logos=logos)
    assert len(narrow.pixels) < len(plain.pixels) and all(x < 64 for x, _ in narrow.pixels)


def test_the_halftime_card_draws_inside_the_panel_for_any_score():
    for width in (128, 64):
        for away, home in ((0, 0), (10, 17), (99, 100)):
            assert halftime(half_game(away, home), width).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("wipe", END_Q, 0.18, 128),
        ("quarter", END_Q, 0.8, 128),
        ("half", END_HALF, 0.8, 128),
        ("game", END_GAME, 0.8, 128),
        ("quarter_64", END_Q, 0.8, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"period_{name}", draw(play, share, width).render(), update_snapshots)


@pytest.mark.parametrize("width", [128, 64])
def test_halftime_snapshot(width, update_snapshots):
    suffix = "" if width == 128 else "_64"
    check_snapshot(f"fb_halftime{suffix}", halftime(width=width).render(), update_snapshots)
