"""``fb_final`` (#426): the held final, its recap, and the hold."""

from __future__ import annotations

import json

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display import football_idle
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import (
    build_final,
    margin_line,
    recap_lines,
    surname,
)
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.teams import TEAMS, team_color
from test_football_idle import Clock, IdleFeed
from test_football_idle_preview import FIXTURES, Art, utc
from test_football_scenes import H, check_snapshot, game, raw_game, renderer

LEADERS = json.loads((FIXTURES / "scoreboard_leaders_trimmed.json").read_text())
FINAL = FbGame.from_api(LEADERS["events"][0])


def final_game(away="WSH", home="NYG", a=24, h=21, leaders=(), short="Final", period=4):
    raw = raw_game(away, home, "post", a, h, short=short, name="STATUS_FINAL", period=period)
    comp = raw["competitions"][0]
    comp["leaders"] = [
        {
            "name": category,
            "leaders": [
                {
                    "displayValue": display,
                    "athlete": {
                        "shortName": name,
                        "jersey": "9",
                        "position": {"abbreviation": "QB"},
                    },
                    "team": {"id": str(TEAMS[team].espn_id)},
                }
            ],
        }
        for category, name, team, display in leaders
    ]
    return FbGame.from_api(raw)


LINES = (
    ("passingYards", "D. Jones", "NYG", "24/33, 312 YDS, 2 TD"),
    ("rushingYards", "S. Barkley", "NYG", "21 CAR, 118 YDS, 1 TD"),
    ("receivingYards", "T. McLaurin", "WSH", "7 REC, 96 YDS"),
)


class Logos:
    """Every crest a bright square, so a dimmed one is told apart."""

    def get(self, abbrev, size):
        return Art((200, 200, 200))


def ctx(games, favourite="NYG"):
    return IdleContext(0.0, utc(2026, 11, 15, 22), list(games), idle.IdleSnapshot(),
                       FootballConfig(favourite_team=favourite))  # fmt: skip


# -- surnames, yards and the margin -----------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("J.J. McCarthy", "MCCARTHY"),
        ("C. Skattebo", "SKATTEBO"),
        ("Odell Beckham Jr.", "BECKHAM"),
        ("A. St. Brown", "BROWN"),
        ("Madonna", "MADONNA"),
        ("", ""),
    ],
)
def test_surnames(name, expected):
    assert surname(name) == expected


def test_the_real_fixtures_leaders_become_recap_lines():
    assert FINAL.is_final and len(FINAL.leaders) == 3
    lines = recap_lines(FINAL)
    assert [(line.surname, line.yards, line.category) for line in lines] == [
        ("MCCARTHY", 293, "passingYards"),
        ("SKATTEBO", 78, "rushingYards"),
        ("LIKELY", 127, "receivingYards"),
    ]
    assert {line.team for line in lines} <= {FINAL.home.abbrev, FINAL.away.abbrev}


def test_a_leader_without_yards_or_on_neither_team_is_dropped():
    g = final_game(
        leaders=(
            ("passingYards", "A. One", "NYG", "no number here"),
            ("rushingYards", "B. Two", "DAL", "10 CAR, 50 YDS"),  # DAL is not in this game
            ("receivingYards", "C. Three", "WSH", "4 REC, 61 YDS"),
        )
    )
    assert [line.surname for line in recap_lines(g)] == ["THREE"]


def test_a_leader_with_no_team_is_dropped_not_guessed():
    g = final_game(leaders=(("passingYards", "A. One", "NYG", "300 YDS"),))
    raw = g.leaders[0]
    import dataclasses

    nameless = dataclasses.replace(g, leaders=(dataclasses.replace(raw, team_id=None),))
    assert recap_lines(nameless) == ()


def test_the_margin_line():
    assert margin_line(final_game(a=20, h=27)) == "NYG WIN BY 7"
    assert margin_line(final_game(a=31, h=27)) == "WSH WIN BY 4"
    assert margin_line(final_game(a=24, h=24)) == "TIE GAME"


# -- the builder ------------------------------------------------------------------------------


def test_the_builder_wants_the_favourites_final_and_marks_overtime():
    view = build_final(ctx([final_game(leaders=LINES)]))
    assert view.status == "FINAL" and len(view.recap) == 3 and view.margin == "WSH WIN BY 3"
    ot = build_final(ctx([final_game(short="Final/OT", period=5)]))
    assert ot.status == "FINAL/OT" and ot.recap == ()
    assert build_final(ctx([final_game()], favourite="DAL")) is None
    assert build_final(ctx([final_game()], favourite="")) is None
    live = FbGame.from_api(raw_game("WSH", "NYG", "in", 3, 0))
    assert build_final(ctx([live])) is None
    assert IDLE_SCREENS["fb_final"](ctx([final_game()])) == build_final(ctx([final_game()]))


# -- drawing ----------------------------------------------------------------------------------


def draw(view, logos=True, width=128):
    r = renderer(width)
    r.nfl_logos = Logos() if logos else None
    c = AsciiCanvas(width, H)
    r.draw_fb_final(c, view, utc(2026, 11, 15))
    return c


def view_of(game_):
    return build_final(ctx([game_], favourite=game_.home.abbrev))


def test_snapshots(update_snapshots):
    full = view_of(final_game("WSH", "NYG", 20, 27, leaders=LINES))
    bare = view_of(final_game("WSH", "NYG", 20, 27))
    for name, view in (("fb_final", full), ("fb_final_no_recap", bare)):
        c = draw(view)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


def test_the_loser_is_dimmed_and_a_tie_dims_nobody():
    def brightness(c, side):
        pixels = [col for (x, _), col in c.pixels.items() if (x < 30 if side == "L" else x > 98)]
        return max((max(p) for p in pixels), default=0)

    away_wins = draw(view_of(final_game(a=30, h=10)))
    assert brightness(away_wins, "L") > brightness(away_wins, "R")
    home_wins = draw(view_of(final_game(a=10, h=30)))
    assert brightness(home_wins, "R") > brightness(home_wins, "L")
    tie = draw(view_of(final_game(a=17, h=17)))
    assert brightness(tie, "L") == brightness(tie, "R")


def test_the_recap_takes_each_leaders_team_colour_and_drops_what_does_not_fit():
    c = draw(view_of(final_game(leaders=LINES)))
    colours = set(c.pixels.values())
    assert team_color("NYG") in colours
    short = recap_segments_for(final_game(leaders=LINES))
    assert [t for t, _ in short] == ["JONES 312 YD", "BARKLEY 118 YD"]  # McLaurin does not fit
    only_two = recap_segments_for(final_game(leaders=LINES[:2]))
    assert len(only_two) == 2


def recap_segments_for(g, width=124):
    return football_idle.recap_segments(renderer(), view_of(g), width)


def test_no_leaders_means_the_margin():
    assert recap_segments_for(final_game(a=20, h=27)) == [("NYG WIN BY 7", football_idle.DIM)]


def test_every_real_and_awkward_name_fits_the_row():
    names = ["J.J. McCarthy", "C. Skattebo", "I. Likely", "Amon-Ra St. Brown",
             "Christian McCaffrey III", "Wolfgang Ziegler-Hammersmith", "X"]  # fmt: skip
    for name in names:
        for yards in (7, 78, 312, 1005):
            g = final_game(leaders=(("passingYards", name, "NYG", f"{yards} YDS"),) * 1
                           + (("rushingYards", name, "WSH", f"{yards} YDS"),))  # fmt: skip
            for width in (128,):
                c = draw(view_of(g), width=width)
                assert not c.out_of_bounds, (name, yards)


def test_every_team_pairing_and_a_missing_crest_fit_the_panel():
    for away, home in (("KC", "NYG"), ("GB", "LAC"), ("DET", "TB")):
        for logos in (True, False):
            c = draw(view_of(final_game(away, home, 41, 38, leaders=LINES[:1] and ())), logos)
            assert c.pixels and not c.out_of_bounds


# -- the hold, through the real mode ----------------------------------------------------------


class Feed(IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None


def test_the_hold_is_sixty_minutes_from_the_end_we_watched_and_never_replays_after_a_restart():
    clock = Clock(1000.0)
    live = game("WSH", "NYG", "in", 10, 7, game_id=3)
    done = final_game(leaders=LINES)
    object.__setattr__(done, "id", live.id) if False else None
    feed = Feed([live])
    cfg = FootballConfig(favourite_team="NYG", rotation=[{"screen": "clock", "seconds": 5}])
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    mode.scene()  # watched live
    feed.games = [FbGame.from_api({**raw_game("WSH", "NYG", "post", 24, 21, short="Final",
                                              name="STATUS_FINAL", game_id=3)})]  # fmt: skip
    mode.worker.poll_once()
    scene = mode.scene()
    assert scene.kind == "fb_final" and scene.fb_idle.status == "FINAL"
    for _ in range(59):
        clock.t += 60
        mode.worker.poll_once()
    assert mode.scene().kind == "fb_final"
    for _ in range(2):
        clock.t += 60
        mode.worker.poll_once()
    assert mode.scene().kind != "fb_final"
    # A fresh board (a restart) that only ever sees the final never holds it.
    fresh = NflMode(client_factory=lambda: feed, monotonic=Clock(5000.0), football=lambda: cfg)
    fresh.worker.poll_once()
    assert fresh.scene().kind != "fb_final"


def test_the_hold_length_is_the_settings():
    clock = Clock(1000.0)
    feed = Feed([game("WSH", "NYG", "in", 10, 7, game_id=3)])
    cfg = FootballConfig(favourite_team="NYG", final_hold_minutes=5)
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    mode.scene()
    feed.games = [FbGame.from_api(raw_game("WSH", "NYG", "post", 24, 21, short="Final",
                                           name="STATUS_FINAL", game_id=3))]  # fmt: skip
    mode.worker.poll_once()
    assert mode.scene().kind == "fb_final"
    for _ in range(6):
        clock.t += 60
        mode.worker.poll_once()
    assert mode.scene().kind != "fb_final"


from test_football_scenes import _pixels, app  # noqa: E402,F401  (the real-app fixture)


def test_the_app_draws_the_held_final(app):  # noqa: F811
    scene = type(app.select_scene())  # noqa: F841
    from nhl_scoreboard.app import Scene

    g = final_game(leaders=LINES)
    assert _pixels(app, Scene("fb_final", fb_game=g, fb_idle=view_of(g)))
