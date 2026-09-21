"""Favourite-mode flow: preview -> countdown -> live -> final (held) -> next preview.

The app takes an injectable wall clock and monotonic clock, so a whole game
day can be walked in a few lines without sleeping.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nhl_scoreboard.app import ScoreboardApp
from nhl_scoreboard.config import Settings
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import Game
from test_app import FakeGraphics, FakeMatrix, FakeOptions

FAV = "NSH"
PUCK_DROP = datetime(2026, 9, 23, 0, 0, tzinfo=UTC)  # 8:00 PM Toronto on the 22nd
NEXT_DROP = datetime(2026, 9, 24, 23, 0, tzinfo=UTC)


def game(gid: int, away: str, home: str, start: datetime, state: str = "FUT", **extra) -> Game:
    raw = {
        "id": gid,
        "gameState": state,
        "startTimeUTC": start.isoformat().replace("+00:00", "Z"),
        "awayTeam": {"abbrev": away, "score": extra.get("away_score", 0)},
        "homeTeam": {"abbrev": home, "score": extra.get("home_score", 0)},
        "period": extra.get("period", 0),
        "periodDescriptor": {"number": extra.get("period", 1), "periodType": "REG"},
        "clock": {"timeRemaining": "12:34", "inIntermission": extra.get("intermission", False)},
    }
    return Game.from_api(raw)


def tick(app: ScoreboardApp, clock: Clock, **delta) -> None:
    """Advance time and poll, as the real loop would have every minute."""
    clock.advance(**delta)
    app.refresh()


class Clock:
    """Wall and monotonic time that advance together."""

    def __init__(self, start: datetime) -> None:
        self.now = start
        self.mono = 1000.0

    def advance(self, **kwargs) -> None:
        delta = timedelta(**kwargs)
        self.now += delta
        self.mono += delta.total_seconds()


class FlowClient:
    def __init__(self) -> None:
        self.today: list[Game] = []
        self.season: list[Game] = []
        self.schedule_calls = 0
        self.fail_schedule = False

    def scores(self, date="now"):
        return list(self.today)

    def situation(self, game_id):
        return None

    def schedule(self, team):
        self.schedule_calls += 1
        if self.fail_schedule:
            raise NHLApiError("boom")
        return sorted(self.season, key=lambda g: g.start_utc)

    def close(self):
        pass


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


def make_app(fake_backend, clock: Clock, client: FlowClient, **cfg) -> ScoreboardApp:
    settings = Settings()
    settings.scoreboard.favourite_team = FAV
    settings.scoreboard.rotation = "favourite"
    for k, v in cfg.items():
        setattr(settings.scoreboard, k, v)
    return ScoreboardApp(
        settings,
        client=client,
        backend=fake_backend,
        clock=lambda: clock.now,
        monotonic=lambda: clock.mono,
    )


@pytest.fixture
def day(fake_backend):
    """A game day: the favourite hosts TBL tonight, plays CAR in two days."""
    client = FlowClient()
    tonight = game(1, "TBL", FAV, PUCK_DROP)
    client.today = [
        game(9, "SEA", "CGY", PUCK_DROP - timedelta(hours=1), "LIVE", period=2),
        tonight,
    ]
    client.season = [
        game(0, FAV, "DAL", PUCK_DROP - timedelta(days=3), "OFF"),
        tonight,
        game(2, FAV, "CAR", NEXT_DROP),
        game(3, "COL", FAV, NEXT_DROP + timedelta(days=2)),
    ]
    clock = Clock(PUCK_DROP - timedelta(hours=6))
    app = make_app(fake_backend, clock, client)
    app.refresh()
    return app, clock, client


def scene(app):
    s = app.select_scene()
    return s.kind, (s.game.id if s.game else None)


def test_morning_of_the_game_is_a_preview(day):
    app, _, _ = day
    assert scene(app) == ("preview", 1)


def test_inside_the_countdown_window(day):
    app, clock, _ = day
    tick(app, clock, hours=4, minutes=30)  # 90 minutes to puck drop
    assert scene(app) == ("countdown", 1)


def test_countdown_window_is_configurable(day):
    app, _, _ = day
    app.settings.scoreboard.countdown_hours = 8
    assert scene(app) == ("countdown", 1)


def test_live_game_takes_priority(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE", period=1)
    tick(app, clock, hours=6, minutes=5)
    assert scene(app) == ("game", 1)


def test_final_holds_then_moves_to_next_preview(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL", period=3)
    tick(app, clock, hours=8, minutes=40)  # first sighting of the final starts the hold
    assert scene(app) == ("game", 1)

    tick(app, clock, minutes=29)
    assert scene(app) == ("game", 1), "still inside final_hold_minutes"

    tick(app, clock, minutes=2)
    assert scene(app) == ("preview", 2), "hold expired: preview the next game"
    assert client.schedule_calls == 1


def test_final_hold_is_configurable(day):
    app, clock, client = day
    app.settings.scoreboard.final_hold_minutes = 5
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, minutes=6)
    assert scene(app) == ("preview", 2)


def test_next_preview_becomes_countdown_in_its_own_window(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)  # hold expired
    clock.now = NEXT_DROP - timedelta(minutes=45)
    app.refresh()
    assert scene(app) == ("countdown", 2)


def test_no_game_today_previews_the_next_one(fake_backend):
    client = FlowClient()
    client.today = [game(9, "SEA", "CGY", PUCK_DROP, "LIVE")]  # someone else's game
    client.season = [game(2, FAV, "CAR", NEXT_DROP)]
    app = make_app(fake_backend, Clock(PUCK_DROP), client)
    app.refresh()
    assert scene(app) == ("preview", 2)


def test_schedule_is_cached_for_an_hour(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)
    for _ in range(5):
        app.select_scene()
    assert client.schedule_calls == 1
    tick(app, clock, hours=1, seconds=1)
    app.select_scene()
    assert client.schedule_calls == 2


def test_schedule_failure_falls_back_to_rotation(day):
    app, clock, client = day
    client.today[1] = dataclasses.replace(client.today[1], state="FINAL")
    client.fail_schedule = True
    tick(app, clock, hours=9)
    tick(app, clock, hours=1)
    kind, gid = scene(app)
    assert kind == "game" and gid in {9, 1}, "no schedule: fall back to today's rotation"


def test_all_rotation_ignores_favourite_flow(day):
    app, _, _ = day
    app.settings.scoreboard.rotation = "all"
    assert scene(app)[0] == "game"


def test_favourite_rotation_without_favourite_degrades_to_all():
    settings = Settings.from_dict({"scoreboard": {"favourite_team": "", "rotation": "favourite"}})
    assert settings.scoreboard.rotation == "all"


def test_unknown_rotation_degrades_to_all():
    settings = Settings.from_dict({"scoreboard": {"rotation": "sideways"}})
    assert settings.scoreboard.rotation == "all"


def test_draw_renders_every_scene_kind(day):
    """Each scene kind reaches the renderer without error."""
    app, clock, client = day
    app.draw()  # preview
    tick(app, clock, hours=5)
    app.draw()  # countdown
    client.today[1] = dataclasses.replace(client.today[1], state="LIVE")
    app.refresh()
    app.draw()  # game
    assert app.matrix.swaps == 3


def test_fixture_file_still_parses_for_schedule_shape():
    """Season-schedule entries lack clock/period; from_api must cope."""
    raw = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())["games"][0]
    for key in ("clock", "period", "periodDescriptor", "goals"):
        raw.pop(key, None)
    g = Game.from_api(raw)
    assert g.is_final and g.period == 0
