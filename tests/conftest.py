from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def score_payload() -> dict:
    """A trimmed capture of a real api-web.nhle.com /score response."""
    return json.loads((FIXTURES / "score.json").read_text())


@pytest.fixture
def mock_pins():
    """gpiozero's own MockFactory as the pin factory, for button tests (#50).

    Every gpiozero device built while this is active claims a simulated pin
    instead of real GPIO; ``mock_pins.pin(n).drive_low()``/``drive_high()``
    press and release a button wired to pin ``n``.
    """
    from gpiozero import Device
    from gpiozero.pins.mock import MockFactory

    previous = Device.pin_factory
    Device.pin_factory = MockFactory()
    yield Device.pin_factory
    Device.pin_factory.reset()
    Device.pin_factory = previous


@pytest.fixture
def standings_payload() -> dict:
    """Synthetic but shape-accurate /standings response (#40).

    Unlike ``score.json`` this is not a trimmed real capture: a live call
    made while filing #40 only ever returned the just-finished season's
    final standings (the off-season quirk documented on ``HockeyClient.
    standings``), so there was no in-season response to trim from. The
    field names and nesting mirror what that call actually returned.
    """
    return json.loads((FIXTURES / "standings.json").read_text())


def pytest_addoption(parser):
    parser.addoption(
        "--update-snapshots",
        action="store_true",
        default=False,
        help="Rewrite tests/snapshots/*.txt from the current rendering",
    )


@pytest.fixture
def update_snapshots(request) -> bool:
    return request.config.getoption("--update-snapshots")


@pytest.fixture(autouse=True)
def _restore_idle_screens():
    """A test may register stand-in idle screens (``test_football_idle_selection.register``); they
    must never outlive it, or a later test on the same worker draws a fake view (a bool) instead
    of the real screen. This keeps that true for every test file, not just the one that owns the
    helper."""
    from scoreboard.football.idle_screens import IDLE_SCREENS

    saved = dict(IDLE_SCREENS)
    yield
    IDLE_SCREENS.clear()
    IDLE_SCREENS.update(saved)
