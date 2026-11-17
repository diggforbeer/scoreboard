"""The app runs both sports' feeds and lets the ranked list pick the sport (epic #470, #474)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from scoreboard.app import SPORT_MIN_DWELL_SECONDS, ScoreboardApp
from scoreboard.config import Settings, TeamEntry
from scoreboard.display.matrix import Backend
from scoreboard.hockey.api import HockeyApiError
from test_app import FakeGraphics, FakeMatrix, FakeOptions
from test_flow import Clock, FlowClient, RecordingHorn, game
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
    def __init__(self, backend, teams):
        self.clock = Clock(START)
        self.hockey = HockeyClient()
        self.football = FootballFeed()
        self.horn = RecordingHorn()
        settings = Settings()
        settings.teams = [TeamEntry(s, t) for s, t in teams]
        self.settings = settings
        self.app = ScoreboardApp(
            settings,
            client=self.hockey,
            backend=backend,
            clock=lambda: self.clock.now,
            monotonic=lambda: self.clock.mono,
            horn=self.horn,
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


def test_with_no_team_ranked_both_feeds_run_and_the_board_starts_on_hockey(backend):
    rig = Rig(backend, [])
    assert rig.app._football is not None and rig.sport == "hockey"


def test_a_hockey_only_list_never_builds_football_s_mode_and_a_football_only_one_skips_hockey(
    backend,
):
    hockey_only = Rig(backend, [("hockey", NSH)])
    assert hockey_only.app._football is None, (
        "no football team is ranked: football's feed is not polled"
    )
    football_only = Rig(backend, [("football", TEN)])
    assert football_only.app._football is not None and football_only.sport == "football"
    football_only.hockey.today, football_only.football.games = [nsh_live()], [ten_far()]
    football_only.poll(60)
    assert football_only.hockey.polls == 0, "no hockey team is ranked: hockey's feed is not polled"


def test_with_no_team_ranked_a_live_game_takes_the_board_hockey_first_else_football(backend):
    rig = Rig(backend, [])
    rig.hockey.today, rig.football.games = [nsh_live()], [ten_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey"
    rig.hockey.today = [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "only football has a live game"
    rig.football.games = [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey", "nothing live: hockey keeps the board (every game, or the clock)"


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
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_soon()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "TEN is 30 minutes from kickoff, inside football's window"


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


def test_when_the_hold_ends_and_the_other_sport_has_nothing_the_board_goes_back_to_hockey(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.football.games, rig.hockey.today = [ten_live()], [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    rig.football.games = [football_game("JAX", TEN, "post", 7, 10, game_id=20, short="Final")]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "the final is held"
    rig.poll(61 * 60)  # past football's 60 minute hold
    rig.football.games = []  # and football's slate is empty: the offseason
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey", "nothing is on and only hockey has anything to show"


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


def test_editing_the_list_starts_and_stops_football_s_feed_and_switches_at_once(backend):
    rig = Rig(backend, [("hockey", NSH)])
    assert rig.app._football is None
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_live()]
    new = Settings()
    new.teams = [TeamEntry("football", TEN)]
    rig.app._apply_reloaded_settings(_adopt_copy(rig.app, new))
    assert rig.app._football is not None, "football's feed now runs"
    rig.app._football.worker.poll_once()
    rig.poll(0)
    assert rig.sport == "football", "an edit takes effect now, not after the dwell"
    back = Settings()
    back.teams = [TeamEntry("hockey", NSH)]
    rig.app._apply_reloaded_settings(_adopt_copy(rig.app, back))
    assert rig.app._football is None and rig.sport == "hockey"


def _adopt_copy(app, new):
    """The reloaded settings object the app is handed (keeps the old one's source path)."""
    new.source_path = app.settings.source_path
    return new


def _adopt(app, new):
    """What ``_apply_reloaded_settings`` does before calling the handler."""
    app.settings = new
    return new


# -- football reads its favourite and horn from the list (#475) ----------------------------------

FOOTBALL_LIST = [("football", TEN), ("football", NYG), ("hockey", NSH)]


def nyg_live():
    return football_game("DAL", NYG, "in", 3, 7, game_id=30)


def test_with_no_team_ranked_football_has_no_favourite_and_no_horn(backend):
    rig = Rig(backend, [])
    cfg = rig.app._football_cfg()
    assert (cfg.favourite_team, cfg.also_follow, cfg.followed_teams, cfg.horn_team) == (
        "",
        [],
        [],
        "",
    )


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


# -- hockey reads its favourite and horn from the list (#476) ------------------------------------

HOCKEY_LIST = [("hockey", NSH), ("hockey", TOR), ("football", TEN)]


def tor_live():
    return game(2, "MTL", TOR, START, "LIVE")


def test_with_no_team_ranked_hockey_has_no_favourite_and_no_horn(backend):
    rig = Rig(backend, [])
    cfg = rig.app._hockey_cfg()
    assert (cfg.favourite_team, cfg.also_follow, cfg.followed_teams, cfg.horn_team) == (
        "",
        [],
        [],
        "",
    )


def test_the_owner_is_hockey_s_favourite_and_the_lead_keeps_the_horn(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_far(), tor_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    cfg = rig.app._hockey_cfg()
    assert cfg.favourite_team == TOR, "TOR is the highest-ranked hockey team that is playing"
    assert cfg.also_follow == [NSH] and cfg.horn_team == NSH
    assert rig.sport == "hockey"


def test_the_board_shows_the_owners_game(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_far(), tor_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    scene = rig.app.select_scene()
    assert scene.game is not None and scene.game.involves(TOR)


def test_the_lead_teams_goal_sounds_the_horn_and_nobody_elses(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_live(), tor_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    rig.app._on_goal(rig.hockey.today[0], NSH)  # the lead owns the board and scores
    assert rig.horn.calls == [NSH] and rig.horn.ding_calls == 0
    rig.app._on_goal(rig.hockey.today[1], TOR)  # a followed team scores
    assert rig.horn.calls == [NSH] and rig.horn.ding_calls == 1, (
        "the ding, as for any followed team"
    )


def test_an_owner_that_is_not_the_lead_gets_the_ding_and_not_the_horn(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_far(), tor_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._hockey_cfg().favourite_team == TOR
    rig.app._on_goal(rig.hockey.today[1], TOR)
    assert rig.horn.calls == [] and rig.horn.ding_calls == 1


def test_when_the_owner_changes_the_favourite_s_cached_schedule_and_leaders_are_dropped(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_far(), tor_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._hockey_cfg().favourite_team == TOR
    rig.app._schedule = (1.0, [nsh_far()])
    rig.app._leaders = (TOR, 1.0, None)
    rig.hockey.today = [
        nsh_live(),
        tor_live(),
    ]  # the lead plays now: it takes the favourite's place
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._hockey_cfg().favourite_team == NSH
    assert rig.app._schedule is None and rig.app._leaders is None


def test_the_caches_are_kept_while_the_favourite_stays_the_same(backend):
    rig = Rig(backend, HOCKEY_LIST)
    rig.hockey.today, rig.football.games = [nsh_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    rig.app._schedule = (1.0, [nsh_far()])
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._schedule is not None


# -- the idle screens alternate between sports (#477) --------------------------------------------


def idle_runs(rig, seconds=420, step=5.0):
    """Which sport had the board as time passes with nothing on: ``[(sport, length)]``."""
    runs, seen = [], []
    for _ in range(int(seconds / step)):
        rig.poll(step)
        seen.append(rig.sport)
    for sport in seen:
        if runs and runs[-1][0] == sport:
            runs[-1][1] += step
        else:
            runs.append([sport, step])
    return [(s, n) for s, n in runs]


def test_with_nothing_on_the_sports_take_turns_each_for_its_rotation(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    rig.poll(1)
    hockey_turn = sum(e.seconds for e in rig.app._effective_rotation())
    football_turn = sum(e.seconds for e in rig.app._football._entries())
    runs = idle_runs(rig, seconds=3 * (hockey_turn + football_turn))
    sports = [s for s, _ in runs]
    assert set(sports) == {"hockey", "football"} and all(a != b for a, b in pairwise(sports))
    inner = runs[1:-1]  # the first and last runs are cut by the window
    for sport, length in inner:
        expected = hockey_turn if sport == "hockey" else football_turn
        assert abs(length - expected) <= 5.0 + 5.0, (sport, length, expected)


def test_a_sport_with_no_games_never_takes_a_turn(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], []
    assert {s for s, _ in idle_runs(rig, seconds=300)} == {"hockey"}


def test_when_neither_sport_has_games_the_top_teams_sport_keeps_the_board(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    rig.hockey.today, rig.football.games = [], []
    assert {s for s, _ in idle_runs(rig, seconds=300)} == {"football"}
    assert rig.app._idle_origin == 0.0


def test_a_segment_s_rows_start_at_the_top_of_its_turn(backend):
    """The segment began ``fraction`` of its length ago: its sport times its rows from there."""
    from scoreboard.priority import idle_segments, segment_at

    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    for _ in range(60):
        rig.poll(7)
        segments = idle_segments(rig.app._unified_rotation(), rig.app._idle_available())
        index, fraction = segment_at(segments, rig.app.monotonic())
        position = rig.app.monotonic() - rig.app._idle_origin
        assert abs(position - fraction * segments[index].seconds) < 1e-6
    assert rig.app._football.idle_origin == rig.app._idle_origin


# -- one mixed rotation list (the combined idle rotation) ----------------------------------------


def mixed(rig, *pairs):
    from scoreboard.config import RotationEntry

    rig.settings.rotation = [RotationEntry(s, float(sec)) for s, sec in pairs]


def test_the_default_rotation_is_each_sports_default_in_the_order_of_their_lead_ranks(backend):
    hockey_first = Rig(backend, [("hockey", NSH), ("football", TEN)])
    screens = [e.screen for e in hockey_first.app._unified_rotation()]
    assert screens[0] == "countdown_preview" and "fb_preview" in screens
    assert screens.index("countdown_preview") < screens.index("fb_preview")
    football_first = Rig(backend, [("football", TEN), ("hockey", NSH)])
    screens = [e.screen for e in football_first.app._unified_rotation()]
    assert screens.index("fb_preview") < screens.index("countdown_preview")
    only_hockey = Rig(backend, [("hockey", NSH)])
    assert not any(e.screen.startswith("fb_") for e in only_hockey.app._unified_rotation())


def test_a_mixed_list_interleaves_the_sports_row_by_row(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    mixed(rig, ("standings", 20), ("fb_week", 20), ("countdown_preview", 20))
    rig.poll(1)
    runs = idle_runs(rig, seconds=300, step=5.0)
    sports = [s for s, _ in runs]
    assert set(sports) == {"hockey", "football"}
    assert all(a != b for a, b in pairwise(sports)), "it never stays on one sport twice in a row"
    # The list is hockey 20 s, football 20 s, hockey 20 s, round again: so football holds 20 s and
    # hockey 40 s (its last row joins the first of the next round).
    for sport, length in runs[1:-1]:
        assert abs(length - (20.0 if sport == "football" else 40.0)) <= 10.0, (sport, length)


def test_each_sport_shows_only_its_rows_of_the_segment_that_is_up(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    mixed(rig, ("standings", 20), ("fb_week", 20), ("countdown_preview", 20), ("fb_schedule", 20))
    seen = {"hockey": set(), "football": set()}
    for _ in range(100):
        rig.poll(5)
        rows = rig.app._sport_rotation(rig.sport)
        seen[rig.sport] |= {e.screen for e in rows}
    assert seen["hockey"] <= {"standings", "countdown_preview", "clock"}
    assert seen["football"] <= {"fb_week", "fb_schedule", "clock"}
    assert seen["hockey"] and seen["football"]


def test_footballs_rows_come_to_it_through_its_settings_view(backend):
    rig = Rig(backend, [("football", TEN)])
    mixed(rig, ("standings", 20), ("fb_week", 20), ("fb_preview", 10))
    rows = [e.screen for e in rig.app._football_cfg().idle_rotation]
    assert rows == ["fb_week", "fb_preview"], "hockey's standings row is not football's"
    assert [e.screen for e in rig.app._football._entries()] == rows


def test_a_hockey_only_list_ignores_football_rows_and_the_reverse(backend):
    rig = Rig(backend, [("hockey", NSH)])
    mixed(rig, ("standings", 20), ("fb_week", 20), ("countdown_preview", 20))
    assert [e.screen for e in rig.app._effective_rotation()] == ["standings", "countdown_preview"]


def test_rows_for_a_sport_with_no_games_are_skipped(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], []
    mixed(rig, ("standings", 20), ("fb_week", 20), ("countdown_preview", 20))
    assert {s for s, _ in idle_runs(rig, seconds=200)} == {"hockey"}


def test_an_owner_interrupts_the_alternation_and_hands_back(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.hockey.today, rig.football.games = [nsh_far()], [ten_far()]
    rig.poll(1)
    rig.hockey.today = [nsh_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    for _ in range(6):
        rig.poll(10)
        assert rig.sport == "hockey", "a live ranked game ends the alternation"
    rig.hockey.today = [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert {s for s, _ in idle_runs(rig, seconds=200)} == {"hockey", "football"}


def test_with_no_team_ranked_the_idle_rotation_is_not_shifted(backend):
    rig = Rig(backend, [])
    rig.hockey.today = [nsh_far()]
    rig.poll(60)
    assert rig.app._idle_origin == 0.0


def test_hockey_s_rotation_starts_at_the_idle_origin(backend):
    from scoreboard.config import RotationEntry

    rig = Rig(backend, [("hockey", NSH), ("football", TEN)])
    rig.settings.rotation = [RotationEntry("clock", 10.0), RotationEntry("countdown_preview", 10.0)]
    upcoming = nsh_far()

    def scene_at(origin):
        rig.app._idle_origin = origin
        return rig.app._rotate_idle_scenes(upcoming, None, allow_fetch=False).kind

    mono = rig.app.monotonic()
    assert scene_at(mono) == "clock", "position 0 of the rotation"
    assert scene_at(mono - 10.0) in ("preview", "countdown"), "ten seconds in: the second entry"
    assert scene_at(mono - 20.0) == "clock", "and round again"
    assert scene_at(0.0) == rig.app._rotate_idle_scenes(upcoming, None, allow_fetch=False).kind


# -- colours follow the overall rank 1 (#478) ----------------------------------------------------


def test_with_no_team_ranked_the_colours_are_plain(backend):
    rig = Rig(backend, [])
    assert rig.app._colour_scheme(NSH) == ("hockey", "")
    assert rig.app._colour_scheme(NSH, clock=True) == ("hockey", "")


def test_the_colours_follow_the_overall_rank_1_whatever_sport_is_on_screen(backend):
    rig = Rig(backend, [("football", TEN), ("hockey", NSH)])
    assert rig.app._colour_scheme("anything") == ("football", TEN)
    assert rig.app._colour_scheme("anything", clock=True) == ("football", TEN)
    rig.hockey.today, rig.football.games = [nsh_live()], [ten_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.app._colour_scheme(NSH) == ("football", TEN), (
        "unchanged as the game on screen changes"
    )


def test_the_clock_is_drawn_in_a_football_teams_colours_when_that_team_is_rank_1():
    from scoreboard.display import holiday
    from scoreboard.display.ascii import AsciiCanvas
    from scoreboard.football.teams import team_color
    from test_football_scenes import renderer

    canvas = AsciiCanvas(128, 32)
    with holiday.use_sport("football"):
        renderer(128).draw_clock(canvas, START, TEN)
    assert tuple(team_color(TEN)) in {tuple(c) for c in canvas.colors(0, 0, 127, 31)}
    plain = AsciiCanvas(128, 32)
    renderer(128).draw_clock(plain, START, "")
    assert tuple(team_color(TEN)) not in {tuple(c) for c in plain.colors(0, 0, 127, 31)}


def test_a_demo_can_ask_for_football_on_a_board_that_ranks_only_hockey(backend):
    """``--demo --sport football`` switches the sport by hand: football's mode must then exist."""
    rig = Rig(backend, [("hockey", NSH)])
    assert rig.app._football is None
    rig.app._switch_sport("football")
    assert rig.app.current_mode() == "football" and rig.app._football is not None


# -- the night-game slots (SNF / MNF) -----------------------------------------------------------


def snf_live():
    """A game kicking off at 8:20pm Eastern on Sunday 2026-11-15 (START's own day), live."""
    return football_game(
        "DAL", "NYG", "in", 7, 10, game_id=40, start="2026-11-16T01:20Z", short="x"
    )


def test_a_ranked_night_slot_puts_that_nights_live_game_on_the_board(backend):
    rig = Rig(backend, [("football", "SNF")])
    rig.hockey.today, rig.football.games = [nsh_far()], [snf_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football"
    assert rig.app._football_cfg().favourite_team == "NYG", "home side stands in as the favourite"


def test_a_team_ranked_above_the_night_slot_keeps_the_board_in_its_own_game(backend):
    rig = Rig(backend, [("hockey", NSH), ("football", "SNF")])
    rig.hockey.today, rig.football.games = [nsh_live()], [snf_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "hockey"
    rig.hockey.today = [nsh_far()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert rig.sport == "football", "nothing above it is on, so the night game gets the board"


def test_the_other_nights_slot_shows_nothing(backend):
    rig = Rig(backend, [("football", "MNF")])
    rig.hockey.today, rig.football.games = [nsh_far()], [snf_live()]
    rig.poll(SPORT_MIN_DWELL_SECONDS + 1)
    assert (
        rig.app._priority().owner(
            {"football": rig.app._football.snapshot.games},
            rig.clock.now,
            rig.app._priority_windows(),
        )
        is None
    )
