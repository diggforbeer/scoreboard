"""Real payloads from Clemson at Duke (2026-11-20), the first live college game captured.

They pin what the feed actually did around halftime: the quarter-end window that is still
``STATUS_IN_PROGRESS``, and a live ``situation`` whose possession and down-and-distance text are
empty while ``down``/``distance`` are set.
"""

import json
from pathlib import Path

from scoreboard.football.models import FbGame

LIVE = Path(__file__).parent / "fixtures" / "football" / "live"


def game(name: str) -> FbGame:
    return FbGame.from_api(json.loads((LIVE / f"{name}.json").read_text()))


def test_the_last_seconds_of_the_half_are_a_live_game_not_halftime():
    g = game("clemson_duke_q2_last_seconds")
    assert g.is_live and not g.is_halftime
    assert g.period == 2


def test_end_of_2nd_quarter_is_halftime_though_the_status_is_still_in_progress():
    g = game("clemson_duke_end_of_2nd")
    assert g.status_name == "STATUS_IN_PROGRESS"
    assert g.is_live and g.is_halftime


def test_the_real_halftime_status_is_halftime():
    g = game("clemson_duke_halftime")
    assert g.status_name == "STATUS_HALFTIME"
    assert g.is_halftime


def test_a_situation_with_empty_text_and_no_possession_parses():
    for name in ("clemson_duke_end_of_2nd", "clemson_duke_halftime"):
        s = game(name).situation
        assert s is not None
        assert (s.down, s.distance) == (2, 10)
        assert s.down_distance_text == ""
        assert not s.is_red_zone
    assert game("clemson_duke_halftime").situation.possession_team_id is None
    assert game("clemson_duke_end_of_2nd").situation.possession_team_id == 150


def test_only_the_second_quarter_end_counts_as_halftime():
    g = game("clemson_duke_end_of_2nd")
    assert g.period == 2
    import dataclasses

    q1 = dataclasses.replace(g, period=1, detail="End of 1st Quarter")
    q4 = dataclasses.replace(g, period=4, detail="End of 4th Quarter")
    assert not q1.is_halftime and not q4.is_halftime
