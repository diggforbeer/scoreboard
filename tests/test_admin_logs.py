"""admin_server's Logs tab (#197): opt-in journal streaming over the
WebSocket, one shared `journalctl -f` follower, backlog then live lines.

journalctl is replaced by a small fake script (`fake_journalctl`) so this
stays hermetic, like the rest of the suite.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from nhl_scoreboard import admin_server, updater


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    config = tmp_path / "scoreboard.toml"
    config.write_text("")
    monkeypatch.setattr(admin_server, "CONFIG_PATH", str(config))
    monkeypatch.setattr(updater, "APP_DIR", tmp_path)
    monkeypatch.setattr(updater, "STATE_FILE", tmp_path / "update-state.json")


def _journal_json(n, message, priority=6):
    return json.dumps(
        {
            "__CURSOR": f"c{n}",
            "__REALTIME_TIMESTAMP": str(1_700_000_000_000_000 + n * 1000),
            "PRIORITY": str(priority),
            "MESSAGE": message,
        }
    )


@pytest.fixture
def fake_journalctl(tmp_path, monkeypatch):
    """Prints two backlog lines for a plain read; for `-f` records its pid,
    prints one new line, then blocks like a real follower."""
    script = tmp_path / "journalctl"
    pids = tmp_path / "pids"
    backlog = [
        _journal_json(1, "2026-09-30 10:00:00,000 INFO    nhl_scoreboard.app: started"),
        _journal_json(2, "2026-09-30 10:00:01,000 ERROR   nhl_scoreboard.nhl: boom"),
    ]
    live = _journal_json(3, "2026-09-30 10:00:02,000 WARNING nhl_scoreboard.app: live")
    lines = [
        "#!/usr/bin/env python3",
        "import os, sys, time",
        "if '-f' in sys.argv:",
        f"    open({str(pids)!r}, 'a').write(str(os.getpid()) + '\\n')",
        f"    print({live!r}, flush=True)",
        "    time.sleep(60)",
        "else:",
        *[f"    print({line!r})" for line in backlog],
    ]
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    monkeypatch.setattr(admin_server, "JOURNAL_COMMAND", [str(script)])
    return pids


async def _drain_initial(client, n=11):
    for _ in range(n):
        await client.recv()


async def _run(scenario):
    async with serve(admin_server._handle, "localhost", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f"ws://localhost:{port}/") as client:
            await _drain_initial(client)
            try:
                return await scenario(client, port)
            finally:
                await admin_server._stop_log_follower()


def _subscribe(client):
    return client.send(json.dumps({"type": "logs_subscribe"}))


def test_parse_reads_the_level_from_the_logging_format():
    entry = admin_server._parse_journal_line(_journal_json(1, "2026-09-30 10:00:00,0 ERROR x: y"))
    assert entry == {
        "cursor": "c1",
        "t": 1_700_000_000_001,
        "level": 3,
        "msg": "2026-09-30 10:00:00,0 ERROR x: y",
    }
    assert admin_server._parse_journal_line(_journal_json(2, "Started.", 5))["level"] == 5


def test_parse_handles_byte_array_messages_and_garbage():
    raw = json.dumps({"__REALTIME_TIMESTAMP": "1000", "MESSAGE": list(b"hi \xff")})
    assert admin_server._parse_journal_line(raw)["msg"].startswith("hi ")
    assert admin_server._parse_journal_line("not json") is None
    assert admin_server._parse_journal_line("{}") is None


def test_subscribe_sends_backlog_then_live_lines(fake_journalctl):
    async def scenario(client, port):
        await _subscribe(client)
        messages = []
        while sum(len(m["entries"]) for m in messages) < 3:
            messages.append(json.loads(await asyncio.wait_for(client.recv(), timeout=5)))
        return messages

    messages = asyncio.run(_run(scenario))
    assert all(m["type"] == "logs" for m in messages)
    backlog = next(m for m in messages if m.get("backlog"))
    live = next(m for m in messages if not m.get("backlog"))
    assert [e["cursor"] for e in backlog["entries"]] == ["c1", "c2"]
    assert [e["level"] for e in backlog["entries"]] == [6, 3]
    assert live["entries"][0]["level"] == 4


def test_nothing_streams_without_subscribing(fake_journalctl):
    async def scenario(client, port):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(client.recv(), timeout=0.5)
        return admin_server._log_task

    assert asyncio.run(_run(scenario)) is None
    assert not fake_journalctl.exists()


def test_one_shared_follower_stopped_when_the_last_subscriber_leaves(fake_journalctl):
    async def scenario(first, port):
        async with connect(f"ws://localhost:{port}/") as second:
            await _drain_initial(second)
            for client in (first, second):
                await _subscribe(client)
                await client.recv()  # backlog
            await asyncio.sleep(0.5)
            started = len(fake_journalctl.read_text().split())
            await first.send(json.dumps({"type": "logs_unsubscribe"}))
            await asyncio.sleep(0.2)
            still_running = admin_server._log_task is not None
            await second.send(json.dumps({"type": "logs_unsubscribe"}))
            await asyncio.sleep(0.2)
            return started, still_running, admin_server._log_task

    started, still_running, after = asyncio.run(_run(scenario))
    assert started == 1
    assert still_running
    assert after is None


def test_follower_stops_when_a_subscriber_disconnects(fake_journalctl):
    async def scenario(client, port):
        await _subscribe(client)
        await client.recv()
        await client.close()
        await asyncio.sleep(0.5)
        return admin_server._log_task, set(admin_server._log_subscribers)

    task, subscribers = asyncio.run(_run(scenario))
    assert task is None
    assert not subscribers


def test_missing_journalctl_reports_an_error(monkeypatch):
    monkeypatch.setattr(admin_server, "JOURNAL_COMMAND", ["/nonexistent/journalctl"])

    async def scenario(client, port):
        await _subscribe(client)
        return [json.loads(await asyncio.wait_for(client.recv(), timeout=5)) for _ in range(2)]

    seen = asyncio.run(_run(scenario))
    assert {"type": "logs", "backlog": True, "entries": []} in seen
    assert any(m["type"] == "error" and m["section"] == "logs" for m in seen)
