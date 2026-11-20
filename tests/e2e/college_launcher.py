"""Starts the real admin server with the trimmed ESPN college table standing in for ESPN (#544).

The e2e page must show the college picker's team list, but a test never calls ESPN: this installs
a source that answers from the committed fixtures, then runs the same ``main()`` that
``python -m scoreboard.admin_server`` does, so everything else is the real entry point.
"""

from __future__ import annotations

import json
from pathlib import Path

from scoreboard import admin_server
from scoreboard.football.college_teams import table_from_payloads

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "football"
TABLE = table_from_payloads(
    json.loads((FIXTURES / "college_standings_trimmed.json").read_text()),
    json.loads((FIXTURES / "college_teams_trimmed.json").read_text()),
)

if __name__ == "__main__":
    admin_server.COLLEGE_SOURCE = lambda: TABLE
    admin_server.main()
