"""The in-game screen lengths as ``[football]`` settings (#445)."""

from __future__ import annotations

import dataclasses

from nhl_scoreboard.config import FOOTBALL_TIMING_RANGES, FootballConfig, Settings
from nhl_scoreboard.football import events as ev
from nhl_scoreboard.football.director import PLAY, PLAYTEXT, Timings, timings_from
from nhl_scoreboard.football.mode import NflMode
from test_football_director import started, td
from test_football_events import make_play


def test_the_settings_table_matches_the_directors_defaults_and_ranges():
    default = Timings()
    for name, (value, low, high) in FOOTBALL_TIMING_RANGES.items():
        assert getattr(default, name) == value, name
        too_low = dataclasses.replace(default, **{name: low - 100}).clamped()
        too_high = dataclasses.replace(default, **{name: high + 100}).clamped()
        assert (getattr(too_low, name), getattr(too_high, name)) == (low, high), name
    assert set(FOOTBALL_TIMING_RANGES) == {f.name for f in dataclasses.fields(Timings)}


def test_the_defaults_are_the_proposed_timings():
    assert timings_from(FootballConfig()) == Timings()


def test_out_of_range_and_garbage_values_are_held_or_defaulted():
    cfg = FootballConfig(
        play_seconds=99, playtext_seconds=0, score_seconds="slow", reversal_seconds=7
    )
    assert cfg.play_seconds == 8.0 and cfg.playtext_seconds == 2.0
    assert cfg.score_seconds == 6.0 and cfg.reversal_seconds == 7.0


def test_the_owners_lengths_reach_the_director():
    rig = started(make_play(1, "rush", off="WSH"))
    rig.director._timings = lambda: timings_from(
        FootballConfig(
            favourite_team="NYG", score_seconds=12, score_detail_seconds=5, playtext_seconds=9
        )
    )
    rig.poll(make_play(1, "rush", off="WSH"), td())
    stages = rig.run()
    by_stage = {(s.stage, type(s.event).__name__): s.seconds for s in stages}
    assert by_stage[("event", "Touchdown")] == 12.0
    assert by_stage[("detail", "Touchdown")] == 5.0
    assert stages[-1].stage == PLAYTEXT and stages[-1].seconds >= 9.0
    assert stages[0].stage == PLAY and isinstance(stages[1].event, ev.Touchdown)


def test_nflmode_builds_its_timings_from_the_football_settings():
    cfg = FootballConfig(favourite_team="NYG", score_seconds=11)
    mode = NflMode(client_factory=lambda: None, football=lambda: cfg)
    assert mode.director._timings().score == 11.0
    cfg.score_seconds = 13  # read afresh each time, so an admin change needs no restart
    assert mode.director._timings().score == 13.0
    plain = NflMode(client_factory=lambda: None)
    assert plain.director._timings().score == 6.0


def test_the_lengths_round_trip_through_the_config_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[football]\nfavourite_team = 'NYG'\n")
    Settings.load(path).save({"football": {"score_seconds": 10.0, "cointoss_seconds": 5.0}})
    football = Settings.load(path).football
    assert (football.score_seconds, football.cointoss_seconds) == (10.0, 5.0)
    assert football.play_seconds == 3.0
