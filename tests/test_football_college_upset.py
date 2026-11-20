"""The upset alert end to end (#557): the screen, the mode over a real feed, and the app.

The feed is a real college client over fixture payloads whose score is changed between polls, so
the alert is detected the way it will be on a Saturday. Ranks come from the fixture AP poll
(Georgia is #1; Missouri is unranked that week).
"""

import dataclasses
from datetime import UTC, datetime, timedelta

from scoreboard.display import football_scenes as fs
from scoreboard.display import football_upset as fu
from scoreboard.display.ascii import AsciiCanvas
from scoreboard.football.upset import Upset
from test_football_scenes import H, check_snapshot, game, renderer, show

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


# -- the screen ---------------------------------------------------------------------------------


def screen_game(away_score, home_score, away_rank, home_rank, state="in", **kw):
    """WSH (away) at NYG (home) in any state, with ranks on the teams."""
    kw.setdefault("short", "Final" if state == "post" else "3:12 - 3rd")
    kw.setdefault("name", "STATUS_FINAL" if state == "post" else "STATUS_IN_PROGRESS")
    g = game("WSH", "NYG", state, away_score, home_score, **kw)
    return dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, rank=away_rank),
        home=dataclasses.replace(g.home, rank=home_rank),
    )


def upset_for(g, final=False):
    away_behind = g.away.score < g.home.score
    behind, ahead = (g.away, g.home) if away_behind else (g.home, g.away)
    return Upset(behind, ahead, final, ahead.score - behind.score)


def draw(g, upset, seconds=0.0, width=128):
    c = AsciiCanvas(width, H)
    renderer(width).draw_fb_upset(c, g, upset, seconds)
    return c


def test_the_alert_screen_and_its_snapshot(update_snapshots):
    g = screen_game(21, 14, None, 5)  # WSH (away, unranked) 21 beats NYG (home, #5) 14
    u = upset_for(g)
    assert u.favourite.rank == 5
    c = draw(g, u)
    art = show("fb_upset_alert", c)
    assert not c.out_of_bounds
    head = c.bbox(0, 0, 127, 14)
    assert abs(head.center_x - 63.5) <= 1.5 and head.y1 <= 14
    assert fu.ALERT in c.colors(0, 0, 127, 14)
    assert fs.RANK_COLOR in c.colors(0, 15, 127, 24), "the favourite's number"
    check_snapshot("fb_upset_alert", art, update_snapshots)


def test_the_header_flashes_and_nothing_else_changes():
    g = screen_game(21, 14, None, 5)
    u = upset_for(g)
    bright, dim = draw(g, u, 0.0), draw(g, u, 0.75)
    assert fu.ALERT in bright.colors(0, 0, 127, 14) and fu.ALERT not in dim.colors(0, 0, 127, 14)
    assert fu.ALERT_DIM in dim.colors(0, 0, 127, 14)
    assert bright.render().splitlines()[16:] == dim.render().splitlines()[16:], "the matchup holds"
    assert draw(g, u, 2.0).render() == bright.render(), "a pure function of the time"


def test_the_final_is_a_steady_gold_upset_final_with_the_margin(update_snapshots):
    g = screen_game(24, 21, None, 2, state="post")
    u = upset_for(g, final=True)
    assert u.final and u.margin == 3
    a, b = draw(g, u, 0.0), draw(g, u, 0.75)
    assert a.render() == b.render(), "no flashing at the final"
    assert fu.FINAL_GOLD in a.colors(0, 0, 127, 14) and fu.ALERT not in a.colors(0, 0, 127, 14)
    art = show("fb_upset_final", a)
    assert not a.out_of_bounds
    check_snapshot("fb_upset_final", art, update_snapshots)


def test_two_ranked_teams_each_get_their_number():
    g = screen_game(21, 14, 12, 3)
    c = draw(g, upset_for(g))
    assert not c.out_of_bounds
    xs = sorted(x for (x, y), rgb in c.lit(0, 15, 127, 24).items() if rgb == fs.RANK_COLOR)
    assert xs and xs[0] < 64 < xs[-1], "a number on each side of the line"


def test_the_widest_matchup_still_fits_with_its_number():
    g = screen_game(138, 141, None, 25)
    # Four-letter FBS abbreviations (TA&M, M-OH) with three-digit scores: the widest it gets.
    g = dataclasses.replace(
        g,
        away=dataclasses.replace(g.away, abbrev="TA&M", is_football=False),
        home=dataclasses.replace(g.home, abbrev="M-OH", is_football=False),
    )
    u = upset_for(g)
    c = draw(g, u)
    assert not c.out_of_bounds
    assert fs.RANK_COLOR in c.colors(0, 15, 127, 24), "there is room for the number"
    xs = [x for (x, y), rgb in c.lit(0, 15, 127, 24).items()]
    assert min(xs) >= 1 and max(xs) <= 126


def test_the_status_line_says_how_far_behind_and_when():
    live = screen_game(21, 14, None, 5)
    assert fu._status(live, upset_for(live), renderer()).endswith("DOWN 7")
    half = screen_game(21, 14, None, 5, name="STATUS_HALFTIME", short="Halftime")
    assert fu._status(half, upset_for(half), renderer()).startswith("HALFTIME")
    done = screen_game(24, 21, None, 2, state="post")
    assert fu._status(done, upset_for(done, True), renderer()) == "FINAL  LOST BY 3"


# -- the mode over a real feed ------------------------------------------------------------------

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from scoreboard.config import FootballConfig, ScoreboardConfig  # noqa: E402
from scoreboard.football.mode import FootballMode  # noqa: E402
from teamcfg import fcfg  # noqa: E402
from test_football_college_ranks import Feed, load  # noqa: E402
from test_football_plays import FakeResponse  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "football"
UGA, MIZ = 61, 142


def board(away=0, home=0, period=2, state="in", name="STATUS_IN_PROGRESS", away_team=None):
    """The fixture game, Missouri (unranked this week) at Georgia (#1), in any state."""
    payload = load("college_scoreboard.json")
    event = payload["events"][0]
    payload["events"] = [event]
    comp = event["competitions"][0]
    for side in comp["competitors"]:
        side["score"] = str(away if side["homeAway"] == "away" else home)
        if away_team is not None and side["homeAway"] == "away":
            side["id"] = side["team"]["id"] = str(away_team[0])
            side["team"]["abbreviation"] = away_team[1]
    comp["status"]["period"] = period
    comp["status"]["type"].update(
        state=state, name=name, completed=state == "post", shortDetail="3:12 - 3rd", detail="x"
    )
    if state == "post":
        comp["status"]["type"].update(shortDetail="Final", detail="Final")
    return payload


class UpsetRig:
    def __init__(self, wide=True, league="college-football", **cfg):
        self.client = Feed(board(), FakeResponse(load("college_rankings_trimmed.json")))
        self.clock = {"mono": 1000.0, "now": datetime(2026, 11, 20, 12, 0, tzinfo=UTC)}
        self.settings = settings = fcfg(favourite_team="UGA", **cfg)
        self.mode = FootballMode(
            lambda: ScoreboardConfig(),
            client_factory=lambda: self.client,
            football=lambda: settings,
            monotonic=lambda: self.clock["mono"],
            utc_now=lambda: self.clock["now"],
            wide=lambda: wide,
            league=league,
        )

    def show(self):
        """Ask for the alert now (it starts the next queued one, so asking has an effect)."""
        return self.mode.upset_scene()

    def step(self, **kw):
        self.client.session.routes["/scoreboard"] = FakeResponse(board(**kw))
        self.mode.worker.poll_once()
        self.mode.track()

    def advance(self, seconds):
        self.clock["mono"] += seconds

    @property
    def alert(self):
        return self.show()


def behind(rig, **kw):
    """Georgia (#1) trailing Missouri 14-21 in the third quarter, after a level look."""
    rig.step(away=14, home=14, period=3)
    rig.step(away=21, home=14, period=3, **kw)


def test_a_ranked_team_falling_behind_after_the_half_alerts_with_both_teams_and_the_margin():
    rig = UpsetRig()
    behind(rig)
    scene = rig.alert
    assert scene is not None and scene.kind == "fb_upset" and scene.animating
    u = scene.fb_upset
    assert (u.favourite.abbrev, u.favourite.rank, u.underdog.abbrev) == ("UGA", 1, "MIZ")
    assert u.underdog.rank is None and u.margin == 7 and not u.final
    assert scene.fb_elapsed == 0.0 and scene.fb_seconds == 8.0


def listed_cfg(favourite, *follow):
    return fcfg(favourite_team=favourite, also_follow=list(follow))


def test_a_game_between_unlisted_teams_never_alerts_however_big_the_upset():
    rig = UpsetRig()
    rig.mode._football = lambda: listed_cfg("ALA")  # Georgia (#1) is not on the list
    behind(rig)
    rig.step(away=45, home=14, period=4)
    assert rig.alert is None
    rig.step(away=45, home=14, period=4, state="post", name="STATUS_FINAL")
    assert rig.alert is None, "nor the final"


def test_a_followed_secondary_being_upset_alerts_with_a_different_primary():
    rig = UpsetRig()
    rig.mode._football = lambda: listed_cfg("ALA", "UGA")
    behind(rig)
    scene = rig.alert
    assert scene is not None and scene.fb_upset.favourite.abbrev == "UGA"


def test_the_listed_team_must_be_the_one_being_upset_not_the_underdog():
    """Open question for the owner: should a followed team *pulling* an upset alert too? Not yet:
    only the rule as stated. Missouri (unranked) is listed and beats Georgia (#1)."""
    rig = UpsetRig()
    rig.mode._football = lambda: listed_cfg("MIZ")
    behind(rig)
    assert rig.alert is None


def test_a_newly_followed_team_already_in_an_upset_does_not_fire():
    rig = UpsetRig()
    rig.mode._football = lambda: listed_cfg("ALA")
    behind(rig)
    assert rig.alert is None
    rig.mode._football = lambda: listed_cfg("ALA", "UGA")  # the owner adds Georgia mid-game
    rig.step(away=21, home=14, period=3)
    assert rig.alert is None, "it was already happening"
    rig.step(away=24, home=21, period=4, state="post", name="STATUS_FINAL")
    assert rig.alert is not None and rig.alert.fb_upset.final, "what happens after still does"


def test_an_upset_that_began_before_the_team_was_followed_is_not_shown_when_it_is_added():
    """It entered the upset while unlisted: following the team a moment later must not make the
    board announce it."""
    rig = UpsetRig()
    rig.mode._football = lambda: listed_cfg("ALA")
    behind(rig)  # Georgia falls behind: nobody listed is involved
    rig.mode._football = lambda: listed_cfg("ALA", "UGA")
    rig.step(away=21, home=14, period=3)
    assert rig.show() is None


def test_removing_a_team_from_the_list_silences_a_queued_alert():
    rig = UpsetRig()
    behind(rig)  # queued for UGA, the favourite
    rig.mode._football = lambda: listed_cfg("ALA")
    assert rig.show() is None


def test_a_game_already_in_an_upset_when_the_board_starts_does_not_announce_it():
    rig = UpsetRig()
    rig.step(away=21, home=14, period=3)
    assert rig.alert is None


def test_nothing_fires_in_the_first_half_and_the_half_itself_starts_it():
    rig = UpsetRig()
    rig.step(away=14, home=14, period=1)
    rig.step(away=21, home=14, period=2)
    assert rig.alert is None, "second quarter"
    rig.step(away=21, home=14, period=2, name="STATUS_HALFTIME")
    assert rig.alert is not None, "the half"


def test_it_stays_for_its_seconds_then_the_board_goes_back():
    rig = UpsetRig()
    behind(rig)
    assert rig.alert.fb_elapsed == 0.0
    rig.advance(3)
    assert rig.alert.fb_elapsed == 3.0
    rig.advance(5)
    assert rig.alert is None


def test_it_alerts_once_per_game_not_each_time_the_lead_changes():
    rig = UpsetRig()
    behind(rig)
    assert rig.show() is not None
    rig.advance(9)
    assert rig.show() is None
    rig.step(away=21, home=28, period=3)
    rig.step(away=35, home=28, period=4)
    assert rig.alert is None


def test_a_ranked_team_that_is_winning_is_no_upset():
    rig = UpsetRig()
    rig.step(away=7, home=7, period=3)
    rig.step(away=7, home=21, period=3)
    assert rig.alert is None


def test_a_ranked_team_that_loses_the_game_gets_an_upset_final():
    rig = UpsetRig()
    behind(rig)
    assert rig.show() is not None
    rig.advance(9)
    assert rig.show() is None
    rig.step(away=24, home=21, period=4, state="post", name="STATUS_FINAL")
    scene = rig.alert
    assert scene is not None and scene.fb_upset.final and scene.fb_upset.margin == 3


def test_an_upset_final_fires_even_if_the_board_missed_the_live_alert():
    rig = UpsetRig()
    rig.step(away=14, home=14, period=3)
    rig.step(away=24, home=21, period=4, state="post", name="STATUS_FINAL")
    assert rig.alert.fb_upset.final


def test_a_game_that_is_already_final_at_startup_is_not_announced():
    rig = UpsetRig()
    rig.step(away=24, home=21, period=4, state="post", name="STATUS_FINAL")
    assert rig.alert is None


def test_the_owner_can_turn_it_off_and_choose_how_long_it_stays():
    off = UpsetRig(upset_alert=False)
    behind(off)
    assert off.alert is None
    long = UpsetRig(upset_seconds=12)
    behind(long)
    assert long.alert.fb_seconds == 12.0
    long.advance(11)
    assert long.alert is not None
    long.advance(2)
    assert long.alert is None


def notre_dame_leads(rig):
    """Notre Dame (AP #3, CFP #6) beating Georgia (#1) at Georgia, after a level look."""
    away = (87, "ND")
    rig.step(away=14, home=14, period=3, away_team=away)
    rig.step(away=21, home=14, period=3, away_team=away)


def test_the_minimum_gap_is_how_far_below_the_leader_must_be_ranked():
    # Notre Dame is two places below Georgia in the AP.
    for gap, fires in ((1, True), (2, True), (3, False)):
        rig = UpsetRig(upset_min_gap=gap)
        notre_dame_leads(rig)
        assert (rig.show() is not None) is fires, f"min gap {gap}"


def test_a_ranked_team_losing_to_a_better_ranked_one_is_no_upset():
    rig = UpsetRig()
    rig.step(away=14, home=14, period=3, away_team=(87, "ND"))
    rig.step(away=14, home=21, period=3, away_team=(87, "ND"))  # Georgia (#1) leads Notre Dame
    assert rig.show() is None


def test_turning_the_alert_off_while_one_is_queued_silences_it():
    rig = UpsetRig()
    behind(rig)  # queued, not yet shown
    rig.settings._base.upset_alert = False
    assert rig.show() is None


def test_a_single_64px_panel_never_shows_the_alert():
    rig = UpsetRig(wide=False)
    behind(rig)
    assert rig.alert is None


def test_the_nfl_mode_has_no_upsets():
    rig = UpsetRig(league="nfl")
    behind(rig)
    assert rig.alert is None


def test_the_alert_uses_the_chosen_poll():
    # Notre Dame is five places below Georgia in the committee's rankings, two in the AP.
    # With a gap of 3 it is an upset by one poll's numbers and not the other's.
    for poll, fires in (("ap", False), ("cfp", True)):
        rig = UpsetRig(upset_min_gap=3, college_poll=poll)
        notre_dame_leads(rig)
        assert (rig.show() is not None) is fires, poll


@pytest.mark.parametrize(
    ("given", "expected"), [(1, 4.0), (8, 8.0), (99, 15.0), ("x", 8.0), (None, 8.0)]
)
def test_the_alert_length_is_held_to_its_range(given, expected):
    assert FootballConfig(upset_seconds=given).upset_seconds == expected


@pytest.mark.parametrize(("given", "expected"), [(0, 1), (3, 3), (99, 25), ("x", 1)])
def test_the_minimum_gap_is_held_to_its_range(given, expected):
    assert FootballConfig(upset_min_gap=given).upset_min_gap == expected


def test_the_alert_is_on_by_default():
    assert FootballConfig().upset_alert is True
    assert FootballConfig(upset_alert=0).upset_alert is False
    assert json.dumps(FootballConfig().upset_seconds)


# -- the app: news whichever sport is on screen --------------------------------------------------

from scoreboard.app import ScoreboardApp  # noqa: E402
from scoreboard.config import Settings, TeamEntry  # noqa: E402
from scoreboard.display.matrix import Backend  # noqa: E402
from scoreboard.football import teams as nfl  # noqa: E402
from test_app import FakeGraphics, FakeMatrix, FakeOptions  # noqa: E402
from test_app_priority import FootballFeed, HockeyClient  # noqa: E402
from test_flow import Clock, RecordingHorn  # noqa: E402
from test_flow import game as hockey_game  # noqa: E402


@pytest.fixture
def backend():
    return Backend(
        name="fake", RGBMatrix=FakeMatrix, RGBMatrixOptions=FakeOptions, graphics=FakeGraphics
    )


class AppRig:
    """Hockey is ranked first and has the board; Georgia is ranked second and not playing."""

    def __init__(self, backend, teams=(("hockey", "NSH"), ("college", "UGA")), **cfg):
        self.clock = Clock(datetime(2026, 11, 21, 17, 0, tzinfo=UTC))
        self.hockey = HockeyClient()
        self.hockey.today = [hockey_game(1, "CHI", "NSH", self.clock.now + timedelta(hours=20))]
        self.feed = Feed(board(), FakeResponse(load("college_rankings_trimmed.json")))
        settings = Settings()
        settings.teams = [TeamEntry(s, t) for s, t in teams]
        for key, value in cfg.items():
            setattr(settings.football, key, value)
        self.app = ScoreboardApp(
            settings,
            client=self.hockey,
            backend=backend,
            clock=lambda: self.clock.now,
            monotonic=lambda: self.clock.mono,
            horn=RecordingHorn(),
            football_client_factory=FootballFeed,
            college_client_factory=lambda: self.feed,
        )

    def poll(self, seconds=0, **score):
        if score:
            self.feed.session.routes["/scoreboard"] = FakeResponse(board(**score))
        if seconds:
            self.clock.advance(seconds=seconds)
        self.app.refresh()
        for mode in self.app._fb_modes():
            mode.worker.poll_once()
        self.app._choose_sport()


def test_an_upset_takes_the_board_even_while_hockey_is_on_screen(backend):
    rig = AppRig(backend)
    rig.poll(away=14, home=14, period=3)
    assert rig.app.current_mode() == "hockey"
    assert rig.app.select_scene().kind != "fb_upset"
    rig.poll(away=21, home=14, period=3)
    scene = rig.app.select_scene()
    assert rig.app.current_mode() == "hockey", "the sport on screen did not change"
    assert scene.kind == "fb_upset" and scene.fb_upset.favourite.abbrev == "UGA"
    rig.poll(seconds=9)
    assert rig.app.select_scene().kind != "fb_upset", "after its seconds the board goes back"


def test_an_upset_in_a_game_nobody_follows_is_not_news(backend):
    """The owner's rule (#588): Georgia is #1 and being upset, but it is not in the ranked list."""
    rig = AppRig(backend, teams=(("hockey", "NSH"), ("college", "ALA")))
    rig.poll(away=14, home=14, period=3)
    rig.poll(away=21, home=14, period=3)
    assert rig.app.select_scene().kind != "fb_upset"


def test_a_secondary_team_being_upset_is_news_while_the_primary_is_on(backend):
    """The owner's example: watching the primary while a followed secondary is upset."""
    rig = AppRig(backend, teams=(("hockey", "NSH"), ("college", "ALA"), ("college", "UGA")))
    rig.poll(away=14, home=14, period=3)
    assert rig.app.current_mode() == "hockey"
    rig.poll(away=21, home=14, period=3)
    scene = rig.app.select_scene()
    assert rig.app.current_mode() == "hockey" and scene.kind == "fb_upset"
    assert scene.fb_upset.favourite.abbrev == "UGA"


def test_with_the_alert_turned_off_nothing_interrupts(backend):
    rig = AppRig(backend, upset_alert=False)
    rig.poll(away=14, home=14, period=3)
    rig.poll(away=21, home=14, period=3)
    assert rig.app.select_scene().kind != "fb_upset"


def test_no_college_team_ranked_means_no_college_feed_and_no_alert(backend):
    rig = AppRig(backend, teams=(("hockey", "NSH"),))
    assert rig.app._college is None
    assert rig.app.select_scene().kind != "fb_upset"


def test_the_alert_is_drawn_with_the_fbs_teams_and_without_the_nfl_logos(backend):
    rig = AppRig(backend)
    rig.poll(away=14, home=14, period=3)
    rig.poll(away=21, home=14, period=3)
    app = rig.app
    sentinel = object()
    app.renderer.football_logos = sentinel
    seen = {}

    def spy(scene):
        seen.update(
            logos=app.renderer.football_logos,
            directory=nfl.active_directory(),
            uga=nfl.is_team("UGA"),
            kind=scene.kind,
        )

    app._draw_scene = spy
    app.draw_scene(app.select_scene())
    assert seen["kind"] == "fb_upset" and seen["logos"] is None and seen["uga"]
    assert seen["directory"].league == "college-football"
    assert app.renderer.football_logos is sentinel and nfl.active_directory() is nfl.NFL_DIRECTORY


def test_a_holiday_never_decorates_the_alert():
    from scoreboard.display.holiday import NO_OVERLAY_SCENES

    assert "fb_upset" in NO_OVERLAY_SCENES
