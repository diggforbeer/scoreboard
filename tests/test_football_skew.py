"""``SkewLog``: when the scoreboard names a play and when the plays feed first has it."""

from __future__ import annotations

import logging

from scoreboard.football.models import FbGame
from scoreboard.football.skew import SkewLog
from test_football_events import make_game, make_play
from test_football_queue import Clock


def game_naming(play_id: str | None, kind: str = "Punt") -> FbGame:
    game = make_game()
    if play_id is None:
        return game
    comp = {
        "id": "1",
        "status": {"type": {"state": "in", "name": "STATUS_IN_PROGRESS"}},
        "competitors": [
            {"homeAway": ha, "score": "0", "team": {"id": str(i), "abbreviation": a}}
            for ha, i, a in (("home", game.home.espn_id, "NYG"), ("away", game.away.espn_id, "WSH"))
        ],
        "situation": {"lastPlay": {"id": play_id, "type": {"text": kind}}},
    }
    return FbGame.from_api({"id": "1", "competitions": [comp]})


def lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name.endswith("football.skew")]


def test_logs_when_the_scoreboard_names_a_play_and_when_the_feed_catches_up(caplog):
    caplog.set_level(logging.INFO)
    clock = Clock()
    skew = SkewLog(clock)
    skew.observe(game_naming("p0002"), [make_play(1, "rush")])
    clock.advance(11.0)
    skew.observe(game_naming("p0002"), [make_play(1, "rush"), make_play(2, "rush")])
    out = lines(caplog)
    assert out[0].startswith("[1] scoreboard names play p0002 (Punt); plays feed has it: no")
    assert out[1] == "[1] plays feed has p0002 (Punt) 11.0s after the scoreboard named it"
    assert len(out) == 2


def test_a_play_the_feed_already_has_is_reported_at_once(caplog):
    caplog.set_level(logging.INFO)
    skew = SkewLog(Clock())
    skew.observe(game_naming("p0001"), [make_play(1, "rush")])
    out = lines(caplog)
    assert "plays feed has it: yes" in out[0]
    assert out[1].endswith("0.0s after the scoreboard named it")


def test_a_named_play_the_feed_never_lists_is_reported_once_the_game_moves_on(caplog):
    caplog.set_level(logging.INFO)
    skew = SkewLog(Clock())
    feed = [make_play(1, "rush")]
    for n in range(1, 6):
        skew.observe(game_naming(f"x{n}"), feed)
    out = lines(caplog)
    assert sum("never listed" in line for line in out) == 2  # x1 and x2, once x4 is named
    assert not any("x4" in line and "never" in line for line in out)


def test_the_same_play_is_not_logged_twice_and_no_situation_is_silent(caplog):
    caplog.set_level(logging.INFO)
    skew = SkewLog(Clock())
    for _ in range(3):
        skew.observe(game_naming("p0001"), [make_play(1, "rush")])
        skew.observe(game_naming(None), [make_play(1, "rush")])
    assert len(lines(caplog)) == 2


def test_forget_drops_finished_games(caplog):
    caplog.set_level(logging.INFO)
    skew = SkewLog(Clock())
    skew.observe(game_naming("p0009"), [])
    skew.forget(lambda game_id: False)
    skew.observe(game_naming("p0009"), [])
    assert sum("scoreboard names play p0009" in line for line in lines(caplog)) == 2
