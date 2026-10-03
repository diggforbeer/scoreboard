"""nhl_scoreboard.admin_server (#178): real app state flows across a real
WebSocket connection, in both directions.

Plain `asyncio.run()` inside ordinary test functions rather than adding
pytest-asyncio as a new dev dependency -- this is the only async code in the
project so far, and a handful of self-contained tests don't need a plugin
for that.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.client
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.sync.client import connect as sync_connect

from nhl_scoreboard import admin_server, updater


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    monkeypatch.setattr(admin_server, "CONFIG_PATH", str(path))
    return path


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "update-state.json"
    monkeypatch.setattr(updater, "STATE_FILE", path)
    return path


@pytest.fixture
def fake_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(
        admin_server.subprocess, "run", lambda *args, **kwargs: calls.append(args[0])
    )
    return calls


@pytest.fixture
def admin_dir(tmp_path, monkeypatch):
    """A real ADMIN_DIR with a built-looking index.html + one asset, for
    the static-file-serving tests (#178 story 10) -- never the real
    frontend/dist, just enough to exercise _static_response's own logic."""
    directory = tmp_path / "admin"
    directory.mkdir()
    (directory / "index.html").write_text("<!doctype html><title>admin</title>")
    (directory / "app.js").write_text("console.log('hi')")
    monkeypatch.setattr(admin_server, "ADMIN_DIR", directory)
    return directory


async def _serve_and_run(scenario):
    async with serve(admin_server._handle, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://localhost:{port}/") as client:
            return await scenario(client)


async def _serve_and_get(path):
    """Same shape as _serve_and_run, but a plain HTTP GET through
    _process_request -- the static-file half of story 10, not the
    WebSocket half."""
    async with serve(
        admin_server._handle, "localhost", 0, process_request=admin_server._process_request
    ) as server:
        port = server.sockets[0].getsockname()[1]

        def _get():
            conn = http.client.HTTPConnection("localhost", port, timeout=5)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                return resp.status, dict(resp.getheaders()), resp.read()
            finally:
                conn.close()

        return await asyncio.to_thread(_get)


async def _skip_initial(client, n=11):
    """Drain the version/audio/scoreboard/status/panel/night_mode/wifi/
    rotation/update/horn_list/snapshot messages every connection opens
    with."""
    for _ in range(n):
        await client.recv()


# -- story 1: version on connect --------------------------------------------


def test_sends_the_installed_version_on_connect(app_dir, config_path):
    (app_dir / "VERSION").write_text("v2026.09.29.4\n")

    async def scenario(client):
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "version", "value": "v2026.09.29.4"}


def test_falls_back_to_unknown_with_no_version_file(app_dir, config_path):
    async def scenario(client):
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "version", "value": "unknown (factory image)"}


def test_connection_stays_open_after_the_initial_messages(app_dir, config_path):
    """The whole point of this over a one-shot HTTP response: the socket is
    still open afterward, ready to keep exchanging messages on."""

    async def scenario(client):
        await _skip_initial(client)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv(), timeout=0.2)
        return client.state.name == "OPEN"

    assert asyncio.run(_serve_and_run(scenario))


# -- story 2: the Audio section ----------------------------------------------


def test_sends_the_current_audio_config_on_connect(app_dir, config_path):
    config_path.write_text('[audio]\nenabled = false\ndevice = "hw:1,0"\n')

    async def scenario(client):
        await client.recv()  # version
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "audio",
        "data": {"enabled": False, "device": "hw:1,0", "horn_dir": "", "volume": 100},
    }


def test_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    # enabled=False here, so _apply_audio_volume's own enabled-gate skips
    # the mixer call -- this test needs no fake amixer runner at all, same
    # "disabled short-circuits before any subprocess" invariant as
    # test_horn_test_reports_not_played_when_audio_disabled below.
    async def scenario(client):
        await _skip_initial(client)
        await client.send(
            json.dumps(
                {
                    "type": "save",
                    "section": "audio",
                    "data": {
                        "enabled": False,
                        "device": "hw:1,0",
                        "horn_dir": "",
                        "volume": 75,
                    },
                }
            )
        )
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "audio"}
    assert json.loads(fresh) == {
        "type": "config",
        "section": "audio",
        "data": {"enabled": False, "device": "hw:1,0", "horn_dir": "", "volume": 75},
    }
    assert 'device = "hw:1,0"' in config_path.read_text()


def test_save_applies_volume_to_the_mixer_immediately_when_enabled(
    app_dir, config_path, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        admin_server.GoalHornPlayer,
        "_amixer",
        staticmethod(lambda cmd: calls.append(cmd) or True),
    )

    async def scenario(client):
        await _skip_initial(client)
        await client.send(
            json.dumps(
                {"type": "save", "section": "audio", "data": {"enabled": True, "volume": 65}}
            )
        )
        return await client.recv(), await client.recv()

    asyncio.run(_serve_and_run(scenario))
    assert calls == [["amixer", "-q", "sset", "PCM", "65%"]]


def test_save_rejects_an_unknown_field_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "audio", "data": {"bogus": "x"}}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "bogus" in message["message"]
    assert config_path.read_text() == ""


def test_save_rejects_the_wrong_type_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(
            json.dumps({"type": "save", "section": "audio", "data": {"enabled": "not a bool"}})
        )
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "enabled" in message["message"]
    assert config_path.read_text() == ""


def test_save_rejects_an_unknown_section(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "bogus-section", "data": {}}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "bogus-section" in message["message"]


def test_unknown_message_type_gets_an_error_not_a_crash(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "not-a-real-type"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


def test_invalid_json_gets_an_error_not_a_crash(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send("not json at all")
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


# -- story 3: the idle rotation list ------------------------------------------


def test_sends_the_current_rotation_on_connect(app_dir, config_path):
    config_path.write_text(
        '[[rotation]]\nscreen = "standings"\nseconds = 12\n\n'
        '[[rotation]]\nscreen = "clock"\nseconds = 8\n'
    )

    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        await client.recv()  # status
        await client.recv()  # panel
        await client.recv()  # night_mode
        await client.recv()  # wifi
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "rotation",
        "data": [
            {"screen": "standings", "seconds": 12.0},
            {"screen": "clock", "seconds": 8.0},
        ],
    }


def test_rotation_save_writes_the_list_in_the_given_order(app_dir, config_path):
    rows = [{"screen": "clock", "seconds": 5}, {"screen": "standings", "seconds": 15}]

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": rows}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "rotation"}
    assert json.loads(fresh)["data"] == [
        {"screen": "clock", "seconds": 5.0},
        {"screen": "standings", "seconds": 15.0},
    ]
    # Order in the file matches the order sent -- no separate "order" field
    # to sort by (#151's HTML version needed one; this doesn't).
    text = config_path.read_text()
    assert text.index('screen = "clock"') < text.index('screen = "standings"')


def test_rotation_save_rejects_an_unknown_screen(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = [{"screen": "bogus-screen", "seconds": 5}]
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "row 1" in message["message"]
    assert config_path.read_text() == ""


@pytest.mark.parametrize("seconds", [0, -5, "five", True])
def test_rotation_save_rejects_non_positive_or_non_numeric_seconds(app_dir, config_path, seconds):
    async def scenario(client):
        await _skip_initial(client)
        data = [{"screen": "clock", "seconds": seconds}]
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert config_path.read_text() == ""


def test_rotation_save_rejects_more_than_the_row_cap(app_dir, config_path):
    rows = [{"screen": "clock", "seconds": 5}] * (admin_server.ROTATION_MAX_ROWS + 1)

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": rows}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert str(admin_server.ROTATION_MAX_ROWS) in message["message"]
    assert config_path.read_text() == ""


def test_rotation_save_rejects_a_non_list_payload(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"screen": "clock", "seconds": 5}  # a single row, not wrapped in a list
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


def test_rotation_save_accepts_an_empty_list(app_dir, config_path):
    """Empty is valid -- falls back to the built-in default rotation, same
    as config.py's own _parse_rotation treats an absent/empty [[rotation]]."""

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": []}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "saved", "section": "rotation"}


# -- story 4: Software update and Reboot -------------------------------------


def test_sends_the_current_update_config_on_connect(app_dir, config_path, state_file):
    state_file.write_text(
        json.dumps(
            {
                "installed": "v2026.09.29",
                "latest": "v2026.09.30",
                "checked_at": "2026-09-30T00:00:00+00:00",
                "available": True,
                "applicable": True,
            }
        )
    )

    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        await client.recv()  # status
        await client.recv()  # panel
        await client.recv()  # night_mode
        await client.recv()  # wifi
        await client.recv()  # rotation
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "update",
        "data": {
            "installed": "v2026.09.29",
            "latest": "v2026.09.30",
            "checked_at": "2026-09-30T00:00:00+00:00",
            "error": "",
            "reason": "",
            "available": True,
            "applicable": True,
            "last_apply": "",
        },
    }


def test_update_check_acks_immediately_and_starts_the_check_unit(
    app_dir, config_path, fake_systemctl
):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "update_check"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "checking"}
    assert fake_systemctl == [
        ["systemctl", "start", "--no-block", "nhl-scoreboard-update-now.service"]
    ]


def test_update_apply_acks_immediately_and_starts_the_apply_unit(
    app_dir, config_path, fake_systemctl
):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "update_apply"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "applying"}
    assert fake_systemctl == [
        ["systemctl", "start", "--no-block", "nhl-scoreboard-update-apply.service"]
    ]


def test_reboot_acks_immediately_and_calls_systemctl_reboot(app_dir, config_path, fake_systemctl):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "reboot"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "rebooting"}
    assert fake_systemctl == [["systemctl", "reboot"]]


def test_horn_test_reports_not_played_when_audio_disabled(app_dir, config_path):
    """enabled=False short-circuits before GoalHornPlayer ever touches a
    subprocess, so this needs no fake runner at all."""
    config_path.write_text("[audio]\nenabled = false\n")

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "test_horn"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "horn_tested", "played": False}


def test_horn_test_plays_the_favourite_teams_horn_when_enabled(
    app_dir, config_path, tmp_path, monkeypatch
):
    # A synthetic horn_dir with both a team-specific and a default file --
    # not the repo's own real assets/horns/ (NSH.wav there is a git-
    # ignored local drop-in, never committed, so relying on it broke this
    # test in CI's clean checkout). Both files present proves this uses
    # the same team-specific-first lookup a real goal would, not just
    # "some file got played".
    horn_dir = tmp_path / "horns"
    horn_dir.mkdir()
    (horn_dir / "NSH.wav").write_bytes(b"fake wav")
    (horn_dir / "_default.wav").write_bytes(b"fake wav")
    config_path.write_text(
        f'[audio]\nenabled = true\nhorn_dir = "{horn_dir}"\nvolume = 33\n'
        '[scoreboard]\nfavourite_team = "NSH"\n'
    )
    calls = []
    mixer_calls = []
    monkeypatch.setattr(
        admin_server.GoalHornPlayer, "_popen", staticmethod(lambda cmd: calls.append(cmd))
    )
    monkeypatch.setattr(
        admin_server.GoalHornPlayer,
        "_amixer",
        staticmethod(lambda cmd: mixer_calls.append(cmd) or True),
    )

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "test_horn"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "horn_tested", "played": True}
    assert len(calls) == 1
    assert calls[0][0] == "aplay"
    assert calls[0][-1].endswith("NSH.wav")
    assert mixer_calls == [["amixer", "-q", "sset", "PCM", "33%"]]


def test_watcher_broadcasts_when_the_update_state_file_changes(
    app_dir, config_path, state_file, monkeypatch
):
    """The actual point of story 4: a check/apply happening out of process
    (a real board would run it via systemd, not this call) still reaches
    every connected client without anyone asking again."""
    monkeypatch.setattr(admin_server, "UPDATE_POLL_SECONDS", 0.02)

    async def scenario():
        watcher = asyncio.create_task(admin_server._watch_update_state())
        try:
            async with serve(admin_server._handle, "localhost", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://localhost:{port}/") as client:
                    await _skip_initial(client)
                    state_file.write_text(
                        json.dumps({"installed": "v1", "latest": "v2", "available": True})
                    )
                    message = await asyncio.wait_for(client.recv(), timeout=2)
                    return json.loads(message)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    received = asyncio.run(scenario())
    assert received["type"] == "config"
    assert received["section"] == "update"
    assert received["data"]["installed"] == "v1"
    assert received["data"]["latest"] == "v2"
    assert received["data"]["available"] is True


def test_watcher_broadcasts_to_every_connected_client(
    app_dir, config_path, state_file, monkeypatch
):
    monkeypatch.setattr(admin_server, "UPDATE_POLL_SECONDS", 0.02)

    async def scenario():
        watcher = asyncio.create_task(admin_server._watch_update_state())
        try:
            async with serve(admin_server._handle, "localhost", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with (
                    connect(f"ws://localhost:{port}/") as client_a,
                    connect(f"ws://localhost:{port}/") as client_b,
                ):
                    await _skip_initial(client_a)
                    await _skip_initial(client_b)
                    state_file.write_text(json.dumps({"installed": "v1"}))
                    a = await asyncio.wait_for(client_a.recv(), timeout=2)
                    b = await asyncio.wait_for(client_b.recv(), timeout=2)
                    return json.loads(a), json.loads(b)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    a, b = asyncio.run(scenario())
    assert a["data"]["installed"] == b["data"]["installed"] == "v1"


# -- story 5: the Scoreboard section ------------------------------------------


_DEFAULT_SCOREBOARD_DATA = {
    "favourite_team": "NSH",
    "timezone": "America/Chicago",
    "rotate_seconds": 8.0,
    "poll_seconds": 60.0,
    "live_poll_seconds": 15.0,
    "show_clock_when_idle": True,
    "prefer_favourite": True,
    "show_logos": True,
    "logo_variant": "dark",
    "goal_flash_seconds": 6.0,
    "goal_detail_seconds": 8.0,
    "three_stars_seconds": 8.0,
    "countdown_hours": 2.0,
    "final_hold_minutes": 30.0,
    "show_standings": True,
    "show_clock_between_games": False,
}

#: show_standings is a real ScoreboardConfig field (and so is in the
#: asdict payload the server sends on connect, above), but is no longer
#: one this section's own save message validates -- the Rotation
#: section's [[rotation]] list is the authoritative control for whether
#: "standings" appears in the idle rotation now (#150/#151); show_standings
#: only still feeds the *derived default* rotation for a board with no
#: explicit [[rotation]]. Every save-message test below sends this, not
#: _DEFAULT_SCOREBOARD_DATA directly, the same way the frontend's
#: saveScoreboard strips it before calling save().
_SCOREBOARD_SAVE_DATA = {k: v for k, v in _DEFAULT_SCOREBOARD_DATA.items() if k != "show_standings"}


def test_sends_the_current_scoreboard_config_on_connect(app_dir, config_path):
    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "scoreboard",
        "data": _DEFAULT_SCOREBOARD_DATA,
    }


def test_scoreboard_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    new_values = {**_SCOREBOARD_SAVE_DATA, "favourite_team": "TOR", "show_logos": False}

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "scoreboard", "data": new_values}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "scoreboard"}
    fresh_data = json.loads(fresh)["data"]
    assert fresh_data["favourite_team"] == "TOR"
    assert fresh_data["show_logos"] is False
    assert 'favourite_team = "TOR"' in config_path.read_text()


def test_scoreboard_save_rejects_an_unknown_field_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_SCOREBOARD_SAVE_DATA, "bogus": "x"}
        await client.send(json.dumps({"type": "save", "section": "scoreboard", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "bogus" in message["message"]
    assert config_path.read_text() == ""


def test_scoreboard_save_rejects_the_wrong_type(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_SCOREBOARD_SAVE_DATA, "rotate_seconds": "not a number"}
        await client.send(json.dumps({"type": "save", "section": "scoreboard", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "rotate_seconds" in message["message"]
    assert config_path.read_text() == ""


def test_scoreboard_save_rejects_an_invalid_logo_variant(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_SCOREBOARD_SAVE_DATA, "logo_variant": "purple"}
        await client.send(json.dumps({"type": "save", "section": "scoreboard", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "logo_variant" in message["message"]
    assert config_path.read_text() == ""


def test_scoreboard_save_rejects_a_non_object_payload(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "scoreboard", "data": [1, 2]}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


# -- story 6: the Status page section -----------------------------------------


def test_sends_the_current_status_config_on_connect(app_dir, config_path):
    config_path.write_text("[status]\nenabled = false\nport = 9000\n")

    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "status",
        "data": {"enabled": False, "port": 9000},
    }


def test_status_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"enabled": False, "port": 9090}
        await client.send(json.dumps({"type": "save", "section": "status", "data": data}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "status"}
    assert json.loads(fresh) == {
        "type": "config",
        "section": "status",
        "data": {"enabled": False, "port": 9090},
    }
    assert "port = 9090" in config_path.read_text()


def test_status_save_rejects_a_non_integer_port(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"enabled": True, "port": 8080.5}
        await client.send(json.dumps({"type": "save", "section": "status", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "port" in message["message"]
    assert "whole number" in message["message"]
    assert config_path.read_text() == ""


def test_status_save_rejects_a_boolean_port(app_dir, config_path):
    """bool is a subclass of int in Python -- True/False must not slip
    through the "must be an int" check."""

    async def scenario(client):
        await _skip_initial(client)
        data = {"enabled": True, "port": True}
        await client.send(json.dumps({"type": "save", "section": "status", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "port" in message["message"]
    assert config_path.read_text() == ""


# -- story 7: the Panel section -------------------------------------------------


#: What a legal save can contain -- every _PANEL_FIELDS key. Excludes
#: pitch_mm: it's a real PanelConfig field (so it shows up in the payload
#: the server sends), but not one _PANEL_FIELDS validates, same as
#: status_server.py's own form never exposing it either (informational
#: only, the driver never reads it).
_DEFAULT_PANEL_SAVE_DATA = {
    "rows": 32,
    "cols": 64,
    "chain_length": 2,
    "parallel": 1,
    "hardware_mapping": "regular",
    "rgb_sequence": "RGB",
    "gpio_slowdown": 4,
    "pwm_bits": 11,
    "pwm_lsb_nanoseconds": 130,
    "brightness": 60,
    "limit_refresh_rate_hz": 0,
    "disable_hardware_pulsing": False,
    "pixel_mapper": "",
    "auto_brightness": False,
    "min_brightness": 10,
    "max_brightness": 100,
    "brightness_poll_seconds": 5.0,
}


def test_sends_the_current_panel_config_on_connect(app_dir, config_path):
    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        await client.recv()  # status
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "panel",
        "data": {**_DEFAULT_PANEL_SAVE_DATA, "pitch_mm": 2.5},
    }


def test_panel_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    new_values = {**_DEFAULT_PANEL_SAVE_DATA, "brightness": 80, "hardware_mapping": "adafruit-hat"}

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "panel", "data": new_values}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "panel"}
    fresh_data = json.loads(fresh)["data"]
    assert fresh_data["brightness"] == 80
    assert fresh_data["hardware_mapping"] == "adafruit-hat"
    assert 'hardware_mapping = "adafruit-hat"' in config_path.read_text()


def test_panel_save_rejects_an_unknown_field_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_PANEL_SAVE_DATA, "pitch_mm": 3.0}
        await client.send(json.dumps({"type": "save", "section": "panel", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "pitch_mm" in message["message"]
    assert config_path.read_text() == ""


def test_panel_save_rejects_the_wrong_type(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_PANEL_SAVE_DATA, "rows": "not an int"}
        await client.send(json.dumps({"type": "save", "section": "panel", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "rows" in message["message"]
    assert config_path.read_text() == ""


def test_panel_save_rejects_an_invalid_hardware_mapping(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_PANEL_SAVE_DATA, "hardware_mapping": "bogus-mapping"}
        await client.send(json.dumps({"type": "save", "section": "panel", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "hardware_mapping" in message["message"]
    assert config_path.read_text() == ""


def test_panel_save_rejects_an_invalid_rgb_sequence(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_PANEL_SAVE_DATA, "rgb_sequence": "XYZ"}
        await client.send(json.dumps({"type": "save", "section": "panel", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "rgb_sequence" in message["message"]
    assert config_path.read_text() == ""


def test_panel_save_rejects_a_non_object_payload(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "panel", "data": [1, 2]}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


# -- story 8: the Night mode section ---------------------------------------------


_DEFAULT_NIGHT_MODE_DATA = {
    "enabled": False,
    "start_time": "22:30",
    "end_time": "07:00",
    "dim_brightness": 0,
    "suppress_scope": "tracked",
    "cooldown_minutes": 15.0,
}


def test_sends_the_current_night_mode_config_on_connect(app_dir, config_path):
    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        await client.recv()  # status
        await client.recv()  # panel
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "night_mode",
        "data": _DEFAULT_NIGHT_MODE_DATA,
    }


def test_night_mode_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    new_values = {**_DEFAULT_NIGHT_MODE_DATA, "enabled": True, "suppress_scope": "all"}

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "night_mode", "data": new_values}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "night_mode"}
    fresh_data = json.loads(fresh)["data"]
    assert fresh_data["enabled"] is True
    assert fresh_data["suppress_scope"] == "all"
    assert "enabled = true" in config_path.read_text()


def test_night_mode_save_rejects_an_unknown_field_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_NIGHT_MODE_DATA, "bogus": "x"}
        await client.send(json.dumps({"type": "save", "section": "night_mode", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "bogus" in message["message"]
    assert config_path.read_text() == ""


def test_night_mode_save_rejects_the_wrong_type(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_NIGHT_MODE_DATA, "dim_brightness": "not an int"}
        await client.send(json.dumps({"type": "save", "section": "night_mode", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "dim_brightness" in message["message"]
    assert config_path.read_text() == ""


def test_night_mode_save_rejects_an_invalid_suppress_scope(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {**_DEFAULT_NIGHT_MODE_DATA, "suppress_scope": "bogus-scope"}
        await client.send(json.dumps({"type": "save", "section": "night_mode", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "suppress_scope" in message["message"]
    assert config_path.read_text() == ""


def test_night_mode_save_rejects_a_non_object_payload(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "night_mode", "data": [1, 2]}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


# -- story 9: the Wi-Fi section -----------------------------------------------


def test_sends_the_current_wifi_config_on_connect(app_dir, config_path):
    async def scenario(client):
        await client.recv()  # version
        await client.recv()  # audio
        await client.recv()  # scoreboard
        await client.recv()  # status
        await client.recv()  # panel
        await client.recv()  # night_mode
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "config",
        "section": "wifi",
        "data": {"connect_timeout_seconds": 90.0},
    }


def test_wifi_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"connect_timeout_seconds": 45}
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": data}))
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "wifi"}
    assert json.loads(fresh) == {
        "type": "config",
        "section": "wifi",
        "data": {"connect_timeout_seconds": 45.0},
    }
    assert "connect_timeout_seconds = 45" in config_path.read_text()


def test_wifi_save_does_not_disturb_ssid_or_password_in_the_file(app_dir, config_path):
    """ssid/password/country aren't modelled by _WIFI_FIELDS at all -- a
    save must only ever touch connect_timeout_seconds, never clobber the
    other keys in the same [wifi] table (config.py's Settings.save()
    patches individual keys, not the whole table, but this is the one
    section where accidentally doing the latter would be dangerous)."""
    config_path.write_text('[wifi]\nssid = "MyNetwork"\npassword = "hunter2"\n')

    async def scenario(client):
        await _skip_initial(client)
        data = {"connect_timeout_seconds": 30}
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": data}))
        return await client.recv(), await client.recv()

    asyncio.run(_serve_and_run(scenario))
    text = config_path.read_text()
    assert 'ssid = "MyNetwork"' in text
    assert 'password = "hunter2"' in text
    assert "connect_timeout_seconds = 30" in text


def test_wifi_save_rejects_an_unknown_field_without_writing_the_file(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"connect_timeout_seconds": 90, "ssid": "MyNetwork"}
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "ssid" in message["message"]
    assert config_path.read_text() == ""


def test_wifi_save_rejects_the_wrong_type(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        data = {"connect_timeout_seconds": "not a number"}
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": data}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "connect_timeout_seconds" in message["message"]
    assert config_path.read_text() == ""


def test_wifi_save_rejects_a_non_object_payload(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": [1, 2]}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received)["type"] == "error"


# -- story 10: static file serving, the snapshot message, AdminServer -------


def test_static_get_serves_index_html(admin_dir):
    status, headers, body = asyncio.run(_serve_and_get("/"))
    assert status == 200
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    assert body == b"<!doctype html><title>admin</title>"


def test_static_get_serves_a_real_asset_with_its_content_type(admin_dir):
    status, headers, body = asyncio.run(_serve_and_get("/app.js"))
    assert status == 200
    assert headers["Content-Type"] == "text/javascript; charset=utf-8"
    assert body == b"console.log('hi')"


def test_static_get_falls_back_to_index_html_for_an_unknown_path(admin_dir):
    """A single-page app with one real route -- any other path (a client-
    side route, or just a typo) gets index.html, same as any other SPA's
    server-side fallback."""
    status, _, body = asyncio.run(_serve_and_get("/some/unknown/path"))
    assert status == 200
    assert body == b"<!doctype html><title>admin</title>"


def test_static_get_rejects_path_traversal(admin_dir):
    """A request for something outside ADMIN_DIR falls back to index.html
    (not a 500, not a real file from elsewhere on disk)."""
    status, _, body = asyncio.run(_serve_and_get("/../../../../etc/passwd"))
    assert status == 200
    assert body == b"<!doctype html><title>admin</title>"


def test_websocket_upgrade_still_works_with_process_request_installed(admin_dir):
    """The same disambiguation _process_request relies on (the Upgrade
    header, not the path) -- a real WS handshake at "/" must still work
    once static-file serving is wired onto the same port."""

    async def scenario(client):
        return await client.recv()

    async def run():
        async with serve(
            admin_server._handle,
            "localhost",
            0,
            process_request=admin_server._process_request,
        ) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                return await scenario(client)

    received = asyncio.run(run())
    assert json.loads(received)["type"] == "version"


def test_sends_an_empty_snapshot_with_no_provider_configured(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client, n=10)  # everything up to but not including snapshot
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "snapshot", "data": {}}


def test_sends_the_configured_snapshot_on_connect(app_dir, config_path, monkeypatch):
    monkeypatch.setattr(admin_server, "SNAPSHOT_PROVIDER", lambda: {"scene": "game", "error": ""})

    async def scenario(client):
        await _skip_initial(client, n=10)
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "snapshot",
        "data": {"scene": "game", "error": ""},
    }


def test_watcher_broadcasts_a_changed_snapshot(app_dir, config_path, monkeypatch):
    """Same proven shape as _watch_update_state's own broadcast test --
    the actual point of story 10's snapshot section: a scene change reaches
    every connected client without anyone asking again."""
    monkeypatch.setattr(admin_server, "SNAPSHOT_POLL_SECONDS", 0.02)
    # A mutable dict the test flips directly, not a stateful iterator --
    # SNAPSHOT_PROVIDER is called from two independent places (the
    # connect-time send and the watcher's own poll loop), so an iterator
    # shared between them would race on which call consumes which value.
    state = {"scene": "preview"}
    monkeypatch.setattr(admin_server, "SNAPSHOT_PROVIDER", lambda: dict(state))

    async def scenario():
        watcher = asyncio.create_task(admin_server._watch_snapshot())
        try:
            async with serve(admin_server._handle, "localhost", 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f"ws://localhost:{port}/") as client:
                    await _skip_initial(client, n=10)  # up to but not including the first snapshot
                    first = json.loads(await client.recv())
                    state["scene"] = "game"
                    second = json.loads(await asyncio.wait_for(client.recv(), timeout=2))
                    return first, second
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher

    first, second = asyncio.run(scenario())
    assert first["data"]["scene"] == "preview"
    assert second["data"]["scene"] == "game"


def test_admin_server_class_starts_and_stops(app_dir, config_path):
    server = admin_server.AdminServer(config_path=str(config_path), port=0, host="localhost")
    server.start()
    try:
        assert server.port != 0
        with sync_connect(f"ws://localhost:{server.port}/", open_timeout=5) as ws:
            message = json.loads(ws.recv(timeout=5))
            assert message["type"] == "version"
    finally:
        server.stop()


def test_admin_server_class_sets_config_path_and_snapshot_provider(app_dir, config_path, tmp_path):
    """start() repoints the module-global CONFIG_PATH/SNAPSHOT_PROVIDER at
    this instance's own values -- the same "just assign the module global"
    convention the rest of this test file already relies on, now exercised
    through the real class instead of a fixture."""
    other_config = tmp_path / "other.toml"
    other_config.write_text('[audio]\nenabled = false\ndevice = "hw:9,0"\nhorn_dir = ""\n')
    server = admin_server.AdminServer(
        config_path=str(other_config),
        port=0,
        host="localhost",
        snapshot=lambda: {"scene": "final"},
    )
    server.start()
    try:
        with sync_connect(f"ws://localhost:{server.port}/", open_timeout=5) as ws:
            messages = [json.loads(ws.recv(timeout=5)) for _ in range(11)]
        audio = next(m for m in messages if m.get("section") == "audio")
        assert audio["data"]["device"] == "hw:9,0"
        snapshot = next(m for m in messages if m["type"] == "snapshot")
        assert snapshot["data"] == {"scene": "final"}
    finally:
        server.stop()


def test_admin_server_class_port_resolves_a_requested_port_of_zero(app_dir, config_path):
    server = admin_server.AdminServer(config_path=str(config_path), port=0, host="localhost")
    assert server.port == 0  # not started yet -- still the requested value
    server.start()
    try:
        assert server.port != 0
    finally:
        server.stop()
    assert server.port == 0  # stop() clears the resolved port


# -- goal horn upload (#193) ---------------------------------------------------


def _wav_b64(frames=100):
    import base64
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b"\x00\x00" * frames)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    path = tmp_path / "uploaded-horns"
    monkeypatch.setenv("NHL_SCOREBOARD_UPLOAD_HORN_DIR", str(path))
    return path


def _upload(team, data):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "upload_horn", "team": team, "data": data}))
        return json.loads(await client.recv())

    return asyncio.run(_serve_and_run(scenario))


def test_upload_horn_stores_team_file(app_dir, config_path, upload_dir):
    reply = _upload("NSH", _wav_b64())
    assert reply == {"type": "horn_uploaded", "name": "NSH.wav"}
    assert (upload_dir / "NSH.wav").is_file()


def test_upload_horn_default_overrides_the_shipped_one(app_dir, config_path, upload_dir):
    reply = _upload("default", _wav_b64())
    assert reply == {"type": "horn_uploaded", "name": "_default.wav"}
    from nhl_scoreboard.audio import GoalHornPlayer

    assert GoalHornPlayer.default().path_for("TOR") == upload_dir / "_default.wav"


@pytest.mark.parametrize("team", ["../evil", "XXX", "nsh", None, 5])
def test_upload_horn_rejects_unknown_team(app_dir, config_path, upload_dir, team):
    reply = _upload(team, _wav_b64())
    assert reply["type"] == "error" and reply["section"] == "horn_upload"
    assert not upload_dir.exists()


def test_upload_horn_rejects_non_wav_and_bad_base64(app_dir, config_path, upload_dir):
    import base64

    not_wav = base64.b64encode(b"definitely not audio").decode()
    assert "valid WAV or MP3" in _upload("NSH", not_wav)["message"]
    assert "base64" in _upload("NSH", "!!!")["message"]
    assert "no audio" in _upload("NSH", _wav_b64(frames=0))["message"]
    assert not upload_dir.exists()


def _mp3_b64(id3=False):
    import base64

    frame = b"\xff\xfb\x90\x00" + b"\x00" * 100
    tag = b"ID3\x03\x00\x00\x00\x00\x00\x05" + b"\x00" * 5 if id3 else b""
    return base64.b64encode(tag + frame).decode()


@pytest.mark.parametrize("id3", [False, True])
def test_upload_horn_accepts_mp3(app_dir, config_path, upload_dir, id3):
    reply = _upload("NSH", _mp3_b64(id3))
    assert reply == {"type": "horn_uploaded", "name": "NSH.mp3"}
    assert (upload_dir / "NSH.mp3").is_file()


def test_upload_horn_replaces_other_format(app_dir, config_path, upload_dir):
    _upload("NSH", _wav_b64())
    _upload("NSH", _mp3_b64())
    assert not (upload_dir / "NSH.wav").exists()
    _upload("NSH", _wav_b64())
    assert (upload_dir / "NSH.wav").is_file()
    assert not (upload_dir / "NSH.mp3").exists()


def test_upload_horn_rejects_oversize(app_dir, config_path, upload_dir, monkeypatch):
    monkeypatch.setattr(admin_server, "HORN_MAX_BYTES", 100)
    assert "too large" in _upload("NSH", _wav_b64(frames=500))["message"]
    assert not upload_dir.exists()


# -- follow-up: the "Custom goal horns" list (play/delete an upload) ----------


def test_sends_an_empty_horn_list_on_connect_with_no_uploads(app_dir, config_path, upload_dir):
    async def scenario(client):
        await _skip_initial(client, n=9)  # up to but not including horn_list
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "horn_list", "horns": []}


def test_sends_the_current_horn_list_on_connect(app_dir, config_path, upload_dir):
    upload_dir.mkdir()
    (upload_dir / "_default.mp3").write_bytes(b"x")
    (upload_dir / "NSH.wav").write_bytes(b"x")

    async def scenario(client):
        await _skip_initial(client, n=9)
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "horn_list",
        "horns": [
            {"team": "default", "filename": "_default.mp3"},
            {"team": "NSH", "filename": "NSH.wav"},
        ],
    }


def test_upload_horn_broadcasts_the_updated_list_to_the_uploading_client(
    app_dir, config_path, upload_dir
):
    """_broadcast() iterates every connected client, including whichever one
    triggered it -- so even a single connection sees its own "horn_uploaded"
    ack followed by a fresh "horn_list" push, not just the direct reply."""

    async def scenario(client):
        await _skip_initial(client, n=9)  # up to but not including horn_list
        before = json.loads(await client.recv())  # horn_list
        await client.recv()  # snapshot, the 11th and last initial message
        await client.send(json.dumps({"type": "upload_horn", "team": "NSH", "data": _wav_b64()}))
        ack = json.loads(await client.recv())
        after = json.loads(await client.recv())
        return before, ack, after

    before, ack, after = asyncio.run(_serve_and_run(scenario))
    assert before == {"type": "horn_list", "horns": []}
    assert ack == {"type": "horn_uploaded", "name": "NSH.wav"}
    assert after == {"type": "horn_list", "horns": [{"team": "NSH", "filename": "NSH.wav"}]}


def test_play_horn_plays_a_specific_teams_horn_not_just_the_favourites(
    app_dir, config_path, tmp_path, monkeypatch
):
    """The favourite is NSH, but this asks for TOR's horn specifically --
    proves play_horn answers "play this named horn", a different question
    from _test_horn's "play whatever the favourite's own horn resolves to"."""
    horn_dir = tmp_path / "horns"
    horn_dir.mkdir()
    (horn_dir / "TOR.wav").write_bytes(b"fake wav")
    (horn_dir / "_default.wav").write_bytes(b"fake wav")
    config_path.write_text(
        f'[audio]\nenabled = true\nhorn_dir = "{horn_dir}"\n[scoreboard]\nfavourite_team = "NSH"\n'
    )
    calls = []
    monkeypatch.setattr(
        admin_server.GoalHornPlayer, "_popen", staticmethod(lambda cmd: calls.append(cmd))
    )
    monkeypatch.setattr(admin_server.GoalHornPlayer, "_amixer", staticmethod(lambda cmd: True))

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": "TOR"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "horn_played",
        "team": "TOR",
        "played": True,
        "reason": "",
    }
    assert len(calls) == 1 and calls[0][-1].endswith("TOR.wav")


def test_play_horn_default_plays_the_default_stem_not_a_literal_default_file(
    app_dir, config_path, tmp_path, monkeypatch
):
    """Locks in path_for()'s own fallback behaviour (documented on
    _play_named_horn): "default" never matches a stored stem directly
    (uploads are always saved as _default.*, never DEFAULT.*), but still
    resolves to the right file via path_for()'s second-tier DEFAULT_STEM
    lookup -- this would silently start playing nothing if that fallback
    ever changed, so it's covered rather than left an accident."""
    horn_dir = tmp_path / "horns"
    horn_dir.mkdir()
    (horn_dir / "_default.wav").write_bytes(b"fake wav")
    config_path.write_text(f'[audio]\nenabled = true\nhorn_dir = "{horn_dir}"\n')
    calls = []
    monkeypatch.setattr(
        admin_server.GoalHornPlayer, "_popen", staticmethod(lambda cmd: calls.append(cmd))
    )
    monkeypatch.setattr(admin_server.GoalHornPlayer, "_amixer", staticmethod(lambda cmd: True))

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": "default"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {
        "type": "horn_played",
        "team": "default",
        "played": True,
        "reason": "",
    }
    assert len(calls) == 1 and calls[0][-1].endswith("_default.wav")


def test_play_horn_reports_not_played_when_audio_disabled(app_dir, config_path):
    config_path.write_text("[audio]\nenabled = false\n")

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": "NSH"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "horn_played"
    assert message["team"] == "NSH"
    assert message["played"] is False
    assert "disabled" in message["reason"]


def test_play_horn_reports_no_file_found_distinct_from_disabled(
    app_dir, config_path, tmp_path, monkeypatch
):
    """#213's own follow-up: a single generic "check Audio is enabled"
    message couldn't tell a disabled board apart from a missing file --
    this is the "enabled=true but genuinely nothing to play" case, which
    must say something different from the disabled case above. horn_dir
    alone isn't enough to isolate this: default_directories() always also
    searches upload_directory() and the repo's own committed
    assets/horns/ (where the real shipped _default.wav lives, and where a
    developer's own git-ignored drop-in horn can sit too) as further
    fallbacks, so default_directories() itself has to be replaced to
    guarantee nothing anywhere resolves."""
    from nhl_scoreboard import audio as audio_module

    empty_dir = tmp_path / "truly-empty"
    monkeypatch.setattr(audio_module, "default_directories", lambda override="": [empty_dir])
    config_path.write_text("[audio]\nenabled = true\n")

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": "NSH"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["played"] is False
    assert "No horn file found" in message["reason"]
    assert "disabled" not in message["reason"]


def test_play_horn_reports_launch_failure_distinct_from_disabled_and_missing(
    app_dir, config_path, tmp_path, monkeypatch
):
    """The third collapsed-to-False case: enabled, a file genuinely
    exists, but the player subprocess itself couldn't launch (this
    project's own dev sandbox hit exactly this -- no aplay/mpg123 on
    PATH -- while verifying #213 live)."""
    horn_dir = tmp_path / "horns"
    horn_dir.mkdir()
    (horn_dir / "NSH.wav").write_bytes(b"fake wav")
    config_path.write_text(f'[audio]\nenabled = true\nhorn_dir = "{horn_dir}"\n')
    monkeypatch.setattr(admin_server.GoalHornPlayer, "_amixer", staticmethod(lambda cmd: True))

    def _raise(cmd):
        raise OSError("aplay not found")

    monkeypatch.setattr(admin_server.GoalHornPlayer, "_popen", staticmethod(_raise))

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": "NSH"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["played"] is False
    assert "player command" in message["reason"]
    assert "disabled" not in message["reason"] and "No horn file" not in message["reason"]


@pytest.mark.parametrize("team", ["../evil", "XXX", "nsh", None, 5])
def test_play_horn_rejects_unknown_team(app_dir, config_path, team):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "play_horn", "team": team}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error" and message["section"] == "horn_action"


def test_delete_horn_removes_the_file_and_broadcasts_the_updated_list(
    app_dir, config_path, upload_dir
):
    _upload("NSH", _wav_b64())

    async def scenario(client):
        await _skip_initial(client, n=9)  # up to but not including horn_list
        before = json.loads(await client.recv())  # horn_list
        await client.recv()  # snapshot, the 11th and last initial message
        await client.send(json.dumps({"type": "delete_horn", "team": "NSH"}))
        ack = json.loads(await client.recv())
        after = json.loads(await client.recv())
        return before, ack, after

    before, ack, after = asyncio.run(_serve_and_run(scenario))
    assert before == {"type": "horn_list", "horns": [{"team": "NSH", "filename": "NSH.wav"}]}
    assert ack == {"type": "horn_deleted", "team": "NSH"}
    assert after == {"type": "horn_list", "horns": []}
    assert not (upload_dir / "NSH.wav").exists()


def test_delete_horn_reverts_playback_to_the_shipped_default(app_dir, config_path, upload_dir):
    """Same verification style as test_upload_horn_default_overrides_the_shipped_one
    -- proves Delete isn't just "remove a file", it actually changes what a
    real goal would play next, by reading path_for() through GoalHornPlayer."""
    _upload("default", _wav_b64())
    from nhl_scoreboard.audio import GoalHornPlayer

    assert GoalHornPlayer.default().path_for("TOR") == upload_dir / "_default.wav"

    async def scenario(client):
        await _skip_initial(client, n=9)  # up to but not including horn_list
        await client.recv()  # the list with the override still present
        await client.recv()  # snapshot, the 11th and last initial message
        await client.send(json.dumps({"type": "delete_horn", "team": "default"}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert json.loads(received) == {"type": "horn_deleted", "team": "default"}
    assert GoalHornPlayer.default().path_for("TOR") != upload_dir / "_default.wav"


@pytest.mark.parametrize("team", ["../evil", "XXX", "nsh", None, 5])
def test_delete_horn_rejects_unknown_team(app_dir, config_path, upload_dir, team):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "delete_horn", "team": team}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error" and message["section"] == "horn_action"


def test_demo_mode_message_calls_setter_and_broadcasts_snapshot(app_dir, config_path, monkeypatch):
    seen = []
    state = {"demo mode": "off"}

    def setter(enabled):
        seen.append(enabled)
        state["demo mode"] = "on" if enabled else "off"

    monkeypatch.setattr(admin_server, "DEMO_SETTER", setter)
    monkeypatch.setattr(admin_server, "SNAPSHOT_PROVIDER", lambda: dict(state))

    async def scenario(client):
        await _skip_initial(client, n=11)
        await client.send(json.dumps({"type": "demo_mode", "enabled": True}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    assert seen == [True]
    assert json.loads(received) == {"type": "snapshot", "data": {"demo mode": "on"}}


def test_demo_mode_message_rejects_non_boolean_and_missing_app(app_dir, config_path, monkeypatch):
    monkeypatch.setattr(admin_server, "DEMO_SETTER", None)

    async def scenario(client):
        await _skip_initial(client, n=11)
        await client.send(json.dumps({"type": "demo_mode", "enabled": "yes"}))
        first = await client.recv()
        await client.send(json.dumps({"type": "demo_mode", "enabled": True}))
        return first, await client.recv()

    first, second = asyncio.run(_serve_and_run(scenario))
    assert json.loads(first)["type"] == "error"
    assert json.loads(second)["type"] == "error"
