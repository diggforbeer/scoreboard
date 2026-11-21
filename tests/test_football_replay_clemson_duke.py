"""Replay of a whole real game: Clemson at Duke, 2026-11-20 (final 20-10).

The fixture is every one of the game's 188 plays as ESPN's ``summary`` listed them afterwards
(trimmed, ``fixtures/football/live/clemson_duke_plays.json``). Fed to the real college director
poll by poll, it answers what the board would have shown through the whole game, which the live
capture could not (it died at halftime).

What it cannot say: feed lag, or how ESPN's own ``situation`` behaved live. The red zone test
*derives* ``isRedZone`` from each play's yard line (inside the opponent's 20); whether ESPN's
flag follows that rule is still unverified.

The scoring plays of the game, in order: CLEM FG (Q2 0:17), CLEM TD (Q3 6:04), DUKE TD (Q3 5:15),
CLEM TD (Q4 8:52), DUKE FG (Q4 6:54), CLEM FG (Q4 1:01).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path

import pytest

from scoreboard.football import director as dr
from scoreboard.football import events as ev
from scoreboard.football.director import Director
from scoreboard.football.models import FbGame, FbSituation, Play
from scoreboard.football.redzone import RedZoneWatcher
from scoreboard.football.teams import use_directory
from scoreboard.football.worker import FeedSnapshot
from teamcfg import fcfg
from test_football_college import _fbs_directory
from test_football_queue import Clock

FIXTURE = Path(__file__).parent / "fixtures" / "football" / "live" / "clemson_duke_plays.json"
FBS = _fbs_directory()
CLEM, DUKE = 228, 150
GAME_ID = 401858303

#: (period, clock, scoring team, event class): the six scores of the game
SCORES = [
    (2, "0:17", "CLEM", ev.FieldGoal),
    (3, "6:04", "CLEM", ev.Touchdown),
    (3, "5:15", "DUKE", ev.Touchdown),
    (4, "8:52", "CLEM", ev.Touchdown),
    (4, "6:54", "DUKE", ev.FieldGoal),
    (4, "1:01", "CLEM", ev.FieldGoal),
]


@pytest.fixture(autouse=True)
def fbs():
    with use_directory(FBS):
        yield


def load():
    data = json.loads(FIXTURE.read_text())
    plays = [Play.from_api(p) for d in data["drives"] for p in d["plays"]]
    drive_sizes = [len(d["plays"]) for d in data["drives"]]
    return plays, drive_sizes


def live_game(state: str = "in", name: str = "STATUS_IN_PROGRESS") -> FbGame:
    comp = {
        "id": str(GAME_ID),
        "status": {"type": {"state": state, "name": name}},
        "competitors": [
            {"homeAway": "home", "score": "0", "team": {"id": str(DUKE), "abbreviation": "DUKE"}},
            {"homeAway": "away", "score": "0", "team": {"id": str(CLEM), "abbreviation": "CLEM"}},
        ],
    }
    return FbGame.from_api({"id": str(GAME_ID), "competitions": [comp]})


def replay(favourite, *, join_at=1, per_play=False, follow=()):
    """Every (scoring team, class, stage name) the board showed, polling as the feed would.

    The first ``join_at`` plays are the baseline (the board started then); after that the plays
    arrive a drive at a time, or one at a time with ``per_play``.
    """
    plays, sizes = load()
    game = live_game()
    clock = Clock()
    cfg = fcfg(favourite_team=favourite, also_follow=list(follow))
    director = Director(lambda: cfg, clock, lambda: 0.0, clock.utc, scores_only=True)
    director.ingest(FeedSnapshot(games=(game,), plays={game.id: tuple(plays[:join_at])}))
    cuts, total = [], 0
    for size in sizes:
        total += size
        cuts.append(total)
    steps = range(join_at + 1, len(plays) + 1) if per_play else [c for c in cuts if c > join_at]
    shown, last = [], None
    for upto in steps:
        director.ingest(FeedSnapshot(games=(game,), plays={game.id: tuple(plays[:upto])}))
        for _ in range(800):
            current = director.current(game.id)
            if current is None:
                break
            if current.stage is not last:
                last = current.stage
                shown.append((last, plays[upto - 1]))
            clock.advance(0.25)
        else:
            raise AssertionError("the director never came to rest")
    return shown


def screens(shown):
    return [
        (p.period, p.clock, s.event.team, type(s.event), s.stage)
        for s, p in shown
        if s.event is not None
    ]


# -- the game itself --------------------------------------------------------------------------


def test_the_fixture_is_the_whole_game_in_order():
    plays, _ = load()
    assert len(plays) == 188
    assert [p.sequence for p in plays] == sorted(p.sequence for p in plays)
    scoring = [(p.period, p.clock) for p in plays if p.scoring_play]
    assert scoring == [(q, c) for q, c, _, _ in SCORES]
    assert (plays[-1].away_score, plays[-1].home_score) == (20, 10)


# -- what the board shows through the game ------------------------------------------------------


def test_the_favourites_four_scores_each_get_a_celebration_and_a_detail_screen():
    got = screens(replay("CLEM"))
    mine = [(q, c, k) for q, c, t, k in SCORES if t == "CLEM"]
    assert [(q, c, k) for q, c, _, k, stage in got if stage == dr.EVENT] == [
        (q, c, k) for q, c, k in mine
    ]
    assert [(q, c, k) for q, c, _, k, stage in got if stage == dr.DETAIL] == [
        (q, c, k) for q, c, k in mine
    ]
    assert len(got) == 8, "two screens per score and nothing for the other 184 plays"


def test_the_other_team_is_the_favourite_and_the_screens_follow_it():
    got = screens(replay("DUKE"))
    theirs = [(q, c, k) for q, c, t, k in SCORES if t == "DUKE"]
    assert [(q, c, k) for q, c, _, k, stage in got if stage == dr.EVENT] == theirs
    assert len(got) == 4


def test_with_nobody_followed_a_whole_game_shows_nothing():
    assert replay("") == []


def test_every_celebration_is_the_scoring_teams_with_the_full_scope():
    for stage, _ in replay("CLEM"):
        if stage.event is not None:
            assert stage.event.scope == ev.Scope.FULL
            assert stage.event.team == "CLEM"


def test_polling_a_play_at_a_time_shows_exactly_the_same_screens():
    by_drive = screens(replay("CLEM"))
    by_play = screens(replay("CLEM", per_play=True))
    assert by_play == by_drive


def test_a_board_that_starts_at_halftime_announces_only_the_second_half():
    plays, _ = load()
    half = next(i for i, p in enumerate(plays) if p.kind.value == "end_half") + 1
    got = [
        (q, c) for q, c, _, _, stage in screens(replay("CLEM", join_at=half)) if stage == dr.EVENT
    ]
    assert got == [(3, "6:04"), (4, "8:52"), (4, "1:01")], "the first half's field goal is baseline"


def test_each_score_is_announced_exactly_once_however_the_feed_repeats_itself():
    plays, _ = load()
    game = live_game()
    clock = Clock()
    cfg = fcfg(favourite_team="CLEM")
    director = Director(lambda: cfg, clock, lambda: 0.0, clock.utc, scores_only=True)
    director.ingest(FeedSnapshot(games=(game,), plays={game.id: tuple(plays[:1])}))
    seen = 0
    for upto in range(2, len(plays) + 1):
        for _ in range(3):  # the same list handed over again, as an idle poll does
            director.ingest(FeedSnapshot(games=(game,), plays={game.id: tuple(plays[:upto])}))
        for _ in range(800):
            current = director.current(game.id)
            if current is None:
                break
            if current.elapsed == 0.0 and current.stage.stage == dr.EVENT:
                seen += 1
            clock.advance(0.25)
    assert seen == 4


# -- the red zone, derived from the plays ---------------------------------------------------------


def red_zone_alerts():
    """Alerts the watcher would queue if ``isRedZone`` were true inside the opponent's 20."""
    plays, _ = load()
    clock = Clock()
    watcher = RedZoneWatcher(clock)
    previous = None
    queued = []
    for p in plays:
        stamp = datetime.fromisoformat(p.wallclock.isoformat() if p.wallclock else "")
        if previous is not None:
            clock.advance(max(0.0, (stamp - previous).total_seconds()))
        previous = stamp
        offence = p.start.team_id if p.start else None
        in_zone = bool(
            p.start
            and p.start.down
            and p.start.yards_to_endzone is not None
            and p.start.yards_to_endzone <= 20
        )
        sit = FbSituation(
            down=p.start.down if p.start else None,
            distance=None,
            yard_line=None,
            short_down_distance_text="",
            down_distance_text="",
            possession_text="",
            possession_team_id=offence,
            is_red_zone=in_zone,
            home_timeouts=3,
            away_timeouts=3,
            last_play=None,
        )
        watcher.observe((dataclasses.replace(live_game(), situation=sit),))
        queued.extend(list(watcher._pending))
        watcher._pending.clear()
    return queued


def test_clemson_drove_into_the_red_zone_four_times_and_duke_never_did():
    alerts = red_zone_alerts()
    assert [a.team_id for a in alerts] == [CLEM] * 4
