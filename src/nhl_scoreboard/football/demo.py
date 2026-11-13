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
from .events import CoinToss, Event, FieldGoal, Scope, Touchdown, Turnover
from .models import FbGame, Play
from .pacing import animation_seconds
from .people import Person
from .reversals import Reversal
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


def _play(
    kind: str,
    text: str,
    start: int,
    end: int,
    offense: str,
    yards: int = 0,
    score: tuple[int, int] = (10, 17),
    scoring: bool = False,
    turnover: bool = False,
    end_team: str | None = None,
) -> Play:
    """A play in the shape ESPN sends it, with made-up numbers."""

    def pos(yard: int, team: str) -> dict[str, Any]:
        return {
            "yardLine": yard,
            "team": {"id": str(TEAMS[team].espn_id)},
            "down": 2,
            "distance": 7,
            "shortDownDistanceText": "2nd & 7",
        }

    return Play.from_api(
        {
            "id": f"demo-{kind}",
            "sequenceNumber": "100",
            "type": {"text": kind},
            "text": text,
            "period": {"number": 3},
            "clock": {"displayValue": "12:24"},
            "statYardage": yards,
            "scoringPlay": scoring,
            "isTurnover": turnover,
            "awayScore": score[0],
            "homeScore": score[1],
            "start": pos(start, offense),
            "end": pos(end, end_team or offense),
        }
    )


def _play_scenes(now: datetime) -> list[DemoStep]:
    """Stills of the generic play scenes (#377): what every play shows until its own screen is
    drawn, and the cards of every event. A designed screen replaces its step with its own."""
    game = _game(now, "in", 10, 17, "12:24 - 3rd", situation=_situation(HOME, 62, 2, 7))
    rush = _play(
        "Rush", "D.Singletary up the middle to WSH 29 for 9 yards (J.Smith).", 62, 71, HOME, 9
    )
    outside = _play(
        "Rush", "B.Robinson right end to NYG 33 for 7 yards (T.Smith).", 40, 33, AWAY, 7,
    )  # fmt: skip
    kneel = _play("Rush", "D.Jones kneels to NYG 22 for -1 yards.", 23, 22, HOME, -1)
    loss = _play(
        "Rush", "D.Singletary left tackle to WSH 41 for -2 yards (J.Smith).", 43, 41, HOME, -2
    )
    punt = _play("Punt", "T.Way punts 51 yards to NYG 24, fair catch by K.Toney.", 24, 76, AWAY)
    td = _play(
        "Rushing Touchdown",
        "D.Singletary rush left end for 3 yards, TOUCHDOWN. G.Gano extra point is GOOD.",
        97, 100, HOME, 3, (10, 24), True,
    )  # fmt: skip
    kick = _play(
        "Field Goal Missed", "G.Gano 38 yard field goal is No Good, Wide Left.", 80, 80, HOME
    )
    pick = _play(
        "Pass Interception Return",
        "D.Jones pass deep left INTERCEPTED by B.Carter at WSH 43.",
        57, 43, HOME, 0, turnover=True, end_team=AWAY,
    )  # fmt: skip
    base = {"game_id": 1, "away_score": 10, "home_score": 17}

    def event(cls: type[Event], play: Play, team: str = HOME, **kw: Any) -> Event:
        return cls(play=play, team=team, scope=Scope.FULL, **{**base, **kw})

    touchdown = event(Touchdown, td, via="run", points=7, extra_point="good", home_score=24)
    miss = event(FieldGoal, kick, made=False, yards=38, miss="Wide Left")
    turnover = event(Turnover, pick, AWAY, reason="interception", lost_by=HOME)
    toss = event(CoinToss, rush, HOME, kicker=AWAY)
    reversal = event(
        Reversal, td, original=touchdown, original_kind="touchdown", title="TOUCHDOWN OVERTURNED",
        rules=("flag_cleared",), rule="flag_cleared", reason="OFFENSIVE HOLDING ON NYG, NO PLAY",
        review=None, current=None,
    )  # fmt: skip

    carrier = Person("rusher", 22, "D. Singletary", "22", "RB", True)
    robinson = Person("rusher", 9, "B. Robinson", "9", "RB", True)

    def scene(
        kind: str,
        stage: str,
        play: Play,
        ev: Event | None = None,
        at: float = 1.5,
        seconds: float = 3.0,
        people: tuple[Person, ...] = (),
    ) -> Scene:
        return Scene(
            kind, fb_game=game, fb_play=play, fb_event=ev, fb_stage=stage, fb_elapsed=at,
            fb_seconds=seconds, fb_people=people, animating=True,
        )  # fmt: skip

    def run(play: Play, at: float, who: Person | None) -> Scene:
        return scene("fb_play", "play", play, at=at, seconds=animation_seconds(play, 3.0),
                     people=(who,) if who else ())  # fmt: skip

    return [
        DemoStep(run(rush, 1.0, carrier), name="fb_run"),
        DemoStep(run(rush, 9.0, carrier), name="fb_run_settled"),
        DemoStep(run(outside, 1.2, robinson), name="fb_run_outside"),
        DemoStep(run(loss, 1.2, carrier), name="fb_run_loss"),
        DemoStep(run(kneel, 1.0, None), name="fb_run_kneel"),
        DemoStep(scene("fb_play", "play", punt), name="fb_play_punt"),
        DemoStep(scene("fb_playtext", "playtext", rush), name="fb_playtext"),
        DemoStep(scene("fb_event", "event", td, touchdown), name="fb_event_touchdown"),
        DemoStep(scene("fb_event", "detail", td, touchdown), name="fb_event_detail"),
        DemoStep(scene("fb_event", "event", kick, miss), name="fb_event_fg_miss"),
        DemoStep(scene("fb_event", "event", pick, turnover), name="fb_event_turnover"),
        DemoStep(scene("fb_event", "event", rush, toss), name="fb_event_cointoss"),
        DemoStep(scene("fb_event", "reversal", td, reversal), name="fb_event_reversal"),
    ]


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
        *_play_scenes(now),
    ]
