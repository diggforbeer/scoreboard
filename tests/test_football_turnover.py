"""``fb_turnover`` (#394): interception, fumble, sack-fumble, muffed punt and turnover on downs.
Events come from the real ``EventDetector`` for the real plays, so the favourite relation, the
reason and the teams are the ones the detector produces."""

from __future__ import annotations

import dataclasses

import pytest

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.app import Scene
from nhl_scoreboard.display import football_plays as fp
from nhl_scoreboard.display import football_turnover as ft
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import EVENT
from test_football_events import detector, make_game, make_play
from test_football_scenes import check_snapshot, renderer


def turnover(label, off, end, favourite="NYG", down=None, follow=()):
    det, game, _ = detector(favourite, follow)
    play = make_play(1, label, off=off, end=end, down=down)
    (event,) = [e for e in det.on_plays(game, [play]) if isinstance(e, ev.Turnover)]
    return event


# NYG is the home team (left) and the favourite; WSH is the visitor (right).
PICK_LOST = turnover(
    "interception_return", "NYG", "WSH"
)  # NYG throws it away: red, arrow to the right
PICK_GAINED = turnover("interception_return", "WSH", "NYG")  # NYG picks it off: green
FUMBLE = turnover("fumble_opponent", "NYG", "WSH")
SACK_FUMBLE = turnover("sack_fumble", "NYG", "WSH")
MUFF = turnover("muffed_punt", "NYG", "WSH")
DOWNS = turnover("rush", "NYG", "WSH", down=4)
OTHERS = turnover("interception_return", "WSH", "NYG", favourite="DAL", follow=["NYG"])


def scene(event, share=1.0):
    return Scene(
        "fb_event",
        fb_game=make_game(),
        fb_play=event.play,
        fb_event=event,
        fb_stage=EVENT,
        fb_elapsed=share * 4.0,
        fb_seconds=4.0,
        animating=True,
    )


def draw(event, share=1.0, width=128, art=None):
    canvas = AsciiCanvas(width, 32)
    r = renderer(width)
    r.nfl_logos = art
    r.draw_fb_play_scene(canvas, scene(event, share))
    assert not canvas.out_of_bounds
    return canvas


def logos(tmp_path):
    base = write_synthetic_nfl_logos(tmp_path) / "nfl"
    libs = {s: LogoLibrary([base / str(s) / "dark"], s) for s in (12, 16)}
    return LogoSet("nfl", "dark", libs)


# -- the words and the colour --------------------------------------------------------


def test_it_is_registered_for_turnover_events():
    assert fp.EVENT_SCREENS[(ev.Turnover, EVENT)] is ft.draw_turnover


@pytest.mark.parametrize(
    "event,title,tag",
    [
        (PICK_LOST, "INTERCEPTION", "INT"),
        (FUMBLE, "FUMBLE", "FUM"),
        (SACK_FUMBLE, "SACK-FUMBLE", "SACK FUM"),
        (MUFF, "MUFFED PUNT", "MUFF"),
        (DOWNS, "ON DOWNS", ""),
    ],
)
def test_the_headline_and_the_tag_by_reason(event, title, tag):
    assert ft.title(scene(event)) == title and ft.TAGS[event.reason] == tag


def test_an_unrecognised_reason_is_just_a_turnover():
    odd = dataclasses.replace(PICK_LOST, reason="turnover")
    assert ft.title(scene(odd)) == "TURNOVER" and ft.detail(scene(odd)).startswith("TURNOVER")


def test_the_alert_is_green_when_the_favourite_gains_red_when_it_loses_and_amber_otherwise():
    assert ft.alert_color(scene(PICK_GAINED)) == fp.GAIN
    assert ft.alert_color(scene(PICK_LOST)) == fp.LOSS
    assert ft.alert_color(scene(OTHERS)) == fp.NEUTRAL


def test_who_took_it_and_where_from_the_play_text():
    assert ft.taker(scene(PICK_LOST)) == "B.CARTER"
    assert ft.spot(scene(PICK_LOST)) == "ATL 43"
    assert ft.detail(scene(PICK_LOST)) == "INT  B.CARTER  ATL 43"
    assert ft.taker(scene(FUMBLE)) == "T.CAMPBELL"
    assert ft.detail(scene(FUMBLE)).startswith("FUM  T.CAMPBELL")
    assert ft.detail(scene(SACK_FUMBLE)).startswith("SACK FUM  C.CURRY")
    assert ft.detail(scene(MUFF)).startswith("MUFF  R.UNDERWOOD")


def test_a_turnover_on_downs_says_who_has_the_ball_instead_of_repeating_the_headline():
    assert ft.detail(scene(DOWNS)).startswith("WSH  BALL")


def test_the_home_team_is_on_the_left_as_on_the_field():
    assert ft.sides(scene(PICK_LOST)) == ("NYG", "WSH")


# -- the animation -------------------------------------------------------------------


def row(canvas, y, x0=0, x1=128):
    return [x for x in range(x0, x1) if (x, y) in canvas.pixels]


def arrow_extent(event, share):
    cells = row(draw(event, share), 22, 22, 106)
    return (min(cells), max(cells)) if cells else None


def test_the_arrow_draws_from_the_team_that_lost_the_ball_toward_the_one_that_gained_it():
    assert arrow_extent(PICK_LOST, 0.05) is None, "not yet"
    early, late = arrow_extent(PICK_LOST, 0.3), arrow_extent(PICK_LOST, 0.6)
    assert early[0] < 30 and late[1] > early[1], "growing to the right: NYG lost it, WSH gained it"
    early, late = arrow_extent(PICK_GAINED, 0.3), arrow_extent(PICK_GAINED, 0.6)
    assert early[1] > 100 and late[0] < early[0], "growing to the left: the favourite picked it off"


def test_a_ball_rides_the_tip_of_the_arrow():
    c = draw(PICK_LOST, 0.4)
    ball = [p for p, col in c.pixels.items() if col == (214, 130, 54)]
    tip = max(x for x in row(c, 22, 22, 106))
    assert ball and abs(max(x for x, _ in ball) - tip) <= 4


def test_the_possession_logo_swaps_sides_when_the_arrow_lands(tmp_path):
    art = logos(tmp_path)
    from nhl_scoreboard.football.teams import team_color

    def brightness(canvas, x0, x1, team):
        return sum(
            1 for (x, y), c in canvas.pixels.items() if x0 <= x < x1 and c == team_color(team)
        )

    before, after = draw(PICK_LOST, 0.3, art=art), draw(PICK_LOST, 0.9, art=art)
    assert brightness(before, 0, 24, "NYG") > 0, "NYG (who lost it) bright before"
    assert brightness(after, 0, 24, "NYG") == 0, "and dimmed after"
    assert brightness(after, 104, 128, "WSH") > 0, "WSH (who gained it) bright after"
    assert brightness(before, 104, 128, "WSH") == 0


def test_the_headline_fades_in_and_the_detail_comes_last():
    assert len(draw(PICK_LOST, 0.0).pixels) < len(draw(PICK_LOST, 0.3).pixels)
    assert not [p for p in draw(PICK_LOST, 0.5).pixels if p[1] >= 27]
    assert [p for p in draw(PICK_LOST, 0.95).pixels if p[1] >= 27]
    assert draw(PICK_LOST, 0.9).pixels == draw(PICK_LOST, 1.0).pixels


def test_the_title_takes_the_alert_colour():
    for event, color in ((PICK_GAINED, fp.GAIN), (PICK_LOST, fp.LOSS), (OTHERS, fp.NEUTRAL)):
        assert color in draw(event, 0.5).pixels.values()


def test_a_64px_panel_has_no_logos_but_keeps_the_words_and_the_arrow():
    c = draw(PICK_LOST, 1.0, 64)
    assert c.pixels and all(x < 64 for x, _ in c.pixels)
    assert [p for p in c.pixels if p[1] >= 27], "the detail"


def test_a_team_that_is_not_one_of_the_32_never_raises():
    odd = dataclasses.replace(PICK_LOST, team="AFC", lost_by="NFC")
    for width in (128, 64):
        assert draw(odd, 1.0, width).pixels


@pytest.mark.parametrize(
    "event",
    [PICK_LOST, PICK_GAINED, FUMBLE, SACK_FUMBLE, MUFF, DOWNS, OTHERS],
    ids=["lost", "gained", "fumble", "sack_fumble", "muff", "downs", "others"],
)
@pytest.mark.parametrize("width", [128, 64])
@pytest.mark.parametrize("share", [0.0, 0.05, 0.12, 0.3, 0.5, 0.6, 0.7, 0.9, 1.0, 2.0])
def test_every_moment_draws_inside_the_panel(event, width, share):
    assert draw(event, share, width).pixels


# -- snapshots -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,event,share,width",
    [
        ("lost", PICK_LOST, 0.9, 128),
        ("arrow", PICK_LOST, 0.35, 128),
        ("gained", PICK_GAINED, 0.9, 128),
        ("fumble", FUMBLE, 0.9, 128),
        ("sack_fumble", SACK_FUMBLE, 0.9, 128),
        ("downs", DOWNS, 0.9, 128),
        ("others", OTHERS, 0.9, 128),
        ("lost_64", PICK_LOST, 0.9, 64),
    ],
)
def test_snapshot(name, event, share, width, update_snapshots):
    check_snapshot(f"turnover_{name}", draw(event, share, width).render(), update_snapshots)
