"""Synthetic college football scenes for ``--demo`` and the docs images (#559).

The college counterpart of the NFL steps in ``demo.py``, appended to them. The FBS table is
ESPN's and needs the network, so the demo carries a small directory of its own: real schools and
their LED-tuned colours (facts, no artwork), with made-up rankings, records and scores. Each step
has ``college=True`` so the app draws it in that directory and with the college logo set, never
the NFL's (``CIN`` and ``BUF`` are different teams in the two leagues).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

from ..demo import DemoStep
from ..scene import Scene
from . import events as ev
from .college_standings import ConferenceRow
from .college_views import ConferenceView, PollRow, PollView, ScoresView, scores_order
from .director import DETAIL, EVENT
from .idle_views import PreviewView
from .models import FbGame, Play
from .teams import Directory, FootballTeam, use_directory
from .upset import Upset

#: (abbreviation, ESPN id, school, nickname, panel name, colour, secondary).
_TEAMS = (
    ("UGA", 61, "Georgia", "Bulldogs", "GEORGIA", (230, 15, 58), (255, 255, 255)),
    ("ALA", 333, "Alabama", "Crimson Tide", "ALABAMA", (230, 39, 73), (255, 255, 255)),
    ("TEX", 251, "Texas", "Longhorns", "TEXAS", (175, 92, 55), (255, 255, 255)),
    ("OSU", 194, "Ohio State", "Buckeyes", "OHIO STATE", (230, 15, 58), (168, 173, 180)),
    ("MICH", 130, "Michigan", "Wolverines", "MICHIGAN", (0, 118, 230), (255, 203, 5)),
    ("IU", 84, "Indiana", "Hoosiers", "INDIANA", (230, 5, 24), (255, 255, 255)),
    ("ND", 87, "Notre Dame", "Fighting Irish", "NOTRE DAME", (22, 126, 230), (201, 151, 0)),
    ("MIA", 2390, "Miami", "Hurricanes", "MIAMI", (244, 116, 35), (9, 230, 139)),
    ("CLEM", 228, "Clemson", "Tigers", "CLEMSON", (245, 102, 0), (255, 255, 255)),
    ("DUKE", 150, "Duke", "Blue Devils", "DUKE", (0, 123, 230), (255, 255, 255)),
    ("UTAH", 254, "Utah", "Utes", "UTAH", (230, 11, 11), (255, 255, 255)),
    ("UCLA", 26, "UCLA", "Bruins", "UCLA", (39, 116, 174), (242, 169, 0)),
    ("AUB", 2, "Auburn", "Tigers", "AUBURN", (0, 107, 230), (242, 101, 34)),
    ("MIZ", 142, "Missouri", "Tigers", "MISSOURI", (241, 184, 45), (255, 255, 255)),
    ("OKST", 197, "Oklahoma State", "Cowboys", "OKLAHOMA ST", (254, 92, 0), (255, 255, 255)),
    ("UTSA", 2636, "UTSA", "Roadrunners", "UTSA", (43, 126, 230), (241, 90, 34)),
    ("USF", 58, "South Florida", "Bulls", "SOUTH FLORIDA", (0, 230, 158), (207, 196, 147)),
    ("WAKE", 154, "Wake Forest", "Demon Deacons", "WAKE FOREST", (206, 184, 136), (255, 255, 255)),
    ("LSU", 99, "LSU", "Tigers", "LSU", (136, 56, 230), (253, 208, 35)),
    ("FSU", 52, "Florida State", "Seminoles", "FLORIDA ST", (120, 47, 64), (206, 184, 136)),
    ("PSU", 213, "Penn State", "Nittany Lions", "PENN STATE", (22, 72, 230), (255, 255, 255)),
    ("ORE", 2483, "Oregon", "Ducks", "OREGON", (0, 147, 75), (255, 244, 27)),
    ("OU", 201, "Oklahoma", "Sooners", "OKLAHOMA", (230, 11, 11), (255, 255, 255)),
    ("TENN", 2633, "Tennessee", "Volunteers", "TENNESSEE", (255, 130, 0), (255, 255, 255)),
    ("VT", 259, "Virginia Tech", "Hokies", "VIRGINIA TECH", (230, 95, 134), (207, 69, 32)),
    ("TCU", 2628, "TCU", "Horned Frogs", "TCU", (146, 47, 230), (255, 255, 255)),
    ("BYU", 252, "BYU", "Cougars", "BYU", (0, 88, 230), (255, 255, 255)),
    ("ARK", 8, "Arkansas", "Razorbacks", "ARKANSAS", (163, 33, 54), (255, 255, 255)),
)

DEMO_DIRECTORY = Directory.of(
    "college-football", (FootballTeam(*row) for row in _TEAMS)
)  # fmt: skip
_IDS = {row[0]: row[1] for row in _TEAMS}

#: The made-up Top 25 of the demo: (abbreviation, record, places moved, points, first-place votes).
_POLL = (
    ("UGA", "10-0", 0, 1485, 52), ("OSU", "10-0", 1, 1431, 8), ("TEX", "9-1", -1, 1380, 1),
    ("ALA", "9-1", 2, 1290, 0), ("MICH", "9-1", 0, 1244, 0), ("MIA", "9-1", 1, 1190, 0),
    ("ND", "9-1", 2, 1141, 0), ("CLEM", "8-2", -3, 1087, 0), ("ORE", "8-2", 0, 1002, 0),
    ("PSU", "8-2", 1, 960, 0), ("IU", "9-1", 3, 902, 0), ("OKST", "8-2", -2, 861, 0),
    ("LSU", "7-3", 0, 790, 0), ("OU", "8-2", 2, 742, 0), ("UTAH", "8-2", -1, 701, 0),
    ("TENN", "7-3", 0, 640, 0), ("USF", "9-1", 4, 588, 0), ("FSU", "7-3", -2, 522, 0),
    ("BYU", "8-2", 1, 468, 0), ("TCU", "7-3", -1, 400, 0), ("VT", "7-3", 0, 351, 0),
    ("ARK", "7-3", 2, 288, 0), ("WAKE", "8-2", 5, 231, 0), ("UCLA", "7-3", -3, 170, 0),
    ("AUB", "6-4", 0, 102, 0),
)  # fmt: skip


def _game(
    away: str,
    home: str,
    state: str,
    a: int,
    h: int,
    short: str,
    period: int,
    ranks: tuple[int | None, int | None] = (None, None),
    situation: tuple[str, int, str, bool] | None = None,
    name: str = "STATUS_IN_PROGRESS",
    start: datetime | None = None,
    records: tuple[str, str] = ("", ""),
    gid: int = 1,
) -> FbGame:
    """A game as ESPN sends one, made in the demo's directory. ``situation`` is (possession,
    yard line from the home goal, down text, red zone); ``records`` are (away, home)."""

    def side(abbrev: str, home_away: str, score: int, record: str) -> dict[str, Any]:
        out: dict[str, Any] = {
            "homeAway": home_away,
            "score": str(score),
            "team": {"id": str(_IDS[abbrev]), "abbreviation": abbrev},
        }
        if record:
            out["records"] = [{"type": "total", "summary": record}]
        return out

    when = (start or datetime(2026, 11, 21, 19, 30, tzinfo=UTC)).astimezone(UTC)
    stamp = when.strftime("%Y-%m-%dT%H:%MZ")
    comp: dict[str, Any] = {
        "id": str(gid),
        "startDate": stamp,
        "status": {
            "period": period,
            "displayClock": "3:12",
            "clock": 192.0,
            "type": {
                "state": state,
                "name": name,
                "shortDetail": short,
                "detail": short,
                "completed": state == "post",
            },
        },
        "competitors": [side(home, "home", h, records[1]), side(away, "away", a, records[0])],
    }
    if situation is not None:
        possession, yard, text, red = situation
        comp["situation"] = {
            "down": int(text[0]),
            "distance": 6,
            "yardLine": yard,
            "downDistanceText": f"{text} at X {yard}",
            "shortDownDistanceText": text,
            "possession": str(_IDS[possession]),
            "isRedZone": red,
        }
    with use_directory(DEMO_DIRECTORY):
        game = FbGame.from_api({"id": str(gid), "date": stamp, "competitions": [comp]})
    return dataclasses.replace(
        game,
        away=dataclasses.replace(game.away, rank=ranks[0]),
        home=dataclasses.replace(game.home, rank=ranks[1]),
    )


def _play(kind: str, text: str, team: str, score: tuple[int, int]) -> Play:
    pos = {
        "yardLine": 98,
        "team": {"id": str(_IDS[team])},
        "down": 2,
        "distance": 7,
        "shortDownDistanceText": "2nd & 7",
    }
    return Play.from_api(
        {
            "id": f"college-{kind}",
            "sequenceNumber": "100",
            "type": {"text": kind},
            "text": text,
            "period": {"number": 2},
            "clock": {"displayValue": "6:41"},
            "statYardage": 2,
            "scoringPlay": True,
            "isTurnover": False,
            "awayScore": score[0],
            "homeScore": score[1],
            "start": pos,
            "end": pos,
        }
    )


def _poll_view(key: str, title: str, label: tuple[str, str, str], team: str, cut: int = 0):
    rows = tuple(
        PollRow(
            rank=i,
            abbrev=abbrev,
            record=record,
            movement=moved,
            points=points,
            firsts=firsts,
            conference="SEC" if key == "cfp" and abbrev in ("UGA", "ALA", "TEX") else "",
        )
        for i, (abbrev, record, moved, points, firsts) in enumerate(_POLL, 1)
    )
    return PollView(key, title, label, rows, team, cut)


def _conference_view(team: str) -> ConferenceView:
    table = (
        ("UGA", "10-0", "7-0", "W10"), ("TEX", "9-1", "6-1", "W3"), ("ALA", "9-1", "6-1", "W5"),
        ("OU", "8-2", "5-2", "W2"), ("LSU", "7-3", "4-3", "L1"), ("TENN", "7-3", "4-3", "W1"),
        ("ARK", "7-3", "3-4", "L2"), ("MIZ", "6-4", "3-4", "L1"), ("AUB", "6-4", "2-5", "L3"),
    )  # fmt: skip
    rows = tuple(
        ConferenceRow(_IDS[abbrev], abbrev, overall, conf, seed, streak)
        for seed, (abbrev, overall, conf, streak) in enumerate(table, 1)
    )
    return ConferenceView("Southeastern Conference", "SEC", rows, team)


def college_demo_steps(now: datetime) -> list[DemoStep]:
    """Every college screen: the scoreboards, the plays, the upset alert, the final and the idle
    screens, with made-up rankings. Appended to the football demo."""

    def step(scene: Scene, name: str) -> DemoStep:
        return DemoStep(scene, name=name, college=True)

    ranked = _game(
        "AUB", "UGA", "in", 14, 24, "3:12 - 2nd", 2, (None, 1), ("UGA", 62, "2nd & 6", False)
    )
    marquee = _game(
        "TEX", "ALA", "in", 17, 20, "11:42 - 4th", 4, (5, 3), ("TEX", 38, "1st & 10", False)
    )
    red = _game(
        "CLEM", "DUKE", "in", 10, 7, "9:30 - 4th", 4, (8, None), ("CLEM", 9, "1st & Goal", True)
    )
    half = _game("UGA", "AUB", "in", 21, 10, "Halftime", 2, (1, None), name="STATUS_HALFTIME")
    soon = _game(
        "TEX", "ALA", "pre", 0, 0, "11/22 - 12:00 PM EST", 0, (5, 3),
        name="STATUS_SCHEDULED", start=now + timedelta(minutes=42, seconds=15),
        records=("8-2", "9-1"),
    )  # fmt: skip
    later = _game(
        "MICH", "OSU", "pre", 0, 0, "11/22 - 12:00 PM EST", 0, (4, 2),
        name="STATUS_SCHEDULED", start=now + timedelta(days=2, hours=3),
    )  # fmt: skip

    td_play = _play("Rushing Touchdown", "J.Smith 2 yard run, TOUCHDOWN.", "UGA", (14, 31))
    touchdown = ev.Touchdown(
        play=td_play, game_id=1, team="UGA", scope=ev.Scope.FULL, away_score=14, home_score=31,
        points=7, away_before=14, home_before=24, via="run", extra_point="good",
    )  # fmt: skip
    fg_play = _play("Field Goal Good", "47 yard field goal is GOOD.", "UGA", (14, 27))
    field_goal = ev.FieldGoal(
        play=fg_play, game_id=1, team="UGA", scope=ev.Scope.FULL, away_score=14, home_score=27,
        points=3, away_before=14, home_before=24, made=True, yards=47,
    )  # fmt: skip

    def event(game: FbGame, e: Any, stage: str, at: float) -> Scene:
        return Scene(
            "fb_event", fb_game=game, fb_event=e, fb_play=e.play, fb_stage=stage, fb_elapsed=at,
            fb_seconds=6.0,
        )  # fmt: skip

    def upset(game: FbGame, final: bool, at: float) -> Scene:
        behind, ahead = (game.away, game.home) if game.away.score < game.home.score else (
            game.home, game.away,
        )  # fmt: skip
        found = Upset(behind, ahead, final, ahead.score - behind.score)
        return Scene("fb_upset", fb_game=game, fb_upset=found, fb_elapsed=at)

    upset_live = _game("MIZ", "UGA", "in", 21, 14, "3:12 - 3rd", 3, (None, 1))
    upset_final = _game("TEX", "OKST", "post", 24, 27, "Final/OT", 5, (5, 19), name="STATUS_FINAL")

    from ..config import FootballConfig
    from ..priority import TeamView
    from .idle import IdleSnapshot
    from .idle_screens import IdleContext
    from .idle_views import build_final

    won = _game("MIZ", "UGA", "post", 17, 31, "Final", 4, (None, 3), name="STATUS_FINAL")
    with use_directory(DEMO_DIRECTORY):
        ctx = IdleContext(
            0.0, now, [won], IdleSnapshot(), TeamView(FootballConfig(), "UGA", [], "UGA")
        )
        final_view = build_final(ctx)

    slate = [
        _game("UTAH", "UCLA", "in", 17, 14, "3:12 - 3rd", 3, (2, 4), gid=1),
        _game("OSU", "MICH", "in", 24, 21, "Halftime", 2, (1, 12), name="STATUS_HALFTIME", gid=2),
        _game(
            "TEX",
            "ALA",
            "pre",
            0,
            0,
            "11/22 - 12:00 PM EST",
            0,
            (8, 7),
            name="STATUS_SCHEDULED",
            gid=3,
        ),
        _game("ND", "MIA", "post", 31, 28, "Final", 4, (3, 5), name="STATUS_FINAL", gid=4),
        _game("UGA", "UTSA", "in", 45, 3, "1:02 - 4th", 4, (6, None), gid=5),
        _game("IU", "UTSA", "post", 30, 27, "Final/OT", 5, (11, None), name="STATUS_FINAL", gid=6),
    ]
    grid = ScoresView(scores_order(slate, False))
    kickoff = datetime(2026, 11, 28, 17, 0, tzinfo=UTC)
    next_game = PreviewView("AUB", "UGA", kickoff, "", "WEEK 14", "6-4", "10-0", None, 1)

    return [
        step(Scene("fb_scores", fb_game=ranked), "cfb_scores_ranked"),
        step(Scene("fb_scores", fb_game=marquee), "cfb_scores_two_ranked"),
        step(Scene("fb_field", fb_game=marquee), "cfb_field"),
        step(Scene("fb_field", fb_game=red), "cfb_field_redzone"),
        step(Scene("fb_halftime", fb_game=half), "cfb_halftime"),
        step(Scene("fb_scores", fb_game=later), "cfb_scores_pregame"),
        step(Scene("fb_countdown", fb_game=soon), "cfb_countdown"),
        step(event(ranked, touchdown, EVENT, 1.0), "cfb_touchdown"),
        step(event(ranked, touchdown, DETAIL, 2.0), "cfb_touchdown_detail"),
        step(event(ranked, field_goal, EVENT, 1.5), "cfb_field_goal"),
        step(upset(upset_live, False, 0.0), "cfb_upset"),
        step(upset(upset_final, True, 0.0), "cfb_upset_final"),
        step(Scene("fb_final", fb_game=won, fb_idle=final_view), "cfb_final"),
        step(
            Scene("cfb_ap", fb_idle=_poll_view("ap", "AP TOP 25", ("AP", "TOP", "25"), "UGA")),
            "cfb_ap",
        ),
        step(
            Scene(
                "cfb_cfp",
                fb_idle=_poll_view("cfp", "CFP RANKINGS", ("CFP", "RANK", "25"), "UGA", cut=12),
            ),
            "cfb_cfp",
        ),
        step(Scene("cfb_conference", fb_idle=_conference_view("UGA")), "cfb_conference"),
        step(Scene("cfb_preview", fb_idle=next_game), "cfb_preview"),
        step(Scene("cfb_scores", fb_idle=grid, fb_page=0), "cfb_scores_grid"),
        step(Scene("cfb_scores", fb_idle=grid, fb_page=1), "cfb_scores_grid_page2"),
    ]
