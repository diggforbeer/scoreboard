"""``[[dates]]`` in the config file (#524): loaded, saved over a hand-edited file, and a valid
rotation screen."""

from __future__ import annotations

from datetime import date

from scoreboard.config import RotationEntry, Settings, screen_sport
from scoreboard.important_dates import ImportantDate

HAND_EDITED = """\
# my board
[scoreboard]
rotate_seconds = 9

[[dates]]
date = 2018-03-14
text = "mom"
icon = "cake"
show_years = true
days_before = 14

[[dates]]
date = 2020-06-01
text = "OUR DAY"
icon = "heart"
repeat = false
"""


def write(tmp_path, text):
    path = tmp_path / "scoreboard.toml"
    path.write_text(text)
    return path


def test_dates_load_from_native_toml_dates(tmp_path):
    dates = Settings.load(write(tmp_path, HAND_EDITED)).dates
    assert dates == [
        ImportantDate(date(2018, 3, 14), "MOM", "cake", True, True, 14),
        ImportantDate(date(2020, 6, 1), "OUR DAY", "heart", False, False, 30),
    ]


def test_no_dates_by_default(tmp_path):
    assert Settings().dates == []
    assert Settings.load(write(tmp_path, "[scoreboard]\n")).dates == []


def test_saving_dates_replaces_the_list_and_keeps_the_rest_of_the_file(tmp_path):
    path = write(tmp_path, HAND_EDITED)
    settings = Settings.load(path)
    settings.save(
        {
            "dates": [
                {
                    "date": date(2019, 7, 4),
                    "text": "FIREWORKS",
                    "icon": "star",
                    "repeat": True,
                    "show_years": False,
                    "days_before": 7,
                }
            ]
        }
    )
    text = path.read_text()
    assert "# my board" in text and "rotate_seconds = 9" in text
    assert text.count("[[dates]]") == 1 and "date = 2019-07-04" in text and "mom" not in text
    assert settings.dates == [ImportantDate(date(2019, 7, 4), "FIREWORKS", "star", True, False, 7)]
    assert Settings.load(path).dates == settings.dates


def test_saving_an_empty_list_removes_the_key(tmp_path):
    path = write(tmp_path, HAND_EDITED)
    settings = Settings.load(path)
    settings.save({"dates": []})
    assert "dates" not in path.read_text() and settings.dates == []


def test_dates_is_a_sportless_rotation_screen_like_the_clock():
    assert screen_sport("dates") == "shared" == screen_sport("clock")


def test_a_dates_rotation_row_is_kept_not_dropped(tmp_path):
    path = write(tmp_path, '[[rotation]]\nscreen = "dates"\nseconds = 8\n')
    assert Settings.load(path).rotation == [RotationEntry("dates", 8.0)]
