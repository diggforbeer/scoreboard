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
def standings_payload() -> dict:
    """Synthetic but shape-accurate /standings response (#40).

    Unlike ``score.json`` this is not a trimmed real capture: a live call
    made while filing #40 only ever returned the just-finished season's
    final standings (the off-season quirk documented on ``NHLClient.
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
