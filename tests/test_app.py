"""Tests for the run loop, using a fake matrix backend.

The real backends need either a Pi or a browser window, so these exercise the
scheduling and selection logic against a stand-in that records draw calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nhl_scoreboard.app import ScoreboardApp
from nhl_scoreboard.config import Settings
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import Game, Situation


class FakeCanvas:
    def __init__(self) -> None:
        self.cleared = 0
        self.pixels = 0

    def Clear(self) -> None:  # noqa: N802 - mirrors the C++ binding's API
        self.cleared += 1

    def SetPixel(self, x, y, r, g, b) -> None:  # noqa: N802
        self.pixels += 1


class FakeMatrix:
    def __init__(self, options=None) -> None:
        self.options = options
        self.swaps = 0

    def CreateFrameCanvas(self):  # noqa: N802
        return FakeCanvas()

    def SwapOnVSync(self, canvas):  # noqa: N802
        self.swaps += 1
        return canvas

    def Clear(self) -> None:  # noqa: N802
        pass


class FakeOptions:
    pass


class FakeFont:
    def LoadFont(self, path: str) -> None:  # noqa: N802
        self.path = path

    def CharacterWidth(self, _codepoint: int) -> int:  # noqa: N802
        return 5


class FakeGraphics:
    Font = FakeFont

    @staticmethod
    def Color(r, g, b):  # noqa: N802
        return (r, g, b)

    @staticmethod
    def DrawText(canvas, font, x, y, color, text):  # noqa: N802
        return len(text) * 5

    @staticmethod
    def DrawLine(canvas, x0, y0, x1, y1, color):  # noqa: N802
        return None


class FakeClient:
    def __init__(self, games: list[Game], fail: bool = False) -> None:
        self._games = games
        self.fail = fail
        self.calls = 0
        self.closed = False
        self.situation_calls: list[int] = []
        self.situations: dict[int, Situation | None] = {}

    def scores(self, date: str = "now") -> list[Game]:
        self.calls += 1
        if self.fail:
            raise NHLApiError("boom")
        return list(self._games)

    def situation(self, game_id: int) -> Situation | None:
        self.situation_calls.append(game_id)
        if self.fail:
            raise NHLApiError("boom")
        return self.situations.get(game_id)

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_backend() -> Backend:
    return Backend(
        name="fake",
        RGBMatrix=FakeMatrix,
        RGBMatrixOptions=FakeOptions,
        graphics=FakeGraphics,
    )


@pytest.fixture
def games() -> list[Game]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())
    return [Game.from_api(raw) for raw in payload["games"]]


def build_app(fake_backend, games, **scoreboard_kwargs) -> ScoreboardApp:
    settings = Settings()
    for key, value in scoreboard_kwargs.items():
        setattr(settings.scoreboard, key, value)
    return ScoreboardApp(settings, client=FakeClient(games), backend=fake_backend)


def test_favourite_team_is_pinned_to_the_front(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="TOR")
    app.refresh()
    assert app.games[0].involves("TOR")


def test_ordering_untouched_when_no_favourite(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="")
    app.refresh()
    assert app.games[0].is_live


def test_poll_interval_speeds_up_for_live_games(fake_backend, games):
    app = build_app(fake_backend, games, poll_seconds=60, live_poll_seconds=15)
    app.refresh()
    assert app.poll_interval() == 15

    app.games = [g for g in app.games if g.is_final]
    assert app.poll_interval() == 60


def test_intermission_does_not_count_as_live_for_polling(fake_backend, games):
    app = build_app(fake_backend, games, poll_seconds=60, live_poll_seconds=15)
    app.games = [g for g in games if g.in_intermission]
    assert app.games, "fixture should contain an intermission game"
    assert app.poll_interval() == 60


def test_rotation_wraps(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    for _ in range(len(app.games)):
        app.advance()
    assert app.index == 0


def test_api_failure_keeps_previous_games(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    assert app.games

    app.client.fail = True
    app.refresh()
    assert app.games, "stale data should stay on the board"


def test_draw_swaps_the_canvas(fake_backend, games):
    app = build_app(fake_backend, games)
    app.refresh()
    app.draw()
    assert app.matrix.swaps == 1


def test_draws_without_data_before_first_success(fake_backend, games):
    app = build_app(fake_backend, games)
    app.draw()
    assert app.matrix.swaps == 1


def test_shutdown_closes_the_client(fake_backend, games):
    app = build_app(fake_backend, games)
    app.shutdown()
    assert app.client.closed


# -- special teams: only the favourite's game and the on-screen game ----------


def home_pp() -> Situation:
    return Situation.from_api(
        {
            "awayTeam": {"strength": 4},
            "homeTeam": {"strength": 5, "situationDescriptions": ["PP"]},
            "timeRemaining": "1:23",
        }
    )


def in_play(games: list[Game]) -> list[Game]:
    """The fixture's intermission games, made live-in-play so they are fetchable."""
    import dataclasses

    return [dataclasses.replace(g, in_intermission=False) if g.is_live else g for g in games]


def test_situations_fetched_only_for_favourite_and_on_screen(fake_backend, games):
    """In 'all' rotation the on-screen game is a second target; nothing else is."""
    games = in_play(games)  # three live games: SEA@CGY, CAR@FLA, UTA@COL
    app = build_app(fake_backend, games, favourite_team="CGY", rotation="all")
    app.refresh()
    favourite_game = next(g for g in app.games if g.involves("CGY"))
    assert app.games[app.index] == favourite_game, "favourite is pinned first: targets coincide"

    app.refresh_situations()
    assert app.client.situation_calls == [favourite_game.id]

    # Rotate: the newly on-screen live game joins the favourite as a target.
    app.advance()
    app.refresh_situations()
    now_showing = app.games[app.index]
    assert now_showing.is_live and now_showing.id != favourite_game.id
    assert set(app.client.situation_calls) == {favourite_game.id, now_showing.id}

    # The third live game is never on screen and never the favourite: never fetched.
    live_ids = {g.id for g in app.games if g.is_live}
    assert len(live_ids) == 3
    assert live_ids - {favourite_game.id, now_showing.id}, "a live game must remain unfetched"
    assert not (live_ids - {favourite_game.id, now_showing.id}) & set(app.client.situation_calls)


def test_situation_not_refetched_within_live_interval(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=15)
    app.refresh()
    app.refresh_situations()
    app.refresh_situations()
    assert len(app.client.situation_calls) == 1


def test_intermission_games_are_not_fetched(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CAR")  # CAR @ FLA is in intermission
    app.refresh()
    app.refresh_situations()
    assert app.client.situation_calls == []
    car = next(g for g in app.games if g.involves("CAR"))
    assert app.with_situation(car).situation is None


def test_with_situation_attaches_and_stale_entries_are_dropped(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY")
    app.refresh()
    game = next(g for g in app.games if g.involves("CGY"))
    app.client.situations[game.id] = home_pp()
    app.refresh_situations()

    shown = app.with_situation(game)
    assert shown.situation is not None
    assert shown.situation.label() == "PP 1:23"
    assert shown.id == game.id

    # Change favourite and move on: the CGY entry is no longer a target.
    app.settings.scoreboard.favourite_team = "NYI"  # final, not live
    while app.games[app.index].involves("CGY"):
        app.advance()
    app.refresh_situations()
    assert game.id not in app.situations


def test_situation_fetch_failure_keeps_last_value(fake_backend, games):
    app = build_app(fake_backend, games, favourite_team="CGY", live_poll_seconds=0)
    app.refresh()
    game = next(g for g in app.games if g.involves("CGY"))
    app.client.situations[game.id] = home_pp()
    app.refresh_situations()
    app.client.fail = True
    app.refresh_situations()
    assert app.with_situation(game).situation is not None
