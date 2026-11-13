"""The research behind ``screens_not_during_games.md`` (#420): the recorded responses must keep
showing what ``football_api.md`` ("Leaders and the playoffs") says, so the doc cannot drift from the
fixtures the idle screens will be tested against."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "football"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def leaders(event):
    return {x["name"]: x["leaders"] for x in event["competitions"][0].get("leaders", [])}


def test_a_final_has_one_leader_per_category_for_the_whole_game_with_a_team():
    final = load("scoreboard_leaders_trimmed.json")["events"][0]
    assert final["status"]["type"]["name"] == "STATUS_FINAL"
    cats = leaders(final)
    assert set(cats) == {"passingYards", "rushingYards", "receivingYards"}
    for rows in cats.values():
        assert len(rows) == 1, "one leader across both teams, not one per team"
        row = rows[0]
        assert row["team"]["id"] == row["athlete"]["team"]["id"]
        assert row["displayValue"] and row["athlete"]["shortName"] and row["athlete"]["jersey"]
    assert "YDS" in cats["passingYards"][0]["displayValue"]
    assert all(not c.get("leaders") for c in final["competitions"][0]["competitors"]), (
        "the competitors carry no leaders of their own"
    )


def test_a_scheduled_games_leaders_are_season_totals_so_only_a_final_may_be_read():
    scheduled = load("scoreboard_leaders_trimmed.json")["events"][1]
    assert scheduled["status"]["type"]["name"] == "STATUS_SCHEDULED"
    passing = leaders(scheduled)["passingYards"][0]["displayValue"]
    assert "CAR" not in passing and passing.count("YDS") == 1 and "/" not in passing


def test_the_calendar_names_the_postseason_rounds_and_the_off_season():
    calendar = load("season_calendar.json")
    assert [(c["label"], c["value"]) for c in calendar] == [
        ("Preseason", "1"), ("Regular Season", "2"), ("Postseason", "3"), ("Off Season", "4"),
    ]  # fmt: skip
    post = next(c for c in calendar if c["label"] == "Postseason")
    assert [e["alternateLabel"] for e in post["entries"]] == [
        "Wild Card", "Div Rd", "Conf Champ", "Super Bowl",
    ]  # fmt: skip
    assert (
        next(c for c in calendar if c["label"] == "Off Season")["startDate"] > post["endDate"][:10]
    )


def test_postseason_games_read_tbd_until_the_teams_are_known():
    week = load("scoreboard_postseason_w2.json")
    assert week["season"]["type"] == 3 and week["week"]["number"] == 2
    assert week["events"] and all(e["shortName"] == "TBD @ TBD" for e in week["events"])


def test_an_empty_day_has_no_season_or_week_keys():
    empty = load("scoreboard_offseason_empty.json")
    assert empty["events"] == [] and "week" not in empty and "season" not in empty
