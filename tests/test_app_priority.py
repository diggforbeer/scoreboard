"""The app runs both sports' feeds and lets the ranked list pick the sport (epic #470, #474)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from scoreboard.app import SPORT_MIN_DWELL_SECONDS, ScoreboardApp
from scoreboard.config import Settings, TeamEntry
from scoreboard.display.matrix import Backend
from scoreboard.hockey.api import HockeyApiError
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_flow import Clock, FlowClient, game
from test_football_scenes import game as football_game

START = datetime(2026, 11, 22, 17, 0, tzinfo=UTC)
NSH, TOR = "NSH", "TOR"
TEN, NYG = "TEN", "NYG"

# NSH hosts a game far away; TEN hosts one far away: nothing is on yet.
FAR = START + timedelta(hours=20)


@pytest.fixture
def backend() -> Backend:
    return Backend(
        name="fake", RGBMatrix=FakeMatrix, RGBMatrixOptions=FakeOptions, graphics=FakeGraphics
    )


class HockeyClient(FlowClient):
    """FlowClient whose score poll can fail."""

    def __init__(self):
        super().__init__()
        self.fail = False
        self.polls = 0

    def scores(self, date="now"):
        self.polls += 1
        if self.fail:
            raise HockeyApiError("boom")
        return list(self.today)


class FootballFeed:
    """The fake ESPN client: a slate, or a failure; nothing else the idle screens ask for."""

    last_error = ""

    def __init__(self):
        self.games = []
        self.fail = False

    def scores(self, date=None):
        if self.fail:
            self.last_error = "feed down"
            return None
        self.last_error = ""
        return list(self.games)

    def plays(self, event_id):
        return []

    def core_plays(self, event_id):
        return None

    def close(self):
        pass


class Rig:
    def __init__(self, backend, teams, *, legacy_sport="hockey"):
        self.clock = Clock(START)
        self.hockey = HockeyClient()
        self.football = FootballFeed()
        settings = Settings()
        settings.scoreboard.sport = legacy_sport
        settings.scoreboard.favourite_team = NSH
        settings.football.favourite_team = TEN
        settings.teams = [TeamEntry(s, t) for s, t in teams]
        self.settings = settings
        self.app = ScoreboardApp(
            settings,
            client=self.hockey,
            backend=backend,
            clock=lambda: self.clock.now,
            monotonic=lambda: self.clock.mono,
            football_client_factory=lambda: self.football,
        )

    def poll(self, seconds=0):
        """Advance time, poll both feeds, and let the list choose, as the loop does."""
        if seconds:
            self.clock.advance(seconds=seconds)
        self.app.refresh()
        if self.app._football is not None:
            self.app._football.worker.poll_once()
        self.app._choose_sport()

    @property
    def sport(self):
        return self.app.current_mode()


def nsh_live():
    return game(1, "CHI", NSH, START, "LIVE")


def ten_live():
    return football_game("JAX", TEN, "in", 7, 10, game_id=20)


def ten_soon():
    return football_game("JAX", TEN, "pre", game_id=20, start="2026-11-22T17:30Z", short="x")


def nsh_far():
    return game(1, "CHI", NSH, FAR)


def ten_far():
    return football_game("JAX", TEN, "pre", game_id=20, start="2026-11-23T13:00Z", short="x")


LIST = [("hockey", NSH), ("football", TEN), ("hockey", TOR)]


# -- both feeds run when there is a ranked list --------------------------------------------------


def test_a_ranked_list_builds_football_s_mode_even_when_hockey_is_on_top(backend):
    rig = Rig(backend, LIST)
    assert rig.app._football is not None, "the football feed runs beside hockey's"
    assert rig.sport == "hockey", "the top-ranked team's sport is where the board starts"


def test_a_football_team_on_top_starts_the_board_on_football(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    assert rig.sport == "football" and rig.app._football is not None


def test_without_a_ranked_list_nothing_changes_hockey_alone_builds_no_football_mode(backend):
    rig = Rig(backend, [])
    assert rig.app._football is None and rig.sport == "hockey"


def test_without_a_ranked_list_the_old_sport_setting_still_decides(backend):
    rig = Rig(backend, [], legacy_sport="football")
    assert rig.sport == "football" and rig.app._football is not None
    rig.hockey.today, rig.football.games = [nsh_live()], [ten_far()]
    rig.poll(60)
    assert rig.sport == "football", "no list: the list does not choose"


# -- the list chooses the sport ------------------------------------------------------------------


def test_the_board_goes_to_football_when_only_the_football_team_has_a_game_on(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    assert rig.app.select_scene().kind.startswith("fb_"), "and it is football's scene"


def test_a_higher_ranked_hockey_game_takes_the_board_back(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    rig.hockey.today = [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey", "NSH is ranked above TEN"
    assert not rig.app.select_scene().kind.startswith("fb_")


def test_a_lower_ranked_team_does_not_pull_the_board_off_a_higher_ranked_live_game(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today, rig.football.games = [nsh_live()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey"


def test_a_countdown_counts_across_sports(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)], legacy_sport="hockey")
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_soon()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "TEN is 30 minutes from kickoff, inside football's window"


def test_with_nothing_on_the_top_teams_sport_has_the_idle_screens(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)], legacy_sport="hockey")
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"


def test_a_final_is_held_across_a_sport_change(backend):
    """Football's final is remembered while hockey has the board, so it is held when football takes
    it back; hockey is ranked first, so only the hold can bring the board to football."""
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.football.games, rig.hockey.today = [ten_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    rig.football.games = [football_game("JAX", TEN, "post", 7, 10, game_id=20, short="Final")]
    rig.hockey.today = [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey", "NSH is live and TEN's final is only a held final"
    rig.hockey.today = [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "NSH's game is over; the TEN final is still inside its hold"


def test_when_the_hold_ends_and_nothing_is_on_the_board_goes_to_the_top_teams_sport(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.football.games, rig.hockey.today = [ten_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    rig.football.games = [football_game("JAX", TEN, "post", 7, 10, game_id=20, short="Final")]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "the final is held"
    rig.poll(61 * 60)  # past football's 60 minute hold
    assert rig.sport == "hockey", "nothing is on: rank 1 (hockey) has the idle screens"


# -- no flicker ----------------------------------------------------------------------------------


def test_the_sport_is_not_switched_twice_within_the_minimum_dwell(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    rig.hockey.today = [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS - 5)  # too soon to switch again
    assert rig.sport == "football"
    rig.poll(6)
    assert rig.sport == "hockey"


def test_switching_football_back_on_starts_its_screens_afresh(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    director = rig.app._football.director
    rig.hockey.today = [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    rig.hockey.today = [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    assert rig.app._football.director is not director, "nothing from before is replayed late"


# -- the other feed alone ------------------------------------------------------------------------


def test_hockey_is_polled_lightly_while_football_has_the_board(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    rig.football.games = [ten_live()]
    rig.hockey.today = [nsh_live()]
    rig.poll(60)
    assert rig.hockey.polls >= 1, "the priority layer can see hockey start"
    assert rig.app._hockey_lite and rig.app.games == [], "but nothing hockey-side is applied"
    assert rig.app._known_scores == {}, "no goal detection, so no horn for a hockey goal"


def test_a_failing_hockey_poll_does_not_stop_football(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    rig.football.games = [ten_live()]
    rig.hockey.fail = True
    rig.poll(60)
    rig.poll(60)
    assert rig.sport == "football"
    assert rig.app.select_scene().kind.startswith("fb_")


def test_a_failing_football_feed_does_not_stop_hockey(backend):
    rig = Rig(backend, LIST)
    rig.hockey.today = [nsh_live()]
    rig.football.fail = True
    rig.poll(60)
    rig.poll(60)
    assert rig.sport == "hockey"
    assert rig.app.select_scene().kind in ("game", "scores", "preview", "countdown")


# -- editing the list while running --------------------------------------------------------------


def test_a_first_ranked_team_starts_football_s_feed_and_an_empty_list_hands_back_to_the_setting(
    backend,
):
    rig = Rig(backend, [])
    assert rig.app._football is None
    new = Settings()
    new.teams = [TeamEntry("football", TEN)]
    rig.app._apply_teams_change(_adopt(rig.app, new))
    assert rig.app._football is not None, "football's feed now runs beside hockey's"
    rig.app._apply_teams_change(_adopt(rig.app, Settings()))
    assert rig.sport == "hockey" and rig.app._football is None, "the old setting decides again"


def _adopt(app, new):
    """What ``_apply_reloaded_settings`` does before calling the handler."""
    app.settings = new
    return new


# -- football reads its favourite and horn from the list (#475) ------------------------------------

FOOTBALL_LIST = [("football", TEN), ("football", NYG), ("hockey", NSH)]


def nyg_live():
    return football_game("DAL", NYG, "in", 3, 7, game_id=30)


def test_without_a_list_football_reads_the_real_settings_object(backend):
    rig = Rig(backend, [], legacy_sport="football")
    assert rig.app._football_cfg() is rig.settings.football


def test_the_owner_is_football_s_favourite_and_the_other_ranked_teams_are_followed(backend):
    rig = Rig(backend, FOOTBALL_LIST)
    rig.football.games, rig.hockey.today = [ten_far(), nyg_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    cfg = rig.app._football_cfg()
    assert cfg.favourite_team == NYG, "NYG is the highest-ranked football team that is playing"
    assert cfg.also_follow == [TEN] and cfg.followed_teams == [NYG, TEN]
    assert cfg.horn_team == TEN, "the horn stays with the lead team, which is not playing"


def test_the_lead_team_is_the_favourite_again_when_it_plays_too(backend):
    rig = Rig(backend, FOOTBALL_LIST)
    rig.football.games, rig.hockey.today = [ten_live(), nyg_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    cfg = rig.app._football_cfg()
    assert (cfg.favourite_team, cfg.horn_team, cfg.also_follow) == (TEN, TEN, [NYG])


def test_with_nobody_on_the_lead_team_is_the_favourite_for_the_idle_screens(backend):
    rig = Rig(backend, FOOTBALL_LIST)
    rig.football.games, rig.hockey.today = [ten_far(), football_game("DAL", NYG, "pre", game_id=30,
        start="2026-11-23T20:00:00Z", short="x")], [nsh_far()]  # fmt: skip
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._football_cfg().favourite_team == TEN


def test_the_football_mode_picks_the_owners_game_and_idle_screens_follow_it(backend):
    rig = Rig(backend, FOOTBALL_LIST)
    rig.football.games, rig.hockey.today = [ten_far(), nyg_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    mode = rig.app._football
    games = list(mode.snapshot.games)
    assert mode._favourite_game(games).involves(NYG) and mode._is_favourite(nyg_live())
    assert not mode._is_favourite(ten_far())
    assert rig.app.select_scene().fb_game.involves(NYG), "the board shows the owner's game"


def test_a_hockey_owner_leaves_football_with_its_lead_team_as_favourite(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN), ("football", NYG)])
    rig.football.games, rig.hockey.today = [nyg_live(), ten_far()], [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey"
    assert rig.app._football_cfg().favourite_team == TEN
