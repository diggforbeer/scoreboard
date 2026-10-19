"""admin_server's live view (#268): opt-in snapshots over the WebSocket.

The render thread's half (when to snapshot) is in test_mirror.py; here a
Mirror is published to by hand, the way ScoreboardApp.swap_canvas() would.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from datetime import UTC, datetime

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
    monkeypatch.setattr(admin_server, "_last_frame_sent", 0)


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


async def _subscribe(client):
    await client.send(json.dumps({"type": "frame_subscribe"}))
    await asyncio.sleep(0.05)  # let the server handle it before publishing


def _publish(mirror, brightness=100, pixel=None):
    mirror.clear()
    if pixel is not None:
        mirror.set_pixel(*pixel)
    mirror.publish(brightness, datetime(2026, 10, 12, 19, 30, tzinfo=UTC))


def test_subscribing_asks_for_a_snapshot_and_sends_it(mirror):
    async def scenario(client, port):
        assert not mirror.watching
        await _subscribe(client)
        await asyncio.sleep(0.05)
        assert mirror.watching and mirror.requested
        _publish(mirror, 60, (1, 0, 255, 0, 0))
        return await _recv(client)

    message = asyncio.run(_run(scenario))
    assert message["type"] == "frame"
    assert (message["width"], message["height"], message["brightness"]) == (4, 2, 60)
    assert message["captured_at"] == "2026-10-12T19:30:00+00:00"
    pixels = base64.b64decode(message["data"])
    assert len(pixels) == 4 * 2 * 3
    assert pixels[3:6] == bytes((255, 0, 0))


def test_each_new_snapshot_is_sent_once(mirror):
    async def scenario(client, port):
        await _subscribe(client)
        _publish(mirror)
        await _recv(client)
        with pytest.raises(TimeoutError):
            await _recv(client, timeout=0.2)
        _publish(mirror)  # a new snapshot, even of the same pixels (Refresh)
        return await _recv(client)

    assert asyncio.run(_run(scenario))["type"] == "frame"


def test_a_stale_snapshot_is_never_sent_to_a_first_viewer(mirror):
    _publish(mirror, pixel=(0, 0, 9, 9, 9))  # from an earlier viewing

    async def scenario(client, port):
        await _subscribe(client)
        with pytest.raises(TimeoutError):
            await _recv(client, timeout=0.2)
        return mirror.requested

    assert asyncio.run(_run(scenario)) is True


def test_a_late_viewer_gets_the_current_snapshot_at_once(mirror):
    async def scenario(first, port):
        await _subscribe(first)
        _publish(mirror)
        await _recv(first)
        mirror.requested = False
        async with connect(f"ws://localhost:{port}/") as second:
            await _drain_initial(second)
            await _subscribe(second)
            return await _recv(second), mirror.requested

    message, requested = asyncio.run(_run(scenario))
    assert message["type"] == "frame"
    assert not requested, "the current snapshot is enough; no new one needed"


def test_refresh_asks_for_a_snapshot(mirror):
    async def scenario(client, port):
        await _subscribe(client)
        _publish(mirror)
        await _recv(client)
        mirror.requested = False
        await client.send(json.dumps({"type": "frame_refresh"}))
        await asyncio.sleep(0.05)
        return mirror.requested

    assert asyncio.run(_run(scenario)) is True


def test_nothing_is_sent_without_subscribing(mirror):
    async def scenario(client, port):
        _publish(mirror)
        with pytest.raises(TimeoutError):
            await _recv(client, timeout=0.2)

    asyncio.run(_run(scenario))
    assert not mirror.watching


def test_watching_stops_when_the_last_viewer_leaves(mirror):
    async def scenario(first, port):
        async with connect(f"ws://localhost:{port}/") as second:
            await _drain_initial(second)
            await _subscribe(first)
            await _subscribe(second)
            await asyncio.sleep(0.05)
            await first.send(json.dumps({"type": "frame_unsubscribe"}))
            await asyncio.sleep(0.05)
            assert mirror.watching, "the second viewer is still watching"
        # second disconnected without unsubscribing
        await asyncio.sleep(0.1)
        return mirror.watching

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
