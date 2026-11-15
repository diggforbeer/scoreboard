"""The halftime rotation: the card leads, then the team stats, then the scores around the league.

Halftime is the longest dead air in a game, so the board stops sitting on one card."""

from __future__ import annotations

from nhl_scoreboard.football.demo import DEMO_STATS
from nhl_scoreboard.football.mode import HALFTIME_CARD_SECONDS
from nhl_scoreboard.football.stats import PAGES
from test_football_idle_selection import BASE, build
from test_football_scenes import game

STATS_PAGE = 6.0  # FootballConfig.stats_seconds
STATS_SECONDS = STATS_PAGE * len(PAGES)


def games():
    return [
        game("WSH", "NYG", "in", 10, 17, short="Halftime", name="STATUS_HALFTIME", game_id=1),
        game("MIA", "IND", "in", 3, 3, game_id=2),
        game("DAL", "PHI", "post", 20, 17, game_id=4, short="Final"),
    ]


def at(mode, clock, t):
    clock.t = BASE + t
    return mode.scene()


def halftime_mode(*, stats=True, wide=True, others=True, **cfg):
    slate = games() if others else games()[:1]
    mode, clock = build(slate, wide=wide, **cfg)
    if stats:
        mode._stats = {1: DEMO_STATS}
    at(mode, clock, 0)  # the first frame of the half: the rotation is timed from here
    return mode, clock


def test_the_card_leads_then_the_stats_then_the_league():
    mode, clock = halftime_mode()
    assert at(mode, clock, 0).kind == "fb_halftime"
    assert at(mode, clock, HALFTIME_CARD_SECONDS - 0.1).kind == "fb_halftime"
    first = at(mode, clock, HALFTIME_CARD_SECONDS + 0.1)
    assert (first.kind, first.fb_stage) == ("fb_event", "stats")
    assert first.fb_stats is DEMO_STATS
    league = at(mode, clock, HALFTIME_CARD_SECONDS + STATS_SECONDS + 0.1)
    assert league.kind == "fb_week"


def test_the_stats_take_turns_between_their_two_pages():
    mode, clock = halftime_mode()
    a = at(mode, clock, HALFTIME_CARD_SECONDS + 0.1)
    b = at(mode, clock, HALFTIME_CARD_SECONDS + STATS_PAGE + 0.1)
    assert (a.fb_elapsed // a.fb_seconds, b.fb_elapsed // b.fb_seconds) == (0, 1)
    # Stable inside a page, so the live view is not re-snapshotted every frame.
    assert at(mode, clock, HALFTIME_CARD_SECONDS + 1) == a


def test_the_league_grid_leaves_out_the_game_at_the_half():
    mode, clock = halftime_mode()
    league = at(mode, clock, HALFTIME_CARD_SECONDS + STATS_SECONDS + 0.1)
    ids = {g.id for g in league.fb_idle.games}
    assert ids == {2, 4}


def test_the_rotation_repeats_until_play_resumes():
    mode, clock = halftime_mode()
    total = HALFTIME_CARD_SECONDS + STATS_SECONDS + 6.0  # one grid page of the other games
    assert at(mode, clock, total + 1).kind == "fb_halftime"
    assert at(mode, clock, total + HALFTIME_CARD_SECONDS + 1).fb_stage == "stats"


def test_a_screen_with_nothing_to_show_drops_out():
    no_stats, clock = halftime_mode(stats=False)
    kinds = {at(no_stats, clock, t).kind for t in range(0, 40, 2)}
    assert kinds == {"fb_halftime", "fb_week"}
    alone, clock = halftime_mode(others=False)
    kinds = {at(alone, clock, t).kind for t in range(0, 40, 2)}
    assert kinds == {"fb_halftime", "fb_event"}
    nothing, clock = halftime_mode(stats=False, others=False)
    assert {at(nothing, clock, t).kind for t in range(0, 40, 2)} == {"fb_halftime"}


def test_a_narrow_panel_keeps_the_plain_card():
    mode, clock = halftime_mode(wide=False)
    assert {at(mode, clock, t).kind for t in range(0, 60, 2)} == {"fb_halftime"}


def test_a_game_that_is_not_at_the_half_is_untouched():
    mode, clock = build([game("WSH", "NYG", "in", 10, 7, game_id=1)])
    assert at(mode, clock, 0).kind == "fb_field"
