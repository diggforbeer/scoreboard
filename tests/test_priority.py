"""The priority layer (epic #470, #472): a table of boards and what each one shows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from scoreboard.config import Settings, TeamEntry
from scoreboard.priority import Kind, Priority, Windows

NOW = datetime(2026, 11, 22, 17, 0, tzinfo=UTC)
WINDOWS = {
    "hockey": Windows(countdown=timedelta(hours=2), final_hold=timedelta(minutes=30)),
    "football": Windows(countdown=timedelta(minutes=60), final_hold=timedelta(minutes=60)),
}


@dataclass
class G:
    """A game of either sport, as far as the priority layer sees one."""

    id: int
    away: str
    home: str
    state: str = "pre"  # pre | live | final
    start_utc: datetime | None = None

    @property
    def is_live(self):
        return self.state == "live"

    @property
    def is_final(self):
        return self.state == "final"

    @property
    def is_pregame(self):
        return self.state == "pre"

    def involves(self, abbrev):
        return abbrev in (self.away, self.home)


def live(gid, away, home):
    return G(gid, away, home, "live")


def soon(gid, away, home, minutes):
    return G(gid, away, home, "pre", NOW + timedelta(minutes=minutes))


def final(gid, away, home):
    return G(gid, away, home, "final")


def board(*rows):
    """``board(("hockey", "NSH"), ("football", "TEN"))``: rank 1 first."""
    return Priority([TeamEntry(s, t) for s, t in rows])


def pick(priority, hockey=(), football=(), ages=None):
    moment = priority.owner(
        {"hockey": list(hockey), "football": list(football)}, NOW, WINDOWS, ages
    )
    return None if moment is None else (moment.sport, moment.team, moment.kind)


LIST = board(("hockey", "NSH"), ("football", "TEN"), ("hockey", "TOR"), ("football", "NYG"))


# -- the list ------------------------------------------------------------------------------------


def test_rank_lead_sports_and_colours():
    assert LIST.rank("football", "TEN") == 2 and LIST.rank("hockey", "TOR") == 3
    assert LIST.rank("hockey", "TEN") is None
    assert LIST.lead("hockey") == "NSH" and LIST.lead("football") == "TEN"
    assert LIST.sports() == ["hockey", "football"]
    assert LIST.colour_team() == TeamEntry("hockey", "NSH")


def test_sports_are_ordered_by_their_lead_teams_rank():
    assert board(("football", "TEN"), ("hockey", "NSH")).sports() == ["football", "hockey"]
    assert board(("football", "TEN"), ("football", "NYG")).sports() == ["football"]


def test_an_empty_list_has_no_lead_and_no_colour_team():
    empty = board()
    assert empty.empty and empty.lead("hockey") is None and empty.colour_team() is None
    assert empty.sports() == [] and empty.rank("hockey", "NSH") is None


def test_it_agrees_with_the_settings_helpers():
    settings = Settings.from_dict(
        {"teams": [{"sport": "football", "team": "TEN"}, {"sport": "hockey", "team": "NSH"}]}
    )
    priority = Priority(settings.teams)
    assert priority.rank("hockey", "NSH") == settings.rank_of("hockey", "NSH") == 2
    assert priority.lead("football") == settings.teams_for("football")[0]


# -- who owns the board --------------------------------------------------------------------------


def test_nothing_on_means_no_owner():
    assert pick(LIST) is None
    assert pick(LIST, hockey=[live(1, "CHI", "STL")], football=[live(2, "DAL", "PHI")]) is None, (
        "nobody ranked plays"
    )


def test_the_better_ranked_live_game_wins_across_sports():
    assert pick(LIST, hockey=[live(1, "NSH", "CHI")], football=[live(2, "TEN", "JAX")]) == (
        "hockey",
        "NSH",
        Kind.LIVE,
    )
    assert pick(LIST, hockey=[live(1, "TOR", "MTL")], football=[live(2, "TEN", "JAX")]) == (
        "football",
        "TEN",
        Kind.LIVE,
    )


def test_a_lower_ranked_team_owns_the_board_when_the_lead_is_not_playing():
    assert pick(LIST, hockey=[live(1, "TOR", "MTL")]) == ("hockey", "TOR", Kind.LIVE)
    assert LIST.lead("hockey") == "NSH", "and the lead team is still the lead"


def test_a_live_game_of_any_rank_beats_a_countdown_of_the_top_team():
    assert pick(LIST, hockey=[soon(1, "NSH", "CHI", 30)], football=[live(2, "NYG", "DAL")]) == (
        "football",
        "NYG",
        Kind.LIVE,
    )


def test_two_countdowns_go_to_the_better_rank():
    assert pick(LIST, hockey=[soon(1, "TOR", "MTL", 20)], football=[soon(2, "TEN", "JAX", 40)]) == (
        "football",
        "TEN",
        Kind.COUNTDOWN,
    )


def test_a_countdown_only_counts_inside_its_sports_window():
    assert pick(LIST, football=[soon(1, "TEN", "JAX", 61)]) is None, "61 minutes out: not yet (60)"
    assert pick(LIST, football=[soon(1, "TEN", "JAX", 60)]) == ("football", "TEN", Kind.COUNTDOWN)
    assert pick(LIST, hockey=[soon(1, "NSH", "CHI", 119)]) == ("hockey", "NSH", Kind.COUNTDOWN), (
        "hockey's window is two hours"
    )
    assert pick(LIST, hockey=[soon(1, "NSH", "CHI", -1)]) is None, "already past the start"


def test_a_countdown_beats_a_held_final():
    ages = {("hockey", 2): timedelta(minutes=1)}
    got = pick(
        LIST, hockey=[final(2, "TOR", "MTL")], football=[soon(1, "NYG", "DAL", 10)], ages=ages
    )
    assert got == ("football", "NYG", Kind.COUNTDOWN)


def test_a_final_is_held_only_while_its_hold_lasts_and_only_if_seen_ending():
    game = final(1, "NSH", "CHI")
    assert pick(LIST, hockey=[game], ages={("hockey", 1): timedelta(minutes=29)}) == (
        "hockey",
        "NSH",
        Kind.FINAL,
    )
    assert pick(LIST, hockey=[game], ages={("hockey", 1): timedelta(minutes=30)}) is None, (
        "the hold is over"
    )
    assert pick(LIST, hockey=[game], ages={}) is None, (
        "a board that joined after the whistle holds nothing"
    )


def test_the_most_recent_final_wins_over_a_better_ranked_older_one():
    ages = {("hockey", 1): timedelta(minutes=20), ("football", 2): timedelta(minutes=5)}
    got = pick(LIST, hockey=[final(1, "NSH", "CHI")], football=[final(2, "NYG", "DAL")], ages=ages)
    assert got == ("football", "NYG", Kind.FINAL)


def test_equally_recent_finals_go_to_the_better_rank():
    ages = {("hockey", 1): timedelta(minutes=5), ("football", 2): timedelta(minutes=5)}
    got = pick(LIST, hockey=[final(1, "NSH", "CHI")], football=[final(2, "NYG", "DAL")], ages=ages)
    assert got == ("hockey", "NSH", Kind.FINAL)


def test_a_game_between_two_ranked_teams_belongs_to_the_better_ranked():
    got = LIST.moments({"hockey": [live(1, "TOR", "NSH")], "football": []}, NOW, WINDOWS)
    assert [(m.team, m.rank) for m in got] == [("NSH", 1), ("TOR", 3)]
    assert pick(LIST, hockey=[live(1, "TOR", "NSH")]) == ("hockey", "NSH", Kind.LIVE)


def test_the_same_abbreviation_in_the_other_sport_is_a_different_team():
    """BUF is ranked as a hockey team; a live football BUF game is nothing to do with it."""
    priority = board(("hockey", "BUF"))
    assert pick(priority, football=[live(1, "BUF", "MIA")]) is None
    assert pick(priority, hockey=[live(2, "BUF", "OTT")]) == ("hockey", "BUF", Kind.LIVE)


def test_a_sport_in_its_offseason_just_has_no_games():
    assert pick(LIST, hockey=[], football=[live(1, "NYG", "DAL")]) == ("football", "NYG", Kind.LIVE)


def test_a_missing_start_time_or_window_is_not_a_countdown():
    pregame = G(1, "NSH", "CHI", "pre", None)
    assert pick(LIST, hockey=[pregame]) is None
    no_window = LIST.moments({"hockey": [soon(1, "NSH", "CHI", 5)]}, NOW, {})
    assert no_window == []


# -- nothing on: the idle screens ----------------------------------------------------------------


def test_idle_screens_alternate_between_sports_in_lead_rank_order():
    turns = {"hockey": 24.0, "football": 36.0}
    assert LIST.idle_sport(0.0, turns) == ("hockey", 0.0)
    assert LIST.idle_sport(12.0, turns) == ("hockey", 0.5)
    assert LIST.idle_sport(24.0, turns) == ("football", 0.0)
    assert LIST.idle_sport(42.0, turns) == ("football", 0.5)
    assert LIST.idle_sport(60.0, turns) == ("hockey", 0.0), "and round again"


def test_the_football_lead_first_when_it_is_ranked_above_the_hockey_lead():
    priority = board(("football", "TEN"), ("hockey", "NSH"))
    assert priority.idle_sport(0.0, {"hockey": 10.0, "football": 10.0})[0] == "football"
    assert priority.idle_sport(10.0, {"hockey": 10.0, "football": 10.0})[0] == "hockey"


def test_a_sport_with_nothing_to_show_is_skipped():
    assert LIST.idle_sport(5.0, {"hockey": None, "football": 30.0}) == ("football", 5 / 30)
    assert LIST.idle_sport(35.0, {"hockey": 0.0, "football": 30.0}) == ("football", 5 / 30)
    assert LIST.idle_sport(0.0, {"hockey": None, "football": None}) is None


def test_a_sport_without_a_ranked_team_never_takes_a_turn():
    only_hockey = board(("hockey", "NSH"))
    assert only_hockey.idle_sport(7.0, {"hockey": 10.0, "football": 10.0}) == ("hockey", 0.7)
    assert board().idle_sport(0.0, {"hockey": 10.0, "football": 10.0}) is None


def test_one_sport_alone_is_unchanged_from_today():
    only_football = board(("football", "TEN"), ("football", "NYG"))
    for clock in (0.0, 9.9, 10.0, 123.4):
        assert only_football.idle_sport(clock, {"football": 10.0})[0] == "football"


@pytest.mark.parametrize("clock", [0.0, 1.0, 23.9, 24.0, 59.9, 60.0, 1234.5])
def test_the_alternation_is_a_pure_function_of_the_clock(clock):
    turns = {"hockey": 24.0, "football": 36.0}
    assert LIST.idle_sport(clock, turns) == LIST.idle_sport(clock, turns)
    sport, fraction = LIST.idle_sport(clock, turns)
    assert 0.0 <= fraction <= 1.0 and sport in ("hockey", "football")


def test_a_sport_holds_its_whole_turn_so_the_board_cannot_flicker():
    turns = {"hockey": 24.0, "football": 36.0}
    seen = [LIST.idle_sport(t / 2, turns)[0] for t in range(0, 120)]  # a minute, every half second
    runs = [seen[0]]
    for sport in seen[1:]:
        if sport != runs[-1]:
            runs.append(sport)
    assert runs == ["hockey", "football"], "one switch per turn, never back and forth"


# -- nothing ranked: the empty list --------------------------------------------------------------


def test_with_no_team_ranked_a_live_game_of_either_sport_takes_the_board_hockey_first():
    empty = board()
    both = {"hockey": [live(1, "NSH", "CHI")], "football": [live(2, "TEN", "JAX")]}
    assert empty.empty_list_sport(both) == "hockey"
    assert empty.empty_list_sport({"hockey": [], "football": [live(2, "TEN", "JAX")]}) == "football"
    assert empty.empty_list_sport({"hockey": [soon(1, "NSH", "CHI", 5)], "football": []}) is None


def test_the_empty_list_rule_does_not_apply_once_a_team_is_ranked():
    assert LIST.empty_list_sport({"hockey": [live(1, "CHI", "STL")], "football": []}) is None


def test_it_also_works_on_the_real_game_models():
    """The Protocol is what both sports' games already offer."""
    from scoreboard.football.models import FbGame
    from scoreboard.hockey.models import Game

    for model in (FbGame, Game):
        for name in ("is_live", "is_final", "is_pregame", "involves", "start_utc"):
            assert hasattr(model, name) or name in getattr(model, "__dataclass_fields__", {}), (
                model,
                name,
            )


# -- the view the screens read (epic #470, #475) ---------------------------------------------------


def test_the_view_makes_the_owner_the_favourite_and_the_other_ranked_teams_followed():
    from scoreboard.config import FootballConfig

    priority = board(
        ("hockey", "NSH"), ("football", "TEN"), ("football", "NYG"), ("football", "DAL")
    )
    base = FootballConfig(final_hold_minutes=33.0, show_bye=False)
    owner = priority.owner({"football": [live(2, "NYG", "JAX")]}, NOW, WINDOWS)
    view = priority.view("football", base, owner)
    assert view.favourite_team == "NYG", "the owner is the favourite of the moment"
    assert view.also_follow == ["TEN", "DAL"] and view.followed_teams == ["NYG", "TEN", "DAL"]
    assert view.horn_team == "TEN", "the horn stays with the sport's lead team"
    assert view.final_hold_minutes == 33.0 and view.show_bye is False, (
        "everything else is the real settings"
    )


def test_the_view_without_a_football_owner_favours_the_lead_team():
    from scoreboard.config import FootballConfig

    priority = board(("hockey", "NSH"), ("football", "TEN"), ("football", "NYG"))
    for owner in (None, priority.owner({"hockey": [live(1, "NSH", "CHI")]}, NOW, WINDOWS)):
        view = priority.view("football", FootballConfig(), owner)
        assert (view.favourite_team, view.also_follow, view.horn_team) == ("TEN", ["NYG"], "TEN")


def test_the_view_of_a_sport_with_no_ranked_team_has_no_favourite():
    from scoreboard.config import FootballConfig

    view = board(("hockey", "NSH")).view("football", FootballConfig(), None)
    assert (view.favourite_team, view.also_follow, view.followed_teams, view.horn_team) == (
        "",
        [],
        [],
        "",
    )


def test_the_view_is_read_through_so_it_follows_the_real_settings_live():
    from scoreboard.config import FootballConfig

    base = FootballConfig()
    view = board(("football", "TEN")).view("football", base, None)
    base.final_hold_minutes = 7.0
    assert view.final_hold_minutes == 7.0
    assert view.idle_rotation == base.idle_rotation
