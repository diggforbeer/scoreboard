"""Timeouts and the two-minute warning (#387): the clock icon that freezes, and who stopped it.

The text rules use the three real fixtures; the situation-count rule builds a game with a
``situation`` block carrying ``homeTimeouts`` / ``awayTimeouts``.
"""

from __future__ import annotations

import dataclasses
from itertools import pairwise

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_stoppage as fs
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.teams import team_color
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, game, renderer

TIMEOUT = make_play(1, "timeout", off="NYG")  # Timeout #1 by CIN at 01:10.
NYG_TIMEOUT = _play("Timeout", "Timeout #2 by NYG at 00:45.", 40, 40, "NYG", 0)
OFFICIAL = make_play(1, "official_timeout", off="NYG")
WARNING = make_play(1, "two_minute_warning", off="NYG")


def scene(play, share, g=None):
    return Scene("fb_play", fb_game=g or make_game(), fb_play=play, fb_stage="play",
                 fb_elapsed=share * 3.0, fb_seconds=3.0, animating=True)  # fmt: skip


def draw(play, share, width=128, g=None, logos=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = logos
    r.draw_fb_play_scene(canvas, scene(play, share, g))
    assert not canvas.out_of_bounds
    return canvas


def with_timeouts(home, away):
    """NYG (home) at WSH (away) live, with the given timeouts left in the situation block."""
    sit = {"down": 1, "distance": 10, "yardLine": 40, "isRedZone": False,
           "downDistanceText": "1st & 10", "shortDownDistanceText": "1st & 10",
           "possession": "19", "homeTimeouts": home, "awayTimeouts": away}  # fmt: skip
    return game("WSH", "NYG", "in", 0, 0, situation=sit)


# -- the rules -----------------------------------------------------------------------


def test_each_stoppage_has_its_lines_and_is_registered_for_its_own_kind():
    assert fs.lines(scene(NYG_TIMEOUT, 0)) == ("TIMEOUT", "NYG 2ND", "00:45")
    assert fs.lines(scene(OFFICIAL, 0))[:2] == ("OFFICIAL", "TIMEOUT")
    assert fs.lines(scene(WARNING, 0)) == ("2-MIN", "WARNING", "2:00")
    for kind in (PlayKind.TIMEOUT, PlayKind.OFFICIAL_TIMEOUT, PlayKind.TWO_MINUTE_WARNING):
        assert kind in fp.PLAY_SCREENS
    assert fp.PLAY_SCREENS.get(PlayKind.END_PERIOD) not in (
        fs.draw_timeout, fs.draw_official_timeout, fs.draw_two_minute_warning,
    )  # fmt: skip
    assert all(pacing.animation_seconds(p, 3.0) == 3.0 for p in (TIMEOUT, OFFICIAL, WARNING))


def test_the_ordinal_stands_in_for_the_hash_the_font_does_not_have():
    assert [fs.ordinal(n) for n in (1, 2, 3, None)] == ["1ST", "2ND", "3RD", ""]


def test_timeouts_left_is_three_less_the_number_unless_the_situation_says_otherwise():
    assert fs.timeouts_left(scene(NYG_TIMEOUT, 0)) == 1
    assert fs.timeouts_left(scene(NYG_TIMEOUT, 0, with_timeouts(2, 3))) == 2, (
        "the feed's count wins"
    )
    assert fs.timeouts_left(scene(NYG_TIMEOUT, 0, with_timeouts(None, 3))) == 1, "none given"
    assert (
        fs.timeouts_left(scene(OFFICIAL, 0)) is None and fs.timeouts_left(scene(WARNING, 0)) is None
    )
    away = _play("Timeout", "Timeout #1 by WSH at 02:10.", 40, 40, "NYG", 0)
    assert fs.timeouts_left(scene(away, 0, with_timeouts(2, 1))) == 1, "the visiting team's count"
    assert fs.timeouts_left(scene(NYG_TIMEOUT, 0, with_timeouts(9, 3))) == 3, "held to 0-3"


def test_the_icon_takes_the_calling_teams_colour_a_neutral_grey_or_amber():
    assert fs.icon_color(scene(NYG_TIMEOUT, 0)) == team_color("NYG")
    assert fs.icon_color(scene(OFFICIAL, 0)) == fs.OFFICIAL_ICON
    assert fs.icon_color(scene(WARNING, 0)) == fs.WARNING_ICON


# -- the animation -------------------------------------------------------------------


def test_the_hand_spins_slowing_and_then_stops_for_good():
    angles = [fs.hand_angle(s / 100) for s in range(0, 36, 5)]
    assert angles == sorted(angles, reverse=True), "winding down toward the stop"
    assert fs.hand_angle(fs.FREEZE_AT) == fs.STOP_ANGLE
    assert fs.hand_angle(0.7) == fs.hand_angle(1.0) == fs.STOP_ANGLE
    steps = [a - b for a, b in pairwise(angles)]
    assert steps == sorted(steps, reverse=True), "slowing down"


def test_the_icon_moves_while_it_spins_and_is_frozen_afterwards():
    assert draw(NYG_TIMEOUT, 0.05).pixels != draw(NYG_TIMEOUT, 0.15).pixels
    assert draw(NYG_TIMEOUT, 0.7).pixels == draw(NYG_TIMEOUT, 1.0).pixels
    assert draw(NYG_TIMEOUT, 0.45).pixels != draw(NYG_TIMEOUT, 0.7).pixels, "the ring flashes"


def lit_dots(canvas, color, x0=98):
    return sum(1 for i in range(3) if canvas.pixels.get((x0 + i * 7 + 2, 14)) == color)


def test_the_timeouts_left_are_shown_as_lit_dots():
    for left, g in ((1, None), (2, with_timeouts(2, 3)), (0, with_timeouts(0, 3)),
                    (3, with_timeouts(3, 3))):  # fmt: skip
        assert lit_dots(draw(NYG_TIMEOUT, 1.0, g=g), team_color("NYG")) == left


def test_an_official_timeout_and_the_warning_have_no_dots_and_no_team():
    for play in (OFFICIAL, WARNING):
        c = draw(play, 1.0)
        assert lit_dots(c, fs.EMPTY_DOT) == 0 and lit_dots(c, team_color("NYG")) == 0
        assert not any(col == team_color("NYG") for col in c.pixels.values())


def test_the_calling_teams_logo_is_shown_and_falls_back_to_its_abbreviation(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    with_logo = draw(NYG_TIMEOUT, 1.0, logos=LogoSet("nfl", "dark", libs))
    without = draw(NYG_TIMEOUT, 1.0)
    left = lambda c: {p for p in c.pixels if p[0] < 28}  # noqa: E731
    assert len(left(with_logo)) > len(left(without)) > 0
    assert with_logo.pixels != without.pixels


def test_a_64px_panel_drops_the_logo_and_the_caption_but_keeps_the_dots():
    c = draw(NYG_TIMEOUT, 1.0, 64)
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    team = [p for p, col in c.pixels.items() if col == team_color("NYG")]
    assert team
    wide = draw(NYG_TIMEOUT, 1.0)
    assert len(c.pixels) < len(wide.pixels)


@pytest.mark.parametrize("label", ["timeout", "official_timeout", "two_minute_warning"])
@pytest.mark.parametrize("off", ["NYG", "WSH"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.1, 0.34, 0.4, 0.5, 0.7, 1.0, 2.0])
def test_every_real_stoppage_draws_inside_the_panel_at_every_moment(label, off, width, share):
    play = make_play(1, label, off=off)
    assert draw(play, share, width).pixels


def test_a_missing_clock_or_team_never_raises():
    bare = dataclasses.replace(make_play(1, "timeout", off="NYG", text="Timeout."))
    assert draw(bare, 0.5).pixels
    assert draw(make_play(1, "two_minute_warning", off="NYG", text=""), 0.5).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("spin", NYG_TIMEOUT, 0.15, 128),
        ("frozen", NYG_TIMEOUT, 1.0, 128),
        ("official", OFFICIAL, 1.0, 128),
        ("warning", WARNING, 1.0, 128),
        ("frozen_64", NYG_TIMEOUT, 1.0, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"timeout_{name}", draw(play, share, width).render(), update_snapshots)
