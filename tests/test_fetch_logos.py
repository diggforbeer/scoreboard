"""scripts/fetch-logos.py: rasterise() image handling and main()'s CLI flow.

Loaded via importlib since the script lives outside src/ and its filename
isn't a valid module name (hyphenated). Network access (fetch()) is always
stubbed -- these tests never touch the real NHL CDN.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PIL = pytest.importorskip("PIL")
pytest.importorskip("cairosvg")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fetch-logos.py"


def load_module():
    spec = importlib.util.spec_from_file_location("fetch_logos", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch_logos = load_module()

# A 100x100 viewBox with a 50x20 rect placed off-centre (both axes), so
# cropping-to-bbox and re-centring are both exercised, not just one.
SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect x="10" y="40" width="50" height="20" fill="#3366ff"/>
</svg>"""


def test_rasterise_crops_and_centres_on_a_transparent_square_canvas():
    image = fetch_logos.rasterise(SVG, 32)
    assert image.size == (32, 32)
    assert image.mode == "RGBA"

    # Corners are outside the drawn rect (which after crop+centring is
    # wider than it is tall) -- must stay transparent, not black.
    for corner in [(0, 0), (31, 0), (0, 31), (31, 31)]:
        assert image.getpixel(corner)[3] == 0

    bbox = image.getbbox()
    assert bbox is not None
    left, top, right, bottom = bbox
    # Drawn area is centred within the square canvas (allow 1px for
    # LANCZOS/rounding), and touches the left/right edges more closely
    # than top/bottom since the source rect is wider than tall.
    assert abs(left - (32 - right)) <= 1
    assert abs(top - (32 - bottom)) <= 1
    assert right - left > bottom - top


def test_rasterise_output_is_always_exactly_size_square():
    for size in (16, 32, 64):
        image = fetch_logos.rasterise(SVG, size)
        assert image.size == (size, size)


def make_svg(hex_color: str) -> bytes:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect x="20" y="20" width="60" height="60" fill="{hex_color}"/>
</svg>""".encode()


def test_main_writes_the_layout_logolibrary_expects(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(abbrev, variant):
        calls.append((abbrev, variant))
        return make_svg("#112233")

    monkeypatch.setattr(fetch_logos, "fetch", fake_fetch)

    code = fetch_logos.main(
        ["--out", str(tmp_path), "--size", "16", "--variant", "dark", "--teams", "NSH", "TOR"]
    )

    assert code == 0
    assert sorted(calls) == [("NSH", "dark"), ("TOR", "dark")]
    for abbrev in ("NSH", "TOR"):
        target = tmp_path / "16" / "dark" / f"{abbrev}.png"
        assert target.is_file()
        assert PIL.Image.open(target).size == (16, 16)


def test_main_one_failure_does_not_stop_the_rest(tmp_path, monkeypatch, capsys):
    def fake_fetch(abbrev, variant):
        if abbrev == "BAD":
            raise RuntimeError("404")
        return make_svg("#112233")

    monkeypatch.setattr(fetch_logos, "fetch", fake_fetch)

    code = fetch_logos.main(
        ["--out", str(tmp_path), "--size", "16", "--variant", "dark", "--teams", "NSH", "BAD"]
    )

    assert code == 1
    assert (tmp_path / "16" / "dark" / "NSH.png").is_file()
    assert not (tmp_path / "16" / "dark" / "BAD.png").exists()
    err = capsys.readouterr().err
    assert "BAD (dark): 404" in err


def test_main_succeeds_with_out_outside_the_repo(tmp_path, monkeypatch):
    """Regression test for the bug found while scoping #79: main() printed
    target.relative_to(REPO_ROOT) *inside* the per-logo try, after the PNG
    was already saved -- with --out pointing outside the repo that raised
    ValueError, and the broad except then counted a successfully-written
    logo as a failure."""
    assert not str(tmp_path).startswith(str(REPO_ROOT))

    monkeypatch.setattr(fetch_logos, "fetch", lambda abbrev, variant: make_svg("#112233"))

    code = fetch_logos.main(
        ["--out", str(tmp_path), "--size", "16", "--variant", "dark", "--teams", "NSH"]
    )

    assert code == 0
    assert (tmp_path / "16" / "dark" / "NSH.png").is_file()


def test_main_both_variants_fetches_dark_and_light(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        fetch_logos,
        "fetch",
        lambda abbrev, variant: (calls.append((abbrev, variant)), make_svg("#112233"))[1],
    )

    code = fetch_logos.main(["--out", str(tmp_path), "--size", "16", "--teams", "NSH"])

    assert code == 0
    assert sorted(calls) == [("NSH", "dark"), ("NSH", "light")]
