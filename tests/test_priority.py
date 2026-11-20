"""The priority layer (epic #470, #472): a table of boards and what each one shows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from scoreboard.config import Settings, TeamEntry
from scoreboard.priority import Kind, Priority, Windows, idle_segments, segment_at

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


# -- nothing on: the one mixed idle rotation ------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """A rotation row, as the priority layer sees one."""

    screen: str
    seconds: float


H, F = "hockey", "football"


def rows(*pairs):
    return [Row(s, sec) for s, sec in pairs]


def seg(entries, available=(H, F)):
    return idle_segments(entries, list(available))


def shape(segments):
    return [(s.sport, [e.screen for e in s.entries], s.seconds) for s in segments]


def test_consecutive_rows_of_a_sport_form_a_segment_and_the_clock_joins_the_run_before_it():
    entries = rows(("standings", 8), ("countdown_preview", 8), ("fb_week", 10), ("clock", 6))
    assert shape(seg(entries)) == [
        (H, ["standings", "countdown_preview"], 16),
        (F, ["fb_week", "clock"], 16),
    ]


def test_rows_can_interleave_the_sports_freely():
    entries = rows(("standings", 8), ("fb_week", 10), ("countdown_preview", 8), ("fb_preview", 5))
    assert [s.sport for s in seg(entries)] == [H, F, H, F]


def test_a_clock_that_comes_first_takes_the_sport_of_the_rows_after_it():
    assert shape(seg(rows(("clock", 4), ("fb_week", 10)))) == [(F, ["clock", "fb_week"], 14)]
    assert shape(seg(rows(("clock", 4), ("standings", 8)))) == [(H, ["clock", "standings"], 12)]


def test_a_lone_clock_belongs_to_the_first_available_sport():
    assert shape(seg(rows(("clock", 4)), available=(F, H))) == [(F, ["clock"], 4)]
    assert seg(rows(("clock", 4)), available=()) == []


def test_a_sport_with_nothing_to_show_has_its_rows_skipped_and_neighbours_merge():
    entries = rows(("standings", 8), ("fb_week", 10), ("countdown_preview", 8))
    assert shape(seg(entries, available=(H,))) == [(H, ["standings", "countdown_preview"], 16)]
    assert shape(seg(entries, available=(F,))) == [(F, ["fb_week"], 10)]
    assert seg(entries, available=()) == []


def test_every_hockey_screen_is_hockeys_and_every_football_screen_footballs():
    from scoreboard.config import (
        COLLEGE_SCREENS,
        FOOTBALL_SCREENS,
        VALID_ROTATION_SCREENS,
        screen_sport,
    )

    for screen in VALID_ROTATION_SCREENS:
        if screen in COLLEGE_SCREENS:
            expected = "college"  # their own sport since #579, tested in test_college_rotation
        else:
            expected = (
                F
                if screen in FOOTBALL_SCREENS
                else ("shared" if screen in ("clock", "dates") else H)
            )
        assert screen_sport(screen) == expected, screen
    assert set(FOOTBALL_SCREENS) <= set(VALID_ROTATION_SCREENS)


def test_the_segment_at_a_time_is_found_and_wraps_round():
    segments = seg(rows(("standings", 24), ("fb_week", 36)))
    assert segment_at(segments, 0.0) == (0, 0.0)
    assert segment_at(segments, 12.0) == (0, 0.5)
    assert segment_at(segments, 24.0) == (1, 0.0)
    assert segment_at(segments, 42.0) == (1, 0.5)
    assert segment_at(segments, 60.0) == (0, 0.0), "and round again"
    assert segment_at([], 5.0) is None


@pytest.mark.parametrize("clock", [0.0, 1.0, 23.9, 24.0, 59.9, 60.0, 1234.5])
def test_the_segment_is_a_pure_function_of_the_clock(clock):
    segments = seg(rows(("standings", 24), ("fb_week", 36)))
    assert segment_at(segments, clock) == segment_at(segments, clock)
    index, fraction = segment_at(segments, clock)
    assert index in (0, 1) and 0.0 <= fraction <= 1.0


def test_a_segment_holds_its_whole_length_so_the_board_cannot_flicker():
    segments = seg(rows(("standings", 24), ("fb_week", 36)))
    seen = [segment_at(segments, t / 2)[0] for t in range(0, 120)]  # a minute, every half second
    runs = [seen[0]]
    for index in seen[1:]:
        if index != runs[-1]:
            runs.append(index)
    assert runs == [0, 1], "one switch per segment, never back and forth"


def test_the_default_one_per_sport_rotation_gives_two_segments_in_lead_rank_order():
    from scoreboard.config import DEFAULT_FOOTBALL_ROTATION

    football_rows = [Row(s, sec) for s, sec in DEFAULT_FOOTBALL_ROTATION]
    hockey_rows = rows(("countdown_preview", 8), ("standings", 8), ("clock", 8))
    both = seg(hockey_rows + football_rows)
    assert [s.sport for s in both] == [H, F]
    assert [s.sport for s in seg(football_rows + hockey_rows)] == [F, H]


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
    assert [e.screen for e in view.idle_rotation][:2] == ["fb_preview", "fb_standings"]


# -- the night-game slots: SNF and MNF rank like teams --------------------------------------------


def _at(year, month, day, hour, minute=0):
    """A kick-off given in Eastern time (November: UTC-5)."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC) + timedelta(hours=5)


class N(G):
    """A football game that knows the night slots, as ``FbGame`` does."""

    def in_slot(self, slot):
        from scoreboard.football.teams import in_night_slot

        return in_night_slot(slot, self.start_utc)


SUN_NIGHT = _at(2026, 11, 15, 20, 20)  # a Sunday
MON_NIGHT = _at(2026, 11, 16, 20, 15)  # a Monday
SUN_NOON = _at(2026, 11, 15, 13)


def test_the_sunday_slot_is_a_sunday_evening_in_eastern_time_and_the_monday_slot_a_monday_one():
    from scoreboard.football.teams import in_night_slot

    assert in_night_slot("SNF", SUN_NIGHT) and not in_night_slot("MNF", SUN_NIGHT)
    assert in_night_slot("MNF", MON_NIGHT) and not in_night_slot("SNF", MON_NIGHT)
    assert not in_night_slot("SNF", SUN_NOON), "the early and late-afternoon games are not it"
    assert not in_night_slot("SNF", _at(2026, 11, 15, 16, 25))
    assert not in_night_slot("SNF", _at(2026, 11, 12, 20, 15)), "Thursday night is not Sunday's"
    assert not in_night_slot("SNF", None) and not in_night_slot("XYZ", SUN_NIGHT)
    # 8:20pm Eastern is already Monday in UTC: the slot is judged in the league's own zone
    assert SUN_NIGHT.weekday() == 0 and in_night_slot("SNF", SUN_NIGHT)


def test_a_slot_shows_that_nights_game_when_nothing_ranked_above_it_is_on():
    game = N(1, "DAL", "NYG", "live", SUN_NIGHT)
    priority = board(("football", "SNF"))
    moment = priority.owner({"football": [game]}, SUN_NIGHT, WINDOWS)
    assert moment is not None and moment.kind is Kind.LIVE and moment.sport == "football"
    assert moment.team == "NYG", "the screens need a side: the home team when none is ranked"


def test_a_team_ranked_above_the_slot_wins_and_one_below_it_does_not():
    night = N(1, "DAL", "NYG", "live", SUN_NIGHT)
    other = N(2, "TEN", "HOU", "live", SUN_NOON)
    above = board(("football", "TEN"), ("football", "SNF"))
    assert above.owner({"football": [night, other]}, SUN_NIGHT, WINDOWS).team == "TEN"
    below = board(("football", "SNF"), ("football", "TEN"))
    assert below.owner({"football": [night, other]}, SUN_NIGHT, WINDOWS).game is night


def test_a_ranked_team_in_the_night_game_is_the_side_the_screens_favour():
    night = N(1, "DAL", "NYG", "live", SUN_NIGHT)
    priority = board(("football", "SNF"), ("football", "DAL"))
    assert priority.owner({"football": [night]}, SUN_NIGHT, WINDOWS).team == "DAL"


def test_a_slot_only_follows_its_own_night():
    monday = N(1, "DAL", "NYG", "live", MON_NIGHT)
    assert board(("football", "SNF")).owner({"football": [monday]}, MON_NIGHT, WINDOWS) is None
    assert board(("football", "MNF")).owner({"football": [monday]}, MON_NIGHT, WINDOWS) is not None


def test_a_slot_has_a_countdown_and_a_held_final_like_a_team():
    kickoff = SUN_NIGHT
    pre = N(1, "DAL", "NYG", "pre", kickoff)
    near = kickoff - timedelta(minutes=30)
    assert (
        board(("football", "SNF")).owner({"football": [pre]}, near, WINDOWS).kind is Kind.COUNTDOWN
    )
    far = kickoff - timedelta(hours=5)
    assert board(("football", "SNF")).owner({"football": [pre]}, far, WINDOWS) is None
    done = N(2, "DAL", "NYG", "final", kickoff)
    ages = {("football", 2): timedelta(minutes=5)}
    assert (
        board(("football", "SNF")).owner({"football": [done]}, kickoff, WINDOWS, ages).kind
        is Kind.FINAL
    )


def test_a_slot_is_not_a_team_it_has_no_horn_idle_screens_or_colours():
    priority = board(("football", "SNF"), ("football", "TEN"), ("hockey", "NSH"))
    assert priority.lead("football") == "TEN" and priority.teams_for("football") == ["TEN"]
    assert priority.colour_team() == TeamEntry("football", "TEN")
    only = board(("football", "MNF"))
    assert only.lead("football") is None and only.colour_team() is None
    assert only.sports() == ["football"], "it still needs the football feed running"
    view = only.view("football", object(), None)
    assert view.favourite_team == "" and view.followed_teams == [] and view.horn_team == ""


def test_slots_are_valid_in_the_football_list_only(tmp_path):
    from scoreboard.config import team_exists

    assert team_exists("football", "SNF") and team_exists("football", "MNF")
    assert not team_exists("hockey", "SNF") and not team_exists("football", "XNF")
    path = tmp_path / "c.toml"
    path.write_text(
        '[[teams]]\nsport = "football"\nteam = "snf"\n\n[[teams]]\nsport = "hockey"\nteam = "SNF"\n'
    )
    assert Settings.load(path).teams == [TeamEntry("football", "SNF")]


def test_the_thursday_slot_is_a_thursday_evening_and_not_a_thanksgiving_afternoon():
    from scoreboard.football.teams import in_night_slot

    assert in_night_slot("TNF", _at(2026, 11, 12, 20, 15))  # an ordinary Thursday night
    assert not in_night_slot("TNF", SUN_NIGHT) and not in_night_slot("TNF", MON_NIGHT)
    assert not in_night_slot("SNF", _at(2026, 11, 12, 20, 15))
    assert not in_night_slot("TNF", _at(2026, 11, 26, 12, 30)), "Thanksgiving's early game"
    assert not in_night_slot("TNF", _at(2026, 11, 26, 16, 30)), "and its afternoon game"
    assert in_night_slot("TNF", _at(2026, 11, 26, 20, 20)), "but its night game is Thursday night"


def test_a_ranked_thursday_slot_shows_that_nights_game():
    game = N(1, "DAL", "NYG", "live", _at(2026, 11, 12, 20, 15))
    moment = board(("football", "TNF")).owner({"football": [game]}, game.start_utc, WINDOWS)
    assert moment is not None and moment.kind is Kind.LIVE
    assert board(("football", "SNF")).owner({"football": [game]}, game.start_utc, WINDOWS) is None
