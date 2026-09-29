"""nhl_scoreboard.ws_server: story 1 of #178 -- one real piece of app state
(the installed version) flows from a Python WebSocket server to a client.

Plain `asyncio.run()` inside an ordinary test function rather than adding
pytest-asyncio as a new dev dependency -- this is the only async code in the
project so far, and a single self-contained test doesn't need a plugin for
that.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nhl_scoreboard import updater, ws_server


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    return tmp_path


def test_sends_the_installed_version_on_connect(app_dir):
    (app_dir / "VERSION").write_text("v2026.09.29.4\n")

    async def scenario() -> str:
        async with serve(ws_server._handle, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                return await client.recv()

    received = asyncio.run(scenario())
    assert json.loads(received) == {"version": "v2026.09.29.4"}


def test_falls_back_to_unknown_with_no_version_file(app_dir):
    async def scenario() -> str:
        async with serve(ws_server._handle, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                return await client.recv()

    received = asyncio.run(scenario())
    assert json.loads(received) == {"version": "unknown (factory image)"}


def test_connection_stays_open_after_the_one_message(app_dir):
    """Story 1's whole point vs. a one-shot HTTP response: the socket is
    still open afterward, ready for a later story to push more on it."""

    async def scenario() -> bool:
        async with serve(ws_server._handle, "localhost", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://localhost:{port}/") as client:
                await client.recv()
                # No second message is sent; a closed connection would raise
                # ConnectionClosed here instead of timing out waiting.
                with pytest.raises(TimeoutError):
                    await asyncio.wait_for(client.recv(), timeout=0.2)
                return client.state.name == "OPEN"

    assert asyncio.run(scenario())
