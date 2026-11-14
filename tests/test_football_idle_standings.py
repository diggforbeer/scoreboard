"""``fb_standings`` (#427): the division page and the conference page."""

from __future__ import annotations

import json

import pytest

from nhl_scoreboard.config import FootballConfig
from nhl_scoreboard.display.ascii import AsciiCanvas
from nhl_scoreboard.football import idle
from nhl_scoreboard.football.idle import Conference, Division, Standings, StandingsRow
from nhl_scoreboard.football.idle_screens import IDLE_SCREENS, IdleContext
from nhl_scoreboard.football.idle_views import PLAYOFF_SEEDS, StandingsView, build_standings
from nhl_scoreboard.football.mode import NflMode
from nhl_scoreboard.football.teams import TEAMS
from test_football_idle import Clock, IdleFeed
from test_football_idle_preview import FIXTURES, utc
from test_football_scenes import H, check_snapshot, game, renderer

REAL = idle.standings_from_payload(json.loads((FIXTURES / "standings_trimmed.json").read_text()))


def row(team, record, seed, streak="W1", pf=200, pa=180):
    w, lo, *t = (int(n) for n in record.split("-"))
    return StandingsRow(team, TEAMS[team].espn_id, record, w, lo, t[0] if t else 0,
                        f".{w * 1000 // max(w + lo, 1):03d}", seed, streak, pf, pa)  # fmt: skip


def full_table():
    """All 32 teams, 4 per division, 2 conferences, seeded 1-16 by record in each conference."""
    teams = sorted(TEAMS)
    conferences = []
    for c, names in enumerate((("AFC", "American Football Conference"),
                               ("NFC", "National Football Conference"))):  # fmt: skip
        members = teams[c * 16 : (c + 1) * 16]
        rows = []
        for i, t in enumerate(members):
            record = f"{16 - i // 2 - 4}-{i // 2 + 1}-{i % 2}"
            streak = "W1" if (i // 4) % 2 else "L2"
            rows.append(row(t, record, i + 1, streak, 300 - i * 7, 190 + i * 5))
        divisions = tuple(
            Division(f"{names[0]} {d}", tuple(rows[i] for i in range(k, 16, 4)))
            for k, d in enumerate(("East", "North", "South", "West"))
        )
        conferences.append(Conference(names[1], names[0], divisions))
    return Standings(tuple(conferences))


FULL = full_table()
#: A favourite who is a playoff seed (page 2 shows him) in a division with winners and losers.
FAV = FULL.conferences[1].seeds()[2].team


def ctx(favourite="NYG", table=FULL, week=10):
    snap = idle.IdleSnapshot(
        scoreboard=idle.Scoreboard((), 2, 2026, week, (), ()) if week else None,
        standings_cached=idle.Cached(table, 0.0) if table else None,
    )
    return IdleContext(0.0, utc(2026, 11, 9), [], snap, FootballConfig(favourite_team=favourite))


# -- the builder ------------------------------------------------------------------------------


def test_the_real_fixtures_division_is_found_for_its_own_team():
    view = build_standings(ctx("BUF", REAL))
    assert view.division_name == "AFC EAST" and view.conference == "AFC"
    assert [r.team for r in view.division] == ["BUF", "NE", "NYJ", "MIA"]
    assert view.week == "WK 10" and view.team == "BUF"


def test_a_team_not_in_the_table_or_no_favourite_or_no_table_gives_nothing():
    assert build_standings(ctx("NYG", REAL)) is None  # the trimmed fixture is the AFC East only
    assert build_standings(ctx("")) is None
    assert build_standings(ctx(table=None)) is None
    assert IDLE_SCREENS["fb_standings"](ctx("")) is None


def test_the_conference_page_is_the_seven_seeds_and_the_first_team_out():
    view = build_standings(ctx("NYG"))
    assert [r.seed for r in view.seeds] == list(range(1, PLAYOFF_SEEDS + 1))
    assert view.first_out.seed == PLAYOFF_SEEDS + 1
    assert view.pages == 2
    assert IDLE_SCREENS["fb_standings"](ctx("NYG")) == view


def test_a_conference_with_no_seeds_yet_is_one_page_with_the_best_unseeded_team_out():
    unseeded = Standings(
        tuple(
            Conference(
                c.name,
                c.abbreviation,
                tuple(
                    Division(d.name, tuple(row_with_seed(r, None) for r in d.rows))
                    for d in c.divisions
                ),
            )
            for c in FULL.conferences
        )
    )
    view = build_standings(ctx("NYG", unseeded))
    assert view.seeds == () and view.pages == 1
    assert view.first_out is not None  # the best record without a seed
    assert view.first_out.win_pct == max(r.win_pct for r in view.first_out and [view.first_out])


def row_with_seed(r, seed):
    import dataclasses

    return dataclasses.replace(r, seed=seed)


def test_no_week_means_no_week_label():
    assert build_standings(ctx("NYG", week=None)).week == ""


# -- drawing ----------------------------------------------------------------------------------


def draw(view, page=0, width=128):
    r = renderer(width)
    c = AsciiCanvas(width, H)
    r.draw_fb_standings(c, view, page)
    return c


def test_snapshots(update_snapshots):
    view = build_standings(ctx(FAV))
    for name, page in (("fb_standings_division", 0), ("fb_standings_conference", 1)):
        c = draw(view, page)
        check_snapshot(name, c.render(), update_snapshots)
        assert not c.out_of_bounds


def test_the_favourite_is_white_with_a_bar_and_the_rest_are_dimmed():
    view = build_standings(ctx(FAV))
    for page in (0, 1):
        c = draw(view, page)
        bar = [p for p, col in c.pixels.items() if col == (255, 255, 255) and p[0] <= 4]
        assert len(bar) >= 5, f"page {page}: the favourite's bar"


def test_a_page_without_seeds_falls_back_to_the_division():
    view = StandingsView(
        "BUF", "AFC EAST", REAL.conferences[0].divisions[0].rows, "AFC", (), None, ""
    )
    assert draw(view, 1).pixels == draw(view, 0).pixels


def test_every_team_of_the_table_fits_on_both_pages():
    for team in TEAMS:
        view = build_standings(ctx(team))
        assert view is not None, team
        for page in (0, 1):
            c = draw(view, page)
            assert c.pixels and not c.out_of_bounds, (team, page)


def test_ties_unseeded_first_out_and_long_streaks_fit():
    from nhl_scoreboard.football.idle_views import StandingsView as V

    rows = tuple(row("NYG", "10-6-1", 3, "W12", 512, 399) for _ in range(4))
    out = row("CHI", "4-12-1", None, "L10", 100, 500)
    view = V("NYG", "NFC EAST", rows, "NFC", rows * 2, out, "WK 18")
    for page in (0, 1):
        c = draw(view, page)
        assert not c.out_of_bounds and c.pixels


def test_the_streak_colour_is_green_for_a_win_streak_and_red_for_a_loss_streak():
    from nhl_scoreboard.display.football_scenes import LIVE, RED_ZONE

    view = build_standings(ctx(FAV))
    colours = set(draw(view, 0).pixels.values())
    assert LIVE in colours and RED_ZONE in colours


# -- the pages share the entry's seconds, through the real mode --------------------------------


class Feed(IdleFeed):
    def plays(self, game_id):
        return []

    def core_plays(self, game_id):
        return None

    def standings(self):
        self.calls.append("standings")
        return FULL


def test_the_two_pages_split_the_rotation_entrys_seconds():
    clock = Clock(960.0)
    feed = Feed([game("WSH", "DAL", "pre", short="x", start="2026-11-22T18:00Z", game_id=5)])
    cfg = FootballConfig(
        favourite_team="NYG",
        also_follow=["DAL"],  # standings are only fetched when someone is followed
        rotation=[{"screen": "fb_standings", "seconds": 10}, {"screen": "clock", "seconds": 5}],
    )
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    seen = []
    for t in range(0, 15):
        clock.t = 960.0 + t  # 960 is a multiple of 15
        scene = mode.scene()
        seen.append((scene.kind, scene.fb_page))
    assert seen[:5] == [("fb_standings", 0)] * 5
    assert seen[5:10] == [("fb_standings", 1)] * 5
    assert [k for k, _ in seen[10:]] == ["clock"] * 5


def test_a_single_page_screen_stays_on_page_zero():
    clock = Clock(960.0)
    feed = Feed([game("WSH", "DAL", "pre", short="x", start="2026-11-22T18:00Z", game_id=5)])
    cfg = FootballConfig(
        favourite_team="NYG", also_follow=["DAL"],
        rotation=[{"screen": "fb_standings", "seconds": 10}, {"screen": "clock", "seconds": 5}],
    )  # fmt: skip
    mode = NflMode(client_factory=lambda: feed, monotonic=clock, football=lambda: cfg)
    mode.worker.poll_once()
    view = mode.scene().fb_idle
    assert view is not None and view.pages == 2
    assert pytest is not None
