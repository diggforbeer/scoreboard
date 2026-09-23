"""scripts/preview.py: smoke test that --fixture runs fully offline and
prints frames, since it's a documented dev command (CLAUDE.md) that
nothing else exercises."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("RGBMatrixEmulator")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "preview.py"


def load_module():
    spec = importlib.util.spec_from_file_location("preview", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preview = load_module()


def test_fixture_run_prints_frames_and_exits_zero(capsys):
    code = preview.main(["--fixture"])

    assert code == 0
    out = capsys.readouterr().out
    assert "128x32" in out
    # Fixture has real game data; abbrevs from the schedule show up as
    # part of an "AWY score @ HOM score" line for each drawn game.
    assert "@" in out
    assert "[" in out  # status label, e.g. "[Final]" / "[7:00 PM CT]"


def test_fixture_run_respects_limit(capsys):
    code = preview.main(["--fixture", "--limit", "1"])

    assert code == 0
    out = capsys.readouterr().out
    assert out.count("@") == 1
