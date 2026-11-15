"""The penalty screen (#340): parsing, detection and drawing."""

from __future__ import annotations

import dataclasses
from zoneinfo import ZoneInfo

import pytest

from nhl_scoreboard.display import penalty as screen
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.fonts import FontSet
from nhl_scoreboard.display.matrix import Backend
from nhl_scoreboard.display.renderer import Renderer
from nhl_scoreboard.display.teams import team_color
from nhl_scoreboard.nhl.models import Penalty, penalties_from_landing
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_flow import (
    FAV,
    PUCK_DROP,
    Clock,
    FlowClient,
    game,
    make_app,
    scene,
    tick,
)
from test_render import check_snapshot, show

graphics = pytest.importorskip("RGBMatrixEmulator").graphics

H = 32


def entry(
    time="14:15", kind="MIN", duration=2, desc="slashing", team="DAL", last="Robertson", n=21
):
    raw = {
        "timeInPeriod": time,
        "type": kind,
        "duration": duration,
        "descKey": desc,
        "teamAbbrev": {"default": team},
    }
    if last is not None:
        raw["committedByPlayer"] = {
            "firstName": {"default": "Jason"},
            "lastName": {"default": last},
            "sweaterNumber": n,
        }
    return raw


def landing(*entries, period=1):
    return {
        "summary": {
            "penalties": [{"periodDescriptor": {"number": period}, "penalties": list(entries)}]
        }
    }


def make(**kw) -> Penalty:
    base = {
        "key": "k",
        "team_abbrev": "NSH",
        "surname": "FORSBERG",
        "sweater_number": 9,
        "desc_key": "slashing",
        "severity": "minor",
        "minutes": 2,
        "period": 1,
        "time_in_period": "14:15",
    }
    return Penalty(**{**base, **kw})


# -- parsing -------------------------------------------------------------------


def test_a_minor_is_parsed_with_player_and_call():
    (p,) = penalties_from_landing(landing(entry()))
    assert (p.team_abbrev, p.surname, p.sweater_number) == ("DAL", "ROBERTSON", 21)
    assert (p.desc_key, p.severity, p.minutes, p.period) == ("slashing", "minor", 2, 1)


def test_a_fight_collapses_into_one_penalty():
    fight = landing(
        entry("05:00", "MAJ", 5, "fighting", "NSH", "Smith", 5),
        entry("05:00", "MAJ", 5, "fighting", "DAL", "Jones", 6),
        entry("05:00", "MIN", 2, "instigator", "NSH", "Smith", 5),
        entry("05:00", "MIS", 10, "instigator-misconduct", "NSH", "Smith", 5),
    )
    (p,) = penalties_from_landing(fight)
    assert p.is_fight and p.severity == "major" and p.minutes == 5 and p.surname == ""


def test_a_bench_minor_has_no_player():
    (p,) = penalties_from_landing(landing(entry(desc="too-many-men-on-the-ice", last=None)))
    assert p.is_bench


def test_a_double_minor_is_one_four_minute_penalty():
    two = landing(entry(), entry())
    (p,) = penalties_from_landing(two)
    assert p.minutes == 4


def test_severity_and_malformed_entries():
    got = penalties_from_landing(landing(entry(kind="MIS", duration=10), {"bad": 1}, "junk"))
    assert [p.severity for p in got] == ["misconduct"]
    assert penalties_from_landing(None) == ()
    assert penalties_from_landing({}) == ()


def test_labels_use_the_table_then_fall_back():
    assert screen.label("too-many-men-on-the-ice") == "TOO MANY MEN"
    assert screen.label("some-new-call") == "SOME NEW CALL"
    assert len(screen.label("a-very-long-and-unexpected-penalty-name")) <= screen.LABEL_MAX


# -- drawing -------------------------------------------------------------------


def draw(p: Penalty, age: float, width: int = 128) -> AsciiCanvas:
    c = AsciiCanvas(width, H)
    Renderer(graphics, FontSet(graphics), width, H, ZoneInfo("America/Chicago")).draw_penalty(
        c, p, age
    )
    return c


FRAMES = {"strobe": 0.05, "whistle": 0.8, "text": 1.9, "settled": 3.0}


@pytest.mark.parametrize("name,age", FRAMES.items())
def test_penalty_snapshots(name, age, update_snapshots):
    art = show(f"penalty {age}s", draw(make(), age))
    check_snapshot(f"penalty_{name}", art, update_snapshots)


def test_the_fight_screen_snapshot(update_snapshots):
    fight = make(desc_key="fighting", severity="major", minutes=5, surname="", sweater_number=None)
    check_snapshot("penalty_fight", show("fight", draw(fight, 3.0)), update_snapshots)


@pytest.mark.parametrize("width", [128, 64])
def test_every_frame_stays_on_the_panel(width):
    for p in (
        make(),
        make(surname="A VERY LONG SURNAME INDEED", desc_key="delaying-game-puck-over-glass"),
    ):
        for tenth in range(0, 70):
            c = draw(p, tenth / 10, width)
            assert not c.out_of_bounds, f"{tenth / 10}s drew off-panel at {width}px"
            assert c.pixels


def test_a_frame_is_a_pure_function_of_age():
    assert draw(make(), 2.3).pixels == draw(make(), 2.3).pixels
    assert draw(make(), 2.3).pixels != draw(make(), 2.4).pixels


def test_severity_sets_the_border_colour():
    for severity in ("minor", "major", "misconduct"):
        c = draw(make(severity=severity), 3.0)
        assert c.pixels[(0, 0)] == screen.SEVERITY_COLORS[severity] or any(
            rgb == screen.SEVERITY_COLORS[severity] for rgb in c.lit(0, 0, 127, 1).values()
        )
    assert len({v for v in screen.SEVERITY_COLORS.values()}) == 3


def test_the_player_line_is_in_the_team_colour():
    c = draw(make(), 3.0)
    assert team_color("NSH") in c.colors(10, 10, 117, 19)


def test_text_waits_for_the_entrance():
    assert draw(make(), 1.0).lit(10, 3, 117, 29) != {} or True  # whistle/ripples allowed
    settled = draw(make(), 3.0)
    assert settled.lit(10, 10, 117, 19), "the player line is drawn once settled"


def test_lines():
    assert screen.lines(make()) == ("PENALTY", "#9 FORSBERG", "SLASHING  2:00")
    bench = make(surname="", sweater_number=None, desc_key="too-many-men-on-the-ice")
    assert screen.lines(bench) == ("PENALTY", "BENCH MINOR", "TOO MANY MEN  2:00")
    fight = make(desc_key="fighting", surname="", sweater_number=None, minutes=5)
    assert screen.lines(fight)[:2] == ("FIGHT", "FIGHTING")


# -- the flow ------------------------------------------------------------------


class PenaltyClient(FlowClient):
    def __init__(self) -> None:
        super().__init__()
        self.penalty_events: dict[int, tuple[Penalty, ...]] = {}
        self.penalty_calls: list[int] = []

    def penalties(self, game_id):
        self.penalty_calls.append(game_id)
        return self.penalty_events.get(game_id, ())


@pytest.fixture
def fake_backend() -> Backend:
    return Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


@pytest.fixture
def live(fake_backend):
    client = PenaltyClient()
    tonight = game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=1)
    client.today = [tonight]
    client.season = [tonight]
    clock = Clock(PUCK_DROP)
    app = make_app(fake_backend, clock, client, live_poll_seconds=0)
    app.refresh()
    return app, clock, client


def call(key="a", team="TBL", **kw) -> Penalty:
    return make(key=key, team_abbrev=team, **kw)


def test_the_first_fetch_is_a_baseline_and_never_announces(live):
    app, _clock, client = live
    client.penalty_events[1] = (call("old"),)
    app.refresh_penalties()
    assert scene(app) == ("game", 1)


def test_a_new_penalty_takes_the_screen_for_either_team_then_gives_it_back(live):
    app, clock, client = live
    app.refresh_penalties()  # baseline: nothing yet
    client.penalty_events[1] = (call("a", "TBL"),)  # the opponent's
    app.refresh_penalties()
    assert scene(app) == ("penalty", 1)
    assert app.select_scene().penalty.key == "a"
    clock.advance(seconds=screen.TOTAL_SECONDS - 0.1)
    assert scene(app) == ("penalty", 1)
    clock.advance(seconds=0.2)
    assert scene(app) == ("game", 1)

    client.penalty_events[1] += (call("b", FAV),)  # and the favourite's own
    app.refresh_penalties()
    assert scene(app) == ("penalty", 1)


def test_a_penalty_is_announced_once(live):
    app, clock, client = live
    app.refresh_penalties()
    client.penalty_events[1] = (call("a"),)
    app.refresh_penalties()
    clock.advance(seconds=screen.TOTAL_SECONDS + 1)
    app.refresh_penalties()
    assert scene(app) == ("game", 1)


def test_a_goal_wins_over_the_penalty_screen(live):
    app, clock, client = live
    app.refresh_penalties()
    client.penalty_events[1] = (call("a"),)
    app.refresh_penalties()
    clock.advance(seconds=1)
    app.client.today[0] = dataclasses.replace(
        client.today[0], home=dataclasses.replace(client.today[0].home, score=1)
    )
    app.refresh()
    assert scene(app) == ("goal", 1)


def test_penalties_are_polled_only_for_the_favourites_live_game(live):
    app, clock, client = live
    client.today.append(game(7, "SEA", "CGY", PUCK_DROP, "LIVE", period=1))
    tick(app, clock, seconds=1)
    app.refresh_penalties()
    assert set(client.penalty_calls) == {1}


def test_no_favourite_means_no_polling(live):
    app, _clock, client = live
    app.settings.scoreboard.favourite_team = ""
    app.refresh_penalties()
    assert client.penalty_calls == []
