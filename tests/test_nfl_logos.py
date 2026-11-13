"""NFL logos (#349): the lookup by sport, the multi-size set, the fetch script and its lift."""

from __future__ import annotations

import importlib.util
import io
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from nfl_logos import write_synthetic_nfl_logos
from nhl_scoreboard.display import logos as logos_mod
from nhl_scoreboard.display.logos import LogoLibrary, LogoSet, default_directories
from nhl_scoreboard.football.teams import ABBREVIATIONS

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "fetch_logos_nfl", REPO_ROOT / "scripts" / "fetch-logos.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def png(color=(200, 30, 30), canvas=100, square=40, alpha=255) -> bytes:
    """A transparent canvas with a coloured square in the middle, as a PNG."""
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    lo = (canvas - square) // 2
    for x in range(lo, lo + square):
        for y in range(lo, lo + square):
            image.putpixel((x, y), (*color, alpha))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def solid(path: Path, color, size=12) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), (*color, 255)).save(path)


# -- where to look -------------------------------------------------------------------------------


def test_nhl_directories_keep_their_original_layout():
    dirs = default_directories(32, "dark")
    assert dirs[-1] == REPO_ROOT / "assets" / "logos" / "32" / "dark"
    assert dirs[-2] == Path("/usr/share/nhl-scoreboard/logos/32/dark")
    assert not any("nfl" in str(d) for d in dirs)


def test_nfl_directories_sit_beside_them_under_nfl_with_the_same_override_slot():
    dirs = default_directories(12, "dark", "nfl")
    assets = REPO_ROOT / "assets" / "logos" / "nfl"
    system = Path("/usr/share/nhl-scoreboard/logos/nfl")
    assert dirs == [
        system / "overrides" / "12" / "dark",
        assets / "overrides" / "12" / "dark",
        system / "12" / "dark",
        assets / "12" / "dark",
    ], "overrides are looked at before the fetched art"


def test_each_sport_has_its_own_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("NHL_SCOREBOARD_LOGO_DIR", str(tmp_path / "nhl"))
    monkeypatch.setenv("NHL_SCOREBOARD_NFL_LOGO_DIR", str(tmp_path / "nfl"))
    assert default_directories(32, "dark", "nhl")[0] == tmp_path / "nhl"
    assert default_directories(12, "dark", "nfl")[0] == tmp_path / "nfl"
    monkeypatch.delenv("NHL_SCOREBOARD_NFL_LOGO_DIR")
    assert tmp_path / "nhl" not in default_directories(12, "dark", "nfl")


def test_an_unknown_sport_is_refused():
    with pytest.raises(ValueError, match="unknown sport"):
        default_directories(12, "dark", "mlb")


def test_buf_is_different_art_in_each_league(monkeypatch, tmp_path):
    """``BUF`` is Buffalo in both, but the Sabres and the Bills are different logos."""
    solid(tmp_path / "nhl" / "BUF.png", (250, 20, 20), 32)
    solid(tmp_path / "nfl" / "BUF.png", (20, 20, 250), 12)
    monkeypatch.setenv("NHL_SCOREBOARD_LOGO_DIR", str(tmp_path / "nhl"))
    monkeypatch.setenv("NHL_SCOREBOARD_NFL_LOGO_DIR", str(tmp_path / "nfl"))
    nhl = LogoLibrary.default(32, "dark", "nhl").get("BUF")
    nfl = LogoLibrary.default(12, "dark", "nfl").get("BUF")
    assert nhl.pixels[0][2] == (250, 20, 20) and nfl.pixels[0][2] == (20, 20, 250)
    assert (nhl.width, nfl.width) == (32, 12)


def test_the_default_library_is_still_the_nhl_one():
    assert LogoLibrary.default().directories == default_directories(32, "dark")


# -- the multi-size set --------------------------------------------------------------------------


def test_a_logo_set_hands_out_a_library_per_size_and_remembers_it(monkeypatch, tmp_path):
    write_synthetic_nfl_logos(tmp_path)
    monkeypatch.setenv("NHL_SCOREBOARD_NFL_LOGO_DIR", str(tmp_path / "nfl" / "12" / "dark"))
    logos = LogoSet("nfl", "dark")
    small = logos.get("KC", 12)
    assert small is not None and (small.width, small.height) == (12, 12)
    assert logos.for_size(12) is logos.for_size(12), "one library per size"
    assert logos.for_size(16) is not logos.for_size(12)
    assert logos.sport == "nfl" and logos.variant == "dark"


def test_both_sizes_resolve_when_both_were_fetched(monkeypatch, tmp_path):
    write_synthetic_nfl_logos(tmp_path)
    monkeypatch.setattr(
        logos_mod,
        "default_directories",
        lambda size, variant, sport="nhl": [tmp_path / sport / str(size) / variant],
    )
    logos = LogoSet("nfl")
    for abbrev in ABBREVIATIONS:
        assert logos.get(abbrev, 12).width == 12 and logos.get(abbrev, 16).width == 16


def test_a_missing_logo_or_size_is_none_so_the_screen_can_fall_back_to_text(tmp_path, monkeypatch):
    write_synthetic_nfl_logos(tmp_path, sizes=(12,))
    monkeypatch.setattr(
        logos_mod,
        "default_directories",
        lambda size, variant, sport="nhl": [tmp_path / sport / str(size) / variant],
    )
    logos = LogoSet("nfl")
    assert logos.get("KC", 12) is not None
    assert logos.get("KC", 16) is None, "16px was never fetched"
    assert logos.get("ZZZ", 12) is None
    assert not logos.for_size(12).has("NSH"), "an NHL-only abbreviation has no NFL logo"


def test_a_pre_built_library_can_be_injected():
    lib = LogoLibrary([], size=12)
    assert LogoSet("nfl", libraries={12: lib}).for_size(12) is lib


# -- the app -------------------------------------------------------------------------------------


@pytest.fixture
def make_app(fake_backend_factory):
    def make(show_logos=True, variant="dark"):
        from nhl_scoreboard.app import ScoreboardApp
        from nhl_scoreboard.config import Settings

        settings = Settings()
        settings.status.enabled = False
        settings.scoreboard.show_logos = show_logos
        settings.scoreboard.logo_variant = variant
        return ScoreboardApp(settings, client=_Stub(), backend=fake_backend_factory())

    return make


class _Stub:
    def scores(self, *a, **k):
        return []

    def close(self):
        pass


@pytest.fixture
def fake_backend_factory():
    from nhl_scoreboard.display.matrix import Backend
    from test_app import FakeGraphics, FakeMatrix, FakeOptions

    return lambda: Backend("fake", FakeMatrix, FakeOptions, FakeGraphics)


def test_the_renderer_has_an_nfl_logo_set_when_logos_are_on(make_app):
    app = make_app(show_logos=True, variant="light")
    assert isinstance(app.renderer.nfl_logos, LogoSet)
    assert app.renderer.nfl_logos.sport == "nfl" and app.renderer.nfl_logos.variant == "light"


def test_and_none_when_logos_are_off(make_app):
    assert make_app(show_logos=False).renderer.nfl_logos is None


def test_a_live_change_of_the_logo_settings_updates_the_nfl_logos_too(make_app):
    import dataclasses

    app = make_app(show_logos=True)
    new = dataclasses.replace(app.settings.scoreboard, show_logos=False)
    app._apply_reloaded_settings(dataclasses.replace(app.settings, scoreboard=new))
    assert app.renderer.logos is None and app.renderer.nfl_logos is None
    back = dataclasses.replace(new, show_logos=True, logo_variant="light")
    app._apply_reloaded_settings(dataclasses.replace(app.settings, scoreboard=back))
    assert app.renderer.nfl_logos is not None and app.renderer.nfl_logos.variant == "light"


# -- the fetch script ----------------------------------------------------------------------------


class Net:
    """Stands in for ESPN: an index of logo links and the PNG each link serves."""

    def __init__(self, bodies=None, missing=(), fail=()):
        self.fetched: list[str] = []
        self.bodies = bodies or {}
        self.missing, self.fail = set(missing), set(fail)

    def index(self):
        out = {}
        for abbrev in ABBREVIATIONS:
            links = {
                "dark": f"https://logos/dark/{abbrev}.png",
                "light": f"https://logos/light/{abbrev}.png",
            }
            if abbrev in self.missing:
                links.pop("dark")
            out[abbrev] = links
        return out

    def url(self, url):
        self.fetched.append(url)
        abbrev = url.rsplit("/", 1)[1][:-4]
        if abbrev in self.fail:
            raise RuntimeError("404")
        return self.bodies.get(url) or png()


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(script, "fetch_nfl_index", n.index)
    monkeypatch.setattr(script, "fetch_url", n.url)
    return n


def test_the_defaults_are_the_two_sizes_and_the_dark_variant(net, tmp_path):
    assert script.main(["--sport", "nfl", "--out", str(tmp_path)]) == 0
    for size in (12, 16):
        files = sorted((tmp_path / "nfl" / str(size) / "dark").glob("*.png"))
        assert [f.stem for f in files] == sorted(ABBREVIATIONS), f"all 32 teams at {size}px"
        assert Image.open(files[0]).size == (size, size)
    assert not (tmp_path / "nfl" / "12" / "light").exists()


def test_each_logo_is_downloaded_once_not_once_per_size(net, tmp_path):
    script.main(["--sport", "nfl", "--out", str(tmp_path)])
    assert len(net.fetched) == 32


def test_the_margin_is_cropped_so_the_pixels_go_to_the_crest(net, tmp_path):
    script.main(["--sport", "nfl", "--out", str(tmp_path), "--teams", "KC", "--size", "12"])
    image = Image.open(tmp_path / "nfl" / "12" / "dark" / "KC.png")
    x0, y0, x1, y1 = image.getbbox()
    assert x1 - x0 >= 11 and y1 - y0 >= 11, "a 40px square in a 100px canvas fills the 12px logo"


def test_both_variants_and_the_light_variant_means_espns_default(net, tmp_path):
    assert script.main(["--sport", "nfl", "--out", str(tmp_path), "--variant", "both",
                        "--teams", "KC", "--size", "12"]) == 0  # fmt: skip
    assert (tmp_path / "nfl" / "12" / "dark" / "KC.png").is_file()
    assert (tmp_path / "nfl" / "12" / "light" / "KC.png").is_file()
    assert "https://logos/light/KC.png" in net.fetched


def test_a_subset_of_teams_and_a_custom_size(net, tmp_path):
    assert script.main(["--sport", "nfl", "--out", str(tmp_path), "--teams", "kc", "NYG",
                        "--size", "8"]) == 0  # fmt: skip
    assert sorted(p.stem for p in (tmp_path / "nfl" / "8" / "dark").glob("*.png")) == ["KC", "NYG"]


def test_one_bad_logo_does_not_stop_the_rest(monkeypatch, tmp_path, capsys):
    n = Net(fail={"GB"})
    monkeypatch.setattr(script, "fetch_nfl_index", n.index)
    monkeypatch.setattr(script, "fetch_url", n.url)
    code = script.main(["--sport", "nfl", "--out", str(tmp_path), "--size", "12"])
    assert code == 1
    files = {p.stem for p in (tmp_path / "nfl" / "12" / "dark").glob("*.png")}
    assert "GB" not in files and len(files) == 31
    assert "GB (dark, 12px): 404" in capsys.readouterr().err


def test_a_team_with_no_logo_for_the_variant_is_a_failure_not_a_crash(
    monkeypatch, tmp_path, capsys
):
    n = Net(missing={"KC"})
    monkeypatch.setattr(script, "fetch_nfl_index", n.index)
    monkeypatch.setattr(script, "fetch_url", n.url)
    assert script.main(["--sport", "nfl", "--out", str(tmp_path), "--size", "12"]) == 1
    assert "KC (dark, 12px): ESPN lists no dark logo" in capsys.readouterr().err


def test_an_unreachable_team_list_is_a_clear_error(monkeypatch, tmp_path, capsys):
    def boom():
        raise OSError("no route")

    monkeypatch.setattr(script, "fetch_nfl_index", boom)
    assert script.main(["--sport", "nfl", "--out", str(tmp_path)]) == 1
    assert "could not read ESPN's team list: no route" in capsys.readouterr().err
    assert not list(tmp_path.rglob("*.png"))


def test_a_team_that_is_not_in_the_nfl_is_refused_before_anything_is_fetched(net, tmp_path, capsys):
    assert script.main(["--sport", "nfl", "--out", str(tmp_path), "--teams", "NSH"]) == 2
    assert "not NFL teams: NSH" in capsys.readouterr().err
    assert net.fetched == []


def test_nhl_art_never_lands_in_the_nfl_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(
        script,
        "fetch",
        lambda abbrev, variant: (
            b"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 10'>"
            b"<rect width='5' height='5'/></svg>"
        ),
    )
    assert script.main(["--out", str(tmp_path), "--size", "16", "32", "--variant", "dark",
                        "--teams", "NSH"]) == 0  # fmt: skip
    assert (tmp_path / "16" / "dark" / "NSH.png").is_file() and (
        tmp_path / "32" / "dark" / "NSH.png"
    ).is_file()
    assert not (tmp_path / "nfl").exists()


def test_the_index_is_read_from_espns_team_list(monkeypatch):
    payload = {"sports": [{"leagues": [{"teams": [
        {"team": {"abbreviation": "kc", "logos": [
            {"rel": ["full", "default"], "href": "https://a/kc.png"},
            {"rel": ["full", "dark"], "href": "https://a/kc-dark.png"},
            {"rel": ["full", "grayscale"], "href": "https://a/gray.png"}]}},
        {"team": {"abbreviation": "NYG", "logos": [{"rel": ["full", "default"], "href": "https://a/nyg.png"}]}},
        {"team": {"abbreviation": "XX", "logos": []}},
    ]}]}]}  # fmt: skip

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: Response())
    index = script.fetch_nfl_index()
    assert index["KC"] == {"dark": "https://a/kc-dark.png", "light": "https://a/kc.png"}
    assert index["NYG"] == {"light": "https://a/nyg.png"}, "a variant ESPN does not list is absent"
    assert index["XX"] == {}


# -- the lift for crests too dim for an LED panel ------------------------------------------------


def lit_mean(image):
    px = image.load()
    vals = [px[x, y] for y in range(image.height) for x in range(image.width) if px[x, y][3] >= 48]
    return sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b, _ in vals) / len(vals)


def test_a_crest_that_is_too_dim_is_brightened_and_a_bright_one_is_left_alone():
    dim = Image.open(io.BytesIO(png((20, 30, 60), canvas=12, square=12))).convert("RGBA")
    lifted, factor = script.lift_dim(dim)
    assert factor > 1.5 and lit_mean(lifted) > lit_mean(dim)
    bright = Image.open(io.BytesIO(png((240, 240, 240), canvas=12, square=12))).convert("RGBA")
    same, factor = script.lift_dim(bright)
    assert factor == 1.0 and same is bright


def test_the_lift_is_capped_so_a_black_crest_is_not_blown_out():
    black = Image.open(io.BytesIO(png((2, 2, 2), canvas=12, square=12))).convert("RGBA")
    lifted, factor = script.lift_dim(black)
    assert factor == script.LIFT_CAP
    assert max(lifted.getpixel((6, 6))[:3]) <= 2 * script.LIFT_CAP + 1


def test_the_lift_keeps_alpha_and_ignores_the_transparent_margin():
    image = Image.open(io.BytesIO(png((20, 20, 20), canvas=20, square=8, alpha=200))).convert(
        "RGBA"
    )
    lifted, _ = script.lift_dim(image)
    assert lifted.getpixel((10, 10))[3] == 200 and lifted.getpixel((0, 0)) == (0, 0, 0, 0)


def test_an_empty_image_is_left_alone():
    empty = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    assert script.lift_dim(empty) == (empty, 1.0)


def test_the_script_lifts_a_dim_crest_and_says_so(monkeypatch, tmp_path, capsys):
    dark = png((10, 10, 25), canvas=40, square=30)
    n = Net(bodies={"https://logos/dark/CAR.png": dark})
    monkeypatch.setattr(script, "fetch_nfl_index", n.index)
    monkeypatch.setattr(script, "fetch_url", n.url)
    script.main(["--sport", "nfl", "--out", str(tmp_path), "--teams", "CAR", "KC", "--size", "12"])
    out = capsys.readouterr().out
    car_line = next(line for line in out.splitlines() if " CAR " in line)
    assert "too dim: brightened" in car_line
    assert "too dim" not in next(line for line in out.splitlines() if " KC " in line)
    # (10, 10, 25) averages 11; brightened by the 3x cap it reaches 33.
    assert lit_mean(Image.open(tmp_path / "nfl" / "12" / "dark" / "CAR.png")) >= 25


# -- the files are never committed ---------------------------------------------------------------


def test_fetched_nfl_art_is_git_ignored_but_the_override_slot_is_not():
    def ignored(path):
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO_ROOT, check=False)
        return result.returncode == 0

    try:
        subprocess.run(["git", "--version"], capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is not available")
    assert ignored("assets/logos/nfl/12/dark/KC.png") and ignored(
        "assets/logos/nfl/16/light/KC.png"
    )
    assert not ignored("assets/logos/nfl/overrides/12/dark/KC.png")
    assert ignored("assets/logos/32/dark/NSH.png"), "the NHL rule is unchanged"
