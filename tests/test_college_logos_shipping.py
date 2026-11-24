"""College crests reach the board image (#541, #605).

The artwork is fetched at image build time and never committed, so the chain is: the CI workflow
fetches and caches it, the image layer copies everything under ``assets/logos``, git ignores the
fetched sizes but not the hand-made overrides, and the app looks where the layer puts it. Each link
is checked here because breaking one is silent: the board just shows abbreviations again.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scoreboard.display.logos import default_directories

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-image.yml"
LAYER = ROOT / "image" / "layer" / "scoreboard.yaml"


def build_steps():
    jobs = yaml.safe_load(WORKFLOW.read_text())["jobs"]
    return next(
        job["steps"]
        for job in jobs.values()
        if any("college" in str(s.get("name", "")).lower() for s in job.get("steps", []))
    )


def step(name):
    return next(s for s in build_steps() if s.get("name") == name)


def test_the_workflow_fetches_the_college_crests_with_the_college_flag():
    fetch = step("Rasterise college logos")
    assert "scripts/fetch-logos.py --sport college" in fetch["run"]
    assert fetch["id"] == "college-logos"


def test_a_failed_fetch_warns_and_does_not_fail_the_image_build():
    fetch = step("Rasterise college logos")
    assert fetch["continue-on-error"] is True
    warn = step("Warn that the college logos could not be fetched")
    assert warn["if"] == "steps.college-logos.outcome == 'failure'"
    assert "::warning" in warn["run"]


def test_the_cache_is_saved_only_after_a_successful_fetch():
    save = step("Save college logos")
    assert save["if"] == "steps.college-logos.outcome == 'success'"
    assert save["uses"].startswith("actions/cache/save@")


def test_the_fetch_is_skipped_on_a_cache_hit():
    fetch = step("Rasterise college logos")
    assert fetch["if"] == "steps.college-logo-cache.outputs.cache-hit != 'true'"
    assert step("Restore college logos")["id"] == "college-logo-cache"


def test_restore_and_save_use_the_same_key_and_paths_and_both_sizes():
    restore, save = step("Restore college logos")["with"], step("Save college logos")["with"]
    assert restore["key"] == save["key"]
    assert restore["path"] == save["path"]
    paths = restore["path"].split()
    assert paths == ["scoreboard/assets/logos/college/12", "scoreboard/assets/logos/college/16"]
    # a change to either file that decides the set of teams or how they are drawn rebuilds it
    assert "scoreboard/scripts/fetch-logos.py" in restore["key"]
    assert "scoreboard/src/scoreboard/football/college_teams.py" in restore["key"]


def test_the_college_steps_come_after_the_football_ones_and_before_the_frontend_build():
    names = [s.get("name", "") for s in build_steps()]
    assert names.index("Warn that the football logos could not be fetched") < names.index(
        "Restore college logos"
    )
    last = max(i for i, n in enumerate(names) if "college logos" in n)
    assert last < next(i for i, n in enumerate(names) if "frontend" in n.lower())


def test_a_change_to_the_fetch_script_still_triggers_an_image_build():
    text = WORKFLOW.read_text()
    assert "scripts/fetch-logos\\.py" in text and "src/" in text


def test_the_layer_copies_the_whole_logos_tree_so_college_ships_beside_football():
    layer = LAYER.read_text()
    assert 'cp -a "$LOGOS"/. "$1/usr/share/scoreboard/logos/"' in layer
    assert 'LOGOS="$IGconf_sb_srcdir/assets/logos"' in layer


def test_the_app_looks_where_the_layer_puts_the_college_crests():
    for size in (12, 16):
        assert Path(f"/usr/share/scoreboard/logos/college/{size}/dark") in default_directories(
            size, "dark", "college"
        )


@pytest.mark.parametrize(
    ("path", "ignored"),
    [
        ("assets/logos/college/12/dark/CLEM.png", True),
        ("assets/logos/college/16/dark/DUKE.png", True),
        ("assets/logos/college/overrides/12/dark/CLEM.png", False),
    ],
)
def test_git_ignores_the_fetched_crests_but_not_the_hand_made_overrides(path, ignored):
    result = subprocess.run(
        ["git", "check-ignore", "-q", path], cwd=ROOT, capture_output=True, check=False
    )
    assert (result.returncode == 0) is ignored


def test_no_college_crest_is_committed():
    tracked = subprocess.run(
        ["git", "ls-files", "assets/logos/college"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert [t for t in tracked if "/overrides/" not in t] == []
