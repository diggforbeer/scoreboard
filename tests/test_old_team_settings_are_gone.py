"""The clean-up of epic #470: nothing reads the old sport / favourite / followed settings."""

from __future__ import annotations

import re
import tomllib
from dataclasses import fields
from pathlib import Path

from scoreboard.config import FootballConfig, ScoreboardConfig, Settings, TeamEntry

ROOT = Path(__file__).resolve().parent.parent
OLD_READ = re.compile(
    r"settings\.(?:scoreboard|football)\.(?:favourite_team|also_follow|followed_teams|sport)\b"
)


def test_no_source_file_reads_the_old_settings():
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if OLD_READ.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "the favourite comes from the priority layer now:\n" + "\n".join(
        offenders
    )


def test_the_settings_objects_no_longer_have_the_old_fields():
    old = {"sport", "favourite_team", "also_follow", "followed_teams"}
    for cls in (ScoreboardConfig, FootballConfig):
        assert old.isdisjoint({f.name for f in fields(cls)}), cls.__name__
        assert not any(hasattr(cls, name) for name in old), cls.__name__


def test_the_shipped_boot_config_ranks_nashville_and_sets_none_of_the_retired_keys():
    raw = tomllib.loads((ROOT / "image/files/boot/scoreboard.toml").read_text())
    assert raw["teams"] == [{"sport": "hockey", "team": "NSH"}]
    for section in ("scoreboard", "football"):
        for key in ("sport", "favourite_team", "also_follow"):
            assert key not in raw.get(section, {}), (section, key)
    assert Settings.from_dict(raw).teams == [TeamEntry("hockey", "NSH")]
