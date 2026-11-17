"""The journal is capped on the SD card (and what the admin page's Logs tab reads stays on disk).

systemd's default lets the persistent journal grow to ~10% of the card with no age limit. The
image installs a drop-in that caps it; this pins the file and the hook that installs it, in the
regex-over-the-layer style of ``tests/test_image_audio_config.py``.
"""

from __future__ import annotations

import configparser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LAYER = REPO_ROOT / "image" / "layer" / "scoreboard.yaml"
DROP_IN = REPO_ROOT / "image" / "files" / "journald" / "scoreboard.conf"

MEGABYTE = 1024 * 1024


def _journal() -> configparser.SectionProxy:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read_string(DROP_IN.read_text())
    return parser["Journal"]


def _bytes(value: str) -> int:
    assert value.endswith("M"), value
    return int(value[:-1]) * MEGABYTE


def test_the_drop_in_caps_the_journal_by_size_file_size_and_age():
    journal = _journal()
    assert 8 * MEGABYTE <= _bytes(journal["SystemMaxUse"]) <= 128 * MEGABYTE
    assert _bytes(journal["SystemMaxFileSize"]) <= _bytes(journal["SystemMaxUse"]) // 4
    assert journal["MaxRetentionSec"].endswith("week") or journal["MaxRetentionSec"].endswith("day")


def test_the_journal_stays_on_disk_so_a_crash_or_power_cut_leaves_logs():
    """RAM-only logs would vanish exactly when they are needed."""
    assert "Storage" not in _journal() or _journal()["Storage"] in ("persistent", "auto")


def test_the_image_installs_the_drop_in_into_journald_conf_d():
    text = LAYER.read_text()
    assert "$1/etc/systemd/journald.conf.d" in text
    assert "journald/scoreboard.conf" in text
