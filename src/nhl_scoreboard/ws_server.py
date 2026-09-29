"""Admin page WebSocket server (#178), story 1: prove the pipeline end to end.

Scope, deliberately narrow -- this is the first of several planned stories,
not the finished thing:

* Local-dev only. Not started by ``ScoreboardApp``, not wired into
  ``image/layer/nhl-scoreboard.yaml`` or any systemd unit -- run it by hand
  (``python -m nhl_scoreboard.ws_server``) alongside the React dev server.
  Deploying this to the real board is a later story (#178 was explicit that
  story 1 shouldn't decide that yet).
* One piece of data. On connect, sends the installed version once (the same
  value the admin page's status grid already shows, via
  ``updater.installed_version()``) as a single JSON message, then holds the
  connection open. No re-push, no subscription protocol, no auth -- proving
  "React SPA <-> Python WebSocket server, one real piece of app state flows
  across it" is the whole job of this story.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os

import websockets
from websockets.asyncio.server import ServerConnection, serve

from .updater import installed_version

log = logging.getLogger(__name__)

#: Overridable so a second instance (or a test) doesn't collide with one
#: already running locally -- same convention as StatusServer's port.
HOST = os.environ.get("NHL_SCOREBOARD_WS_HOST", "localhost")
PORT = int(os.environ.get("NHL_SCOREBOARD_WS_PORT", "8765"))


async def _handle(connection: ServerConnection) -> None:
    payload = json.dumps({"version": installed_version() or "unknown (factory image)"})
    await connection.send(payload)
    log.info("Sent version to %s: %s", connection.remote_address, payload)
    # Story 1 only ever sends the one message above; holding the connection
    # open (rather than returning, which closes it) is what actually makes
    # this a WebSocket "server pushes, client just listens" instead of a
    # one-shot HTTP-shaped request/response -- a later story adds real
    # ongoing pushes on top of this same open connection.
    await connection.wait_closed()


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
