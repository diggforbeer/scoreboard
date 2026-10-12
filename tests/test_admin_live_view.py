"""admin_server's live view (#268): opt-in frame streaming over the WebSocket.

The render thread's half is in test_mirror.py; here a Mirror is published
to by hand, the way ScoreboardApp.swap_canvas() would.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nhl_scoreboard import admin_server, updater
from nhl_scoreboard.display.mirror import Mirror


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = tmp_path / "scoreboard.toml"
    config.write_text("")
    monkeypatch.setattr(admin_server, "CONFIG_PATH", str(config))
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "update-state.json")
    monkeypatch.setattr(admin_server, "FRAME_POLL_SECONDS", 0.02)
    monkeypatch.setattr(admin_server, "_frame_subscribers", set())
    monkeypatch.setattr(admin_server, "_last_frame_sent", None)


@pytest.fixture
def mirror(monkeypatch):
    mirror = Mirror(4, 2)
    monkeypatch.setattr(admin_server, "MIRROR", mirror)
    return mirror


async def _drain_initial(client, n=12):
    for _ in range(n):
        await client.recv()


async def _run(scenario):
    watcher = asyncio.create_task(admin_server._watch_frames())
    try:
        async with serve(admin_server._handle, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                await _drain_initial(client)
                return await scenario(client, port)
    finally:
        watcher.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher


async def _recv(client, timeout=2):
    return json.loads(await asyncio.wait_for(client.recv(), timeout=timeout))


def _subscribe(client):
    return client.send(json.dumps({"type": "frame_subscribe"}))


def test_subscribing_turns_recording_on_and_streams_frames(mirror):
    async def scenario(client, port):
        assert not mirror.active
        await _subscribe(client)
        await asyncio.sleep(0.05)
        assert mirror.active
        mirror.set_pixel(1, 0, 255, 0, 0)
        mirror.publish(brightness=60)
        return await _recv(client)

    message = asyncio.run(_run(scenario))
    assert message["type"] == "frame"
    assert (message["width"], message["height"], message["brightness"]) == (4, 2, 60)
    pixels = base64.b64decode(message["data"])
    assert len(pixels) == 4 * 2 * 3
    assert pixels[3:6] == bytes((255, 0, 0))


def test_an_unchanged_frame_is_not_sent_twice(mirror):
    async def scenario(client, port):
        await _subscribe(client)
        mirror.publish(brightness=100)
        await _recv(client)
        mirror.publish(brightness=100)  # same pixels, next frame
        with pytest.raises(TimeoutError):
            await _recv(client, timeout=0.2)
        mirror.set_pixel(0, 0, 1, 1, 1)
        mirror.publish(brightness=100)
        return await _recv(client)

    assert asyncio.run(_run(scenario))["type"] == "frame"


def test_a_late_viewer_gets_the_current_frame_at_once(mirror):
    async def scenario(first, port):
        await _subscribe(first)
        mirror.publish(brightness=100)
        await _recv(first)
        async with connect(f"ws://localhost:{port}/") as second:
            await _drain_initial(second)
            await _subscribe(second)
            return await _recv(second)

    assert asyncio.run(_run(scenario))["type"] == "frame"


def test_nothing_streams_without_subscribing(mirror):
    async def scenario(client, port):
        mirror.publish(brightness=100)
        with pytest.raises(TimeoutError):
            await _recv(client, timeout=0.2)

    asyncio.run(_run(scenario))
    assert not mirror.active


def test_recording_stops_when_the_last_viewer_leaves(mirror):
    async def scenario(first, port):
        async with connect(f"ws://localhost:{port}/") as second:
            await _drain_initial(second)
            await _subscribe(first)
            await _subscribe(second)
            await asyncio.sleep(0.05)
            await first.send(json.dumps({"type": "frame_unsubscribe"}))
            await asyncio.sleep(0.05)
            assert mirror.active, "the second viewer is still watching"
        # second disconnected without unsubscribing
        await asyncio.sleep(0.1)
        return mirror.active

    assert asyncio.run(_run(scenario)) is False


def test_no_live_app_says_so():
    async def scenario(client, port):
        await _subscribe(client)
        return await _recv(client)

    message = asyncio.run(_run(scenario))
    assert message == {
        "type": "error",
        "section": "live_view",
        "message": "no live panel to mirror",
    }
