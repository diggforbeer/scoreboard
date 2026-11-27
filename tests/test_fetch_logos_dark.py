"""``lift_dark`` in scripts/fetch-logos.py: black marks on a dark end zone become readable."""

import importlib.util
from pathlib import Path

from PIL import Image

_spec = importlib.util.spec_from_file_location(
    "fetch_logos", Path(__file__).resolve().parents[1] / "scripts" / "fetch-logos.py"
)
fetch_logos = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_logos)


def _luma(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def test_dark_pixels_reach_the_floor_and_bright_ones_are_untouched():
    image = Image.new("RGBA", (3, 1), (0, 0, 0, 0))
    image.putpixel((0, 0), (0, 0, 0, 255))
    image.putpixel((1, 0), (200, 210, 220, 255))
    out = fetch_logos.lift_dark(image)
    assert _luma(out.getpixel((0, 0))) >= fetch_logos.DARK_FLOOR - 1
    assert out.getpixel((1, 0)) == (200, 210, 220, 255)
    assert out.getpixel((2, 0)) == (0, 0, 0, 0), "transparent pixels stay transparent"


def test_only_the_dark_end_zone_crests_are_lifted():
    assert {"CAR", "CHI", "TB"} == fetch_logos.DARK_CRESTS
