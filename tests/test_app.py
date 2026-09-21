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
from nhl_scoreboard.nhl.models import Game


class FakeCanvas:
    def __init__(self) -> None:
        self.cleared = 0

    def Clear(self) -> None:  # noqa: N802 - mirrors the C++ binding's API
        self.cleared += 1


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

    def scores(self, date: str = "now") -> list[Game]:
        self.calls += 1
        if self.fail:
            raise NHLApiError("boom")
        return list(self._games)

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
