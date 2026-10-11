"""The shootout screen (#259): parsing, polling cadence and the grid itself."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from nhl_scoreboard.display.renderer import LIVE, LOSS, SUBDUED
from nhl_scoreboard.nhl.models import Game, Shootout, ShootoutAttempt, shootout_from_landing
from test_flow import FAV, PUCK_DROP, Clock, FlowClient, game, make_app
from test_flow import fake_backend as fake_backend  # fixture, re-exported for this module
from test_render import H, W, canvas, check_snapshot, make_renderer, show

# The 2026-10-10 NSH @ OTT capture from the issue: OTT (home) shot first.
CAPTURE = [
    ("OTT", "save", False),
    ("NSH", "goal", False),
    ("OTT", "goal", False),
    ("NSH", "save", False),
    ("OTT", "goal", True),
    ("NSH", "save", False),
]


def landing(events=CAPTURE, live=(1, 2)) -> dict:
    return {
        "summary": {
            "shootout": {
                "liveScore": {"away": live[0], "home": live[1]},
                "events": [
                    {
                        "sequence": i,
                        "teamAbbrev": {"default": team},
                        "result": result,
                        "gameWinner": winner,
                    }
                    for i, (team, result, winner) in enumerate(events, start=1)
                ],
            }
        }
    }


def so_game(away="NSH", home="OTT", state="LIVE", shootout=None) -> Game:
    raw = {
        "id": 7,
        "gameState": state,
        "startTimeUTC": "2026-10-10T23:00:00Z",
        "awayTeam": {"abbrev": away, "score": 2},
        "homeTeam": {"abbrev": home, "score": 2},
        "period": 5,
        "periodDescriptor": {"number": 5, "periodType": "SO"},
        "clock": {"timeRemaining": "00:00", "running": False},
    }
    return dataclasses.replace(Game.from_api(raw), shootout=shootout)


def rounds(spec: list[str], away="NSH", home="OTT") -> Shootout:
    attempts = []
    for pair in spec:
        for abbrev, mark in zip((away, home), pair, strict=True):
            if mark != "-":
                attempts.append(ShootoutAttempt(len(attempts) + 1, abbrev, mark == "g"))
    goals = [sum(a.scored for a in attempts if a.team_abbrev == t) for t in (away, home)]
    return Shootout(tuple(attempts), goals[0], goals[1])


# -- parsing ------------------------------------------------------------------


def test_absent_shootout_is_none():
    assert shootout_from_landing({"summary": {}}) is None
    assert shootout_from_landing(None) is None


def test_events_group_by_team_not_position():
    parsed = shootout_from_landing(landing())
    assert parsed.results_for("OTT") == (False, True, True)
    assert parsed.results_for("NSH") == (True, False, False)
    assert (parsed.away_goals, parsed.home_goals) == (1, 2)
    assert parsed.winner_decided


def test_unknown_result_is_a_miss_and_logged(caplog):
    with caplog.at_level(logging.WARNING):
        parsed = shootout_from_landing(landing([("NSH", "post", False)], live=(0, 0)))
    assert parsed.results_for("NSH") == (False,)
    assert "post" in caplog.text


def test_empty_events_and_malformed_event_are_tolerated():
    assert shootout_from_landing(landing([])).attempts == ()
    raw = landing()
    raw["summary"]["shootout"]["events"].append({"nonsense": True})
    assert len(shootout_from_landing(raw).attempts) == 6


# -- app: cadence and data flow --------------------------------------------------


@pytest.fixture
def so_app(fake_backend):
    clock = Clock(PUCK_DROP)
    client = FlowClient()
    client.today = [dataclasses.replace(so_game(FAV, "OTT"), id=1)]
    app = make_app(fake_backend, clock, client, shootout_poll_seconds=5.0)
    app.refresh()
    return app, clock, client


def test_poll_interval_speeds_up_in_a_shootout(so_app):
    app, _, _ = so_app
    assert app.poll_interval() == 5.0


def test_shootout_is_fetched_on_its_own_cadence(so_app):
    app, clock, client = so_app
    app.refresh_shootouts()
    app.refresh_shootouts()  # inside the interval: no second request
    assert client.shootout_calls == [1]
    clock.advance(seconds=5)
    app.refresh_shootouts()
    assert client.shootout_calls == [1, 1]


def test_shootout_reaches_the_drawn_game_and_survives_a_failed_fetch(so_app):
    app, clock, client = so_app
    client.shootouts[1] = rounds(["gx"])
    app.refresh_shootouts()
    shown = app.with_situation(app.games[0])
    assert shown.shows_shootout and shown.shootout == client.shootouts[1]
    client.fail_shootout = True
    clock.advance(seconds=5)
    app.refresh_shootouts()
    assert app.with_situation(app.games[0]).shootout == client.shootouts[1]


def test_finished_shootout_gets_one_last_fetch_then_stops(so_app):
    app, clock, client = so_app
    app.refresh_shootouts()
    final = dataclasses.replace(app.games[0], state="OFF")
    app.games = [final]
    client.shootouts[1] = rounds(["gx", "gx", "gx"])
    clock.advance(seconds=5)
    app.refresh_shootouts()
    assert app.with_situation(final).shootout == client.shootouts[1]
    n = len(client.shootout_calls)
    clock.advance(seconds=60)
    app.refresh_shootouts()
    assert len(client.shootout_calls) == n


def test_non_shootout_games_are_never_fetched(fake_backend):
    clock = Clock(PUCK_DROP)
    client = FlowClient()
    client.today = [game(1, "TBL", FAV, PUCK_DROP, "LIVE", period=2)]
    app = make_app(fake_backend, clock, client)
    app.refresh()
    app.refresh_shootouts()
    assert client.shootout_calls == []


# -- renderer ---------------------------------------------------------------------


def cell_colours(c, row: int) -> list[set]:
    """Distinct colours of each cell column in one row (0 = away, 1 = home)."""
    centre = (8, 20)[row]
    out = []
    for col in range(8):
        x0 = 34 + col * 11
        out.append(c.colors(x0, centre - 4, x0 + 8, centre + 4))
    return out


def test_grid_places_goals_and_misses_in_the_right_rows():
    c = canvas()
    # Away NSH: goal, miss, goal. Home OTT: miss, goal, (pending).
    make_renderer().draw_shootout(c, so_game(shootout=rounds(["gx", "xg", "g-"])))
    assert not c.out_of_bounds
    away, home = cell_colours(c, 0), cell_colours(c, 1)
    assert away[0] == {LIVE} and away[1] == {LOSS} and away[2] == {LIVE}
    assert home[0] == {LOSS} and home[1] == {LIVE} and home[2] == {SUBDUED}
    assert away[3] == set()  # nothing beyond the first three rounds


def test_empty_live_shootout_shows_three_pending_cells_per_team():
    c = canvas()
    make_renderer().draw_shootout(c, so_game())
    assert not c.out_of_bounds
    for row in (0, 1):
        cells = cell_colours(c, row)
        assert cells[:3] == [{SUBDUED}] * 3 and cells[3] == set()


def test_uneven_attempt_counts_do_not_break_the_grid():
    c = canvas()
    make_renderer().draw_shootout(c, so_game(shootout=rounds(["gx", "g-"])))
    assert not c.out_of_bounds
    assert cell_colours(c, 0)[1] == {LIVE}
    assert cell_colours(c, 1)[1] == {SUBDUED}


def test_sudden_death_grows_the_grid_then_scrolls_to_the_latest():
    c = canvas()
    spec = ["gx", "xg", "gg", "xx", "gx", "gg", "xx", "gx", "xg", "gg"]
    make_renderer().draw_shootout(c, so_game(shootout=rounds(spec)))
    assert not c.out_of_bounds
    away = cell_colours(c, 0)
    assert all(len(colours) == 1 and colours != [{SUBDUED}] for colours in away)
    # Capacity is 8 columns; the last away attempt (round 10, goal) is the last cell.
    assert away[-1] == {LIVE}
    assert c.bbox(W - 3, 0, W - 1, H - 1) is None  # nothing crowds the right edge


def test_winner_tally_is_highlighted_once_final():
    live, final = canvas(), canvas()
    data = rounds(["xg", "gx", "xg"])
    make_renderer().draw_shootout(live, so_game(shootout=data))
    make_renderer().draw_shootout(final, so_game(state="OFF", shootout=data))
    tally = (24, 0, 28, 31)
    assert (255, 210, 0) not in live.colors(*tally)
    assert (255, 210, 0) in final.colors(24, 14, 28, 26)  # home (OTT, 2-1) row
    assert (255, 210, 0) not in final.colors(24, 2, 28, 12)


@pytest.mark.parametrize(
    ("name", "state", "spec"),
    [
        ("shootout_start", "LIVE", []),
        ("shootout_live", "LIVE", ["gx", "g-"]),
        ("shootout_sudden_death", "LIVE", ["gx", "xg", "gg", "xx", "gx", "gg", "x-"]),
        ("shootout_final", "OFF", ["xg", "gx", "xg"]),
    ],
)
def test_shootout_snapshots(name, state, spec, update_snapshots):
    c = canvas()
    data = rounds(spec) if spec else None
    make_renderer().draw_shootout(c, so_game(state=state, shootout=data))
    assert not c.out_of_bounds
    check_snapshot(name, show(name, c), update_snapshots)
