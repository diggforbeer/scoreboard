"""The red zone marker on a live college game (#562), built on ESPN's ``isRedZone`` flag as sent.

The drawing is the NFL's (the field tints the 20 yards the offence attacks and the down and
distance turns red); these tests pin that a college game gets it, on the right side, with real
FBS teams, and that missing or contradictory data draws nothing. The flag itself is taken as
ESPN sends it: it was never seen true in the one live game captured (Clemson at Duke), so the
rule "inside the opponent's 20" is *not* applied by us (``football_api.md``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scoreboard.display import football_scenes as fs
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.display.football_field import RED_ZONE_TINT
from scoreboard.football.geometry import FieldLayout
from scoreboard.football.models import FbGame
from scoreboard.football.redzone import attacking_team
from scoreboard.football.teams import use_directory
from test_football_college import _fbs_directory
from test_football_scenes import H, check_snapshot, renderer

FBS = _fbs_directory()
CLEM, DUKE = 228, 150
LIVE_FIXTURES = Path(__file__).parent / "fixtures" / "football" / "live"


def college_game(sit, *, short="9:30 - 4th", name="STATUS_IN_PROGRESS", period=4, a=10, h=7):
    comp = {
        "id": "401858303",
        "status": {
            "period": period,
            "displayClock": short.split(" ")[0],
            "clock": 570.0,
            "type": {
                "state": "in",
                "name": name,
                "shortDetail": short,
                "detail": short,
                "completed": False,
            },
        },
        "competitors": [
            {
                "homeAway": "home",
                "score": str(h),
                "team": {"id": str(DUKE), "abbreviation": "DUKE"},
            },
            {
                "homeAway": "away",
                "score": str(a),
                "team": {"id": str(CLEM), "abbreviation": "CLEM"},
            },
        ],
    }
    if sit is not None:
        comp["situation"] = sit
    with use_directory(FBS):
        return FbGame.from_api({"id": "401858303", "competitions": [comp]})


def sit(possession, *, red, yard=9, text="1st & Goal at DUKE 9", short="1st & Goal"):
    return {
        "down": 1,
        "distance": 9,
        "yardLine": yard,
        "downDistanceText": text,
        "shortDownDistanceText": short,
        "possession": None if possession is None else str(possession),
        "isRedZone": red,
        "homeTimeouts": 3,
        "awayTimeouts": 3,
    }


def field(g, width=128) -> AsciiCanvas:
    c = AsciiCanvas(width, H)
    with use_directory(FBS):
        renderer(width).draw_fb_field(c, g)
    assert not c.out_of_bounds
    return c


def board(g, width=128) -> AsciiCanvas:
    c = AsciiCanvas(width, H)
    with use_directory(FBS):
        renderer(width).draw_fb_scores(c, g)
    assert not c.out_of_bounds
    return c


def tint_columns(c: AsciiCanvas, width=128):
    return sorted({x for (x, y), rgb in c.pixels.items() if rgb == RED_ZONE_TINT and y > 8})


# -- which end is tinted --------------------------------------------------------------------------


def test_clemson_away_with_the_ball_in_the_red_zone_tints_the_home_end_it_attacks():
    # The away team drives toward 0: the left end, the 20 yards from the home goal line.
    layout = FieldLayout.for_panel(128)
    cols = tint_columns(field(college_game(sit(CLEM, red=True, yard=9))))
    assert cols, "the red zone is marked"
    assert min(cols) >= layout.px(0) and max(cols) <= layout.px(20)


def test_duke_home_with_the_ball_in_the_red_zone_tints_the_far_end():
    layout = FieldLayout.for_panel(128)
    g = college_game(sit(DUKE, red=True, yard=91, text="1st & Goal at CLEM 9"))
    cols = tint_columns(field(g))
    assert cols and min(cols) >= layout.px(80) and max(cols) <= layout.px(100)


def test_the_down_and_distance_turns_red_on_the_field_band_and_the_scoreboard():
    g = college_game(sit(CLEM, red=True))
    assert fs.RED_ZONE in field(g).colors(64, 0, 127, 7)
    assert fs.RED_ZONE in board(g).colors(0, 14, 127, 21)


def test_a_single_64px_panel_still_marks_it():
    g = college_game(sit(CLEM, red=True))
    c = field(g, 64)
    assert tint_columns(c, 64) and fs.RED_ZONE in c.colors(0, 0, 63, 7)


# -- the flag is taken as sent ---------------------------------------------------------------


def test_inside_the_20_without_the_flag_draws_nothing_red():
    # Clemson at the DUKE 13: inside the 20, but ESPN did not say so, so neither do we.
    g = college_game(sit(CLEM, red=False, yard=13, text="2nd & 3 at DUKE 13", short="2nd & 3"))
    assert not tint_columns(field(g))
    assert fs.RED_ZONE not in field(g).colors(0, 0, 127, 7)
    assert fs.RED_ZONE not in board(g).colors(0, 14, 127, 21)


def test_the_flag_with_no_one_in_possession_tints_no_end():
    g = college_game(sit(None, red=True))
    assert not tint_columns(field(g))
    assert fs.RED_ZONE not in field(g).colors(0, 0, 127, 7), "nobody to mark: the band stays plain"


def test_the_nulls_the_real_feed_sent_draw_nothing_red_and_do_not_fail():
    # Real halftime-time shape: flag false, possession and both texts null (Clemson at Duke).
    g = college_game(sit(None, red=False, text=None, short=None))
    assert not tint_columns(field(g)) and fs.RED_ZONE not in board(g).colors(0, 0, 127, 31)
    flagged = college_game(sit(None, red=True, text=None, short=None))
    assert not tint_columns(field(flagged)) and fs.RED_ZONE not in board(flagged).colors(
        0, 14, 127, 21
    )


def test_no_situation_at_all_draws_the_plain_field():
    assert not tint_columns(field(college_game(None)))


# -- never at the half ----------------------------------------------------------------------------


def test_the_real_end_of_2nd_quarter_payload_is_not_a_red_zone_even_if_flagged():
    raw = json.loads((LIVE_FIXTURES / "clemson_duke_end_of_2nd.json").read_text())
    raw["competitions"][0]["situation"]["isRedZone"] = True
    raw["competitions"][0]["situation"]["possession"] = str(CLEM)
    with use_directory(FBS):
        g = FbGame.from_api(raw)
    assert g.is_halftime and attacking_team(g) is None


# -- the snapshot -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "possession", "yard"), [("clemson_goal_to_go", CLEM, 9), ("duke_goal_to_go", DUKE, 91)]
)
def test_the_red_zone_field_snapshot(update_snapshots, name, possession, yard):
    text = "1st & Goal at DUKE 9" if possession == CLEM else "1st & Goal at CLEM 9"
    g = college_game(sit(possession, red=True, yard=yard, text=text))
    check_snapshot(f"fb_field_college_redzone_{name}", field(g).render(), update_snapshots)


# -- the band when the score is wide (found in the mockups) ----------------------------------------


def band_columns(c: AsciiCanvas, color):
    return sorted({x for (x, y), rgb in c.pixels.items() if y <= 6 and rgb == color})


def test_a_two_digit_score_between_four_letter_teams_does_not_run_into_the_down_and_distance():
    # CLEM 17 DUKE 10 with 1ST&GOAL did print the 10 over the 1ST: no room for all of it.
    g = college_game(sit(DUKE, red=True, yard=91, text="1st & Goal at CLEM 9"), a=17, h=10)
    c = field(g)
    white, red = band_columns(c, fs.WHITE), band_columns(c, fs.RED_ZONE)
    assert white and red
    assert min(red) - max(white) >= 3, "a clear gap between the score and the down"


def test_the_down_shrinks_only_when_the_score_leaves_no_room():
    tight = college_game(sit(DUKE, red=True, yard=91, text="1st & Goal at CLEM 9"), a=17, h=10)
    roomy = college_game(sit(DUKE, red=True, yard=91, text="1st & Goal at CLEM 9"), a=3, h=0)
    wide = band_columns(field(roomy), fs.RED_ZONE)
    narrow = band_columns(field(tight), fs.RED_ZONE)
    assert len(wide) > len(narrow), "the short score keeps the full 1ST&GOAL"


def test_goal_to_go_shrinks_to_the_down_and_a_g_and_other_downs_to_down_and_distance():
    from scoreboard.display.football_scenes import _squeezed_down
    from scoreboard.football.models import FbSituation

    goal = FbSituation.from_api(sit(CLEM, red=True))
    other = FbSituation.from_api(
        sit(CLEM, red=False, yard=40, text="3rd & 7 at DUKE 40", short="3rd & 7")
        | {"down": 3, "distance": 7}
    )
    assert _squeezed_down(goal) == "1&G"
    assert _squeezed_down(other) == "3&7"


# -- the clock is never cut (found checking the NFL: it has been wrong there all along) ------------


def clock_columns(c: AsciiCanvas):
    """The columns the band's game clock lit (it is drawn in the live-game colour)."""
    return sorted({x for (x, y), rgb in c.pixels.items() if y <= 6 and rgb == fs.LIVE})


@pytest.mark.parametrize("short", ["10:30 - 4th", "15:00 - 1st", "12:24 - 3rd"])
def test_a_goal_to_go_down_does_not_cut_a_two_digit_minute_clock(short):
    # 1ST&GOAL left 33px for ``4TH 10:30`` (36px): it read ``4TH 1...``, a minute left.
    goal = college_game(sit(CLEM, red=True), short=short, a=3, h=0)
    plain = college_game(
        sit(CLEM, red=False, yard=40, text="3rd & 7 at DUKE 40", short="3rd & 7"),
        short=short,
        a=3,
        h=0,
    )
    assert clock_columns(field(goal)) == clock_columns(field(plain)), "the whole clock is drawn"
