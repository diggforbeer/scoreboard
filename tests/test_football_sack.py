"""``Sack`` (#385): the quarterback drops back, a burst at the sack spot, the marker slides back.
Geometry plays use ``football.demo._play`` (NYG home, driving right); the real sacks in
``play_cases.json`` are swept for stray pixels."""

from __future__ import annotations

import pytest

from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_field as ff
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_sack as fs
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import pacing
from nhl_scoreboard.football.demo import _play
from nhl_scoreboard.football.geometry import FIELD_BOTTOM, FieldLayout
from nhl_scoreboard.football.models import PlayKind
from nhl_scoreboard.football.people import Person
from test_football_events import make_game, make_play
from test_football_scenes import check_snapshot, renderer

LAYOUT = FieldLayout.for_panel(128)
QB = Person("passer", 8, "D. Jones", "8", "QB", True)
LONDON = Person("sackedBy", 30, "L. London", "91", "DE", True)
SACK = _play(
    "Sack", "(Shotgun) D.Jones sacked at NYG 34 for -6 yards (L.London).", 40, 34, "NYG", -6
)
ZERO = _play("Sack", "(Shotgun) D.Jones sacked at NYG 40 for 0 yards (L.London).", 40, 40, "NYG", 0)
AWAY_SACK = _play("Sack", "(Shotgun) M.Penix sacked at WSH 46 for -6 yards (L.London).",
                  40, 46, "WSH", -6)  # fmt: skip


def scene(play, share, people=(QB, LONDON)):
    return Scene("fb_play", fb_game=make_game(), fb_play=play, fb_people=people, fb_stage="play",
                 fb_elapsed=share * 3.0, fb_seconds=3.0, animating=True)  # fmt: skip


def draw(play, share, people=(QB, LONDON), width=128):
    canvas = AsciiCanvas(width, 32)
    renderer(width).draw_fb_play_scene(canvas, scene(play, share, people))
    assert not canvas.out_of_bounds
    return canvas


def column(canvas, color):
    """The columns that hold a full-height line of ``color`` (a marker)."""
    cols = {}
    for (x, y), c in canvas.pixels.items():
        if c == color and y >= 8:
            cols[x] = cols.get(x, 0) + 1
    return sorted(x for x, n in cols.items() if n >= 12)


def whites(canvas):
    return [p for p, c in canvas.pixels.items() if c == fp.WHITE]


# -- the rules -----------------------------------------------------------------------


def test_the_label_says_the_loss_in_red_and_a_zero_sack_is_neutral():
    assert fs.sack_label(scene(SACK, 0)) == ("SACK -6", fp.LOSS)
    assert fs.sack_label(scene(ZERO, 0)) == ("SACK 0", fp.NEUTRAL)


def test_the_sackers_number_falls_back_to_the_name_in_the_text():
    assert fs.sacker_label(scene(SACK, 0)) == "91"
    assert fs.sacker_label(scene(SACK, 0, (QB,))) == "LONDON"
    nameless = _play("Sack", "D.Jones sacked at NYG 34 for -6 yards.", 40, 34, "NYG", -6)
    assert fs.sacker_label(scene(nameless, 0, (QB,))) == ""


def test_it_is_registered_for_sacks_only_and_is_a_three_second_play():
    assert fp.PLAY_SCREENS[PlayKind.SACK] is fs.draw_sack
    assert PlayKind.SACK_FUMBLE not in fp.PLAY_SCREENS, "the turnover story's"
    assert pacing.animation_seconds(SACK, 3.0) == 3.0


# -- the animation -------------------------------------------------------------------


def test_the_quarterbacks_number_drops_back_behind_the_line_before_the_hit():
    early, later = draw(SACK, 0.02), draw(SACK, 0.3)
    ex = sum(x for x, _ in whites(early)) / len(whites(early))
    lx = sum(x for x, _ in whites(later)) / len(whites(later))
    assert lx < ex - 3, "back toward his own goal (the home team drives right)"
    assert lx < LAYOUT.px(40), "behind the line of scrimmage"


def test_the_away_quarterback_drops_back_to_the_right():
    early, later = draw(AWAY_SACK, 0.02), draw(AWAY_SACK, 0.3)
    ex = sum(x for x, _ in whites(early)) / len(whites(early))
    lx = sum(x for x, _ in whites(later)) / len(whites(later))
    assert lx > ex + 3


def test_a_burst_goes_off_at_the_sack_spot_and_then_is_gone(monkeypatch):
    calls = []
    monkeypatch.setattr(
        fs, "draw_burst", lambda canvas, x, y, progress: calls.append((x, progress))
    )
    for share in (0.2, 0.9):
        draw(SACK, share)
    assert calls == [], "not before the hit and not after it"
    draw(SACK, 0.5)
    draw(SACK, 0.62)
    assert [x for x, _ in calls] == [LAYOUT.px(34)] * 2, "at the sack spot"
    assert calls[0][1] < calls[1][1], "growing"


def test_the_burst_grows_and_fades_and_stays_near_its_centre():
    def spokes(progress):
        c = AsciiCanvas(40, 32)
        fs.draw_burst(c, 20, 16, progress)
        return c.pixels

    small, big = spokes(0.0), spokes(1.0)
    radius = lambda px: max(max(abs(x - 20), abs(y - 16)) for x, y in px)  # noqa: E731
    assert radius(small) < radius(big) <= fs.BURST_RADIUS
    assert max(c[0] for c in small.values()) > max(c[0] for c in big.values()), "it fades"


def test_the_scrimmage_line_slides_back_to_the_sack_spot_while_the_first_down_line_stays():
    first = LAYOUT.px(47)  # the line to gain: 7 yards past the original line
    for share, expected in ((0.2, 40), (1.0, 34)):
        c = draw(SACK, share)
        assert column(c, ff.SCRIMMAGE) == [LAYOUT.px(expected)], share
        assert column(c, ff.FIRST_DOWN) == [first], "the first-down line does not move"
    mid = column(draw(SACK, 0.7), ff.SCRIMMAGE)[0]
    assert LAYOUT.px(34) < mid < LAYOUT.px(40), "caught between the two, sliding"


def test_the_slide_only_goes_backwards():
    xs = [column(draw(SACK, s / 100), ff.SCRIMMAGE)[0] for s in range(40, 100, 5)]
    assert xs == sorted(xs, reverse=True)


def test_the_away_team_is_pushed_back_to_the_right():
    xs = [column(draw(AWAY_SACK, s / 100), ff.SCRIMMAGE)[0] for s in range(40, 100, 5)]
    assert xs == sorted(xs) and abs(xs[-1] - LAYOUT.px(46)) <= 1


def test_a_sack_for_no_loss_plays_the_burst_without_a_slide():
    xs = {column(draw(ZERO, s / 100), ff.SCRIMMAGE)[0] for s in range(0, 100, 10)}
    assert xs == {LAYOUT.px(40)}


def test_a_sack_for_no_loss_still_has_its_burst(monkeypatch):
    calls = []
    monkeypatch.setattr(fs, "draw_burst", lambda canvas, x, y, progress: calls.append(x))
    draw(ZERO, 0.5)
    assert calls == [LAYOUT.px(40)]


def test_the_sackers_number_stays_at_the_spot_in_red_once_it_has_settled():
    reds = [p for p, c in draw(SACK, 1.0).pixels.items() if c == fs.SACKER]
    assert reds and all(abs(x - LAYOUT.px(34)) <= 6 for x, _ in reds)
    assert not [p for p, c in draw(SACK, 0.2).pixels.items() if c == fs.SACKER]


REAL = ["sack", "sack_zero", "sack_at_midfield"]


@pytest.mark.parametrize("label", REAL)
@pytest.mark.parametrize("off", ["NYG", "WSH"])
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.1, 0.3, 0.4, 0.5, 0.6, 0.7, 0.9, 1.0, 2.0])
def test_every_real_sack_draws_inside_the_panel_at_every_moment(label, off, width, share):
    play = make_play(1, label, off=off)
    c = draw(play, share, width=width)
    assert c.pixels
    assert all(y <= FIELD_BOTTOM for (x, y), col in c.pixels.items() if col == ff.BALL)


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,play,share,width",
    [
        ("drop", SACK, 0.25, 128),
        ("hit", SACK, 0.5, 128),
        ("slide", SACK, 0.72, 128),
        ("settled", SACK, 1.0, 128),
        ("away_settled", AWAY_SACK, 1.0, 128),
        ("hit_64", SACK, 0.5, 64),
    ],
)
def test_snapshot(name, play, share, width, update_snapshots):
    check_snapshot(f"sack_{name}", draw(play, share, width=width).render(), update_snapshots)
