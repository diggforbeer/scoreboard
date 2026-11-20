"""The rank badge on the football game scenes (#547): the number beside a ranked college team.

The badge is gold, 128px panels only, and only where it fits. Unranked teams draw exactly as they
always did (every existing football snapshot is unchanged); these are the new ones.
"""

import dataclasses

import pytest

from scoreboard.display import football_scenes as fs
from scoreboard.display.ascii import AsciiCanvas
from test_football_scenes import GAMES, H, check_snapshot, game, renderer, show

GOLD = fs.RANK_COLOR


def ranked(g, away=None, home=None):
    return dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, rank=away),
        home=dataclasses.replace(g.home, rank=home),
    )


def scores(g, width=128):
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_scores(c, g)
    return c


def field(g, width=128):
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_field(c, g)
    return c


def halftime(g, width=128):
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_halftime(c, g)
    return c


def test_the_badge_text_is_the_number_and_only_on_a_wide_panel():
    live = GAMES["live"]
    assert fs.rank_badge(ranked(live, away=5).away, renderer(128)) == "5"
    assert fs.rank_badge(ranked(live, away=25).away, renderer(128)) == "25"
    assert fs.rank_badge(ranked(live, away=5).away, renderer(64)) == ""
    assert fs.rank_badge(live.away, renderer(128)) == ""


# -- the text scoreboard ------------------------------------------------------------------------


def test_a_ranked_matchup_draws_both_badges_beside_the_abbreviations(update_snapshots):
    g = ranked(GAMES["live"], away=5, home=12)
    c = scores(g)
    art = show("fb_scores_ranked", c)
    assert not c.out_of_bounds
    left, right = c.lit(0, 0, 62, 14), c.lit(64, 0, 127, 14)
    for half, lit in (("left", left), ("right", right)):
        gold = [x for (x, y), rgb in lit.items() if rgb == GOLD]
        team = [x for (x, y), rgb in lit.items() if rgb not in (GOLD, fs.WHITE, fs.DIM)]
        assert gold and team, f"{half}: a badge and an abbreviation"
        assert max(gold) < min(team), f"{half}: the badge sits left of the abbreviation"
    check_snapshot("fb_scores_ranked", art, update_snapshots)


def test_only_the_ranked_team_gets_a_badge(update_snapshots):
    g = ranked(GAMES["live"], away=3)
    c = scores(g)
    art = show("fb_scores_ranked_one", c)
    assert GOLD in c.colors(0, 0, 62, 14) and GOLD not in c.colors(64, 0, 127, 14)
    check_snapshot("fb_scores_ranked_one", art, update_snapshots)


def _team_xs(canvas, x0, x1):
    """The x of every lit pixel that belongs to the abbreviation (not a badge, score, rule or
    the possession ball)."""
    from scoreboard.display import football_ball as fball

    return [
        x
        for (x, y), rgb in canvas.lit(x0, 0, x1, 14).items()
        if rgb not in (GOLD, fs.WHITE, fs.DIM, fball.LEATHER)
    ]


def test_the_abbreviation_moves_right_for_the_badge_and_the_score_stays_put():
    plain, with_badge = scores(GAMES["live"]), scores(ranked(GAMES["live"], away=5, home=5))
    for x0, x1 in ((0, 62), (64, 127)):
        assert with_badge.bbox(x0, 0, x1, 14).x1 == plain.bbox(x0, 0, x1, 14).x1, (
            "the score is right-aligned and does not move"
        )
        assert min(_team_xs(with_badge, x0, x1)) > min(_team_xs(plain, x0, x1))


def test_a_badge_is_dropped_rather_than_run_into_the_score():
    # The longest FBS abbreviations are four letters (TA&M, M-OH): with a two-digit score the
    # "25" badge still fits; with a three-digit score there is no room, so it is dropped.
    two = ranked(game("TA&M", "M-OH", "in", 38, 41), away=25, home=24)
    three = dataclasses.replace(
        two,
        away=dataclasses.replace(two.away, score=138),
        home=dataclasses.replace(two.home, score=141),
    )
    assert GOLD in scores(two).colors(0, 0, 62, 14) and GOLD in scores(two).colors(64, 0, 127, 14)
    c = scores(three)
    assert not c.out_of_bounds
    assert GOLD not in c.colors(0, 0, 127, 14), "no room: the badges are dropped, not squeezed"
    for x0, x1 in ((0, 62), (64, 127)):
        whites = [x for (x, y), rgb in c.lit(x0, 0, x1, 14).items() if rgb == fs.WHITE]
        assert max(_team_xs(c, x0, x1)) < min(whites), "abbreviation then score, no overlap"


def test_a_pregame_has_badges_and_no_scores():
    g = ranked(GAMES["pregame"], away=8, home=21)
    c = scores(g)
    assert GOLD in c.colors(0, 0, 62, 14) and GOLD in c.colors(64, 0, 127, 14)
    assert fs.WHITE not in c.colors(0, 0, 127, 14)
    assert not c.out_of_bounds


def test_the_possession_ball_stays_four_pixels_after_the_abbreviation_when_it_moves():
    from scoreboard.display import football_ball as fball

    def gaps(canvas):
        """(abbreviation right edge to ball left edge) for each half that has the ball."""
        out = []
        for x0, x1 in ((0, 62), (64, 127)):
            ball = [x for (x, y), rgb in canvas.lit(x0, 0, x1, 14).items() if rgb == fball.LEATHER]
            if ball:
                out.append(min(ball) - max(_team_xs(canvas, x0, x1)))
        return out

    plain = gaps(scores(GAMES["live"]))
    assert plain, "the fixture's live game has a team with the ball"
    assert gaps(scores(ranked(GAMES["live"], away=5, home=12))) == plain


@pytest.mark.parametrize("name", ["live", "red_zone", "final", "pregame", "big_scores"])
def test_a_single_64px_panel_never_shows_a_badge_and_draws_as_before(name):
    g = GAMES[name]
    ranked_game = ranked(g, away=1, home=2)
    assert GOLD not in scores(ranked_game, 64).colors(0, 0, 63, 31)
    assert scores(ranked_game, 64).render() == scores(g, 64).render()


# -- the field band and the halftime card --------------------------------------------------------


def test_the_field_band_shows_the_ranks_when_there_is_room(update_snapshots):
    # No down and distance (a kickoff, between quarters): the whole band is free for the badges.
    g = ranked(GAMES["live_no_situation"], away=5, home=12)
    c = field(g)
    art = show("fb_field_ranked", c)
    assert not c.out_of_bounds
    assert GOLD in c.colors(0, 0, 127, 9), "the badges are in the band at the top"
    check_snapshot("fb_field_ranked", art, update_snapshots)


def test_with_a_down_and_distance_the_band_drops_badges_that_would_crowd_it():
    # The common case on a Saturday: clock, score and "2ND&3" leave no room for two badges.
    g = ranked(GAMES["live"], away=5, home=12)
    assert GOLD not in field(g).colors(0, 0, 127, 9)
    assert field(g).render() == field(GAMES["live"]).render(), "it is drawn exactly as unranked"


@pytest.mark.parametrize("name", ["live", "red_zone", "big_scores"])
def test_the_band_score_never_runs_into_the_down_and_distance(name):
    # Seen in a mockup: badges widened the score block into the "1ST&10" on the right.
    base = GAMES[name]
    for ranks in ((None, None), (5, None), (None, 12), (5, 12), (25, 24)):
        g = ranked(base, away=ranks[0], home=ranks[1])
        c = field(g)
        assert not c.out_of_bounds
        band = c.lit(0, 0, 127, 7)
        down = [x for (x, y), rgb in band.items() if rgb in (fs.SITUATION, fs.RED_ZONE)]
        score = [
            x
            for (x, y), rgb in band.items()
            if rgb not in (fs.SITUATION, fs.RED_ZONE, fs.status_color(g))
        ]
        assert down and score
        assert max(score) < min(down) - 1, (
            f"{name} {ranks}: the score touches the down and distance"
        )


def test_the_rank_colour_is_not_one_the_band_already_uses():
    used = {fs.WHITE, fs.LIVE, fs.SITUATION, fs.RED_ZONE, fs.HALFTIME, fs.FINAL, fs.PREGAME}
    assert GOLD not in used
    # and not near the down-and-distance yellow, which is what the first (gold) version was
    assert sum(abs(a - b) for a, b in zip(GOLD, fs.SITUATION, strict=True)) > 150


def test_the_band_drops_the_badges_when_the_clock_leaves_no_room_for_them():
    g = ranked(GAMES["live"], away=5, home=12)
    r = renderer(128)
    for min_x, badges in ((0, True), (66, False)):
        c = AsciiCanvas(128, H)
        fs._score(r, c, g, 6, None, min_x=min_x)
        assert not c.out_of_bounds, f"min_x={min_x}"
        assert (GOLD in c.colors(0, 0, 127, 9)) is badges, f"min_x={min_x}"


def test_the_field_band_without_ranks_is_unchanged():
    g = GAMES["live"]
    assert field(g).render() == field(ranked(g)).render()


def test_the_halftime_card_shows_the_ranks_on_the_score_line(update_snapshots):
    g = ranked(GAMES["halftime"], away=4, home=17)
    c = halftime(g)
    art = show("fb_halftime_ranked", c)
    assert not c.out_of_bounds
    assert GOLD in c.colors(0, 22, 127, 31)
    check_snapshot("fb_halftime_ranked", art, update_snapshots)


def test_halftime_without_ranks_and_on_64px_are_unchanged():
    g = GAMES["halftime"]
    assert halftime(g).render() == halftime(ranked(g)).render()
    assert halftime(ranked(g, away=4, home=17), 64).render() == halftime(g, 64).render()


def test_the_game_helper_builds_unranked_teams():
    assert game("WSH", "NYG", "in", 1, 2).home.rank is None
