"""Minimal read-only web status page for headless debugging (#48).

Stdlib-only (`http.server`), matching the project's "no heavy dependencies on
the device" stance. Serves a single HTML page rendering whatever snapshot
dict it's handed -- it has no knowledge of ``ScoreboardApp``, which builds
the snapshot from its own in-memory state (see ``ScoreboardApp.status_snapshot``).

No auth, bound to 0.0.0.0 by default: this is a status page for a device
already trusted on the local network, not something to port-forward.
"""

from __future__ import annotations

import html
import logging
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger(__name__)


def _render_html(snapshot: dict[str, str]) -> bytes:
    rows = "".join(
        f"<tr><th>{html.escape(key)}</th><td>{html.escape(value)}</td></tr>"
        for key, value in snapshot.items()
    )
    page = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="10">
<title>NHL Scoreboard status</title>
<style>
body {{ font-family: sans-serif; background: #111; color: #eee; padding: 2rem; }}
h1 {{ font-size: 1.2rem; }}
table {{ border-collapse: collapse; }}
th, td {{ text-align: left; padding: 0.25rem 1.5rem 0.25rem 0; }}
th {{ color: #888; font-weight: normal; white-space: nowrap; }}
</style>
</head>
<body>
<h1>NHL Scoreboard status</h1>
<table>{rows}</table>
</body>
</html>
"""
    return page.encode("utf-8")


def _make_handler(snapshot: Callable[[], dict[str, str]]) -> type[BaseHTTPRequestHandler]:
    class StatusRequestHandler(BaseHTTPRequestHandler):
        server_version = "nhl-scoreboard-status/1.0"

        def do_GET(self) -> None:
            if self.path not in ("/", "/index.html"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = _render_html(snapshot())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            log.debug("status server: %s", format % args)

    return StatusRequestHandler


class StatusServer:
    """Serves the status page on a background thread until ``stop()``."""

    def __init__(
        self,
        snapshot: Callable[[], dict[str, str]],
        port: int,
        host: str = "0.0.0.0",  # intentional: a LAN status page, see module docstring
    ) -> None:
        self._snapshot = snapshot
        self._host = host
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        """The bound port -- resolves a requested port of 0 to the one actually picked."""
        if self._httpd is not None:
            return self._httpd.server_address[1]
        return self._port

    def start(self) -> None:
        self._httpd = ThreadingHTTPServer((self._host, self._port), _make_handler(self._snapshot))
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="status-server", daemon=True
        )
        self._thread.start()
        log.info("Status page listening on http://%s:%d/", self._host, self.port)

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
