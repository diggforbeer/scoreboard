"""Tests for the ``nhl-scoreboard`` command line entry point.

``--dump`` is exercised end to end through ``main()`` with the NHL client
stubbed out; nothing here touches the network or a matrix backend.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from nhl_scoreboard import __main__ as cli
from nhl_scoreboard.config import Settings
from nhl_scoreboard.nhl.api import NHLApiError
from nhl_scoreboard.nhl.models import Game


@pytest.fixture
def games() -> list[Game]:
    payload = json.loads((Path(__file__).parent / "fixtures" / "score.json").read_text())
    # Pregame labels use "%-I", which Windows' strftime rejects; the dump
    # format is the same for every state, so finals and live games suffice.
    return [g for g in map(Game.from_api, payload["games"]) if not g.is_pregame]


def stub_client(monkeypatch, games=None, error=None):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def scores(self, date="now"):
            if error is not None:
                raise error
            return games

    monkeypatch.setattr(cli, "NHLClient", FakeClient)


def dump_args(tmp_path, *extra: str) -> list[str]:
    # An explicit, absent config keeps the run off any real /boot or /etc file.
    return ["--dump", "-c", str(tmp_path / "absent.toml"), *extra]


def test_dump_prints_one_right_aligned_line_per_game(monkeypatch, tmp_path, capsys, games):
    stub_client(monkeypatch, games)

    assert cli.main(dump_args(tmp_path)) == 0

    assert capsys.readouterr().out.splitlines() == [
        "NYI  1 @ NJD  2  FINAL",
        "SJS  2 @ ANA  6  FINAL",
        "NSH  1 @ TBL  2  FINAL",
        "WSH  2 @ BOS  3  F/SO",
        "CAR  3 @ FLA  5  INT2",
        "UTA  1 @ COL  1  INT2",
        "SEA  2 @ CGY  1  1ST 05:05",
    ]


def test_dump_with_no_games_says_so(monkeypatch, tmp_path, capsys):
    stub_client(monkeypatch, [])

    assert cli.main(dump_args(tmp_path)) == 0

    assert capsys.readouterr().out == "No games today.\n"


def test_dump_api_failure_exits_1_with_a_message_not_a_traceback(monkeypatch, tmp_path, capsys):
    stub_client(monkeypatch, error=NHLApiError("boom"))

    assert cli.main(dump_args(tmp_path)) == 1

    captured = capsys.readouterr()
    assert "error: boom" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_dump_never_imports_a_matrix_backend(monkeypatch, tmp_path, games):
    # --dump must work on a machine with no matrix backend installed, so the
    # backend loader is imported only after the dump branch has returned.
    # Another test may already have imported these; clear them for this call
    # (monkeypatch restores the originals afterwards).
    watched = (
        "nhl_scoreboard.app",
        "nhl_scoreboard.display.matrix",
        "rgbmatrix",
        "RGBMatrixEmulator",
    )
    for name in watched:
        monkeypatch.delitem(sys.modules, name, raising=False)
    stub_client(monkeypatch, games)

    assert cli.main(dump_args(tmp_path)) == 0

    assert [name for name in watched if name in sys.modules] == []


def test_dump_survives_a_bad_timezone(monkeypatch, tmp_path, capsys, caplog, games):
    path = tmp_path / "scoreboard.toml"
    path.write_text('[scoreboard]\ntimezone = "America/Chicagoo"\n')
    stub_client(monkeypatch, games[:1])

    assert cli.main(["--dump", "-c", str(path)]) == 0

    assert capsys.readouterr().out == "NYI  1 @ NJD  2  FINAL\n"
    assert "America/Chicagoo" in caplog.text


def test_junk_log_level_falls_back_instead_of_crashing(monkeypatch, tmp_path, capsys, games):
    stub_client(monkeypatch, games[:1])

    assert cli.main(dump_args(tmp_path, "--log-level", "BOGUS")) == 0

    assert capsys.readouterr().out == "NYI  1 @ NJD  2  FINAL\n"


def test_config_path_reaches_settings_load(monkeypatch, tmp_path):
    seen = []

    def fake_load(path=None):
        seen.append(path)
        return Settings()

    monkeypatch.setattr(cli.Settings, "load", staticmethod(fake_load))
    stub_client(monkeypatch, [])

    cli.main(["--dump", "--config", str(tmp_path / "mine.toml")])

    assert seen == [str(tmp_path / "mine.toml")]


@pytest.mark.parametrize("backend", ["rgbmatrix", "RGBMatrixEmulator"])
def test_backend_accepts_the_two_known_backends(backend):
    assert cli.build_parser().parse_args(["--backend", backend]).backend == backend


def test_backend_rejects_anything_else(capsys):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["--backend", "hub75"])

    assert "hub75" in capsys.readouterr().err
