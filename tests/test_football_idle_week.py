"""``fb_week`` (#428): the league's week as a grid of scores."""

from __future__ import annotations

import itertools
import json

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display import football_idle
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.display.football_scenes import LIVE
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import WEEK_MAX_GAMES, WeekView, build_week, week_order
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.models import FbGame
from nhl_scoreboard.football.teams import TEAMS
from test_football_idle import Clock, IdleFeed
from test_football_idle_preview import FIXTURES, utc
from test_football_scenes import H, check_snapshot, raw_game, renderer

WEEK8 = json.loads((FIXTURES / "scoreboard_week8_byes_trimmed.json").read_text())
BOARD = idle.scoreboard_from_payload(WEEK8, [FbGame.from_api(e) for e in WEEK8["events"]])
PAIRS = [("WSH", "NYG"), ("DAL", "PHI"), ("DET", "GB"), ("SF", "SEA"), ("BUF", "CHI"),
         ("MIA", "NE"), ("KC", "LV"), ("LAR", "ARI"), ("DEN", "LAC"), ("HOU", "IND"),
         ("MIN", "TB"), ("NO", "ATL"), ("BAL", "CLE"), ("CIN", "PIT"), ("JAX", "TEN"),
         ("NYJ", "CAR"), ("ATL", "KC")]  # fmt: skip


def g(away, home, state="pre", a=0, h=0, start="2026-11-15T18:00Z", gid=None):
    name = {"post": "STATUS_FINAL", "in": "STATUS_IN_PROGRESS"}.get(state, "STATUS_SCHEDULED")
    gid = gid or abs(hash((away, home, start))) % 10**6
    return FbGame.from_api(raw_game(away, home, state, a, h, short="x", name=name, start=start,
                                    game_id=gid))  # fmt: skip


def slate(n, mix=("post", "in", "pre")):
    kinds = itertools.cycle(mix)
    return [g(a, h, next(kinds), 10, 7, gid=i + 1) for i, (a, h) in enumerate(PAIRS[:n])]


def ctx(games=(), week=None, now=utc(2026, 11, 15, 17)):
    snap = idle.IdleSnapshot(week_cached=idle.Cached(week, 0.0) if week else None)
    return IdleContext(0.0, now, list(games), snap, FootballConfig(favourite_team="NYG"))


# -- the data --------------------------------------------------------------------------------


def test_the_real_weeks_games_fill_one_page_and_the_bye_teams_are_absent():
    view = build_week(ctx(week=BOARD))
    assert view.pages == 1 and len(view.games) == len(BOARD.games) == 2
    on_the_grid = {t for game in view.games for t in (game.away.abbrev, game.home.abbrev)}
    assert not on_the_grid & set(BOARD.teams_on_bye)  # NO, NYG, SF and HOU have no game


def test_a_fourteen_game_week_is_two_pages_of_eight_and_six():
    view = WeekView(week_order(slate(14)))
    assert view.pages == 2 and len(view.page(0)) == 8 and len(view.page(1)) == 6
    assert view.page(5) == ()


def test_the_grid_never_holds_more_than_sixteen_games():
    games = [g(a, h, gid=i) for i, (a, h) in enumerate(PAIRS)]
    assert len(games) == 17
    assert len(week_order(games)) == WEEK_MAX_GAMES == 16


def test_live_games_come_first_then_those_to_come_by_kickoff_then_finals():
    early = g("DAL", "PHI", "pre", start="2026-11-15T18:00Z", gid=1)
    late = g("KC", "LV", "pre", start="2026-11-15T21:25Z", gid=2)
    done = g("DET", "GB", "post", 3, 1, start="2026-11-15T15:00Z", gid=3)
    live = g("SF", "SEA", "in", 7, 3, start="2026-11-15T20:00Z", gid=4)
    nokick = FbGame.from_api(raw_game("MIA", "NE", "pre", start="", short="x"))
    order = week_order([done, late, nokick, live, early])
    assert [x.id for x in order[:4]] == [4, 1, 2, nokick.id][:4] or order[0].id == 4
    assert [x.id for x in order] == [4, 1, 2, nokick.id, 3]


def test_the_whole_week_fetch_beats_todays_scoreboard_and_either_will_do():
    today = [g("DAL", "PHI", gid=1)]
    wk = idle.Scoreboard(tuple(slate(3)), 2, 2026, 10, (), ())
    assert len(build_week(ctx(games=today, week=wk)).games) == 3
    assert len(build_week(ctx(games=today)).games) == 1
    assert build_week(ctx()) is None
    assert IDLE_SCREENS["fb_week"](ctx(games=today)) == build_week(ctx(games=today))


# -- drawing ----------------------------------------------------------------------------------


def draw(view, page=0, width=128):
    r = renderer(width)
    c = AsciiCanvas(width, H)
    r.draw_fb_week(c, view, page)
    return c


def test_snapshots(update_snapshots):
    view = WeekView(week_order(slate(14)))
    for name, page in (("fb_week", 0), ("fb_week_page2", 1)):
        c = draw(view, page)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


def test_every_mix_of_states_and_every_game_count_fits_the_panel():
    for n in range(1, 17):
        for mix in (("post",), ("in",), ("pre",), ("post", "in", "pre"), ("pre", "post")):
            view = WeekView(week_order(slate(n, mix) if n <= 17 else []))
            for page in range(view.pages):
                c = draw(view, page)
                assert c.pixels and not c.out_of_bounds, (n, mix, page)


def test_a_short_week_fills_from_the_top_left_with_no_divider():
    one = draw(WeekView(week_order(slate(2))))
    assert one.pixels and all(y < 15 for (_, y) in one.pixels)  # one row of cells only
    assert not any(y == football_idle.WEEK_RULE_Y for (_, y) in one.pixels)
    full = draw(WeekView(week_order(slate(8))))
    assert any(y == football_idle.WEEK_RULE_Y for (_, y) in full.pixels)


def test_the_winner_is_bright_the_loser_dim_and_a_live_score_is_green():
    final = draw(WeekView((g("WSH", "NYG", "post", 17, 24),)))
    scores = {col for (x, _), col in final.pixels.items() if x > 20}  # the score column
    assert (255, 255, 255) in scores and football_idle.DIM in scores
    live = draw(WeekView((g("SF", "SEA", "in", 14, 10),)))
    assert LIVE in set(live.pixels.values())


def test_a_tie_dims_nobody_and_a_pregame_shows_only_its_hour():
    tie = draw(WeekView((g("WSH", "NYG", "post", 20, 20),)))
    assert (255, 255, 255) not in set(tie.pixels.values())
    pre = draw(WeekView((g("WSH", "NYG", "pre"),)))
    assert LIVE not in set(pre.pixels.values()) and (255, 255, 255) not in set(pre.pixels.values())


@pytest.mark.parametrize(
    ("start", "label"),
    [
        ("2026-11-15T18:00Z", "12P"),  # noon in Chicago
        ("2026-11-15T22:25Z", "4P"),
        ("2026-11-16T01:20Z", "7P"),
        ("2026-11-15T15:30Z", "9A"),
        ("2026-11-16T06:00Z", "12A"),
        ("", ""),
    ],
)
def test_the_kickoff_hour_is_in_the_boards_zone(start, label):
    game = FbGame.from_api(raw_game("WSH", "NYG", "pre", start=start, short="x"))
    assert football_idle.kickoff_hour(game, renderer()) == label


def test_every_team_fits_a_cell():
    names = sorted(TEAMS)
    games = [g(names[i], names[i + 1], "post", 100 + i, 9, gid=i) for i in range(0, 16, 2)]
    c = draw(WeekView(tuple(games)))
    assert not c.out_of_bounds


# -- paging through the real mode ---------------------------------------------------------------


class Feed(IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None


def test_the_pages_split_the_entrys_seconds_and_one_page_stays_put():
    clock = Clock(960.0)
    feed = Feed(slate(12))
    cfg = FootballConfig(
        favourite_team="NYG",
        rotation=[{"screen": "fb_week", "seconds": 10}, {"screen": "clock", "seconds": 5}],
    )
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    seen = []
    for t in range(0, 15):
        clock.t = 960.0 + t
        scene = mode.scene()
        seen.append((scene.kind, scene.fb_page))
    assert seen[:5] == [("fb_week", 0)] * 5 and seen[5:10] == [("fb_week", 1)] * 5
    feed.games = slate(3)
    mode.worker.poll_once()
    pages = set()
    for t in range(0, 10):
        clock.t = 960.0 + t
        pages.add(mode.scene().fb_page)
    assert pages == {0}


def test_the_losers_abbreviation_is_dimmer_than_the_winners():
    c = draw(WeekView((g("WSH", "NYG", "post", 17, 24),)))
    bright = {
        y: max(max(col) for (x, yy), col in c.pixels.items() if yy == y and x < 20)
        for y in (4, 5, 6, 10, 11, 12)
        if any(yy == y and x < 20 for (x, yy) in c.pixels)
    }
    away_rows = [v for y, v in bright.items() if y < 9]
    home_rows = [v for y, v in bright.items() if y >= 9]
    assert away_rows and home_rows and max(away_rows) < max(home_rows)


def test_a_page_out_of_range_shows_the_nearest_page():
    view = WeekView(week_order(slate(12)))

    def grid(page):  # the games, not the page dots on the bottom row
        return {p: c for p, c in draw(view, page).pixels.items() if p[1] < 31}

    assert grid(9) == grid(1) and grid(-3) == grid(0)
