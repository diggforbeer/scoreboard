"""Synthetic NFL scenes for ``--demo`` and the docs images (#359): every screen, no ESPN needed.

The NFL counterpart of ``nhl_scoreboard.demo``. Games are built from raw ESPN-shaped dicts
through ``FbGame.from_api()`` -- the construction the tests and the live worker use -- so a
demo frame goes through exactly the parsing and drawing a real one would, with made-up numbers.

Steps are ``DemoStep``s with a unique file-safe ``name``; ``scripts/render-screens.py --sport
nfl`` writes one ``docs/football/<name>.png`` per step. A new designed screen adds its steps
here (and its picture to ``football_screen.md``) and retires its hand-drawn mockup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ..app import Scene
from ..demo import DemoStep
from .events import CoinToss, Event, FieldGoal, GenericScore, Scope, Touchdown, Turnover
from .models import FbGame, Play
from .pacing import animation_seconds
from .people import Person
from .reversals import Reversal
from .teams import TEAMS

#: The matchup every demo screen shows: away at home, so the home team is on the left.
AWAY, HOME = "WSH", "NYG"


def _side(abbrev: str, home_away: str, score: int, record: str = "") -> dict[str, Any]:
    side: dict[str, Any] = {
        "homeAway": home_away,
        "score": str(score),
        "team": {"id": str(TEAMS[abbrev].espn_id), "abbreviation": abbrev},
    }
    if record:
        side["records"] = [{"type": "total", "summary": record}]
    return side


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
    records: tuple[str, str] = ("", ""),
    broadcast: str = "",
    leaders: tuple[tuple[str, str, str, str], ...] = (),
) -> FbGame:
    """``records`` are (home, away); ``broadcast`` is the network, if any."""
    start = (start or now).astimezone(UTC)  # the feed's times are UTC
    comp: dict[str, Any] = {
        "id": "1",
        "startDate": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
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
        "competitors": [
            _side(HOME, "home", home_score, records[0]),
            _side(AWAY, "away", away_score, records[1]),
        ],
    }
    if broadcast:
        comp["broadcasts"] = [{"names": [broadcast]}]
    if leaders:  # (category, short name, team, display) as the scoreboard gives a final's leaders
        comp["leaders"] = [
            {
                "name": category,
                "leaders": [
                    {
                        "displayValue": display,
                        "athlete": {
                            "shortName": name,
                            "jersey": "1",
                            "position": {"abbreviation": "QB"},
                        },
                        "team": {"id": str(TEAMS[team].espn_id)},
                    }
                ],
            }
            for category, name, team, display in leaders
        ]
    if situation is not None:
        comp["situation"] = situation
    return FbGame.from_api(
        {"id": "1", "date": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "competitions": [comp]}
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
    yac: int | None = None,
) -> Play:
    """A play in the shape ESPN sends it, with made-up numbers."""

    def pos(yard: int, team: str) -> dict[str, Any]:
        return {
            "yardLine": yard,
            "team": {"id": str(TEAMS[team].espn_id)},
            "down": 2,
            "distance": 7,
            "shortDownDistanceText": "2nd & 7",
            "possessionText": f"{HOME} {yard}" if yard <= 50 else f"{AWAY} {100 - yard}",
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
            "yardsAfterCatch": yac,
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
    pass_play = _play(
        "Pass Reception",
        "(Shotgun) M.Penix pass short right to J.Dotson to NYG 33 for 12 yards (D.Knight).",
        45, 33, AWAY, 12, yac=4,
    )  # fmt: skip
    deep = _play(
        "Pass Reception", "(Shotgun) D.Jones pass deep left to W.Robinson to WSH 33 for 28 yards.",
        39, 67, HOME, 28, yac=12,
    )  # fmt: skip
    kickoff = _play(
        "Kickoff",
        "N.Folk kicks 60 yards from NYG 35 to WSH 5. D.Meyers to WSH 25 for 20 yards (N.Muse).",
        35, 75, HOME, 0, end_team=AWAY,
    )  # fmt: skip
    touchback = _play(
        "Kickoff", "A.Szmyt kicks 65 yards from WSH 35 to end zone, Touchback to the NYG 35.",
        65, 35, AWAY, 0, end_team=HOME,
    )  # fmt: skip
    onside = _play(
        "Kickoff",
        "N.Folk kicks onside 19 yards from NYG 35 to WSH 46. M.Nabers (didn't try to advance) "
        "to WSH 46 for no gain.",
        35, 54, HOME, 0, end_team=AWAY,
    )  # fmt: skip
    incomplete = _play(
        "Pass Incompletion", "(Shotgun) M.Penix pass incomplete short left to K.Pitts.",
        55, 55, HOME, 0,
    )  # fmt: skip
    deep_incomplete = _play(
        "Pass Incompletion", "(Shotgun) D.Jones pass incomplete deep right.", 40, 40, HOME, 0,
    )  # fmt: skip
    spike = _play(
        "Pass Incompletion", "(No Huddle) D.Jones spiked the ball to stop the clock.",
        33, 33, HOME, 0,
    )  # fmt: skip
    false_start = _play(
        "Penalty",
        "(Shotgun) PENALTY on NYG-J.Taylor, False Start, 5 yards, enforced at NYG 40 - No Play.",
        40, 35, HOME, -5,
    )  # fmt: skip
    holding = _play(
        "Penalty",
        "(Shotgun) D.Jones scrambles up the middle to NYG 46 for 6 yards (L.London).PENALTY on "
        "NYG-M.Bergeron, Offensive Holding, 10 yards, enforced at NYG 40 - No Play.",
        40, 30, HOME, -10,
    )  # fmt: skip
    declined = _play(
        "Penalty",
        "D.Jones pass incomplete short left.Penalty on WSH-N.Muse, Offensive Offside, declined.",
        40, 40, HOME, 0,
    )  # fmt: skip
    timeout = _play("Timeout", "Timeout #2 by NYG at 00:45.", 40, 40, HOME, 0)
    official = _play("Official Timeout", "Official Timeout at 11:12.", 40, 40, HOME, 0)
    warning = _play("Two-Minute Warning", "Two-Minute Warning", 40, 40, HOME, 0)
    halftime_game = _game(now, "in", 10, 17, "Halftime", name="STATUS_HALFTIME")
    end_q = _play("End Period", "END QUARTER 1", 46, 46, HOME, 0)
    end_half = _play("End of Half", "END QUARTER 2", 46, 46, HOME, 0)
    end_game = _play("End of Game", "END GAME", 46, 46, HOME, 0)
    kneel = _play("Rush", "D.Jones kneels to NYG 22 for -1 yards.", 23, 22, HOME, -1)
    loss = _play(
        "Rush", "D.Singletary left tackle to WSH 41 for -2 yards (J.Smith).", 43, 41, HOME, -2
    )
    odd = _play(
        "Blocked Punt", "T.Way punt is BLOCKED by J.Smith, recovered at NYG 20.", 24, 20, AWAY, 0
    )
    sack = _play(
        "Sack", "(Shotgun) D.Jones sacked at NYG 34 for -6 yards (L.London).", 40, 34, HOME, -6
    )
    sack_zero = _play(
        "Sack", "(Shotgun) D.Jones sacked at NYG 40 for 0 yards (L.London).", 40, 40, HOME, 0
    )
    fair_catch = _play(
        "Punt", "J.Bailey punts 53 yards to WSH 12, Center-L.McCullough, fair catch by D.Meyers.",
        35, 88, HOME, 0, end_team=AWAY,
    )  # fmt: skip
    punt_return = _play(
        "Punt",
        "R.Rehkow punts 51 yards to NYG 27, Center-W.Wagner. O.Zaccheaus to NYG 24 for -3 yards.",
        78, 24, AWAY, -3, end_team=HOME,
    )  # fmt: skip
    out_of_bounds = _play(
        "Punt", "J.Bailey punts 37 yards to WSH 17, Center-L.McCullough, out of bounds.",
        46, 83, HOME, 0, end_team=AWAY,
    )  # fmt: skip
    punt_touchback = _play(
        "Punt", "T.Way punts 53 yards to end zone, Center-T.Ott, Touchback.",
        47, 20, AWAY, 0, end_team=HOME,
    )  # fmt: skip
    downed = _play(
        "Punt", "E.Evans punts 58 yards to WSH 18, Center-J.McQuaide, downed by NYG-J.Whittington.",
        24, 82, HOME, 0, end_team=AWAY,
    )  # fmt: skip
    td = _play(
        "Rushing Touchdown",
        "D.Singletary rush left end for 3 yards, TOUCHDOWN. G.Gano extra point is GOOD.",
        97, 100, HOME, 3, (10, 24), True,
    )  # fmt: skip
    miss_text = "{} yard field goal is No Good, {}."
    kick = _play("Field Goal Missed", miss_text.format("G.Gano 38", "Wide Left"), 62, 62, HOME, 38)
    miss_right = _play(
        "Field Goal Missed", miss_text.format("C.Smyth 52", "Wide Right"), 48, 48, HOME, 52
    )
    miss_short = _play(
        "Field Goal Missed", miss_text.format("C.Smyth 55", "Short"), 45, 45, HOME, 55
    )
    miss_block = _play(
        "Field Goal Missed", miss_text.format("C.Smyth 40", "Blocked"), 60, 60, HOME, 40
    )
    pick = _play(
        "Pass Interception Return",
        "D.Jones pass deep left INTERCEPTED by B.Carter at WSH 43.",
        57, 43, HOME, 0, turnover=True, end_team=AWAY,
    )  # fmt: skip
    base = {"game_id": 1, "away_score": 10, "home_score": 17}

    def event(cls: type[Event], play: Play, team: str = HOME, **kw: Any) -> Event:
        return cls(play=play, team=team, **{"scope": Scope.FULL, **base, **kw})

    touchdown = event(Touchdown, td, via="run", points=7, extra_point="good", home_score=24)
    pass_td = _play(
        "Passing Touchdown",
        "(Shotgun) M.Penix pass short right to C.Woerner for 1 yard, TOUCHDOWN. N.Folk extra point "
        "is GOOD.",
        99, 100, HOME, 1, (10, 24), True,
    )  # fmt: skip
    pass_touchdown = event(
        Touchdown, pass_td, via="pass", points=7, extra_point="good", home_score=24
    )
    fg_play = _play(
        "Field Goal Good", "N.Folk 31 yard field goal is GOOD.", 69, 69, HOME, 31, (10, 20), True
    )
    field_goal = event(FieldGoal, fg_play, made=True, yards=31, points=3, home_score=20)
    plain_play = _play(
        "Field Goal Good", "E.Evans 38 yard field goal is GOOD.", 21, 21, AWAY, 38, (13, 17), True
    )
    plain_fg = event(
        FieldGoal, plain_play, AWAY, scope=Scope.PLAIN, made=True, yards=38, points=3, away_score=13
    )
    quick_fg = event(
        FieldGoal, fg_play, scope=Scope.QUICK, made=True, yards=31, points=3, home_score=20
    )
    quick_td = event(
        Touchdown, td, via="run", points=7, extra_point="good", home_score=24, scope=Scope.QUICK
    )
    miss = event(FieldGoal, kick, made=False, yards=38, miss="Wide Left")
    turnover = event(Turnover, pick, AWAY, reason="interception", lost_by=HOME, favourite="lost")
    fumble_play = _play(
        "Fumble Recovery (Opponent)",
        "(Shotgun) D.Jones pass short left to K.Pitts to NYG 20 for 9 yards. FUMBLES (L.London), "
        "RECOVERED by WSH-T.Campbell at NYG 19.",
        30, 19, HOME, 0, turnover=True, end_team=AWAY,
    )  # fmt: skip
    fumble = event(Turnover, fumble_play, AWAY, reason="fumble", lost_by=HOME, favourite="lost")
    gained_play = _play(
        "Pass Interception Return",
        "(Shotgun) M.Penix pass short middle INTERCEPTED by D.Singletary at NYG 43.",
        57, 43, AWAY, 0, turnover=True, end_team=HOME,
    )  # fmt: skip
    gained = event(
        Turnover, gained_play, HOME, reason="interception", lost_by=AWAY, favourite="gained"
    )
    downs_play = _play(
        "Rush", "D.Jones rush up the middle for 1 yard.", 40, 41, HOME, 1, end_team=AWAY
    )
    on_downs = event(
        Turnover, downs_play, AWAY, reason="on_downs", lost_by=HOME, favourite="neither"
    )
    safety_play = _play(
        "Safety",
        "(Shotgun) M.Penix sacked in End Zone for a SAFETY. The ball is free kicked to WSH.",
        4, 2, AWAY, -2, (10, 19),
    )  # fmt: skip
    safety = event(GenericScore, safety_play, points=2, home_score=19)
    two_point_play = _play(
        "Two-Point Conversion",
        "TWO-POINT CONVERSION ATTEMPT. D.Jones pass to K.Pitts is complete. ATTEMPT SUCCEEDS.",
        98, 100, HOME, 2, (10, 26),
    )  # fmt: skip
    two_point = event(GenericScore, two_point_play, points=2, home_score=26, scope=Scope.QUICK)
    toss = event(CoinToss, rush, HOME, kicker=AWAY)
    reversal = event(
        Reversal, td, original=touchdown, original_kind="touchdown", title="TOUCHDOWN OVERTURNED",
        rules=("flag_cleared",), rule="flag_cleared", reason="OFFENSIVE HOLDING ON NYG, NO PLAY",
        review=None, current=None, down_distance="1st & 10",
    )  # fmt: skip
    long_reversal = event(
        Reversal, td, original=touchdown, original_kind="touchdown", title="FIELD GOAL NEGATED",
        rules=("flag_cleared",), rule="flag_cleared",
        reason="D.JONES PASS INCOMPLETE SHORT LEFT TO K.PITTS, THE PLAY WAS REVERSED",
        review=None, current=None, down_distance="3rd & 7",
    )  # fmt: skip

    carrier = Person("rusher", 22, "D. Singletary", "22", "RB", True)
    woerner = Person("scorer", 40, "C. Woerner", "14", "TE", True)
    penix = Person("passer", 41, "M. Penix", "9", "QB", True)
    folk = Person("kicker", 42, "N. Folk", "6", "K", True)
    zaccheaus = Person("returner", 5, "O. Zaccheaus", "5", "WR", True)
    meyers = Person("returner", 4, "D. Meyers", "11", "WR", True)
    london = Person("sackedBy", 30, "L. London", "91", "DE", True)
    pitts = Person("target", 7, "K. Pitts", "8", "TE", True)
    robinson = Person("rusher", 9, "B. Robinson", "9", "RB", True)
    qb = Person("passer", 9, "M. Penix", "9", "QB", True)
    dotson = Person("receiver", 1, "J. Dotson", "1", "WR", True)
    wr = Person("receiver", 2, "W. Robinson", "17", "WR", True)
    jones = Person("passer", 3, "D. Jones", "8", "QB", True)

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

    def run(play: Play, at: float, *who: Person | None) -> Scene:
        return scene("fb_play", "play", play, at=at, seconds=animation_seconds(play, 3.0),
                     people=tuple(p for p in who if p))  # fmt: skip

    return [
        DemoStep(run(rush, 1.0, carrier), name="fb_run"),
        DemoStep(run(rush, 9.0, carrier), name="fb_run_settled"),
        DemoStep(run(outside, 1.2, robinson), name="fb_run_outside"),
        DemoStep(run(loss, 1.2, carrier), name="fb_run_loss"),
        DemoStep(run(kneel, 1.0, None), name="fb_run_kneel"),
        DemoStep(run(kickoff, 1.5, meyers), name="kickoff_air"),
        DemoStep(run(kickoff, 3.8, meyers), name="kickoff_return"),
        DemoStep(run(touchback, 3.2, None), name="kickoff_touchback"),
        DemoStep(run(onside, 1.2, None), name="kickoff_onside"),
        DemoStep(run(end_q, 0.5), name="end_quarter_wipe"),
        DemoStep(run(end_q, 2.0), name="end_quarter"),
        DemoStep(run(end_half, 2.0), name="end_half"),
        DemoStep(run(end_game, 2.0), name="end_game"),
        DemoStep(Scene("fb_halftime", fb_game=halftime_game), name="halftime"),
        DemoStep(run(timeout, 0.5, jones), name="timeout_spin"),
        DemoStep(run(timeout, 2.0, jones), name="timeout"),
        DemoStep(run(official, 2.0), name="timeout_official"),
        DemoStep(run(warning, 2.0), name="timeout_two_minute"),
        DemoStep(run(holding, 0.6, jones), name="penalty_after_run"),
        DemoStep(run(false_start, 1.6, jones), name="penalty_flag"),
        DemoStep(run(false_start, 2.6, jones), name="penalty"),
        DemoStep(run(false_start, 4.0, jones), name="penalty_no_play"),
        DemoStep(run(declined, 2.6, jones), name="penalty_declined"),
        DemoStep(run(sack, 0.7, jones, london), name="sack_drop"),
        DemoStep(run(sack, 1.6, jones, london), name="sack"),
        DemoStep(run(sack, 3.0, jones, london), name="sack_settled"),
        DemoStep(run(sack_zero, 1.5, jones, london), name="sack_zero"),
        DemoStep(run(incomplete, 1.1, qb, pitts), name="incomplete_air"),
        DemoStep(run(incomplete, 1.9, qb, pitts), name="incomplete"),
        DemoStep(run(deep_incomplete, 1.9, jones), name="incomplete_deep"),
        DemoStep(run(spike, 1.9, jones), name="incomplete_spike"),
        DemoStep(run(pass_play, 0.2, qb, dotson), name="fb_pass_snap"),
        DemoStep(run(pass_play, 1.0, qb, dotson), name="fb_pass"),
        DemoStep(run(pass_play, 2.2, qb, dotson), name="fb_pass_catch"),
        DemoStep(run(pass_play, 9.0, qb, dotson), name="fb_pass_settled"),
        DemoStep(run(deep, 1.0, jones, wr), name="fb_pass_deep"),
        DemoStep(scene("fb_play", "play", odd), name="fb_play_generic"),
        DemoStep(run(fair_catch, 1.5, meyers), name="punt_air"),
        DemoStep(run(fair_catch, 4.0, meyers), name="punt_fair_catch"),
        DemoStep(run(punt_return, 3.8, zaccheaus), name="punt_return"),
        DemoStep(run(out_of_bounds, 3.4, None), name="punt_out_of_bounds"),
        DemoStep(run(punt_touchback, 3.1, None), name="punt_touchback"),
        DemoStep(run(downed, 3.2, None), name="punt_downed"),
        DemoStep(scene("fb_playtext", "playtext", rush), name="fb_playtext"),
        DemoStep(
            scene("fb_event", "event", td, touchdown, at=0.06, seconds=6.0), name="touchdown_flash"
        ),
        DemoStep(
            scene("fb_event", "event", td, touchdown, at=1.3, seconds=6.0), name="touchdown_strobe"
        ),
        DemoStep(
            scene("fb_event", "event", td, touchdown, at=2.2, seconds=6.0), name="touchdown_letters"
        ),
        DemoStep(scene("fb_event", "event", td, touchdown, at=4.2, seconds=6.0), name="touchdown"),
        DemoStep(
            scene("fb_event", "event", td, quick_td, at=2.0, seconds=4.0), name="touchdown_quick"
        ),
        DemoStep(
            scene("fb_event", "event", safety_play, safety, at=1.0, seconds=6.0), name="fb_score"
        ),
        DemoStep(
            scene("fb_event", "event", two_point_play, two_point, at=1.0, seconds=4.0),
            name="fb_score_quick",
        ),
        DemoStep(
            scene(
                "fb_event", "detail", pass_td, pass_touchdown, seconds=8.0, people=(woerner, penix)
            ),
            name="score_detail",
        ),
        DemoStep(
            scene("fb_event", "detail", td, touchdown, seconds=8.0, people=(carrier,)),
            name="score_detail_run",
        ),
        DemoStep(
            scene("fb_event", "detail", fg_play, field_goal, seconds=8.0, people=(folk,)),
            name="score_detail_fieldgoal",
        ),
        DemoStep(
            scene("fb_play", "play", fg_play, field_goal, at=2.0, seconds=4.0), name="fieldgoal"
        ),
        DemoStep(
            scene("fb_play", "play", plain_play, plain_fg, at=2.0, seconds=4.0),
            name="fieldgoal_opponent",
        ),
        DemoStep(
            scene("fb_event", "event", fg_play, field_goal, at=0.8, seconds=6.0),
            name="fieldgoal_celebration",
        ),
        DemoStep(
            scene("fb_event", "event", fg_play, quick_fg, at=1.5, seconds=4.0),
            name="fieldgoal_quick",
        ),
        DemoStep(scene("fb_play", "play", kick, miss, at=1.9, seconds=3.0), name="fg_miss"),
        DemoStep(
            scene("fb_play", "play", miss_right, miss, at=1.9, seconds=3.0), name="fg_miss_right"
        ),
        DemoStep(
            scene("fb_play", "play", miss_short, miss, at=1.9, seconds=3.0), name="fg_miss_short"
        ),
        DemoStep(
            scene("fb_play", "play", miss_block, miss, at=1.9, seconds=3.0), name="fg_miss_blocked"
        ),
        DemoStep(
            scene("fb_event", "event", pick, turnover, at=1.1, seconds=4.0), name="turnover_arrow"
        ),
        DemoStep(scene("fb_event", "event", pick, turnover, at=3.4, seconds=4.0), name="turnover"),
        DemoStep(
            scene("fb_event", "event", gained_play, gained, at=3.4, seconds=4.0),
            name="turnover_gained",
        ),
        DemoStep(
            scene("fb_event", "event", fumble_play, fumble, at=3.4, seconds=4.0),
            name="turnover_fumble",
        ),
        DemoStep(
            scene("fb_event", "event", downs_play, on_downs, at=3.4, seconds=4.0),
            name="turnover_on_downs",
        ),
        DemoStep(scene("fb_event", "event", rush, toss, at=1.1, seconds=6.0), name="cointoss_flip"),
        DemoStep(
            scene("fb_event", "event", rush, toss, at=3.2, seconds=6.0), name="cointoss_landed"
        ),
        DemoStep(
            scene("fb_event", "event", rush, toss, at=5.5, seconds=6.0), name="cointoss_result"
        ),
        DemoStep(scene("fb_event", "reversal", td, reversal, at=2.0, seconds=5.0), name="reversal"),
        DemoStep(
            scene("fb_event", "reversal", td, long_reversal, at=3.2, seconds=5.0),
            name="reversal_scrolling",
        ),
    ]


def _preview_steps() -> list[DemoStep]:
    """The next-game preview (#424): plain, a Thursday-night game, and Thanksgiving."""
    from .idle_views import PreviewView, game_tag

    def view(start: datetime, away: str, home: str, week: str, records: tuple[str, str]):
        return Scene(
            "fb_preview",
            fb_idle=PreviewView(away, home, start, game_tag(start), week, *records),
        )

    plain = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    night = datetime(2026, 12, 4, 0, 20, tzinfo=UTC)
    turkey = datetime(2026, 11, 26, 17, 30, tzinfo=UTC)
    return [
        DemoStep(view(plain, "DAL", "NYG", "WEEK 11", ("4-5", "5-3-1")), name="fb_preview"),
        DemoStep(
            view(night, "NYG", "PHI", "WEEK 13", ("5-3-1", "7-2")), name="fb_preview_primetime"
        ),
        DemoStep(
            view(turkey, "DET", "NYG", "WEEK 12", ("6-3", "5-3-1")), name="fb_preview_thanksgiving"
        ),
    ]


def _final_steps(now: datetime) -> list[DemoStep]:
    """The held final (#426): with the recap, and without leaders (the margin instead)."""
    from .idle_views import build_final

    def view(game: FbGame):
        from ..config import FootballConfig
        from .idle import IdleSnapshot
        from .idle_screens import IdleContext

        ctx = IdleContext(0.0, now, [game], IdleSnapshot(), FootballConfig(favourite_team=HOME))
        return Scene("fb_final", fb_game=game, fb_idle=build_final(ctx))

    leaders = (
        ("passingYards", "D. Jones", HOME, "24/33, 312 YDS, 2 TD"),
        ("rushingYards", "S. Barkley", HOME, "21 CAR, 118 YDS, 1 TD"),
        ("receivingYards", "T. McLaurin", AWAY, "7 REC, 96 YDS"),
    )
    kwargs = {"detail": "Final", "name": "STATUS_FINAL"}
    return [
        DemoStep(view(_game(now, "post", 20, 27, leaders=leaders, **kwargs)), name="fb_final"),
        DemoStep(view(_game(now, "post", 20, 27, **kwargs)), name="fb_final_no_recap"),
    ]


def _bye_steps() -> list[DemoStep]:
    """The bye-week screen (#425): with the next game known, and without."""
    from .idle_views import ByeView, PreviewView

    start = datetime(2026, 11, 22, 18, 0, tzinfo=UTC)
    nxt = PreviewView("NYG", "DAL", start, "", "WEEK 11")
    return [
        DemoStep(Scene("fb_bye", fb_idle=ByeView("NYG", nxt)), name="fb_bye"),
        DemoStep(Scene("fb_bye", fb_idle=ByeView("NYG")), name="fb_bye_no_next"),
    ]


def nfl_demo_steps(now: datetime) -> list[DemoStep]:
    """Every NFL screen there is, in a sensible viewing order."""
    pregame = _game(now, "pre", name="STATUS_SCHEDULED", start=now + timedelta(days=2, hours=3))
    countdown = _game(
        now,
        "pre",
        name="STATUS_SCHEDULED",
        start=now + timedelta(minutes=42, seconds=15),
        records=("5-3-1", "4-5"),
        broadcast="FOX",
    )
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
        step("fb_countdown", "fb_countdown", countdown),
        *_preview_steps(),
        *_bye_steps(),
        *_final_steps(now),
        step("fb_scores", "fb_scores_live", live),
        step("fb_scores", "fb_scores_redzone", red),
        step("fb_scores", "fb_scores_halftime", half),
        step("fb_scores", "fb_scores_final", final),
        step("fb_field", "fb_field", live),
        step("fb_field", "fb_field_redzone", red),
        *_play_scenes(now),
    ]
