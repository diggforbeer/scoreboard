"""The idle rotation makes room for college football (#579).

College screens have their own names (``cfb_*``), so the one ``[[rotation]]`` list can hold them,
the alternation gives college a segment of its own, and a college board with nothing on draws its
rows through the same dispatch as the other sports. No college screen is drawn yet (they arrive
with #551-#556): these tests register stand-ins, and show that with none the board skips college
instead of holding it on the plain scoreboards.
"""

from __future__ import annotations

import logging

import pytest

from scoreboard.config import (
    COLLEGE_SCREENS,
    DEFAULT_COLLEGE_ROTATION,
    DEFAULT_FOOTBALL_ROTATION,
    FOOTBALL_SCREENS,
    VALID_ROTATION_SCREENS,
    RotationEntry,
    Settings,
    _parse_rotation,
    screen_sport,
)
from scoreboard.display.college_idle import COLLEGE_DRAWERS, college_screen
from scoreboard.display.matrix import Backend
from scoreboard.football.idle_screens import IDLE_SCREENS
from scoreboard.priority import idle_segments, segment_at
from teamcfg import fcfg
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_app_college import CollegeRig, scoreboard
from test_app_priority import idle_runs, nsh_far

H, F, C = "hockey", "football", "college"


@pytest.fixture
def backend():
    return Backend(
        name="fake", RGBMatrix=FakeMatrix, RGBMatrixOptions=FakeOptions, graphics=FakeGraphics
    )


class Row:
    def __init__(self, screen, seconds):
        self.screen, self.seconds = screen, float(seconds)


def shape(segments):
    return [(s.sport, [e.screen for e in s.entries], s.seconds) for s in segments]


# -- the names ----------------------------------------------------------------------------------


def test_every_college_screen_is_college_s_and_a_valid_rotation_row():
    assert COLLEGE_SCREENS == (
        "cfb_preview",
        "cfb_ap",
        "cfb_cfp",
        "cfb_conference",
        "cfb_week",
        "cfb_schedule",
        "cfb_scores",
    )
    for screen in COLLEGE_SCREENS:
        assert screen_sport(screen) == C and screen in VALID_ROTATION_SCREENS
    assert not set(COLLEGE_SCREENS) & set(FOOTBALL_SCREENS), "the NFL's names stay the NFL's"
    assert all(screen_sport(s) == F for s in FOOTBALL_SCREENS)


def test_the_loader_keeps_college_rows_and_still_drops_unknown_ones(caplog):
    raw = [
        {"screen": "cfb_ap", "seconds": 8},
        {"screen": "CFB_Preview", "seconds": "6"},
        {"screen": "cfb_nope", "seconds": 8},
        {"screen": "fb_ap", "seconds": 8},
    ]
    with caplog.at_level(logging.WARNING):
        rows = _parse_rotation(raw)
    assert [(r.screen, r.seconds) for r in rows] == [("cfb_ap", 8.0), ("cfb_preview", 6.0)]
    assert "cfb_nope" in caplog.text and "fb_ap" in caplog.text
    loaded = Settings.from_dict({"rotation": [{"screen": "cfb_cfp", "seconds": 9}]})
    assert [r.screen for r in loaded.rotation] == ["cfb_cfp"]


def test_the_default_college_rotation_is_the_next_game_first_and_ends_on_the_clock():
    names = [s for s, _ in DEFAULT_COLLEGE_ROTATION]
    assert names[0] == "cfb_preview" and names[-1] == "clock"
    assert set(names) <= set(COLLEGE_SCREENS) | {"clock"}
    assert "cfb_cfp" not in names and "cfb_scores" not in names, "the opt-in ones"
    assert DEFAULT_FOOTBALL_ROTATION[0][0] == "fb_preview", "the NFL's is unchanged"


# -- the segments across three sports ------------------------------------------------------------


def test_three_sports_form_three_segments_and_the_clock_joins_the_run_before_it():
    entries = [
        Row("standings", 8),
        Row("cfb_ap", 8),
        Row("cfb_week", 10),
        Row("fb_week", 10),
        Row("clock", 6),
    ]
    assert shape(idle_segments(entries, [H, F, C])) == [
        (H, ["standings"], 8),
        (C, ["cfb_ap", "cfb_week"], 18),
        (F, ["fb_week", "clock"], 16),
    ]


def test_a_sport_that_is_not_available_loses_its_rows_and_its_neighbours_merge():
    entries = [Row("cfb_ap", 8), Row("fb_week", 10), Row("cfb_week", 10)]
    assert shape(idle_segments(entries, [F, C])) == [
        (C, ["cfb_ap"], 8),
        (F, ["fb_week"], 10),
        (C, ["cfb_week"], 10),
    ]
    assert shape(idle_segments(entries, [C])) == [(C, ["cfb_ap", "cfb_week"], 18)]
    assert idle_segments(entries, [H]) == []


def test_a_college_segment_takes_its_turn_in_the_clock_s_cycle():
    segments = idle_segments([Row("standings", 10), Row("cfb_ap", 20)], [H, C])
    assert segment_at(segments, 5.0) == (0, 0.5)
    assert segment_at(segments, 10.0) == (1, 0.0)
    assert segment_at(segments, 35.0) == (0, 0.5), "it wraps"


# -- the app ------------------------------------------------------------------------------------


@pytest.fixture
def screens():
    """Stand-in college screens (restored after): ``cfb_preview`` shows, ``cfb_ap`` has nothing."""
    saved, drawers = dict(IDLE_SCREENS), dict(COLLEGE_DRAWERS)
    drawn = []
    IDLE_SCREENS["cfb_preview"] = lambda ctx: True
    IDLE_SCREENS["cfb_ap"] = lambda ctx: False
    college_screen("cfb_preview")(lambda r, canvas, scene, now: drawn.append(scene.kind))
    yield drawn
    IDLE_SCREENS.clear()
    IDLE_SCREENS.update(saved)
    COLLEGE_DRAWERS.clear()
    COLLEGE_DRAWERS.update(drawers)


def far_college_game():
    payload = scoreboard(state="pre")
    for node in (payload["events"][0], payload["events"][0]["competitions"][0]):
        for key in ("date", "startDate"):
            if key in node:
                node[key] = "2026-11-28T20:30Z"
    return payload


def rig(backend, teams, rotation=None):
    r = CollegeRig(backend, teams, far_college_game())
    r.hockey.today = [nsh_far()]
    if rotation is not None:
        r.settings.rotation = [RotationEntry(s, float(sec)) for s, sec in rotation]
    r.poll(1)
    return r


def test_college_sits_out_the_alternation_until_it_has_a_row_it_can_draw(backend):
    # Only rows with nothing to show here (no polls fetched): the preview, now built (#554), has
    # a next game on this slate, so it is left out of the rotation to make the premise true.
    r = rig(backend, [("hockey", "NSH"), ("college", "UGA")], [("cfb_ap", 20), ("cfb_cfp", 20)])
    assert r.app._college.snapshot.games, "it has a slate"
    assert not r.app._college.has_idle_rows()
    assert r.app._idle_available() == ["hockey"]
    assert {s for s, _ in idle_runs(r, seconds=200)} == {"hockey"}


def test_college_takes_its_turn_beside_hockey_once_a_screen_can_draw(backend, screens):
    r = rig(backend, [("hockey", "NSH"), ("college", "UGA")])
    assert r.app._college.has_idle_rows()
    assert r.app._idle_available() == ["hockey", "college"]
    runs = idle_runs(r, seconds=400)
    assert {s for s, _ in runs} == {"hockey", "college"}
    assert r.app._unified_rotation()[-1].screen == "clock"
    kinds = set()
    for _ in range(60):
        r.poll(3)
        if r.sport == "college":
            kinds.add(r.app.select_scene().kind)
    assert "cfb_preview" in kinds and kinds <= {"cfb_preview", "clock"}, "never the scoreboards"


def test_the_default_rotation_orders_the_sports_by_their_lead_ranks(backend):
    college_first = rig(backend, [("college", "UGA"), ("hockey", "NSH")])
    screens_ = [e.screen for e in college_first.app._unified_rotation()]
    assert screens_[0] == "cfb_preview" and screens_.index("cfb_preview") < screens_.index(
        "countdown_preview"
    )
    hockey_first = rig(backend, [("hockey", "NSH"), ("college", "UGA")])
    screens_ = [e.screen for e in hockey_first.app._unified_rotation()]
    assert screens_.index("countdown_preview") < screens_.index("cfb_preview")
    assert [e.screen for e in hockey_first.app._sport_rotation(C)] == [
        s for s, _ in DEFAULT_COLLEGE_ROTATION
    ]
    nfl = [e.screen for e in hockey_first.app._sport_rotation(F)]
    assert nfl == [s for s, _ in DEFAULT_FOOTBALL_ROTATION], "football's is still its own"


def test_a_mixed_list_gives_college_only_its_own_rows(backend, screens):
    r = rig(
        backend,
        [("hockey", "NSH"), ("college", "UGA")],
        [("standings", 20), ("cfb_preview", 20), ("clock", 5)],
    )
    assert [e.screen for e in r.app._sport_rotation(C)] == ["cfb_preview", "clock"]
    segments = idle_segments(r.app._unified_rotation(), r.app._idle_available())
    assert shape(segments) == [(H, ["standings"], 20), (C, ["cfb_preview", "clock"], 25)]
    assert [e.screen for e in r.app._college._entries()] == ["cfb_preview", "clock"]


def test_a_college_row_with_nothing_to_show_is_skipped_never_blank(backend, screens):
    r = rig(
        backend,
        [("college", "UGA"), ("hockey", "NSH")],
        [("cfb_ap", 20), ("cfb_preview", 20)],
    )
    kinds = set()
    for _ in range(40):
        r.poll(2)
        if r.sport == "college":
            kinds.add(r.app.select_scene().kind)
    assert kinds == {"cfb_preview"}, "cfb_ap has nothing, so only the next row shows"


def test_the_drawer_dispatch_draws_a_college_scene_through_the_registry(backend, screens):
    r = rig(backend, [("college", "UGA"), ("hockey", "NSH")], [("cfb_preview", 20)])
    for _ in range(5):
        r.poll(3)
    scene = r.app.select_scene()
    assert scene.kind == "cfb_preview"
    r.app.draw_scene(scene)
    assert screens == ["cfb_preview"]


def test_the_nfl_never_gets_college_rows_and_college_never_gets_the_nfl_s(backend):
    r = rig(
        backend,
        [("hockey", "NSH"), ("college", "UGA")],
        [("fb_week", 10), ("cfb_week", 10), ("clock", 4)],
    )
    assert [e.screen for e in r.app._sport_rotation(C)] == ["cfb_week", "clock"]
    assert [e.screen for e in r.app._sport_rotation(F)] == ["fb_week", "clock"]


def test_no_idle_rows_before_data_on_a_single_panel_or_without_a_favourite(backend, screens):
    fresh = CollegeRig(backend, [("hockey", "NSH"), ("college", "UGA")], far_college_game())
    assert not fresh.app._college.snapshot.has_data
    assert not fresh.app._college.has_idle_rows(), "nothing fetched yet"
    r = rig(backend, [("hockey", "NSH"), ("college", "UGA")])
    mode = r.app._college
    assert mode.has_idle_rows()
    mode._wide = lambda: False
    assert not mode.has_idle_rows(), "the idle screens are 128px only"
    mode._wide = lambda: True
    mode._football = lambda: fcfg(favourite_team="")
    assert not mode.has_idle_rows(), "the idle screens are the favourite's"
