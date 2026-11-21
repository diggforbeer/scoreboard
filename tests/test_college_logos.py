"""College logos (#541): where they live, how the fetch script picks and writes them, and that a
college scene never borrows the NFL's art for a shared abbreviation."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scoreboard.display.logos import LogoSet, default_directories

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_script():
    spec = importlib.util.spec_from_file_location(
        "fetch_logos_college", REPO_ROOT / "scripts" / "fetch-logos.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = load_script()


def png(color, canvas=100, square=40) -> bytes:
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    lo = (canvas - square) // 2
    for x in range(lo, lo + square):
        for y in range(lo, lo + square):
            image.putpixel((x, y), (*color, 255))
    buf = io.BytesIO()
    image.save(buf, "PNG")
    return buf.getvalue()


def solid(path: Path, color, size=12) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (size, size), (*color, 255)).save(path)


# -- where to look -------------------------------------------------------------------------------


def test_college_directories_sit_under_college_with_the_override_slot_first():
    dirs = default_directories(12, "dark", "college")
    assets = REPO_ROOT / "assets" / "logos" / "college"
    system = Path("/usr/share/scoreboard/logos/college")
    assert dirs == [
        system / "overrides" / "12" / "dark",
        assets / "overrides" / "12" / "dark",
        system / "12" / "dark",
        assets / "12" / "dark",
    ]
    assert not any("football" in str(d) for d in dirs)


def test_college_has_its_own_environment_variable(monkeypatch, tmp_path):
    monkeypatch.setenv("SCOREBOARD_COLLEGE_LOGO_DIR", str(tmp_path / "college"))
    monkeypatch.setenv("SCOREBOARD_FOOTBALL_LOGO_DIR", str(tmp_path / "football"))
    assert default_directories(12, "dark", "college")[0] == tmp_path / "college"
    assert default_directories(12, "dark", "football")[0] == tmp_path / "football"
    monkeypatch.delenv("SCOREBOARD_COLLEGE_LOGO_DIR")
    assert tmp_path / "college" not in default_directories(12, "dark", "college")


def test_cin_is_a_different_crest_in_each_league(monkeypatch, tmp_path):
    """``CIN`` is the Bengals in the NFL and the Bearcats in the FBS."""
    solid(tmp_path / "football" / "CIN.png", (250, 120, 0))
    solid(tmp_path / "college" / "CIN.png", (220, 20, 20))
    monkeypatch.setenv("SCOREBOARD_FOOTBALL_LOGO_DIR", str(tmp_path / "football"))
    monkeypatch.setenv("SCOREBOARD_COLLEGE_LOGO_DIR", str(tmp_path / "college"))
    nfl = LogoSet("football", "dark").get("CIN", 12)
    fbs = LogoSet("college", "dark").get("CIN", 12)
    assert nfl.pixels[0][2] == (250, 120, 0) and fbs.pixels[0][2] == (220, 20, 20)


def test_a_team_with_no_college_crest_is_none_so_the_screen_falls_back_to_text(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("SCOREBOARD_COLLEGE_LOGO_DIR", str(tmp_path))
    assert LogoSet("college", "dark").get("UGA", 12) is None


# -- the fetch script ----------------------------------------------------------------------------


TEAMS = {
    "UGA": 61,
    "CIN": 2132,
    "TEX": 251,
}


class Net:
    def __init__(self, dark=None, default=None, fail=()):
        self.dark = dark or {}
        self.default = default or {}
        self.fail = set(fail)
        self.fetched: list[str] = []

    def table(self):
        return SimpleNamespace(
            teams=[SimpleNamespace(abbrev=a, espn_id=i) for a, i in TEAMS.items()]
        )

    def url(self, url):
        self.fetched.append(url)
        espn_id = int(url.rsplit("/", 1)[1][:-4])
        abbrev = next(a for a, i in TEAMS.items() if i == espn_id)
        variant = "dark" if "500-dark" in url else "default"
        if (abbrev, variant) in self.fail:
            raise RuntimeError("404")
        source = self.dark if variant == "dark" else self.default
        return source.get(abbrev) or png((200, 30, 30))


@pytest.fixture
def net(monkeypatch):
    n = Net()
    monkeypatch.setattr(script, "fetch_college_table", n.table)
    monkeypatch.setattr(script, "fetch_url", n.url)
    return n


def test_the_defaults_are_the_two_sizes_for_every_team(net, tmp_path):
    assert script.main(["--sport", "college", "--out", str(tmp_path)]) == 0
    for size in (12, 16):
        files = sorted((tmp_path / "college" / str(size) / "dark").glob("*.png"))
        assert [f.stem for f in files] == sorted(TEAMS)
        assert Image.open(files[0]).size == (size, size)
    assert not (tmp_path / "football").exists(), "never the NFL's tree"


def test_each_variant_is_downloaded_once_per_team_not_once_per_size(net, tmp_path):
    script.main(["--sport", "college", "--out", str(tmp_path)])
    assert len(net.fetched) == 2 * len(TEAMS)
    assert "https://a.espncdn.com/i/teamlogos/ncaa/500-dark/61.png" in net.fetched
    assert "https://a.espncdn.com/i/teamlogos/ncaa/500/61.png" in net.fetched


def test_the_brighter_variant_is_kept(monkeypatch, tmp_path):
    n = Net(dark={"UGA": png((40, 40, 40))}, default={"UGA": png((230, 230, 230))})
    monkeypatch.setattr(script, "fetch_college_table", n.table)
    monkeypatch.setattr(script, "fetch_url", n.url)
    script.main(["--sport", "college", "--out", str(tmp_path), "--teams", "uga", "--size", "12"])
    image = Image.open(tmp_path / "college" / "12" / "dark" / "UGA.png")
    assert script.lit_mean(image) > 200, "the near-black dark art lost to the light default"


def test_a_tie_keeps_the_dark_variant(monkeypatch, tmp_path):
    n = Net(dark={"UGA": png((200, 0, 0))}, default={"UGA": png((200, 0, 0))})
    name, _ = script.best_variant({"default": n.default["UGA"], "dark": n.dark["UGA"]}, 12)
    assert name == "dark"


def test_one_variant_missing_is_fine_while_the_other_exists(monkeypatch, tmp_path):
    n = Net(fail={("TEX", "dark")})
    monkeypatch.setattr(script, "fetch_college_table", n.table)
    monkeypatch.setattr(script, "fetch_url", n.url)
    assert script.main(["--sport", "college", "--out", str(tmp_path), "--size", "12"]) == 0
    assert (tmp_path / "college" / "12" / "dark" / "TEX.png").is_file()


def test_no_variant_at_all_is_a_failure_not_a_crash(monkeypatch, tmp_path, capsys):
    n = Net(fail={("TEX", "dark"), ("TEX", "default")})
    monkeypatch.setattr(script, "fetch_college_table", n.table)
    monkeypatch.setattr(script, "fetch_url", n.url)
    code = script.main(["--sport", "college", "--out", str(tmp_path), "--size", "12"])
    assert code == 1
    assert "TEX: no logo downloaded" in capsys.readouterr().err
    assert not (tmp_path / "college" / "12" / "dark" / "TEX.png").exists()
    assert (tmp_path / "college" / "12" / "dark" / "UGA.png").is_file(), "the rest still land"


def test_a_subset_and_an_unknown_team(net, tmp_path, capsys):
    assert script.main(["--sport", "college", "--out", str(tmp_path), "--teams", "cin",
                        "--size", "12"]) == 0  # fmt: skip
    assert [p.stem for p in (tmp_path / "college" / "12" / "dark").glob("*.png")] == ["CIN"]
    assert script.main(["--sport", "college", "--out", str(tmp_path), "--teams", "KC"]) == 2
    assert "not FBS teams: KC" in capsys.readouterr().err


def test_an_unreadable_team_table_is_a_clear_error(monkeypatch, tmp_path, capsys):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(script, "fetch_college_table", boom)
    assert script.main(["--sport", "college", "--out", str(tmp_path)]) == 1
    assert "could not read ESPN's FBS team list" in capsys.readouterr().err


def test_a_dim_crest_is_brightened(monkeypatch, tmp_path, capsys):
    n = Net(dark={"UGA": png((20, 20, 40))}, default={"UGA": png((20, 20, 40))})
    monkeypatch.setattr(script, "fetch_college_table", n.table)
    monkeypatch.setattr(script, "fetch_url", n.url)
    script.main(["--sport", "college", "--out", str(tmp_path), "--teams", "UGA", "--size", "12"])
    assert "brightened" in capsys.readouterr().out
    assert script.lit_mean(Image.open(tmp_path / "college" / "12" / "dark" / "UGA.png")) > 20


def test_lit_mean_of_nothing_is_zero():
    assert script.lit_mean(Image.new("RGBA", (4, 4), (0, 0, 0, 0))) == 0.0
