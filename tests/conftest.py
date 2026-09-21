from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def score_payload() -> dict:
    """A trimmed capture of a real api-web.nhle.com /score response."""
    return json.loads((FIXTURES / "score.json").read_text())
