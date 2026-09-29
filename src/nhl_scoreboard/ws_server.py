"""Admin page WebSocket server (#178).

Scope, deliberately narrow -- built as vertical slices, not the finished
thing:

* Local-dev only. Not started by ``ScoreboardApp``, not wired into
  ``image/layer/nhl-scoreboard.yaml`` or any systemd unit -- run it by hand
  (``python -m nhl_scoreboard.ws_server``) alongside the React dev server.
  Deploying this to the real board is a later story (#178 was explicit that
  story 1 shouldn't decide that yet).
* Story 1: prove the pipeline. On connect, sends the installed version once
  (the same value the admin page's status grid already shows, via
  ``updater.installed_version()``).
* Story 2: the first real config section, Audio (``enabled``/``device``/
  ``horn_dir`` -- the smallest section, chosen to prove the read/edit/save
  round trip before a bigger one). Also sends the current ``[audio]``
  values on connect, and handles a ``save`` message the same way
  ``status_server.py``'s ``/save`` POST does: write into a throwaway
  ``Settings`` instance (never the live app's, which this process doesn't
  even have -- it always loads fresh from disk), never mutate anything in
  memory. Deliberately hardcoded to Audio's own 3 fields rather than
  generalised over every section the way ``status_server.py``'s
  ``_Field``/``_coerce_section`` machinery is -- one section isn't enough
  evidence yet for what the right shared shape is; that generalisation is
  a later story's job once a second section shows the actual pattern.

No auth, same trust model as ``status_server.py`` (a LAN-only admin tool).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os

import websockets
from websockets.asyncio.server import ServerConnection, serve

from .config import AudioConfig, ConfigWriteError, Settings
from .updater import installed_version

log = logging.getLogger(__name__)

#: Overridable so a second instance (or a test) doesn't collide with one
#: already running locally -- same convention as StatusServer's port.
HOST = os.environ.get("NHL_SCOREBOARD_WS_HOST", "localhost")
PORT = int(os.environ.get("NHL_SCOREBOARD_WS_PORT", "8765"))
#: scoreboard.toml to read/write. Defaults to the same git-ignored dev
#: config every other local-dev command uses (`nhl-scoreboard -c
#: scoreboard.local.toml`); DEFAULT_CONFIG_PATHS (config.py) are real
#: device-only paths that don't exist on a dev machine.
CONFIG_PATH = os.environ.get("NHL_SCOREBOARD_CONFIG", "scoreboard.local.toml")


def _audio_payload(settings: Settings) -> dict[str, object]:
    return {"type": "config", "section": "audio", "data": dataclasses.asdict(settings.audio)}


async def _send_version(connection: ServerConnection) -> None:
    value = installed_version() or "unknown (factory image)"
    await connection.send(json.dumps({"type": "version", "value": value}))


async def _send_audio_config(connection: ServerConnection) -> None:
    settings = Settings.load(CONFIG_PATH)
    await connection.send(json.dumps(_audio_payload(settings)))


def _coerce_audio(data: dict[str, object]) -> dict[str, object]:
    """Validate an incoming save's ``data`` against AudioConfig's own field
    types. JSON already carries real types (unlike an HTML form's fields,
    which are always strings) -- there's no `bool("false") == True` trap to
    guard against here the way status_server.py's _coerce_section has to.
    """
    errors: dict[str, str] = {}
    known = {f.name for f in dataclasses.fields(AudioConfig)}
    for key in data:
        if key not in known:
            errors[key] = f"unknown field {key!r}"
    if "enabled" in data and not isinstance(data["enabled"], bool):
        errors["enabled"] = "must be a boolean"
    for key in ("device", "horn_dir"):
        if key in data and not isinstance(data[key], str):
            errors[key] = "must be a string"
    if errors:
        raise ValueError(json.dumps(errors))
    return data


async def _handle_save(connection: ServerConnection, message: dict[str, object]) -> None:
    section = message.get("section")
    if section != "audio":
        error = {"type": "error", "message": f"unknown section {section!r}"}
        await connection.send(json.dumps(error))
        return
    try:
        values = _coerce_audio(message.get("data") or {})
        Settings.load(CONFIG_PATH).save({"audio": values})
    except (ValueError, ConfigWriteError) as exc:
        error = {"type": "error", "section": "audio", "message": str(exc)}
        await connection.send(json.dumps(error))
        return
    await connection.send(json.dumps({"type": "saved", "section": "audio"}))
    await _send_audio_config(connection)  # fresh from disk, same discipline as status_server.py


async def _handle(connection: ServerConnection) -> None:
    await _send_version(connection)
    await _send_audio_config(connection)
    log.info("Sent initial state to %s", connection.remote_address)
    async for raw in connection:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            await connection.send(json.dumps({"type": "error", "message": "invalid JSON"}))
            continue
        if message.get("type") == "save":
            await _handle_save(connection, message)
        else:
            await connection.send(json.dumps({"type": "error", "message": "unknown message type"}))


async def run(host: str = HOST, port: int = PORT) -> None:
    async with serve(_handle, host, port) as server:
        log.info("Admin WebSocket server listening on ws://%s:%d/", host, port)
        await server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log.info("websockets %s", websockets.__version__)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run())


if __name__ == "__main__":
    main()
