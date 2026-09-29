"""nhl_scoreboard.ws_server (#178): real app state flows across a real
WebSocket connection, in both directions.

Plain `asyncio.run()` inside ordinary test functions rather than adding
pytest-asyncio as a new dev dependency -- this is the only async code in the
project so far, and a handful of self-contained tests don't need a plugin
for that.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nhl_scoreboard import updater, ws_server


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "scoreboard.toml"
    path.write_text("")
    monkeypatch.setattr(ws_server, "CONFIG_PATH", str(path))
    return path


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    path = tmp_path / "update-state.json"
    monkeypatch.setattr(updater, "STATE_FILE", path)
    return path


@pytest.fixture
def fake_systemctl(monkeypatch):
    calls = []
    monkeypatch.setattr(ws_server.subprocess, "run", lambda *args, **kwargs: calls.append(args[0]))
    return calls


async def _serve_and_run(scenario):
    async with serve(ws_server._handle, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://localhost:{port}/") as client:
            return await scenario(client)


async def _skip_initial(client, n=5):
    """Drain the version/audio/scoreboard/rotation/update messages every
    connection opens with."""
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
        "data": {"enabled": False, "device": "hw:1,0", "horn_dir": ""},
    }


def test_save_writes_the_file_and_confirms_with_fresh_config(app_dir, config_path):
    async def scenario(client):
        await _skip_initial(client)
        await client.send(
            json.dumps(
                {
                    "type": "save",
                    "section": "audio",
                    "data": {"enabled": False, "device": "hw:1,0", "horn_dir": ""},
                }
            )
        )
        return await client.recv(), await client.recv()

    saved, fresh = asyncio.run(_serve_and_run(scenario))
    assert json.loads(saved) == {"type": "saved", "section": "audio"}
    assert json.loads(fresh) == {
        "type": "config",
        "section": "audio",
        "data": {"enabled": False, "device": "hw:1,0", "horn_dir": ""},
    }
    assert 'device = "hw:1,0"' in config_path.read_text()


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
        await client.send(json.dumps({"type": "save", "section": "wifi", "data": {}}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert "wifi" in message["message"]


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
    rows = [{"screen": "clock", "seconds": 5}] * (ws_server.ROTATION_MAX_ROWS + 1)

    async def scenario(client):
        await _skip_initial(client)
        await client.send(json.dumps({"type": "save", "section": "rotation", "data": rows}))
        return await client.recv()

    received = asyncio.run(_serve_and_run(scenario))
    message = json.loads(received)
    assert message["type"] == "error"
    assert str(ws_server.ROTATION_MAX_ROWS) in message["message"]
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


def test_watcher_broadcasts_when_the_update_state_file_changes(
    app_dir, config_path, state_file, monkeypatch
):
    """The actual point of story 4: a check/apply happening out of process
    (a real board would run it via systemd, not this call) still reaches
    every connected client without anyone asking again."""
    monkeypatch.setattr(ws_server, "UPDATE_POLL_SECONDS", 0.02)

    async def scenario():
        watcher = asyncio.create_task(ws_server._watch_update_state())
        try:
            async with serve(ws_server._handle, "localhost", 0) as server:
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
    monkeypatch.setattr(ws_server, "UPDATE_POLL_SECONDS", 0.02)

    async def scenario():
        watcher = asyncio.create_task(ws_server._watch_update_state())
        try:
            async with serve(ws_server._handle, "localhost", 0) as server:
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
    new_values = {**_DEFAULT_SCOREBOARD_DATA, "favourite_team": "TOR", "show_logos": False}

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
        data = {**_DEFAULT_SCOREBOARD_DATA, "bogus": "x"}
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
        data = {**_DEFAULT_SCOREBOARD_DATA, "rotate_seconds": "not a number"}
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
        data = {**_DEFAULT_SCOREBOARD_DATA, "logo_variant": "purple"}
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
