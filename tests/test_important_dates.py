"""Important dates (#524): the pure rules shared by the config loader, the admin page and the
screen."""

from __future__ import annotations

import logging
from datetime import date, datetime

import pytest

from scoreboard.important_dates import (
    DATE_TEXT_MAX,
    DateView,
    ImportantDate,
    clean_text,
    countdown_text,
    occurrence,
    parse_dates,
    parse_day,
    pick,
    text_problem,
    upcoming,
    view_for,
    years_text,
)

TODAY = date(2026, 11, 18)


def entry(day="2018-03-14", **kwargs) -> ImportantDate:
    return ImportantDate(date.fromisoformat(day), kwargs.pop("text", "MOM"), **kwargs)


# -- the text -------------------------------------------------------------------------------


def test_clean_text_capitalises_and_squeezes_spaces():
    assert clean_text("  mom   &  dad ") == "MOM & DAD"


@pytest.mark.parametrize(
    "text", ["MOM", "NATE & EM", "LILY'S DAY!", "A-B, C.D?", "A" * DATE_TEXT_MAX]
)
def test_drawable_text_has_no_problem(text):
    assert text_problem(text) is None


@pytest.mark.parametrize(
    ("text", "why"),
    [("", "enter some text"), ("A" * (DATE_TEXT_MAX + 1), "at most 14"), ("MOM <3", "can't use <")],
)
def test_undrawable_text_says_why(text, why):
    assert why in text_problem(text)


# -- the day ---------------------------------------------------------------------------------


def test_parse_day_takes_toml_dates_and_picker_strings_only():
    assert parse_day(date(2018, 3, 14)) == date(2018, 3, 14)
    assert parse_day(datetime(2018, 3, 14, 9, 30)) == date(2018, 3, 14)
    assert parse_day(" 2018-03-14 ") == date(2018, 3, 14)
    assert parse_day("2018-02-30") is None
    assert parse_day("March 14") is None
    assert parse_day(20180314) is None
    assert parse_day(None) is None


# -- when it falls -----------------------------------------------------------------------------


def test_a_repeating_date_is_this_years_until_it_passes_then_next_years():
    mom = entry("2018-03-14")
    assert occurrence(mom, date(2026, 3, 14)) == date(2026, 3, 14)  # the day itself counts
    assert occurrence(mom, date(2026, 3, 15)) == date(2027, 3, 14)
    assert occurrence(mom, date(2026, 1, 1)) == date(2026, 3, 14)


def test_a_repeating_date_never_comes_before_the_year_it_began():
    assert occurrence(entry("2030-06-01"), TODAY) == date(2030, 6, 1)


def test_a_feb_29_date_falls_on_the_28th_in_a_year_without_one():
    leap = entry("2020-02-29")
    assert occurrence(leap, date(2026, 2, 1)) == date(2026, 2, 28)
    assert occurrence(leap, date(2028, 2, 1)) == date(2028, 2, 29)


def test_a_one_off_is_its_own_day_and_gone_after():
    trip = entry("2026-12-20", repeat=False)
    assert occurrence(trip, TODAY) == date(2026, 12, 20)
    assert occurrence(trip, date(2026, 12, 20)) == date(2026, 12, 20)
    assert occurrence(trip, date(2026, 12, 21)) is None


# -- the window --------------------------------------------------------------------------------


def test_a_date_shows_from_days_before_through_the_day_and_not_earlier():
    mom = entry("2018-12-18", days_before=30)  # 30 days from TODAY
    assert view_for(mom, TODAY) == DateView("MOM", "star", 30)
    assert view_for(mom, date(2026, 11, 17)) is None  # 31 days out
    assert view_for(mom, date(2026, 12, 18)) == DateView("MOM", "star", 0)
    assert view_for(mom, date(2026, 12, 19)) is None  # next year's is 364 days away


def test_each_date_has_its_own_window():
    near = entry("2018-11-25", text="NEAR", days_before=3)  # 7 days out
    far = entry("2018-12-10", text="FAR", days_before=30)  # 22 days out
    assert [v.text for v in upcoming([near, far], TODAY)] == ["FAR"]
    assert [v.text for v in upcoming([near, far], date(2026, 11, 23))] == ["NEAR", "FAR"]


def test_upcoming_is_nearest_first_with_ties_by_text():
    a = entry("2018-11-20", text="B")
    b = entry("2018-11-19", text="Z")
    c = entry("2018-11-20", text="A")
    assert [(v.text, v.days) for v in upcoming([a, b, c], TODAY)] == [("Z", 1), ("A", 2), ("B", 2)]


def test_upcoming_with_nothing_near_is_empty():
    assert upcoming([entry("2018-03-14")], TODAY) == []
    assert upcoming([], TODAY) == []


# -- the years ---------------------------------------------------------------------------------


def test_years_count_up_to_the_day_being_shown():
    mom = entry("2018-11-25", icon="cake", show_years=True)
    assert view_for(mom, TODAY).years == 8  # her 8th, on 2026-11-25
    assert view_for(mom, date(2026, 11, 25)).years == 8


def test_years_are_left_out_unless_asked_for_and_never_zero_or_for_a_one_off():
    assert view_for(entry("2018-11-25", show_years=False), TODAY).years is None
    assert view_for(entry("2026-11-25", show_years=True), TODAY).years is None  # the first one
    assert view_for(entry("2018-11-25", repeat=False, show_years=True), TODAY) is None  # passed
    one_off = entry("2026-11-25", repeat=False, show_years=True)
    assert view_for(one_off, TODAY).years is None


@pytest.mark.parametrize(
    ("icon", "years", "text"),
    [
        ("cake", 8, "TURNS 8"),
        ("balloon", 40, "TURNS 40"),
        ("heart", 1, "1 YEAR"),
        ("heart", 9, "9 YEARS"),
        ("gift", 2, "2 YEARS"),
        ("star", None, None),
    ],
)
def test_the_years_line(icon, years, text):
    assert years_text(DateView("X", icon, 3, years)) == text


# -- the words -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("icon", "days", "text"),
    [
        ("cake", 12, "12 DAYS"),
        ("cake", 2, "2 DAYS"),
        ("cake", 1, "TOMORROW"),
        ("cake", 0, "BIRTHDAY!"),
        ("balloon", 0, "CELEBRATE!"),
        ("heart", 0, "ANNIVERSARY!"),
        ("gift", 0, "TODAY!"),
        ("star", 0, "TODAY!"),
    ],
)
def test_the_big_line(icon, days, text):
    assert countdown_text(DateView("X", icon, days)) == text


def test_the_longest_greeting_still_fits_beside_the_icon():
    """The 7x13B font is 7px a letter; the text column is 102px at 128px wide."""
    from scoreboard.important_dates import DAY_OF_TEXT

    assert max(len(t) for t in DAY_OF_TEXT.values()) * 7 <= 102


# -- sharing the slot -----------------------------------------------------------------------------


def test_the_slot_is_shared_evenly_and_never_runs_off_the_end():
    views = [DateView("A", "cake", 0), DateView("B", "cake", 1), DateView("C", "cake", 2)]
    assert [pick(views, t, 9).text for t in (0, 2.9, 3, 5.9, 6, 8.99, 9, 30)] == [
        "A", "A", "B", "B", "C", "C", "C", "C",
    ]  # fmt: skip
    assert pick(views[:1], 100, 5).text == "A"
    with pytest.raises(ValueError):
        pick([], 0, 5)


# -- loading from the file -------------------------------------------------------------------------


def row(**kwargs):
    return {"date": date(2018, 3, 14), "text": "MOM", **kwargs}


def test_a_row_loads_with_defaults():
    [mom] = parse_dates([row()])
    assert mom == ImportantDate(
        date(2018, 3, 14), "MOM", icon="star", repeat=True, show_years=False, days_before=30
    )


def test_a_hand_edit_is_repaired_where_it_can_be_and_dropped_where_not(caplog):
    rows = [
        row(text="lily's  day, with a very long name", icon="rocket", days_before=9000),
        row(text="@#$"),  # nothing drawable left
        row(date="not a date"),
        row(date=None),
        "MOM",
        row(text="OK", days_before=0, repeat="no", show_years="yes"),
    ]
    with caplog.at_level(logging.WARNING):
        dates = parse_dates(rows)
    assert [d.text for d in dates] == ["LILY'S DAY, WI", "OK"]
    assert dates[0].icon == "star" and dates[0].days_before == 365
    assert dates[1].days_before == 1 and dates[1].repeat is True and dates[1].show_years is False
    assert "unknown icon" in caplog.text and "not a date" in caplog.text


def test_only_the_first_ten_are_kept(caplog):
    with caplog.at_level(logging.WARNING):
        assert len(parse_dates([row(text=f"D{i}") for i in range(12)])) == 10
    assert "only the first 10" in caplog.text


@pytest.mark.parametrize("raw", [None, [], "MOM", {"date": "2018-03-14"}])
def test_nothing_usable_is_an_empty_list(raw):
    assert parse_dates(raw) == []
