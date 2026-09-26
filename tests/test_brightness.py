from __future__ import annotations

from nhl_scoreboard.brightness import REFERENCE_LUX, lux_to_brightness


def test_darkness_maps_to_min_brightness():
    assert lux_to_brightness(0, 10, 100) == 10


def test_reference_lux_and_beyond_maps_to_max_brightness():
    assert lux_to_brightness(REFERENCE_LUX, 10, 100) == 100
    assert lux_to_brightness(REFERENCE_LUX * 10, 10, 100) == 100


def test_negative_lux_is_clamped_like_darkness():
    assert lux_to_brightness(-5, 10, 100) == 10


def test_monotonically_increasing_with_lux():
    values = [lux_to_brightness(lux, 10, 100) for lux in (0, 1, 10, 100, 1000)]
    assert values == sorted(values)


def test_low_light_moves_brightness_more_than_an_equal_high_light_step():
    """The curve is logarithmic: 1 -> 11 lux should move brightness more
    than 500 -> 510 lux, the same +10 lux step much higher up the range."""
    low_step = lux_to_brightness(11, 10, 100) - lux_to_brightness(1, 10, 100)
    high_step = lux_to_brightness(510, 10, 100) - lux_to_brightness(500, 10, 100)
    assert low_step > high_step


def test_result_stays_within_the_clamp_range():
    for lux in (0, 0.1, 1, 50, 1000, 100000):
        result = lux_to_brightness(lux, 20, 80)
        assert 20 <= result <= 80
