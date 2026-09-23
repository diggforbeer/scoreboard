"""LogoLibrary: lookup, decoding, and graceful absence."""

from __future__ import annotations

import pytest

from nhl_scoreboard.display.logos import ALPHA_FLOOR, LogoLibrary, decode

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def make_logo(path, size=32, color=(0, 114, 206), alpha=255):
    """A filled circle, which is enough to exercise every decode branch."""
    from PIL import ImageDraw

    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse((2, 2, size - 3, size - 3), fill=(*color, alpha))
    im.save(path)
    return im


def test_finds_logo_by_abbrev_case_insensitively(tmp_path):
    make_logo(tmp_path / "TOR.png")
    lib = LogoLibrary([tmp_path])
    assert lib.has("tor")
    assert lib.get("TOR").abbrev == "TOR"
    assert lib.path_for(" tor ") == tmp_path / "TOR.png"


def test_missing_logo_is_none_not_error(tmp_path):
    lib = LogoLibrary([tmp_path, tmp_path / "nope"])
    assert lib.get("XXX") is None
    assert not lib.has("XXX")


def test_first_directory_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    make_logo(a / "TOR.png", color=(255, 0, 0))
    make_logo(b / "TOR.png", color=(0, 255, 0))
    logo = LogoLibrary([a, b]).get("TOR")
    assert logo.pixels[0][2] == (255, 0, 0)


def test_decode_drops_transparent_and_composites_alpha():
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    im.putpixel((0, 0), (200, 100, 50, 255))  # opaque
    im.putpixel((1, 0), (200, 100, 50, 128))  # half: composited over black
    im.putpixel((2, 0), (200, 100, 50, ALPHA_FLOOR - 1))  # below floor: dropped
    im.putpixel((3, 0), (5, 5, 5, 255))  # opaque but near-black: dropped
    logo = decode("T", im, 4)
    assert logo.pixels == ((0, 0, (200, 100, 50)), (1, 0, (100, 50, 25)))


def test_decode_resizes_off_size_input():
    im = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    logo = decode("T", im, 32)
    assert (logo.width, logo.height) == (32, 32)
    assert len(logo.pixels) == 32 * 32


def test_decode_resize_uses_lanczos(monkeypatch):
    """A mis-sized override must get fetch-logos.py's filter, not Pillow's default."""
    calls = []
    real_resize = Image.Image.resize

    def spy(self, *args, **kwargs):
        calls.append(kwargs.get("resample", args[1] if len(args) > 1 else None))
        return real_resize(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "resize", spy)
    logo = decode("T", Image.new("RGBA", (64, 64), (255, 255, 255, 255)), 32)
    assert (logo.width, logo.height) == (32, 32)
    # Pillow re-enters resize() for RGBA (premultiplied pass), so only the
    # outermost call -- decode()'s own -- is ours.
    assert calls[0] == Image.LANCZOS


def test_cache_loads_once(tmp_path, monkeypatch):
    make_logo(tmp_path / "TOR.png")
    lib = LogoLibrary([tmp_path])
    first = lib.get("TOR")
    (tmp_path / "TOR.png").unlink()
    assert lib.get("TOR") is first


# -- overrides for crests that don't downscale legibly (#12) ----------------


def test_override_directory_is_checked_before_the_fetched_one():
    from nhl_scoreboard.display.logos import default_directories

    # Compare path components, not strings: str(Path) uses "\" on Windows.
    tails = [d.parts[-4:] for d in default_directories(32, "dark")]
    override = tails.index(("logos", "overrides", "32", "dark"))
    fetched = tails.index(("assets", "logos", "32", "dark"))
    assert override < fetched, "override tier must be searched first"


def test_wsh_override_ships_and_is_legible():
    """The Capitals' official crest is fine linework that turns to mush at
    32px (#12); this repo carries a hand-picked replacement instead of
    falling back to text for every Capitals game. Sanity-check it's
    actually there and isn't itself a near-empty or corrupt image."""
    from nhl_scoreboard.display.logos import LogoLibrary

    lib = LogoLibrary.default(variant="dark")
    logo = lib.get("WSH")
    assert logo is not None, "assets/logos/overrides/32/dark/WSH.png is missing"
    assert lib.path_for("WSH") is not None
    resolved = str(lib.path_for("WSH"))
    assert "overrides" in resolved, f"must resolve to the override, not the fetched one: {resolved}"
    # A bold two-colour mark should light a healthy fraction of the panel;
    # a near-empty result would mean the source image or background-removal
    # step went wrong.
    assert 200 <= len(logo.pixels) <= 32 * 32 * 0.8
