"""Synthetic NFL scenes for ``--demo`` and the docs images (#359): every screen, no ESPN needed.

The NFL counterpart of ``nhl_scoreboard.demo``. Games are built from raw ESPN-shaped dicts
through ``FbGame.from_api()`` -- the construction the tests and the live worker use -- so a
demo frame goes through exactly the parsing and drawing a real one would, with made-up numbers.

Steps are ``DemoStep``s with a unique file-safe ``name``; ``scripts/render-screens.py --sport
nfl`` writes one ``docs/football/<name>.png`` per step. A new designed screen adds its steps
here (and its picture to ``football_screen.md``) and retires its hand-drawn mockup.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..app import Scene
from ..demo import DemoStep
from .models import FbGame
from .teams import TEAMS

#: The matchup every demo screen shows: away at home, so the home team is on the left.
AWAY, HOME = "WSH", "NYG"


def _side(abbrev: str, home_away: str, score: int) -> dict[str, Any]:
    return {
        "homeAway": home_away,
        "score": str(score),
        "team": {"id": str(TEAMS[abbrev].espn_id), "abbreviation": abbrev},
    }


def _situation(
    possession: str, yard_line: int, down: int = 1, distance: int = 10, red_zone: bool = False
) -> dict[str, Any]:
    short = f"{down}{('st', 'nd', 'rd', 'th')[down - 1]} & {distance}"
    return {
        "down": down,
        "distance": distance,
        "yardLine": yard_line,
        "downDistanceText": short,
        "shortDownDistanceText": short,
        "possession": str(TEAMS[possession].espn_id),
        "isRedZone": red_zone,
    }


def _game(
    now: datetime,
    state: str,
    away_score: int = 0,
    home_score: int = 0,
    detail: str = "",
    name: str = "STATUS_IN_PROGRESS",
    situation: dict[str, Any] | None = None,
    start: datetime | None = None,
) -> FbGame:
    start = start or now
    comp: dict[str, Any] = {
        "id": "1",
        "startDate": start.strftime("%Y-%m-%dT%H:%MZ"),
        "status": {
            "period": 3,
            "clock": 744.0,
            "type": {
                "state": state,
                "name": name,
                "shortDetail": detail,
                "detail": detail,
                "completed": state == "post",
            },
        },
        "competitors": [_side(HOME, "home", home_score), _side(AWAY, "away", away_score)],
    }
    if situation is not None:
        comp["situation"] = situation
    return FbGame.from_api(
        {"id": "1", "date": start.strftime("%Y-%m-%dT%H:%MZ"), "competitions": [comp]}
    )


def nfl_demo_steps(now: datetime) -> list[DemoStep]:
    """Every NFL screen there is, in a sensible viewing order."""
    pregame = _game(now, "pre", name="STATUS_SCHEDULED", start=now + timedelta(days=2, hours=3))
    live = _game(now, "in", 10, 17, "12:24 - 3rd", situation=_situation(HOME, 62, 2, 7))
    red = _game(now, "in", 10, 17, "2:01 - 4th", situation=_situation(AWAY, 6, 1, 6, red_zone=True))
    half = _game(now, "in", 10, 17, "Halftime", name="STATUS_HALFTIME")
    final = _game(now, "post", 20, 27, "Final", name="STATUS_FINAL")

    def step(kind: str, name: str, game: FbGame | None = None) -> DemoStep:
        return DemoStep(Scene(kind, fb_game=game), name=name)

    return [
        step("fb_connecting", "fb_connecting"),
        step("fb_no_data", "fb_no_data"),
        step("fb_no_games", "fb_no_games"),
        step("fb_scores", "fb_scores_pregame", pregame),
        step("fb_scores", "fb_scores_live", live),
        step("fb_scores", "fb_scores_redzone", red),
        step("fb_scores", "fb_scores_halftime", half),
        step("fb_scores", "fb_scores_final", final),
        step("fb_field", "fb_field", live),
        step("fb_field", "fb_field_redzone", red),
    ]
